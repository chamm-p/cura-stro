"""Subframe-Verwaltung pro Aufnahme (V2 Phase B).

Browser-Drag&Drop-Upload + Auflistung/Aggregation. Die Dateien wandern ins
NAS-Archiv (``RAW/<Objekt>/<Gerät>/``), die Detailzahlen aggregieren unter der
einen Observation (siehe services/archive.py).
"""

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.observation import Observation
from app.models.subframe import SubFrame
from app.models.user import User
from app.services import archive

router = APIRouter(tags=["subframes"])

# Akzeptierte Sub-Endungen (zusätzlich erlauben wir unbekannte – nichts geht verloren).
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
        "id": str(s.id),
        "filename": s.original_filename,
        "frame_type": s.frame_type,
        "filter": s.filter_name,
        "exposure_s": s.exposure_s,
        "binning": s.binning,
        "captured_at": s.captured_at.isoformat() if s.captured_at else None,
        "sequence": s.sequence,
        "verified": s.verified,
        "source": s.source,
    }


@router.get("/api/observations/{obs_id}/subframes")
async def list_subframes(obs_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    obs = await _owned_observation(db, user, obs_id)
    rows = await db.scalars(
        select(SubFrame).where(SubFrame.observation_id == obs.id).order_by(SubFrame.captured_at, SubFrame.sequence)
    )
    frames = [_frame_out(s) for s in rows]
    return {"summary": await archive.summary(db, obs), "frames": frames}


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
    items = []
    skipped = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext and ext not in _ALLOWED:
            skipped.append(f.filename)
            continue
        items.append((f.filename or "sub.fit", archive.streaming_writer(f)))
    if not items:
        raise HTTPException(400, "Keine passenden Sub-Dateien (FITS/XISF). Übersprungen: " + ", ".join(skipped))
    result = await archive.import_streams(db, user, obs, items, source="upload")
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
    if s.archive_path:
        Path(s.archive_path).unlink(missing_ok=True)
    await db.delete(s)
