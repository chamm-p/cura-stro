"""PixInsight-Ergebnisse (V2 Phase C) — Registrierung + Watch-Folder.

Ergebnisbilder liegen im NAS-Archiv unter ``Developer/<Objekt>/<Gerät>/``.
Der Watch-Folder scannt diese Ordner und hängt neu aufgetauchte Master
automatisch an die passende Aufnahme (Status → entwickelt)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import PurePosixPath

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session
from app.models.observation import Observation
from app.models.result_file import ResultFile
from app.models.user import User
from app.services import archive

logger = logging.getLogger("uvicorn.error")
_cfg = get_settings()

RESULT_EXTS = {".xisf", ".tif", ".tiff", ".fit", ".fits", ".fts", ".jpg", ".jpeg", ".png"}


async def developer_reldir(db, user: User, obs: Observation) -> str:
    return archive.reldir(archive.folder_name(user, "Developer"),
                          await archive.object_label(db, obs), await archive.device_label(db, obs))


async def _existing(db, obs: Observation) -> set[str]:
    return set(await db.scalars(select(ResultFile.filename).where(ResultFile.observation_id == obs.id)))


async def scan_import(db, user: User, obs: Observation, *, source: str = "watch") -> int:
    """Developer-Ordner der Aufnahme scannen und neue Bild-Master registrieren.
    Liefert die Anzahl neu hinzugefügter Ergebnisse."""
    storage = archive.get_storage(user)
    reld = await developer_reldir(db, user, obs)
    try:
        names = await asyncio.to_thread(storage.listdir, reld)
    except Exception:  # noqa: BLE001
        names = []
    known = await _existing(db, obs)
    added = 0
    for nm in names:
        if nm in known or PurePosixPath(nm).suffix.lower() not in RESULT_EXTS:
            continue
        rel = f"{reld}/{nm}"
        db.add(ResultFile(user_id=user.id, observation_id=obs.id, filename=nm,
                          archive_path=storage.full_path(rel), source=source))
        known.add(nm)
        added += 1
    if added:
        if obs.status != "entwickelt":
            obs.status = "entwickelt"
        obs.is_new = False
    await db.flush()
    return added


async def watch_loop():
    """Hintergrund-Scheduler: scannt regelmäßig die Developer-Ordner aller
    Aufnahmen mit Daten (Status raw/entwickelt) und hängt neue Master an."""
    if not _cfg.result_watch_enabled:
        logger.info("Result-Watch aus (deaktiviert).")
        return
    await asyncio.sleep(30)
    while True:
        try:
            async with async_session() as db:
                obss = list(await db.scalars(
                    select(Observation).where(Observation.status.in_(["raw", "entwickelt"]))))
                total = 0
                for obs in obss:
                    user = await db.get(User, obs.user_id)
                    if not user:
                        continue
                    try:
                        total += await scan_import(db, user, obs)
                    except Exception:  # noqa: BLE001
                        pass
                await db.commit()
                if total:
                    logger.info("Result-Watch: %d neue Ergebnis(se) angehängt", total)
        except Exception:  # noqa: BLE001
            logger.exception("Result-Watch-Lauf fehlgeschlagen")
        await asyncio.sleep(_cfg.result_watch_interval_min * 60)
