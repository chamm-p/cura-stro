"""ASIAir-Rig-CRUD (V2 Phase A) — Mapping ASIAir ↔ Teleskop.

Eine ASIAir je Gerät: das Mapping liefert den ``<Gerät>``-Ordner beim Import
(Phase B), da der Dateiname das Teleskop nicht enthält.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.asiair import AsiairRig
from app.models.observing import Telescope
from app.models.user import User
from app.schemas.asiair import RigCreate, RigOut, RigUpdate

router = APIRouter(prefix="/api/asiair", tags=["asiair"])


def _out(r: AsiairRig, scope: Telescope | None) -> RigOut:
    return RigOut(
        id=str(r.id),
        name=r.name,
        host=r.host,
        share=r.share,
        telescope_id=str(r.telescope_id) if r.telescope_id else None,
        telescope_name=scope.name if scope else None,
    )


async def _uuid_or_none(val: str | None) -> uuid.UUID | None:
    if not val:
        return None
    try:
        return uuid.UUID(val)
    except ValueError:
        raise HTTPException(400, "Ungültige ID")


async def _scope(db: AsyncSession, user: User, scope_id: uuid.UUID | None) -> Telescope | None:
    if not scope_id:
        return None
    scope = await db.scalar(select(Telescope).where(Telescope.id == scope_id, Telescope.user_id == user.id))
    if not scope:
        raise HTTPException(404, "Teleskop nicht gefunden")
    return scope


@router.get("/rigs", response_model=list[RigOut])
async def list_rigs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(select(AsiairRig).where(AsiairRig.user_id == user.id).order_by(AsiairRig.name)))
    scopes = {t.id: t for t in await db.scalars(select(Telescope).where(Telescope.user_id == user.id))}
    return [_out(r, scopes.get(r.telescope_id)) for r in rows]


@router.post("/rigs", response_model=RigOut, status_code=201)
async def create_rig(body: RigCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    scope_id = await _uuid_or_none(body.telescope_id)
    scope = await _scope(db, user, scope_id)
    r = AsiairRig(user_id=user.id, name=body.name, host=body.host or None, share=body.share or None, telescope_id=scope_id)
    db.add(r)
    await db.flush()
    return _out(r, scope)


async def _owned(db: AsyncSession, user: User, rig_id: str) -> AsiairRig:
    rid = await _uuid_or_none(rig_id)
    r = await db.scalar(select(AsiairRig).where(AsiairRig.id == rid, AsiairRig.user_id == user.id))
    if not r:
        raise HTTPException(404, "ASIAir nicht gefunden")
    return r


@router.patch("/rigs/{rig_id}", response_model=RigOut)
async def update_rig(
    rig_id: str, body: RigUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    r = await _owned(db, user, rig_id)
    data = body.model_dump(exclude_unset=True)
    if "telescope_id" in data:
        scope_id = await _uuid_or_none(data.pop("telescope_id"))
        await _scope(db, user, scope_id)
        r.telescope_id = scope_id
    for k in ("name", "host", "share"):
        if k in data:
            setattr(r, k, data[k] or None if k != "name" else data[k])
    await db.flush()
    scope = await db.get(Telescope, r.telescope_id) if r.telescope_id else None
    return _out(r, scope)


@router.delete("/rigs/{rig_id}", status_code=204)
async def delete_rig(rig_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, user, rig_id))
