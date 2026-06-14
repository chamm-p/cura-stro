"""Filing-Core (V2 Phase B) — Subs ins NAS-Archiv einsortieren.

Gemeinsame Logik für beide Importwege (Browser-Drag&Drop und ASIAir-SMB):
parst den ASIAir-Dateinamen, legt die Datei unter
``<root>/RAW/<Objekt>/<Gerät>/`` ab, schreibt einen ``SubFrame``-Datensatz
(Dublettenschutz) und aggregiert alles unter der *einen* Observation. Der
Status wandert dabei von ``geplant`` auf ``raw`` (``entwickelt`` bleibt).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.catalog import CatalogObject
from app.models.observation import Observation
from app.models.observing import Telescope
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import asiair as asi

_cfg = get_settings()


def effective_archive_root(user: User) -> str:
    """Archiv-Wurzel: Nutzer-Override aus Settings, sonst config/ENV."""
    return (user.settings or {}).get("archive_root") or _cfg.archive_root


async def object_label(db: AsyncSession, obs: Observation) -> str:
    """Ordnername für das Objekt: Katalog-Ident (z. B. „M11") oder Freitext."""
    if obs.catalog_object_id:
        obj = await db.get(CatalogObject, obs.catalog_object_id)
        if obj and obj.ident:
            return obj.ident
    return obs.target_label or "Unbenannt"


async def device_label(db: AsyncSession, obs: Observation) -> str:
    """Ordnername für das Gerät: Teleskopname (= dein <Gerät>-Ordner)."""
    if obs.telescope_id:
        scope = await db.get(Telescope, obs.telescope_id)
        if scope and scope.name:
            return scope.name
    return "Unbekannt"


async def target_dir(db: AsyncSession, user: User, obs: Observation, kind: str = "RAW") -> Path:
    root = effective_archive_root(user)
    obj = await object_label(db, obs)
    dev = await device_label(db, obs)
    return Path(str(asi.archive_dir(root, kind, obj, dev)))


async def _existing_filenames(db: AsyncSession, obs: Observation) -> set[str]:
    rows = await db.scalars(
        select(SubFrame.original_filename).where(SubFrame.observation_id == obs.id)
    )
    return set(rows)


def _bump_status(obs: Observation) -> None:
    """Geplant → raw, sobald Subs da sind. „entwickelt" bleibt unangetastet."""
    if obs.status != "entwickelt":
        obs.status = "raw"
    obs.is_new = False


async def file_one(
    db: AsyncSession,
    user: User,
    obs: Observation,
    filename: str,
    writer: Callable[[Path], Awaitable[int]],
    *,
    source: str,
    dest: Path | None = None,
    known: set[str] | None = None,
) -> dict:
    """Eine Datei ablegen + ``SubFrame`` schreiben. ``writer`` erhält den
    Zielpfad und gibt die geschriebene Größe zurück. Liefert ein Status-Dict
    (``filed`` | ``duplicate``)."""
    safe_name = Path(filename).name
    if known is not None and safe_name in known:
        return {"file": safe_name, "status": "duplicate"}

    parsed = asi.parse_frame_filename(safe_name)
    if dest is None:
        dest = await target_dir(db, user, obs, "RAW")
    dest.mkdir(parents=True, exist_ok=True)
    out_path = dest / safe_name

    size = await writer(out_path)
    verified = out_path.exists() and size > 0

    sub = SubFrame(
        user_id=user.id,
        observation_id=obs.id,
        frame_type=(parsed.frame_type if parsed else "Light"),
        filter_name=(parsed.filter_name if parsed else None),
        exposure_s=(parsed.exposure_s if parsed else None),
        binning=(parsed.binning if parsed else None),
        captured_at=(parsed.captured_at if parsed else None),
        sequence=(parsed.sequence if parsed else None),
        original_filename=safe_name,
        archive_path=str(out_path),
        file_size=size,
        source=source,
        verified=verified,
    )
    db.add(sub)
    if known is not None:
        known.add(safe_name)
    return {"file": safe_name, "status": "filed", "parsed": parsed is not None,
            "filter": parsed.filter_name if parsed else None}


async def import_streams(
    db: AsyncSession,
    user: User,
    obs: Observation,
    items: list[tuple[str, Callable[[Path], Awaitable[int]]]],
    *,
    source: str,
) -> dict:
    """Mehrere Dateien einsortieren. ``items`` = Liste (Dateiname, writer)."""
    known = await _existing_filenames(db, obs)
    dest = await target_dir(db, user, obs, "RAW")
    results = []
    for name, writer in items:
        results.append(await file_one(db, user, obs, name, writer, source=source, dest=dest, known=known))
    filed = [r for r in results if r["status"] == "filed"]
    if filed:
        _bump_status(obs)
    await db.flush()
    return {
        "filed": len(filed),
        "duplicates": sum(1 for r in results if r["status"] == "duplicate"),
        "results": results,
        "dest": str(dest),
        "summary": await summary(db, obs),
    }


async def summary(db: AsyncSession, obs: Observation) -> dict:
    """Aggregat über alle Subs der Aufnahme (pro Filter)."""
    rows = await db.scalars(select(SubFrame).where(SubFrame.observation_id == obs.id))
    subs = list(rows)
    agg = asi.aggregate_frames([
        {"filter_name": s.filter_name, "exposure_s": s.exposure_s} for s in subs
    ])
    nights = sorted({s.captured_at.date().isoformat() for s in subs if s.captured_at})
    return {**agg, "nights": nights, "verified": sum(1 for s in subs if s.verified)}


# ─── Writer-Fabriken ───
def streaming_writer(upload, chunk_size: int = 1024 * 1024) -> Callable[[Path], Awaitable[int]]:
    """Writer für FastAPI-UploadFile: streamt auf Platte (kein Voll-RAM)."""
    async def _write(out_path: Path) -> int:
        size = 0
        with open(out_path, "wb") as f:
            while chunk := await upload.read(chunk_size):
                f.write(chunk)
                size += len(chunk)
        return size
    return _write


def copyfile_writer(src_path: str) -> Callable[[Path], Awaitable[int]]:
    """Writer, der eine vorhandene Datei (z. B. SMB-temp) ans Ziel kopiert."""
    async def _write(out_path: Path) -> int:
        shutil.copyfile(src_path, out_path)
        return out_path.stat().st_size
    return _write
