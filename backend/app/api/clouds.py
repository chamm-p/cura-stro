"""meteoblue-Wolken (Vision-LLM): Status + manueller Refresh (V2)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.observing import Location
from app.models.user import User
from app.services import cloud_vision, clouds

router = APIRouter(prefix="/api/clouds", tags=["clouds"])


async def _loc(db: AsyncSession, user: User, location_id: str) -> Location:
    try:
        loc = await db.scalar(select(Location).where(Location.id == uuid.UUID(location_id), Location.user_id == user.id))
    except ValueError:
        loc = None
    if not loc:
        raise HTTPException(404, "Standort nicht gefunden")
    return loc


@router.get("/status")
async def status(location_id: str = Query(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    loc = await _loc(db, user, location_id)
    row = await clouds.get_cached(db, loc.id)
    return {
        "vision_enabled": cloud_vision.is_enabled(),
        "has_url": bool(loc.meteoblue_url),
        "source": row.source if row else None,
        "fetched_at": row.fetched_at.isoformat() if row and row.fetched_at else None,
        "hours": len(row.hours) if row and row.hours else 0,
    }


@router.post("/refresh")
async def refresh(location_id: str = Query(...), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    loc = await _loc(db, user, location_id)
    if not cloud_vision.is_enabled():
        raise HTTPException(400, "Vision-LLM nicht konfiguriert (LLM_GATEWAY_URL/LLM_TOKEN).")
    if not loc.meteoblue_url:
        raise HTTPException(400, "Für diesen Standort ist keine meteoblue-URL hinterlegt.")
    n = await clouds.refresh_location(db, loc)
    row = await clouds.get_cached(db, loc.id)
    return {"hours": n, "fetched_at": row.fetched_at.isoformat() if row and row.fetched_at else None}
