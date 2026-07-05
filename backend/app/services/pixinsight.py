"""PixInsight-Integration — Backend als File-Broker.

Der Mac-Agent (mac-agent/agent.py) läuft auf dem Mac, auf dem PixInsight
installiert ist. Der Mac braucht **keinen SMB-Mount** — alle Dateien werden
über HTTP transferiert:

    1. Backend liest RAW-Lights vom NAS (Storage-Abstraktion)
    2. Calib (Flats/Darks/Bias): Fingerprint je Datei (SHA-256, DB-Cache) →
       existiert für das Set schon ein Master auf dem NAS (Calib/Masters/),
       wird nur der referenziert — sonst die Roh-Subs
    3. Cache-Handshake mit dem Agent: POST /calib/check → nur fehlende
       Dateien werden per /calib/upload übertragen (jede genau einmal)
    4. Lights als ZIP (ZIP_STORED, von Platte gestreamt) per POST /process
    5. Mac-Agent startet PixInsight headless (cura_batch.js, CURA_CALIB
       zeigt auf die Cache-Pfade)
    6. Backend lädt Ergebnis-ZIP per GET /results/{job_id} herunter
    7. Frisch gebaute Bias/Dark/Flat-Master → NAS Calib/Masters/ + DB-
       Registrierung (CalibMaster); Rest → Prepared/<Obj>/<Ger>/
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
import hashlib
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
from app.models.calib import CalibFile, CalibMaster
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

# Fertige Kalibrier-Master (Bias/Dark/Flat) landen hier auf dem NAS und
# werden bei Folgejobs statt der Roh-Subs an den Agent geschickt.
CALIB_MASTERS_FOLDER = "Calib/Masters"

# Reihenfolge: (kind, Setup-Feld, Dateiname den cura_batch.js erzeugt)
CALIB_KINDS = [
    ("bias", "bias_dir", "master_bias.xisf"),
    ("dark", "darks_dir", "master_dark.xisf"),
    ("flat", "flats_dir", "master_flat.xisf"),
]

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
    # Calib-Cache: set_hash je Art (für Master-Registrierung nach dem Job)
    # und Transfer-Statistik (im Cache vorhanden vs. hochgeladen).
    calib_set_hashes: dict[str, str] = field(default_factory=dict)
    calib_transfer: dict[str, Any] | None = None

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
    db: AsyncSession, user: User, obs: Observation, dest_dir: Path
) -> list[tuple[str, str]]:
    """Liest alle RAW-Dateien einer Observation vom Storage in ein lokales
    Temp-Verzeichnis und liefert (filename, lokaler Pfad) Paare.

    Bewusst NICHT in den RAM (waren vorher (filename, bytes)-Paare):
    30 Subs ≈ 300+ MB, die sonst doppelt gepuffert würden."""
    storage = archive.get_storage(user)
    subs = await db.scalars(
        select(SubFrame).where(SubFrame.observation_id == obs.id)
    )
    subs = list(subs)
    if not subs:
        raise ValueError("Keine Sub-Frames für diese Aufnahme — erst ASIAir-Daten importieren")

    storage_kind = getattr(storage, "kind", "unknown")
    storage_root = storage.display_root()
    dest_dir.mkdir(parents=True, exist_ok=True)

    files: list[tuple[str, str]] = []
    errors: list[str] = []
    for sub in subs:
        if not sub.archive_path:
            errors.append(f"{sub.original_filename}: kein archive_path gesetzt")
            logger.warning("PixInsight: %s — kein archive_path", sub.original_filename)
            continue
        rel = _rel_from_archive_path(storage, sub)
        local = dest_dir / sub.original_filename
        try:
            await asyncio.to_thread(storage.fetch, rel, str(local))
            files.append((sub.original_filename, str(local)))
            logger.info("PixInsight: RAW gelesen — %s (%d bytes, rel=%s)",
                        sub.original_filename, local.stat().st_size, rel)
        except Exception as e:
            local.unlink(missing_ok=True)
            err_msg = f"{sub.original_filename}: {e} (archive_path={sub.archive_path}, rel={rel}, storage={storage_kind}, root={storage_root})"
            errors.append(err_msg)
            logger.warning("PixInsight: Konnte RAW-Datei nicht lesen — %s", err_msg)

    if not files and errors:
        first_err = errors[0]
        raise ValueError(
            f"Konnte keine RAW-Dateien vom Storage lesen (storage={storage_kind}, root={storage_root}). "
            f"Erster Fehler: {first_err}"
        )
    return files


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _clean_rel(rel_dir: str, name: str) -> str:
    return "/".join(p for p in (rel_dir + "/" + name).replace("\\", "/").split("/") if p)


async def _hash_calib_dir(
    db: AsyncSession, storage, user: User, rel_dir: str, tmpdir: str
) -> list[dict[str, Any]]:
    """Fingerprints für alle Dateien eines Calib-Verzeichnisses auf dem NAS.

    Nutzt den DB-Cache (CalibFile): solange Größe+mtime unverändert sind,
    wird der gespeicherte SHA-256 verwendet — sonst wird die Datei einmal
    geholt und gehasht (die lokale Kopie bleibt im tmpdir für einen evtl.
    Upload liegen)."""
    try:
        names = await asyncio.to_thread(storage.listdir, rel_dir)
    except Exception as e:
        logger.warning("PixInsight: Calib-Verzeichnis nicht lesbar — %s: %s", rel_dir, e)
        return []
    entries: list[dict[str, Any]] = []
    for name in sorted(names):
        rel = _clean_rel(rel_dir, name)
        try:
            size, mtime = await asyncio.to_thread(storage.stat, rel)
        except Exception as e:
            logger.warning("PixInsight: Calib-Datei nicht lesbar — %s: %s", rel, e)
            continue
        row = await db.scalar(
            select(CalibFile).where(CalibFile.user_id == user.id, CalibFile.path == rel)
        )
        local: str | None = None
        if row and row.file_size == size and abs(row.mtime - mtime) < 1.0:
            sha = row.sha256
        else:
            local = str(Path(tmpdir) / f"h_{uuid.uuid4().hex}{Path(name).suffix}")
            await asyncio.to_thread(storage.fetch, rel, local)
            sha = await asyncio.to_thread(_sha256_file, local)
            if row:
                row.file_size, row.mtime, row.sha256 = size, mtime, sha
            else:
                db.add(CalibFile(user_id=user.id, path=rel, file_size=size, mtime=mtime, sha256=sha))
            logger.info("PixInsight: Calib gehasht — %s (%s…)", name, sha[:12])
        entries.append({
            "name": name, "rel": rel, "size": size,
            "ext": Path(name).suffix.lower(), "sha256": sha, "local": local,
        })
    return entries


async def _prepare_calibration(
    db: AsyncSession, user: User, calib_dirs: dict[str, str], tmpdir: str
) -> dict[str, Any]:
    """Baut den Kalibrier-Plan für den Agent.

    Je Art (bias/dark/flat): existiert für das aktuelle Datei-Set schon ein
    fertiger Master auf dem NAS (CalibMaster, gleicher set_hash), wird NUR
    dieser referenziert — sonst die Roh-Subs. Übertragen wird später nichts
    davon blind: der Agent meldet per /calib/check, was ihm fehlt.
    """
    storage = archive.get_storage(user)
    calib_msg: dict[str, Any] = {
        "master_bias": None, "master_dark": None, "master_flat": None,
        "bias_subs": [], "dark_subs": [], "flat_subs": [],
    }
    manifest: list[dict[str, Any]] = []
    sources: dict[str, tuple[str, str]] = {}   # sha → ("local", pfad) | ("nas", rel)
    set_hashes: dict[str, str] = {}
    entries_by_kind: dict[str, list[dict[str, Any]]] = {}

    for kind, dir_key, _master_name in CALIB_KINDS:
        rel_dir = calib_dirs.get(dir_key, "")
        if not rel_dir:
            continue
        entries = await _hash_calib_dir(db, storage, user, rel_dir, tmpdir)
        if not entries:
            logger.warning("PixInsight: Calib-Verzeichnis %s leer/nicht gefunden: %s", kind, rel_dir)
            continue
        entries_by_kind[kind] = entries
        set_hash = hashlib.sha256(
            "\n".join(sorted(e["sha256"] for e in entries)).encode()
        ).hexdigest()
        set_hashes[kind] = set_hash

        master = await db.scalar(
            select(CalibMaster).where(
                CalibMaster.user_id == user.id,
                CalibMaster.kind == kind,
                CalibMaster.set_hash == set_hash,
            )
        )
        if master and await asyncio.to_thread(storage.exists, master.archive_path):
            item = {
                "sha256": master.sha256,
                "size": master.file_size or 0,
                "ext": Path(master.filename).suffix.lower() or ".xisf",
            }
            calib_msg[f"master_{kind}"] = item
            manifest.append(item)
            sources[master.sha256] = ("nas", master.archive_path)
            logger.info("PixInsight: %s-Master vom NAS wiederverwendet (%s, set=%s…)",
                        kind, master.filename, set_hash[:12])
        else:
            for e in entries:
                item = {"sha256": e["sha256"], "size": e["size"], "ext": e["ext"]}
                calib_msg[f"{kind}_subs"].append(item)
                manifest.append(item)
                sources[e["sha256"]] = ("local", e["local"]) if e["local"] else ("nas", e["rel"])
            logger.info("PixInsight: %s — %d Subs, Master wird gebaut (set=%s…)",
                        kind, len(entries), set_hash[:12])

    return {
        "calib": calib_msg, "manifest": manifest, "sources": sources,
        "set_hashes": set_hashes, "entries_by_kind": entries_by_kind,
    }


async def _sync_calib_cache(
    storage, plan: dict[str, Any], tmpdir: str
) -> dict[str, Any] | None:
    """Handshake mit dem Agent-Cache: /calib/check → nur Fehlendes hochladen.

    Liefert eine Transfer-Statistik — oder None, wenn der Agent den Cache
    noch nicht kennt (alte Version) → Legacy-Fallback (Calib im ZIP)."""
    manifest = plan["manifest"]
    if not manifest:
        return {"present": 0, "uploaded": 0, "uploaded_bytes": 0}
    token = await _agent_token()
    by_sha = {m["sha256"]: m for m in manifest}
    async with httpx.AsyncClient(timeout=600.0) as client:
        resp = await client.post(
            await _agent_url("/calib/check"),
            json={"token": token, "files": list(by_sha.values())},
        )
        if resp.status_code == 404:
            return None  # Agent kennt den Calib-Cache nicht (v0.7)
        resp.raise_for_status()
        missing = [s for s in resp.json().get("missing", []) if s in by_sha]

        uploaded_bytes = 0
        for sha in missing:
            m = by_sha[sha]
            src_kind, src = plan["sources"][sha]
            local = src
            if src_kind == "nas":
                local = str(Path(tmpdir) / f"u_{sha[:16]}{m['ext']}")
                await asyncio.to_thread(storage.fetch, src, local)
            with open(local, "rb") as f:
                up = await client.post(
                    await _agent_url("/calib/upload"),
                    data={"token": token, "sha256": sha, "ext": m["ext"]},
                    files={"file": (f"{sha}{m['ext']}", f, "application/octet-stream")},
                )
                up.raise_for_status()
            uploaded_bytes += Path(local).stat().st_size
            logger.info("PixInsight: Calib hochgeladen — %s… (%s)", sha[:12], m["ext"])

    return {
        "present": len(by_sha) - len(missing),
        "uploaded": len(missing),
        "uploaded_bytes": uploaded_bytes,
    }


def _create_zip_at(files: list[tuple[str, str]], zip_path: str) -> int:
    """Erstellt ein ZIP auf Platte aus (arcname, lokaler Pfad) Paaren.

    ZIP_STORED statt DEFLATED: FITS-Daten sind Rauschen und komprimieren
    praktisch nicht — Deflate kostet nur CPU."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for arcname, local in files:
            zf.write(local, arcname)
    return Path(zip_path).stat().st_size


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


async def _harvest_calib_masters(
    db: AsyncSession, user: User, bjob: BackendJob, local_dir: Path
) -> list[str]:
    """Stufe 3: frisch gebaute Bias/Dark/Flat-Master aus dem Ergebnis
    abzweigen und aufs NAS legen (Calib/Masters/), in der DB registrieren.

    Die Dateien werden aus local_dir ENTFERNT, damit sie nicht zusätzlich
    im Prepared-Baum landen. Folgejobs mit demselben Calib-Set schicken dann
    nur noch diese Master an den Agent statt der Roh-Subs."""
    if not bjob.calib_set_hashes:
        return []
    storage = archive.get_storage(user)
    harvested: list[str] = []
    for kind, _dir_key, master_name in CALIB_KINDS:
        set_hash = bjob.calib_set_hashes.get(kind)
        if not set_hash:
            continue
        candidates = [f for f in local_dir.rglob(master_name) if f.is_file()]
        if not candidates:
            continue
        local = candidates[0]
        existing = await db.scalar(
            select(CalibMaster).where(
                CalibMaster.user_id == user.id,
                CalibMaster.kind == kind,
                CalibMaster.set_hash == set_hash,
            )
        )
        if existing:
            # Master für dieses Set schon registriert (z. B. Re-Run) —
            # Datei nur aus dem Ergebnis entfernen.
            local.unlink(missing_ok=True)
            continue
        filename = f"master_{kind}_{set_hash[:16]}.xisf"
        dest_rel = f"{CALIB_MASTERS_FOLDER}/{filename}"
        try:
            sha = await asyncio.to_thread(_sha256_file, str(local))
            size = local.stat().st_size
            await asyncio.to_thread(storage.put, dest_rel, str(local))
            db.add(CalibMaster(
                user_id=user.id, kind=kind, set_hash=set_hash,
                archive_path=dest_rel, filename=filename,
                sha256=sha, file_size=size,
            ))
            local.unlink(missing_ok=True)
            harvested.append(dest_rel)
            logger.info("PixInsight: %s-Master aufs NAS gelegt — %s (set=%s…)",
                        kind, dest_rel, set_hash[:12])
        except Exception as e:
            logger.warning("PixInsight: Konnte %s-Master nicht aufs NAS legen: %s", kind, e)
    if harvested:
        await db.flush()
    return harvested


async def _cleanup_agent_job(agent_job_id: str) -> None:
    """Sendet DELETE /jobs/{job_id} an den Agent, damit dieser seine
    Temp-Dateien (Input + Output) restlos aufraeumt."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(
                await _agent_url(f"/jobs/{agent_job_id}"),
                params={"token": await _agent_token()},
            )
            if resp.status_code == 200:
                logger.info("PixInsight: Agent-Job %s aufgeraeumt (DELETE)", agent_job_id[:8])
            elif resp.status_code == 404:
                logger.debug("PixInsight: Agent-Job %s bereits geloescht", agent_job_id[:8])
            else:
                logger.warning("PixInsight: Agent-Cleanup returned %d", resp.status_code)
    except Exception as e:
        logger.warning("PixInsight: Agent-Cleanup fehlgeschlagen (nicht kritisch): %s", e)




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

    tmpdir_obj = tempfile.TemporaryDirectory(prefix="curastro_pi_")
    tmpdir = tmpdir_obj.name
    try:
        async with async_session() as db:
            # Observation und User laden
            obs = await db.get(Observation, uuid.UUID(obs_id))
            user = await db.get(User, uuid.UUID(user_id))
            if not obs or not user:
                job.status = "failed"
                job.error = "Observation oder User nicht gefunden"
                return

            # RAW-Dateien vom NAS in ein lokales Temp-Verzeichnis holen
            logger.info("PixInsight [job=%s]: sammle RAW-Dateien …", job.id)
            raw_files = await _collect_raw_files(db, user, obs, Path(tmpdir) / "raw")
            if not raw_files:
                job.status = "failed"
                job.error = "Konnte keine RAW-Dateien vom Storage lesen"
                return

            job.input_files = len(raw_files)
            logger.info("PixInsight [job=%s]: %d RAW-Dateien gelesen", job.id, len(raw_files))

            # Kalibrier-Plan: Fingerprints (DB-Cache), Master vom NAS falls
            # vorhanden, sonst Roh-Subs — übertragen wird erst nach /calib/check.
            calib_plan = await _prepare_calibration(db, user, calib_dirs, tmpdir)
            job.calib_set_hashes = calib_plan["set_hashes"]

            # Observation-Status setzen (committet auch die CalibFile-Hashes)
            obs.status = "in_bearbeitung"
            obs.is_new = False
            await db.commit()

            storage = archive.get_storage(user)

        # Cache-Handshake mit dem Agent: nur fehlende Calib-Dateien hochladen
        legacy_calib: list[tuple[str, str]] = []
        calib_json = ""
        try:
            transfer = await _sync_calib_cache(storage, calib_plan, tmpdir)
        except Exception as e:
            logger.warning("PixInsight [job=%s]: Calib-Cache-Sync fehlgeschlagen (%s) — Legacy-Fallback", job.id, e)
            transfer = None
        if transfer is None:
            # Alter Agent ohne Calib-Cache: Roh-Subs klassisch ins ZIP packen.
            logger.warning("PixInsight [job=%s]: Agent ohne Calib-Cache — Calib-Frames wandern ins ZIP", job.id)
            for kind, entries in calib_plan["entries_by_kind"].items():
                for e in entries:
                    local = e["local"]
                    if not local:
                        local = str(Path(tmpdir) / f"l_{uuid.uuid4().hex}{e['ext']}")
                        await asyncio.to_thread(storage.fetch, e["rel"], local)
                    legacy_calib.append((e["name"], local))
        else:
            job.calib_transfer = transfer
            calib_json = json.dumps(calib_plan["calib"])
            logger.info(
                "PixInsight [job=%s]: Calib-Cache — %d im Cache, %d hochgeladen (%.1f MB)",
                job.id, transfer["present"], transfer["uploaded"],
                transfer["uploaded_bytes"] / (1024 * 1024),
            )

        # ZIP (nur Lights + ggf. Legacy-Calib) auf Platte erstellen
        zip_files = raw_files + legacy_calib
        zip_path = str(Path(tmpdir) / "raw_frames.zip")
        zip_size = await asyncio.to_thread(_create_zip_at, zip_files, zip_path)
        logger.info("PixInsight [job=%s]: ZIP erstellt (%.1f MB, %d Dateien)",
                    job.id, zip_size / (1024 * 1024), len(zip_files))

        # ZIP an Mac-Agent hochladen (gestreamt von Platte)
        agent_url = await _agent_url("/process")
        logger.info(
            "PixInsight [job=%s]: sende ZIP (%.1f MB) an %s (mode=%s, flats=%s, darks=%s, bias=%s)",
            job.id, zip_size / (1024 * 1024), agent_url, mode,
            calib_dirs.get("flats_dir") or "(keine)",
            calib_dirs.get("darks_dir") or "(keine)",
            calib_dirs.get("bias_dir") or "(keine)",
        )

        form_data = {
            "frame_info": json.dumps(frame_info),
            "mode": mode,
            "token": await _agent_token(),
        }
        if calib_json:
            form_data["calib"] = calib_json

        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                with open(zip_path, "rb") as zf_handle:
                    resp = await client.post(
                        agent_url,
                        files={"file": ("raw_frames.zip", zf_handle, "application/zip")},
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
    finally:
        tmpdir_obj.cleanup()


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

            # Frisch gebaute Bias/Dark/Flat-Master aufs NAS legen (Calib/Masters/)
            # und aus dem Ergebnis entfernen — Folgejobs nutzen sie direkt.
            harvested = await _harvest_calib_masters(db, user, bjob, tmp_path)

            # Ergebnis-Dateien ins Storage (NAS) schreiben
            prepared_rel = await prepared_reldir(db, user, obs)
            written = await _write_prepared_to_storage(user, prepared_rel, tmp_path)

        # Status auf 'vorbereitet' setzen
        obs.status = "vorbereitet"
        obs.is_new = False
        await db.flush()

        bjob.status = "completed"

        # Agent-Job restlos aufraeumen (Input + Output auf dem Mac loeschen)
        if bjob.agent_job_id:
            await _cleanup_agent_job(bjob.agent_job_id)

        return {
            "job_id": job_id,
            "status": "vorbereitet",
            "result_files": written,
            "result_count": len(written),
            "prepared_dir": prepared_rel,
            "calib_masters_saved": harvested,
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

    # 2. Calibration-Dirs aus Setup — Pfade auf dem NAS (relativ zum Archiv-Root)
    calib_dirs = await _get_calibration_dirs(db, obs)
    has_any = any(calib_dirs.values())
    storage = archive.get_storage(user)
    calib_info: dict[str, Any] = {
        "configured": has_any,
        "flats_dir": calib_dirs.get("flats_dir") or None,
        "darks_dir": calib_dirs.get("darks_dir") or None,
        "bias_dir": calib_dirs.get("bias_dir") or None,
    }
    # Calib-Verzeichnisse auf dem NAS prüfen (Dateizähler)
    for dir_key, label in [("flats_dir", "Flats"), ("darks_dir", "Darks"), ("bias_dir", "Bias")]:
        rel_dir = calib_dirs.get(dir_key, "")
        if not rel_dir:
            continue
        try:
            names = await asyncio.to_thread(storage.listdir, rel_dir)
            calib_info[dir_key + "_count"] = len(names)
            if not names:
                warnings.append({
                    "level": "warning",
                    "code": "empty_" + dir_key,
                    "message": label + "-Verzeichnis auf dem NAS ist leer oder existiert nicht: " + rel_dir,
                })
        except Exception as e:
            calib_info[dir_key + "_count"] = 0
            warnings.append({
                "level": "warning",
                "code": "unreadable_" + dir_key,
                "message": label + "-Verzeichnis auf dem NAS nicht lesbar: " + rel_dir + " (" + str(e) + ")",
            })
    if not has_any:
        warnings.append({
            "level": "warning",
            "code": "no_calibration_dir",
            "message": "Keine Calibration-Verzeichnisse für dieses Setup konfiguriert — Flats/Darks/Bias müssen im ZIP enthalten sein oder manuell in PixInsight geladen werden.",
        })

    # 3. Agent-Health
    agent = await check_agent_health()
    agent_info: dict[str, Any] = {
        "available": agent.get("available", False),
        "pixinsight_found": agent.get("pixinsight_found", False),
        "pixinsight_running": agent.get("pixinsight_running", False),
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
    elif agent.get("pixinsight_running"):
        warnings.append({
            "level": "warning",
            "code": "pixinsight_running",
            "message": "PixInsight läuft bereits (GUI oder hängengebliebener Prozess). Der Agent killt es vor dem Batch — ungespeicherte GUI-Arbeiten gehen verloren.",
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
