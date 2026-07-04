"""PixInsight-Integration — Backend als File-Broker.

Der Mac-Agent (mac-agent/agent.py) läuft auf dem Mac, auf dem PixInsight
installiert ist. Der Mac braucht **keinen SMB-Mount** — alle Dateien werden
über HTTP transferiert:

    1. Backend liest RAW-Dateien vom NAS (Storage-Abstraktion)
    2. Backend zippt die RAW-Dateien in ein temporäres Verzeichnis
    3. Backend lädt das ZIP per multipart-POST an den Mac-Agent hoch
    4. Mac-Agent entpackt, startet PixInsight/WBPP headless (oder Shell-Sim)
    5. Mac-Agent zippt die Ergebnisse
    6. Backend lädt Ergebnis-ZIP per GET /results/{job_id} herunter
    7. Backend entpackt und schreibt auf NAS unter Prepared/<Obj>/<Ger>/
    8. Status → 'vorbereitet' (WBPP fertig, manuelle Entwicklung offen)

Der Nutzer kann dann in PixInsight manuell weiterarbeiten und das fertige
Bild später in den Developer-Ordner legen → Watch-Loop → Status 'entwickelt'.

Status-Fluss:
    raw → in_bearbeitung → vorbereitet → (manuelle Entwicklung) → entwickelt

Processing-Modi:
    wbpp       — WeightedBatchPreProcessing (vollständig, langsam)
    fastbatch  — FastBatchProcessing (schneller, weniger Optionen)
    shell_sim  — Shell-Simulation (Test-Modus, kein PixInsight nötig)

Calibration-Frames:
    Pro Setup (Teleskop+Kamera) kann ein calibration_dir hinterlegt werden
    (Pfad auf dem Mac, wo Flats/Darks/Bias liegen). Dieser Pfad wird an den
    Mac-Agent durchgereicht.

Architektur (asynchron):
    POST /process → erstellt BackendJob, startet Hintergrund-Task, kehrt
    SOFORT zurück mit job_id.  Der Hintergrund-Task liest die RAW-Dateien,
    zippt sie und lädt sie zum Agent hoch.  Das Frontend pollt
    /status/{job_id} bis der Job auf dem Agent abgeschlossen ist.
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
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import async_session
from app.models.observation import Observation
from app.models.observing import Setup
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import archive

logger = logging.getLogger("uvicorn.error")
_cfg = get_settings()

# Verzeichnisname für WBPP-Ergebnisse (Master-Files, kalibrierte Frames).
# Liegen im Archiv unter Prepared/<Objekt>/<Gerät>/.
PREPARED_FOLDER = "Prepared"

# Gültige Processing-Modi
VALID_MODES = {"wbpp", "fastbatch", "shell_sim"}


# ─── In-Memory Job-Tracker (Backend-Seite) ───
# Verfolgt den Status eines PixInsight-Jobs über beide Phasen:
#   1. Backend sammelt RAW-Dateien und lädt sie zum Agent (Phase: starting → sent)
#   2. Agent verarbeitet (Phase: sent → running → completed/failed)
@dataclass
class BackendJob:
    id: str
    obs_id: str
    user_id: str
    status: str  # starting · sent · running · completed · failed
    agent_job_id: str | None = None
    mode: str = "wbpp"
    error: str | None = None
    input_files: int = 0
    calibration_dir: str = ""
    flats_dir: str = ""
    darks_dir: str = ""
    bias_dir: str = ""
    frame_info: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_backend_jobs: dict[str, BackendJob] = {}


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


async def _get_calibration_dirs(db: AsyncSession, obs: Observation) -> dict[str, str]:
    """Liest die Kalibrierungs-Pfade aus dem Setup (Teleskop+Kamera).

    Gibt ein Dict mit 'flats_dir', 'darks_dir', 'bias_dir' zurück.
    Wenn nur das Legacy-Feld calibration_dir gesetzt ist, wird es für
    alle drei verwendet (Fallback).
    """
    result = {"flats_dir": "", "darks_dir": "", "bias_dir": ""}
    if not obs.telescope_id:
        return result
    setup = await db.scalar(
        select(Setup).where(Setup.telescope_id == obs.telescope_id)
    )
    if not setup:
        return result
    result["flats_dir"] = setup.flats_dir or ""
    result["darks_dir"] = setup.darks_dir or ""
    result["bias_dir"] = setup.bias_dir or ""
    # Legacy-Fallback: calibration_dir für alle drei verwenden, wenn die
    # separaten Felder nicht gesetzt sind.
    if setup.calibration_dir and not any(result.values()):
        result["flats_dir"] = setup.calibration_dir
        result["darks_dir"] = setup.calibration_dir
        result["bias_dir"] = setup.calibration_dir
    return result


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


def _rel_from_archive_path(storage: archive.Storage, sub: SubFrame) -> str:
    """Leitet den relativen Pfad für storage.fetch aus dem SubFrame ab."""
    full = sub.archive_path or ""
    root = storage.display_root()
    if full.startswith(root):
        return full[len(root):].lstrip("/\\")
    return full


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

    storage_kind = getattr(storage, "kind", "unknown")
    storage_root = storage.display_root()

    files: list[tuple[str, bytes]] = []
    errors: list[str] = []
    for sub in subs:
        if not sub.archive_path:
            errors.append(f"{sub.original_filename}: kein archive_path gesetzt")
            logger.warning("PixInsight: %s — kein archive_path", sub.original_filename)
            continue
        rel = _rel_from_archive_path(storage, sub)
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(sub.original_filename).suffix) as tmp:
                tmp_path = tmp.name
            await asyncio.to_thread(storage.fetch, rel, tmp_path)
            with open(tmp_path, "rb") as f:
                content = f.read()
            files.append((sub.original_filename, content))
            logger.info("PixInsight: RAW gelesen — %s (%d bytes, rel=%s)", sub.original_filename, len(content), rel)
        except Exception as e:
            err_msg = f"{sub.original_filename}: {e} (archive_path={sub.archive_path}, rel={rel}, storage={storage_kind}, root={storage_root})"
            errors.append(err_msg)
            logger.warning("PixInsight: Konnte RAW-Datei nicht lesen — %s", err_msg)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    if not files and errors:
        first_err = errors[0]
        raise ValueError(
            f"Konnte keine RAW-Dateien vom Storage lesen (storage={storage_kind}, root={storage_root}). "
            f"Erster Fehler: {first_err}"
        )
    return files


def _create_zip(files: list[tuple[str, bytes]]) -> bytes:
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


# ─── Hintergrund-Task: RAW-Dateien sammeln und an Agent senden ───
async def _do_batch_transfer(
    job: BackendJob,
    obs_id: str,
    user_id: str,
    mode: str,
    calib_dirs: dict[str, str],
    frame_info: dict[str, Any],
) -> None:
    """Hintergrund-Task: liest RAW-Dateien vom NAS, zippt sie und lädt sie
    per HTTP an den Mac-Agent hoch.  Aktualisiert den BackendJob-Status."""
    from datetime import datetime, timezone

    try:
        async with async_session() as db:
            # Observation und User laden
            obs = await db.get(Observation, uuid.UUID(obs_id))
            user = await db.get(User, uuid.UUID(user_id))
            if not obs or not user:
                job.status = "failed"
                job.error = "Observation oder User nicht gefunden"
                return

            # RAW-Dateien vom NAS lesen
            logger.info("PixInsight [job=%s]: sammle RAW-Dateien …", job.id)
            raw_files = await _collect_raw_files(db, user, obs)
            if not raw_files:
                job.status = "failed"
                job.error = "Konnte keine RAW-Dateien vom Storage lesen"
                return

            job.input_files = len(raw_files)
            logger.info("PixInsight [job=%s]: %d RAW-Dateien gelesen, erstelle ZIP …", job.id, len(raw_files))

            # ZIP erstellen (im Thread, da CPU-bound)
            zip_bytes = await asyncio.to_thread(_create_zip, raw_files)
            logger.info("PixInsight [job=%s]: ZIP erstellt (%d bytes)", job.id, len(zip_bytes))

            # Observation-Status setzen
            obs.status = "in_bearbeitung"
            obs.is_new = False
            await db.commit()

        # ZIP an Mac-Agent hochladen (außerhalb der DB-Session)
        agent_url = await _agent_url("/process")
        logger.info(
            "PixInsight [job=%s]: sende ZIP (%d bytes) an %s (mode=%s, flats=%s, darks=%s, bias=%s)",
            job.id, len(zip_bytes), agent_url, mode,
            calib_dirs.get("flats_dir") or "(keine)",
            calib_dirs.get("darks_dir") or "(keine)",
            calib_dirs.get("bias_dir") or "(keine)",
        )

        form_data = {
            "frame_info": json.dumps(frame_info),
            "mode": mode,
            "token": await _agent_token(),
        }
        if calib_dirs.get("flats_dir"):
            form_data["flats_dir"] = calib_dirs["flats_dir"]
        if calib_dirs.get("darks_dir"):
            form_data["darks_dir"] = calib_dirs["darks_dir"]
        if calib_dirs.get("bias_dir"):
            form_data["bias_dir"] = calib_dirs["bias_dir"]

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.post(
                    agent_url,
                    files={"file": ("raw_frames.zip", zip_bytes, "application/zip")},
                    data=form_data,
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            job.status = "failed"
            job.error = f"Mac-Agent nicht erreichbar unter {_cfg.pixinsight_agent_url}"
            # Observation-Status zurücksetzen
            async with async_session() as db:
                obs = await db.get(Observation, uuid.UUID(obs_id))
                if obs:
                    obs.status = "raw"
                    await db.commit()
            return
        except httpx.HTTPStatusError as e:
            job.status = "failed"
            job.error = f"Mac-Agent Fehler: {e.response.status_code} — {e.response.text[:200]}"
            async with async_session() as db:
                obs = await db.get(Observation, uuid.UUID(obs_id))
                if obs:
                    obs.status = "raw"
                    await db.commit()
            return

        agent_job_id = data.get("job_id")
        job.agent_job_id = agent_job_id
        job.status = "sent"
        logger.info(
            "PixInsight [job=%s]: Agent akzeptiert — agent_job_id=%s, status=%s",
            job.id, agent_job_id, data.get("status"),
        )

    except Exception as e:
        logger.exception("PixInsight [job=%s]: Fehler im Hintergrund-Task", job.id)
        job.status = "failed"
        job.error = str(e)
        # Observation-Status zurücksetzen
        try:
            async with async_session() as db:
                obs = await db.get(Observation, uuid.UUID(obs_id))
                if obs:
                    obs.status = "raw"
                    await db.commit()
        except Exception:
            pass


async def trigger_batch(
    db: AsyncSession, user: User, obs: Observation, *, mode: str = "wbpp"
) -> dict[str, Any]:
    """Startet den PixInsight-Batch für diese Observation — ASYNCHRON.

    Erstellt sofort einen BackendJob und startet einen Hintergrund-Task, der
    die RAW-Dateien sammelt, zippt und an den Mac-Agent sendet.
    Kehrt SOFORT zurück mit der job_id — das Frontend pollt den Status.

    Parameter:
        mode — Processing-Modus: "wbpp", "fastbatch" oder "shell_sim"
    """
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert (PIXINSIGHT_AGENT_URL)")

    if mode not in VALID_MODES:
        mode = "wbpp"

    # Calibration-Dir aus Setup holen
    calib_dirs = await _get_calibration_dirs(db, obs)

    # Frame-Info sammeln
    frame_info = await _frame_summary(db, obs)
    logger.info(
        "PixInsight: trigger_batch für obs=%s, mode=%s, flats=%s, darks=%s, bias=%s, frame_info=%s",
        obs.id, mode,
        calib_dirs.get("flats_dir") or "(keine)",
        calib_dirs.get("darks_dir") or "(keine)",
        calib_dirs.get("bias_dir") or "(keine)",
        frame_info,
    )

    # BackendJob erstellen
    from datetime import datetime, timezone
    job = BackendJob(
        id=str(uuid.uuid4()),
        obs_id=str(obs.id),
        user_id=str(user.id),
        status="starting",
        mode=mode,
        calibration_dir=calib_dirs.get("flats_dir", ""),
        flats_dir=calib_dirs.get("flats_dir", ""),
        darks_dir=calib_dirs.get("darks_dir", ""),
        bias_dir=calib_dirs.get("bias_dir", ""),
        frame_info=frame_info,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _backend_jobs[job.id] = job

    # Hintergrund-Task starten (nicht-blockierend)
    asyncio.create_task(_do_batch_transfer(
        job, str(obs.id), str(user.id), mode, calib_dirs, frame_info,
    ))

    # Observation-Status sofort auf "in_bearbeitung" setzen
    obs.status = "in_bearbeitung"
    obs.is_new = False
    await db.flush()

    return {
        "job_id": job.id,
        "status": "starting",
        "mode": mode,
        "agent_url": _cfg.pixinsight_agent_url,
        "input_files": 0,  # wird im Hintergrund gefüllt
        "calibration_dir": calib_dirs.get("flats_dir") or None,
        "flats_dir": calib_dirs.get("flats_dir") or None,
        "darks_dir": calib_dirs.get("darks_dir") or None,
        "bias_dir": calib_dirs.get("bias_dir") or None,
        "frame_info": frame_info,
    }


async def poll_job_results(
    db: AsyncSession, user: User, obs: Observation, job_id: str
) -> dict[str, Any]:
    """Fragt den Job-Status ab.  Wenn der Job auf dem Agent abgeschlossen ist,
    lädt er die Ergebnis-ZIP herunter, entpackt sie und schreibt die Dateien
    ins Prepared-Verzeichnis auf dem NAS.  Setzt den Status auf 'vorbereitet'.
    """
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert")

    # Backend-Job suchen
    bjob = _backend_jobs.get(job_id)
    if not bjob:
        raise ValueError(f"Job {job_id} nicht gefunden")

    # Phase 1: Backend sammelt noch Dateien
    if bjob.status == "starting":
        return {"job_id": job_id, "status": "starting", "message": "RAW-Dateien werden gesammelt …"}

    # Phase 1 fehlgeschlagen
    if bjob.status == "failed":
        return {"job_id": job_id, "status": "failed", "error": bjob.error or "Unbekannter Fehler"}

    # Phase 2: Agent verarbeitet — Status beim Agent abfragen
    if bjob.status in ("sent", "running") and bjob.agent_job_id:
        token = await _agent_token()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    await _agent_url(f"/status/{bjob.agent_job_id}"),
                    params={"token": token},
                )
                resp.raise_for_status()
                status_data = resp.json()
        except httpx.ConnectError:
            return {"job_id": job_id, "status": "unknown", "error": "Agent nicht erreichbar"}
        except httpx.HTTPStatusError as e:
            return {"job_id": job_id, "status": "error", "error": f"Agent: {e.response.status_code}"}

        agent_status = status_data.get("status", "unknown")

        # Backend-Job-Status synchronisieren
        if agent_status == "running":
            bjob.status = "running"

        if agent_status != "completed":
            return {"job_id": job_id, "status": agent_status, "details": status_data}

        # Job abgeschlossen → Ergebnis-ZIP herunterladen
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                resp = await client.get(
                    await _agent_url(f"/results/{bjob.agent_job_id}"),
                    params={"token": token},
                )
                if resp.status_code == 409:
                    # Race condition: Agent sagt "completed" aber /results sagt "not ready"
                    return {"job_id": job_id, "status": "running", "message": "Ergebnisse werden noch gepackt …"}
                resp.raise_for_status()
                zip_bytes = resp.content
        except httpx.ConnectError:
            return {"job_id": job_id, "status": "error", "error": "Agent nicht erreichbar für Download"}
        except httpx.HTTPStatusError as e:
            return {"job_id": job_id, "status": "error", "error": f"Download fehlgeschlagen: {e.response.status_code}"}

        # ZIP entpacken
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            extracted = await _extract_zip(zip_bytes, tmp_path)

            if not extracted:
                return {"job_id": job_id, "status": "error", "error": "Ergebnis-ZIP ist leer"}

            # Ergebnis-Dateien ins Storage (NAS) schreiben
            prepared_rel = await prepared_reldir(db, user, obs)
            written = await _write_prepared_to_storage(user, prepared_rel, tmp_path)

        # Status auf 'vorbereitet' setzen
        obs.status = "vorbereitet"
        obs.is_new = False
        await db.flush()

        bjob.status = "completed"

        return {
            "job_id": job_id,
            "status": "vorbereitet",
            "result_files": written,
            "result_count": len(written),
            "prepared_dir": prepared_rel,
        }

    # Bereits abgeschlossen
    if bjob.status == "completed":
        return {"job_id": job_id, "status": "vorbereitet", "message": "Bereits abgeschlossen"}

    return {"job_id": job_id, "status": bjob.status}


async def check_job_status(job_id: str) -> dict[str, Any]:
    """Fragt den Status eines laufenden PixInsight-Jobs ab — über den
    Backend-Job-Tracker und ggf. den Mac-Agent."""
    if not _cfg.pixinsight_agent_url:
        raise ValueError("PixInsight-Agent-URL nicht konfiguriert")

    # Backend-Job suchen
    bjob = _backend_jobs.get(job_id)
    if not bjob:
        return {"status": "unknown", "error": f"Job {job_id} nicht gefunden"}

    # Phase 1: Backend sammelt noch Dateien
    if bjob.status == "starting":
        return {
            "status": "starting",
            "message": "RAW-Dateien werden gesammelt und an den Mac-Agent gesendet …",
            "input_files": bjob.input_files,
        }

    # Phase 1 fehlgeschlagen
    if bjob.status == "failed":
        return {"status": "failed", "error": bjob.error or "Unbekannter Fehler"}

    # Bereits abgeschlossen
    if bjob.status == "completed":
        return {"status": "completed", "input_files": bjob.input_files}

    # Phase 2: Agent verarbeitet — Status beim Agent abfragen
    if bjob.agent_job_id:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    await _agent_url(f"/status/{bjob.agent_job_id}"),
                    params={"token": await _agent_token()},
                )
                resp.raise_for_status()
                agent_data = resp.json()
        except httpx.ConnectError:
            return {"status": "unknown", "error": "Agent nicht erreichbar"}
        except httpx.HTTPStatusError as e:
            return {"status": "error", "error": f"Agent: {e.response.status_code}"}

        agent_status = agent_data.get("status", "unknown")

        # Backend-Job-Status synchronisieren
        if agent_status == "running":
            bjob.status = "running"
        elif agent_status == "completed":
            bjob.status = "completed"
        elif agent_status == "failed":
            bjob.status = "failed"
            bjob.error = agent_data.get("error", "Agent-Job fehlgeschlagen")

        return {
            "status": agent_status,
            "input_files": bjob.input_files,
            "agent_job_id": bjob.agent_job_id,
            "error": agent_data.get("error"),
        }

    return {"status": bjob.status}


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


# ─── Pre-Flight-Check ───
async def precheck(
    db: AsyncSession, user: User, obs: Observation
) -> dict[str, Any]:
    """Pre-Flight-Check vor dem PixInsight-Batch.

    Prüft:
      - Anzahl Sub-Frames nach Frame-Typ (Lights/Darks/Flats/Bias)
      - Ob alle Sub-Frames ein archive_path haben (auf dem NAS liegen)
      - Calibration-Dir aus dem Setup (falls gesetzt)
      - Mac-Agent erreichbar? PixInsight gefunden?
      - Gesamtgröße-Schätzung der RAW-Dateien

    Liefert eine strukturierte Antwort mit ``warnings`` und ``can_start``.
    """
    warnings: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    # 1. Sub-Frames analysieren
    subs = await db.scalars(
        select(SubFrame).where(SubFrame.observation_id == obs.id)
    )
    subs = list(subs)

    frame_counts: dict[str, int] = {}
    missing_archive: list[str] = []
    total_size: int = 0

    for s in subs:
        ft = (s.frame_type or "Light").lower()
        frame_counts[ft] = frame_counts.get(ft, 0) + 1
        if not s.archive_path:
            missing_archive.append(s.original_filename)
        if s.file_size:
            total_size += s.file_size

    light_count = frame_counts.get("light", 0)
    dark_count = frame_counts.get("dark", 0)
    flat_count = frame_counts.get("flat", 0)
    bias_count = frame_counts.get("bias", 0)
    darkflat_count = frame_counts.get("darkflat", 0)

    if not subs:
        errors.append({
            "level": "error",
            "code": "no_subframes",
            "message": "Keine Sub-Frames für diese Aufnahme — erst ASIAir-Daten importieren.",
        })
    else:
        if light_count == 0:
            errors.append({
                "level": "error",
                "code": "no_lights",
                "message": "Keine Light-Frames gefunden — ohne Lights ist kein Stacking möglich.",
            })
        if missing_archive:
            warnings.append({
                "level": "warning",
                "code": "missing_archive_path",
                "message": f"{len(missing_archive)} Sub-Frame(s) ohne archive_path (nicht auf NAS abgelegt): {', '.join(missing_archive[:5])}{'…' if len(missing_archive) > 5 else ''}",
            })

    # 2. Calibration-Dir aus Setup
    calib_dirs = await _get_calibration_dirs(db, obs)
    calib_info: dict[str, Any] = {
        "configured": bool(calibration_dir),
        "path": calibration_dir or None,
    }
    if not calibration_dir:
        warnings.append({
            "level": "warning",
            "code": "no_calibration_dir",
            "message": "Kein Calibration-Verzeichnis für dieses Setup konfiguriert — Flats/Darks/Bias müssen im ZIP enthalten sein oder manuell in PixInsight geladen werden.",
        })

    # 3. Agent-Health
    agent = await check_agent_health()
    agent_info: dict[str, Any] = {
        "available": agent.get("available", False),
        "pixinsight_found": agent.get("pixinsight_found", False),
        "shell_sim_available": agent.get("shell_sim_available", False),
        "wbpp_script_found": agent.get("wbpp_script_found", False),
        "fastbatch_script_found": agent.get("fastbatch_script_found", False),
        "active_jobs": agent.get("active_jobs", 0),
    }
    if not agent.get("available"):
        errors.append({
            "level": "error",
            "code": "agent_unreachable",
            "message": f"Mac-Agent nicht erreichbar unter {_cfg.pixinsight_agent_url} — ist der Agent auf dem Mac gestartet?",
        })
    elif not agent.get("pixinsight_found") and not agent.get("shell_sim_available"):
        errors.append({
            "level": "error",
            "code": "no_processing_available",
            "message": "Agent erreichbar, aber weder PixInsight noch Shell-Simulation verfügbar.",
        })
    elif not agent.get("pixinsight_found"):
        warnings.append({
            "level": "warning",
            "code": "pixinsight_not_found",
            "message": "Agent erreichbar, aber PixInsight nicht gefunden — nur Shell-Simulation verfügbar.",
        })

    # 4. Frame-Info für Anzeige
    frame_info = await _frame_summary(db, obs)

    # 5. can_start bestimmen
    can_start = len(errors) == 0

    return {
        "can_start": can_start,
        "frame_counts": {
            "lights": light_count,
            "darks": dark_count,
            "flats": flat_count,
            "bias": bias_count,
            "darkflats": darkflat_count,
            "total": len(subs),
        },
        "missing_archive_count": len(missing_archive),
        "estimated_size_mb": round(total_size / (1024 * 1024), 1) if total_size else 0,
        "calibration_dir": calib_info,
        "agent": agent_info,
        "frame_info": frame_info,
        "warnings": warnings,
        "errors": errors,
    }
