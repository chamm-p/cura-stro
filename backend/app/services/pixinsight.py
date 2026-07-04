"""PixInsight-Integration — Backend als File-Broker.

Der Mac-Agent (mac-agent/agent.py) läuft auf dem Mac, auf dem PixInsight
installiert ist. Der Mac braucht **keinen SMB-Mount** — alle Dateien werden
über HTTP transferiert:

    1. Backend liest RAW-Dateien vom NAS (Storage-Abstraktion)
    2. Backend zippt die RAW-Dateien in ein temporäres Verzeichnis
    3. Backend lädt das ZIP per multipart-POST an den Mac-Agent hoch
    4. Mac-Agent entpackt, startet PixInsight/WBPP headless
    5. Mac-Agent zippt die Ergebnisse
    6. Backend lädt Ergebnis-ZIP per GET /results/{job_id} herunter
    7. Backend entpackt und schreibt auf NAS unter Prepared/<Obj>/<Ger>/
    8. Status → 'vorbereitet' (WBPP fertig, manuelle Entwicklung offen)

Der Nutzer kann dann in PixInsight manuell weiterarbeiten und das fertige
Bild später in den Developer-Ordner legen → Watch-Loop → Status 'entwickelt'.

Status-Fluss:
    raw → in_bearbeitung → vorbereitet → (manuelle Entwicklung) → entwickelt
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.observation import Observation
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import archive

logger = logging.getLogger("uvicorn.error")
_cfg = get_settings()

# Verzeichnisname für WBPP-Ergebnisse (Master-Files, kalibrierte Frames).
# Liegen im Archiv unter Prepared/<Objekt>/<Gerät>/.
PREPARED_FOLDER = "Prepared"


async def _agent_url(path: str = "") -> str:
    base = _cfg.pixinsight_agent_url.rstrip("/")
    return f"{base}{path}"


async def _agent_token() -> str:
    return _cfg.pixinsight_agent_token


async def raw_reldir(db: AsyncSession, user: User, obs: Observation) -> str:
    """Relativer Pfad zum RAW-Verzeichnis der Aufnahme."""
    return archive.reldir(
        archive.folder_name(user, "RAW"),
        await archive.object_label(db, obs),
        await archive.device_label(db, obs),
    )


async def prepared_reldir(db: AsyncSession, user: User, obs: Observation) -> str:
    """Relativer Pfad zum Prepared-Verzeichnis der Aufnahme."""
    return archive.reldir(
        PREPARED_FOLDER,
        await archive.object_label(db, obs),
        await archive.device_label(db, obs),
    )


async def _frame_summary(db: AsyncSession, obs: Observation) -> dict[str, Any]:
    """Sammelt Frame-Info für das PixInsight-Skript (Filter, Belichtungen, etc.)."""
    subs = await db.scalars(select(SubFrame).where(SubFrame.observation_id == obs.id))
    subs = list(subs)
    by_filter: dict[str, dict] = {}
    for s in subs:
        f = s.filter_name or "—"
        slot = by_filter.setdefault(f, {"filter": f, "subs": 0, "exposures_s": set()})
        slot["subs"] += 1
        if s.exposure_s:
            slot["exposures_s"].add(s.exposure_s)
    filters = []
    for slot in by_filter.values():
        filters.append({
            "filter": slot["filter"],
            "subs": slot["subs"],
            "exposures_s": sorted(slot["exposures_s"]),
        })
    frame_types = {}
    for s in subs:
        ft = (s.frame_type or "Light").lower()
        frame_types[ft] = frame_types.get(ft, 0) + 1
    return {
        "object_name": await archive.object_label(db, obs),
        "device_name": await archive.device_label(db, obs),
        "total_subs": len(subs),
        "filters": filters,
        "frame_types": frame_types,
    }


async def _collect_raw_files(
    db: AsyncSession, user: User, obs: Observation
) -> list[tuple[str, bytes]]:
    """Liest alle RAW-Dateien einer Observation vom Storage und liefert
    (filename, content) Paare."""
    storage = archive.get_storage(user)
    subs = await db.scalars(
        select(SubFrame).where(SubFrame.observation_id == obs.id)
    )
    subs = list(subs)
    if not subs:
        raise ValueError("Keine Sub-Frames für diese Aufnahme — erst ASIAir-Daten importieren")

    files: list[tuple[str, bytes]] = []
    for sub in subs:
        # archive_path ist der volle Pfad im Storage; rel ist relativ zum Root.
        # Wir nutzen den originalen Dateinamen für das ZIP.
        rel = sub.archive_path
        if not rel:
            continue
        # Für LocalStorage ist archive_path ein absoluter Pfad; für SmbStorage
        # ein UNC-Pfad. Wir nutzen storage.fetch, um die Datei lokal zu holen.
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(sub.original_filename).suffix) as tmp:
                tmp_path = tmp.name
            await asyncio.to_thread(storage.fetch, _rel_from_archive_path(storage, sub), tmp_path)
            with open(tmp_path, "rb") as f:
                content = f.read()
            files.append((sub.original_filename, content))
        except Exception as e:
            logger.warning("Konnte RAW-Datei nicht lesen: %s — %s", sub.original_filename, e)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    return files


def _rel_from_archive_path(storage: archive.Storage, sub: SubFrame) -> str:
    """Leitet den relativen Pfad für storage.fetch aus dem SubFrame ab."""
    # SubFrame.archive_path ist der volle Pfad (full_path). Für fetch brauchen
    # wir den relativen Pfad. Bei LocalStorage ist das root/rel.
    # Wir bauen rel aus den bekannten Komponenten.
    # Einfachster Weg: archive_path enthält den vollen Pfad — wir extrahieren
    # den Teil nach dem Storage-Root.
    full = sub.archive_path or ""
    root = storage.display_root()
    if full.startswith(root):
        return full[len(root):].lstrip("/\\")
    # Fallback: aus den Komponenten zusammenbauen
    return full


async def _create_zip(files: list[tuple[str, bytes]]) -> bytes:
    """Erstellt ein ZIP im Speicher aus (filename, content) Paaren."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files:
            zf.writestr(name, content)
    return buf.getvalue()


async def _extract_zip(zip_bytes: bytes, dest_dir: Path) -> list[str]:
    """Entpackt ein ZIP ins Zielverzeichnis und liefert die Dateinamen."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            # Pfad innerhalb des ZIP sichern entpacken
            target = dest_dir / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            names.append(info.filename)
    return names


async def _write_prepared_to_storage(
    user: User, prepared_rel: str, local_dir: Path
) -> list[str]:
    """Schreibt die Ergebnis-Dateien vom lokalen Temp-Verzeichnis ins
    Storage (NAS) unter Prepared/<Obj>/<Ger>/."""
    storage = archive.get_storage(user)
    # Verzeichnis im Storage anlegen
    await asyncio.to_thread(storage.makedirs, prepared_rel)
    written: list[str] = []
    for f in sorted(local_dir.rglob("*")):
        if not f.is_file():
            continue
        rel_within = f.relative_to(local_dir)
        rel = f"{prepared_rel}/{rel_within}"
        try:
            await asyncio.to_thread(storage.put, rel, str(f))
            written.append(str(rel_within))
        except Exception as e:
            logger.warning("Konnte Ergebnis-Datei nicht schreiben: %s — %s", rel_within, e)
    return written


async def trigger_batch(db: AsyncSession, user: User, obs: Observation) -> dict[str, Any]:
    """Triggert den Mac-Agent, um PixInsight für diese Observation zu starten.

    Liest die RAW-Dateien vom NAS, zippt sie, lädt sie per HTTP an den Mac-Agent
    hoch. Der Agent verarbeitet sie mit PixInsight/WBPP. Die Ergebnisse werden
    später per poll_job_results abgeholt und ins Prepared-Verzeichnis geschrieben.
    """
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert (PIXINSIGHT_AGENT_URL)")

    # Frame-Info sammeln
    frame_info = await _frame_summary(db, obs)

    # RAW-Dateien vom NAS lesen
    raw_files = await _collect_raw_files(db, user, obs)
    if not raw_files:
        raise ValueError("Konnte keine RAW-Dateien vom Storage lesen")

    # ZIP erstellen
    zip_bytes = await _create_zip(raw_files)

    # Observation-Status setzen
    obs.status = "in_bearbeitung"
    obs.is_new = False
    await db.flush()

    # ZIP an Mac-Agent hochladen
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                await _agent_url("/process"),
                files={"file": ("raw_frames.zip", zip_bytes, "application/zip")},
                data={
                    "frame_info": json.dumps(frame_info),
                    "token": await _agent_token(),
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        obs.status = "raw"  # Zurücksetzen — Agent nicht erreichbar
        await db.flush()
        raise ValueError(
            f"Mac-Agent nicht erreichbar unter {_cfg.pixinsight_agent_url}. "
            "Ist der Agent auf dem Mac gestartet?"
        )
    except httpx.HTTPStatusError as e:
        obs.status = "raw"
        await db.flush()
        raise ValueError(f"Mac-Agent Fehler: {e.response.status_code} — {e.response.text}")

    return {
        "job_id": data.get("job_id"),
        "status": data.get("status", "queued"),
        "agent_url": _cfg.pixinsight_agent_url,
        "input_files": data.get("input_files", len(raw_files)),
        "frame_info": frame_info,
    }


async def poll_job_results(
    db: AsyncSession, user: User, obs: Observation, job_id: str
) -> dict[str, Any]:
    """Fragt den Job-Status beim Mac-Agent ab. Wenn der Job abgeschlossen ist,
    lädt er die Ergebnis-ZIP herunter, entpackt sie und schreibt die Dateien
    ins Prepared-Verzeichnis auf dem NAS. Setzt den Status auf 'vorbereitet'.
    """
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert")

    token = await _agent_token()

    # Status abfragen
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                await _agent_url(f"/status/{job_id}"),
                params={"token": token},
            )
            resp.raise_for_status()
            status_data = resp.json()
    except httpx.ConnectError:
        return {"status": "unknown", "error": "Agent nicht erreichbar"}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": f"Agent: {e.response.status_code}"}

    job_status = status_data.get("status", "unknown")

    if job_status != "completed":
        return {"job_id": job_id, "status": job_status, "details": status_data}

    # Job abgeschlossen → Ergebnis-ZIP herunterladen
    try:
        async with httpx.AsyncClient(timeout=600.0) as client:
            resp = await client.get(
                await _agent_url(f"/results/{job_id}"),
                params={"token": token},
            )
            resp.raise_for_status()
            zip_bytes = resp.content
    except httpx.ConnectError:
        return {"status": "error", "error": "Agent nicht erreichbar für Download"}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": f"Download fehlgeschlagen: {e.response.status_code}"}

    # ZIP entpacken
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        extracted = await _extract_zip(zip_bytes, tmp_path)

        if not extracted:
            return {"status": "error", "error": "Ergebnis-ZIP ist leer"}

        # Ergebnis-Dateien ins Storage (NAS) schreiben
        prepared_rel = await prepared_reldir(db, user, obs)
        written = await _write_prepared_to_storage(user, prepared_rel, tmp_path)

    # Status auf 'vorbereitet' setzen
    obs.status = "vorbereitet"
    obs.is_new = False
    await db.flush()

    return {
        "job_id": job_id,
        "status": "vorbereitet",
        "result_files": written,
        "result_count": len(written),
        "prepared_dir": prepared_rel,
    }


async def check_job_status(job_id: str) -> dict[str, Any]:
    """Fragt den Status eines laufenden PixInsight-Jobs vom Mac-Agent ab."""
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                await _agent_url(f"/status/{job_id}"),
                params={"token": await _agent_token()},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        return {"status": "unknown", "error": "Agent nicht erreichbar"}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": f"Agent: {e.response.status_code}"}


async def check_agent_health() -> dict[str, Any]:
    """Health-Check des Mac-Agents."""
    if not _cfg.pixinsight_agent_url:
        return {"available": False, "reason": "nicht konfiguriert"}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(await _agent_url("/health"))
            resp.raise_for_status()
            data = resp.json()
            return {"available": True, **data}
    except Exception as e:
        return {"available": False, "reason": str(e)}
