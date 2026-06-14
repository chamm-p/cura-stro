"""Subframe-Verwaltung pro Aufnahme (V2 Phase B).

Browser-Drag&Drop-Upload + Auflistung/Aggregation. Dateien werden zwischen-
gepuffert und dann über die Speicher-Abstraktion (lokal/SMB) ins Archiv
gelegt (``RAW/<Objekt>/<Gerät>/``); Detailzahlen aggregieren unter der einen
Observation (siehe services/archive.py).
"""

import asyncio
import os
import tempfile
import uuid
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.observation import Observation
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import archive

router = APIRouter(tags=["subframes"])
settings = get_settings()
_TMP = Path(settings.outputs_dir) / "tmp"
_ALLOWED = {".fit", ".fits", ".fts", ".xisf"}


async def _owned_observation(db: AsyncSession, user: User, obs_id: str) -> Observation:
    try:
        o = await db.scalar(
            select(Observation).where(Observation.id == uuid.UUID(obs_id), Observation.user_id == user.id)
        )
    except ValueError:
        o = None
    if not o:
        raise HTTPException(404, "Aufnahme nicht gefunden")
    return o


def _frame_out(s: SubFrame) -> dict:
    return {
        "id": str(s.id), "filename": s.original_filename, "frame_type": s.frame_type,
        "filter": s.filter_name, "exposure_s": s.exposure_s, "binning": s.binning,
        "captured_at": s.captured_at.isoformat() if s.captured_at else None,
        "sequence": s.sequence, "verified": s.verified, "source": s.source,
    }


@router.get("/api/observations/{obs_id}/subframes")
async def list_subframes(obs_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    obs = await _owned_observation(db, user, obs_id)
    rows = await db.scalars(
        select(SubFrame).where(SubFrame.observation_id == obs.id).order_by(SubFrame.captured_at, SubFrame.sequence)
    )
    return {"summary": await archive.summary(db, obs), "frames": [_frame_out(s) for s in rows]}


@router.post("/api/observations/{obs_id}/subframes/upload")
async def upload_subframes(
    obs_id: str,
    files: list[UploadFile],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obs = await _owned_observation(db, user, obs_id)
    if not files:
        raise HTTPException(400, "Keine Dateien übergeben.")
    _TMP.mkdir(parents=True, exist_ok=True)

    items: list[tuple[str, str]] = []
    temps: list[str] = []
    skipped: list[str] = []
    try:
        for f in files:
            ext = Path(f.filename or "").suffix.lower()
            if ext and ext not in _ALLOWED:
                skipped.append(f.filename or "?")
                continue
            fd, tmp = tempfile.mkstemp(dir=_TMP, suffix=ext or ".fit")
            os.close(fd)
            with open(tmp, "wb") as out:
                while chunk := await f.read(1024 * 1024):
                    out.write(chunk)
            items.append((f.filename or "sub.fit", tmp))
            temps.append(tmp)
        if not items:
            raise HTTPException(400, "Keine passenden Sub-Dateien (FITS/XISF). Übersprungen: " + ", ".join(skipped))
        result = await archive.import_files(db, user, obs, items, source="upload")
    finally:
        for t in temps:
            try:
                os.unlink(t)
            except OSError:
                pass
    result["skipped"] = skipped
    return result


@router.delete("/api/observations/{obs_id}/subframes/{sub_id}", status_code=204)
async def delete_subframe(
    obs_id: str, sub_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    obs = await _owned_observation(db, user, obs_id)
    try:
        s = await db.scalar(
            select(SubFrame).where(SubFrame.id == uuid.UUID(sub_id), SubFrame.observation_id == obs.id)
        )
    except ValueError:
        s = None
    if not s:
        raise HTTPException(404, "Sub nicht gefunden")
    # Datei im aktuellen Storage entfernen (rel-Pfad rekonstruieren → SMB-fähig).
    obj = await archive.object_label(db, obs)
    dev = await archive.device_label(db, obs)
    rel = f"{archive.reldir('RAW', obj, dev)}/{PurePosixPath(s.original_filename).name}"
    storage = archive.get_storage(user)
    try:
        await asyncio.to_thread(storage.delete, rel)
    except Exception:  # noqa: BLE001
        pass
    await db.delete(s)
