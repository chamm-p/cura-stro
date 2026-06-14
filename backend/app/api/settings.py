"""Nutzer-Settings: Nachtfenster + Default-Standort (in user.settings JSONB)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.observing import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/api/settings", tags=["settings"])

DEFAULTS = {"night_start": "22:00", "night_end": "05:00", "default_location_id": None}


def _read(user: User) -> SettingsOut:
    s = {**DEFAULTS, **(user.settings or {})}
    return SettingsOut(
        night_start=s.get("night_start") or "22:00",
        night_end=s.get("night_end") or "05:00",
        default_location_id=s.get("default_location_id"),
    )


@router.get("", response_model=SettingsOut)
async def get_settings(user: User = Depends(get_current_user)):
    return _read(user)


@router.patch("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    new = dict(user.settings or {})
    new.update(body.model_dump(exclude_unset=True))
    user.settings = new  # Reassign → SQLAlchemy erkennt die JSONB-Änderung.
    await db.flush()
    return _read(user)
