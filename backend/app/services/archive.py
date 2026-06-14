"""Filing-Core (V2 Phase B) — Subs ins Archiv einsortieren.

Schreibt über eine Speicher-Abstraktion (lokal ODER NAS-SMB, siehe
services/storage.py): parst den ASIAir-Dateinamen, legt die Datei unter
``RAW/<Objekt>/<Gerät>/`` ab, schreibt einen ``SubFrame`` (Dublettenschutz)
und aggregiert alles unter der *einen* Observation. Status: geplant → raw
(entwickelt bleibt).
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.catalog import CatalogObject
from app.models.observation import Observation
from app.models.observing import Telescope
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import asiair as asi
from app.services.storage import LocalStorage, SmbStorage, Storage

_cfg = get_settings()


# ─── Konfiguration / Speicher-Backend ───
def archive_config(user: User) -> dict:
    """Archiv-Konfig aus user.settings['archive'] (Default: lokal)."""
    a = dict((user.settings or {}).get("archive") or {})
    return {
        "mode": a.get("mode") or "local",
        "root": a.get("root") or _cfg.archive_root,
        "nas": dict(a.get("nas") or {}),
    }


def get_storage(user: User, override: dict | None = None) -> Storage:
    cfg = override or archive_config(user)
    if cfg.get("mode") == "smb":
        nas = cfg.get("nas") or {}
        return SmbStorage(nas.get("host"), nas.get("share"), nas.get("path"),
                          nas.get("username"), nas.get("password"))
    return LocalStorage(cfg.get("root"))


def effective_archive_root(user: User) -> str:
    return get_storage(user).display_root()


# ─── Pfad-/Label-Logik ───
async def object_label(db: AsyncSession, obs: Observation) -> str:
    if obs.catalog_object_id:
        obj = await db.get(CatalogObject, obs.catalog_object_id)
        if obj and obj.ident:
            return obj.ident
    return obs.target_label or "Unbenannt"


async def device_label(db: AsyncSession, obs: Observation) -> str:
    if obs.telescope_id:
        scope = await db.get(Telescope, obs.telescope_id)
        if scope and scope.name:
            return scope.name
    return "Unbekannt"


def reldir(kind: str, obj_label: str, dev_label: str) -> str:
    if kind not in ("RAW", "Developer"):
        raise ValueError(f"Ungültige Archiv-Art: {kind!r}")
    return f"{kind}/{asi.safe_component(obj_label)}/{asi.safe_component(dev_label)}"


async def _existing_filenames(db: AsyncSession, obs: Observation) -> set[str]:
    rows = await db.scalars(
        select(SubFrame.original_filename).where(SubFrame.observation_id == obs.id)
    )
    return set(rows)


def _bump_status(obs: Observation) -> None:
    if obs.status != "entwickelt":
        obs.status = "raw"
    obs.is_new = False


# ─── Import ───
async def import_files(
    db: AsyncSession,
    user: User,
    obs: Observation,
    items: list[tuple[str, str]],
    *,
    source: str,
    kind: str = "RAW",
) -> dict:
    """``items`` = Liste (Originalname, lokaler Temp-Pfad). Legt jede Datei via
    Storage ab und schreibt die SubFrame-Zeilen."""
    storage = get_storage(user)
    obj = await object_label(db, obs)
    dev = await device_label(db, obs)
    base = reldir(kind, obj, dev)
    known = await _existing_filenames(db, obs)
    results = []
    filed = 0

    for name, temp_path in items:
        from pathlib import PurePosixPath
        safe = PurePosixPath(name.replace("\\", "/")).name
        if safe in known:
            results.append({"file": safe, "status": "duplicate"})
            continue
        parsed = asi.parse_frame_filename(safe)
        rel = f"{base}/{safe}"
        try:
            size = await asyncio.to_thread(storage.put, rel, temp_path)
        except Exception as e:  # noqa: BLE001
            results.append({"file": safe, "status": "error", "error": str(e)})
            continue
        verified = size > 0
        db.add(SubFrame(
            user_id=user.id, observation_id=obs.id,
            frame_type=(parsed.frame_type if parsed else "Light"),
            filter_name=(parsed.filter_name if parsed else None),
            exposure_s=(parsed.exposure_s if parsed else None),
            binning=(parsed.binning if parsed else None),
            captured_at=(parsed.captured_at if parsed else None),
            sequence=(parsed.sequence if parsed else None),
            original_filename=safe, archive_path=storage.full_path(rel),
            file_size=size, source=source, verified=verified,
        ))
        known.add(safe)
        filed += 1
        results.append({"file": safe, "status": "filed",
                        "filter": parsed.filter_name if parsed else None})

    if filed:
        _bump_status(obs)
    await db.flush()
    return {
        "filed": filed,
        "duplicates": sum(1 for r in results if r["status"] == "duplicate"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "results": results,
        "dest": storage.full_path(base),
        "summary": await summary(db, obs),
    }


async def summary(db: AsyncSession, obs: Observation) -> dict:
    rows = await db.scalars(select(SubFrame).where(SubFrame.observation_id == obs.id))
    subs = list(rows)
    agg = asi.aggregate_frames([
        {"filter_name": s.filter_name, "exposure_s": s.exposure_s} for s in subs
    ])
    nights = sorted({s.captured_at.date().isoformat() for s in subs if s.captured_at})
    return {**agg, "nights": nights, "verified": sum(1 for s in subs if s.verified)}


async def delete_subframe_file(user: User, archive_path: str | None, rel: str | None = None) -> None:
    """Best-effort: Datei im aktuellen Storage entfernen (für Subframe-Delete)."""
    if not archive_path and not rel:
        return
    storage = get_storage(user)
    try:
        if rel:
            await asyncio.to_thread(storage.delete, rel)
        elif isinstance(storage, LocalStorage) and archive_path:
            from pathlib import Path
            await asyncio.to_thread(lambda: Path(archive_path).unlink(missing_ok=True))
    except Exception:  # noqa: BLE001
        pass
