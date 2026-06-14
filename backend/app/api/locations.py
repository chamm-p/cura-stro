"""Standort-CRUD (Phase 2)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.observing import Location
from app.models.user import User
from app.schemas.observing import LocationCreate, LocationOut, LocationUpdate

router = APIRouter(prefix="/api/locations", tags=["locations"])


def _out(loc: Location) -> LocationOut:
    return LocationOut(
        id=str(loc.id),
        name=loc.name,
        latitude=loc.latitude,
        longitude=loc.longitude,
        elevation_m=loc.elevation_m,
        timezone=loc.timezone,
        bortle=loc.bortle,
        meteoblue_url=loc.meteoblue_url,
        is_default=loc.is_default,
    )


async def _clear_default(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Location).where(Location.user_id == user_id).values(is_default=False)
    )


@router.get("", response_model=list[LocationOut])
async def list_locations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(
        select(Location).where(Location.user_id == user.id).order_by(Location.is_default.desc(), Location.name)
    )
    return [_out(r) for r in rows]


@router.post("", response_model=LocationOut, status_code=201)
async def create_location(
    body: LocationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    if body.is_default:
        await _clear_default(db, user.id)
    loc = Location(user_id=user.id, **body.model_dump())
    db.add(loc)
    await db.flush()
    return _out(loc)


async def _get_owned(db: AsyncSession, user: User, loc_id: str) -> Location:
    try:
        lid = uuid.UUID(loc_id)
    except ValueError:
        raise HTTPException(404, "Standort nicht gefunden")
    loc = await db.scalar(select(Location).where(Location.id == lid, Location.user_id == user.id))
    if not loc:
        raise HTTPException(404, "Standort nicht gefunden")
    return loc


@router.patch("/{loc_id}", response_model=LocationOut)
async def update_location(
    loc_id: str, body: LocationUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    loc = await _get_owned(db, user, loc_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("is_default"):
        await _clear_default(db, user.id)
    for k, v in data.items():
        setattr(loc, k, v)
    await db.flush()
    return _out(loc)


@router.delete("/{loc_id}", status_code=204)
async def delete_location(
    loc_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    loc = await _get_owned(db, user, loc_id)
    await db.delete(loc)
