"""Equipment-CRUD: Teleskope, Kameras, Filter (Phase 2)."""

import math
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.observing import Camera, Filter, Setup, Telescope, setup_filters
from app.models.user import User
from app.schemas.observing import (
    CameraCreate,
    CameraOut,
    FilterCreate,
    FilterOut,
    SetupCreate,
    SetupFilterOut,
    SetupOut,
    SetupUpdate,
    TelescopeCreate,
    TelescopeOut,
)

router = APIRouter(prefix="/api/equipment", tags=["equipment"])


# ─── Teleskope ───
def suggested_limiting_magnitude(aperture_mm: float | None) -> float | None:
    """Stellare Grenzgröße aus der Öffnung: m ≈ 2.7 + 5·log10(D_mm).

    Praktischer Richtwert für die Objektliste (Punktquellen-Limit). Bei
    ausgedehnten Objekten ist die effektive Grenze flächenhelligkeitsabhängig
    niedriger — daher nur ein Vorschlag, vom Nutzer überschreibbar."""
    if not aperture_mm or aperture_mm <= 0:
        return None
    return round(2.7 + 5.0 * math.log10(aperture_mm), 1)


def _scope_out(t: Telescope) -> TelescopeOut:
    ratio = None
    if t.aperture_mm and t.focal_length_mm and t.aperture_mm > 0:
        ratio = round(t.focal_length_mm / t.aperture_mm, 2)
    return TelescopeOut(
        id=str(t.id),
        name=t.name,
        aperture_mm=t.aperture_mm,
        focal_length_mm=t.focal_length_mm,
        limiting_magnitude=t.limiting_magnitude,
        notes=t.notes,
        focal_ratio=ratio,
        suggested_limiting_magnitude=suggested_limiting_magnitude(t.aperture_mm),
    )


@router.get("/telescopes", response_model=list[TelescopeOut])
async def list_telescopes(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Telescope).where(Telescope.user_id == user.id).order_by(Telescope.name))
    return [_scope_out(t) for t in rows]


@router.post("/telescopes", response_model=TelescopeOut, status_code=201)
async def create_telescope(
    body: TelescopeCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    t = Telescope(user_id=user.id, **body.model_dump())
    db.add(t)
    await db.flush()
    return _scope_out(t)


@router.patch("/telescopes/{tid}", response_model=TelescopeOut)
async def update_telescope(
    tid: str, body: TelescopeCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    t = await _owned(db, Telescope, user, tid)
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    await db.flush()
    return _scope_out(t)


@router.delete("/telescopes/{tid}", status_code=204)
async def delete_telescope(tid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Telescope, user, tid))


# ─── Kameras ───
def _cam_out(c: Camera) -> CameraOut:
    return CameraOut(
        id=str(c.id),
        name=c.name,
        pixel_size_um=c.pixel_size_um,
        res_x=c.res_x,
        res_y=c.res_y,
        sensor_type=c.sensor_type,
    )


@router.get("/cameras", response_model=list[CameraOut])
async def list_cameras(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Camera).where(Camera.user_id == user.id).order_by(Camera.name))
    return [_cam_out(c) for c in rows]


@router.post("/cameras", response_model=CameraOut, status_code=201)
async def create_camera(
    body: CameraCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    c = Camera(user_id=user.id, **body.model_dump())
    db.add(c)
    await db.flush()
    return _cam_out(c)


@router.patch("/cameras/{cid}", response_model=CameraOut)
async def update_camera(
    cid: str, body: CameraCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    c = await _owned(db, Camera, user, cid)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    await db.flush()
    return _cam_out(c)


@router.delete("/cameras/{cid}", status_code=204)
async def delete_camera(cid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Camera, user, cid))


# ─── Filter ───
def _filt_out(f: Filter) -> FilterOut:
    return FilterOut(id=str(f.id), name=f.name, kind=f.kind, bandwidth_nm=f.bandwidth_nm)


@router.get("/filters", response_model=list[FilterOut])
async def list_filters(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.scalars(select(Filter).where(Filter.user_id == user.id).order_by(Filter.name))
    return [_filt_out(f) for f in rows]


@router.post("/filters", response_model=FilterOut, status_code=201)
async def create_filter(
    body: FilterCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    f = Filter(user_id=user.id, **body.model_dump())
    db.add(f)
    await db.flush()
    return _filt_out(f)


@router.patch("/filters/{fid}", response_model=FilterOut)
async def update_filter(
    fid: str, body: FilterCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    f = await _owned(db, Filter, user, fid)
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    await db.flush()
    return _filt_out(f)


@router.delete("/filters/{fid}", status_code=204)
async def delete_filter(fid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Filter, user, fid))


# ─── Setups (Teleskop + Kamera + Filter) ───
async def _setup_filters(db: AsyncSession, setup_id) -> list[Filter]:
    return list(await db.scalars(
        select(Filter).join(setup_filters, setup_filters.c.filter_id == Filter.id)
        .where(setup_filters.c.setup_id == setup_id).order_by(Filter.name)
    ))


async def _setup_out(db: AsyncSession, s: Setup) -> SetupOut:
    scope = await db.get(Telescope, s.telescope_id)
    cam = await db.get(Camera, s.camera_id)
    sname = scope.name if scope else "?"
    cname = cam.name if cam else "?"
    ratio = None
    if scope and scope.aperture_mm and scope.focal_length_mm:
        ratio = round(scope.focal_length_mm / scope.aperture_mm, 2)
    flt = await _setup_filters(db, s.id)
    return SetupOut(
        id=str(s.id),
        name=s.name or f"{sname} + {cname}",
        telescope_id=str(s.telescope_id),
        telescope_name=sname,
        camera_id=str(s.camera_id),
        camera_name=cname,
        focal_ratio=ratio,
        filters=[SetupFilterOut(id=str(f.id), name=f.name, kind=f.kind, bandwidth_nm=f.bandwidth_nm) for f in flt],
    )


async def _set_setup_filters(db: AsyncSession, user: User, setup_id, filter_ids: list[str]) -> None:
    await db.execute(setup_filters.delete().where(setup_filters.c.setup_id == setup_id))
    for fid in filter_ids:
        f = await _owned(db, Filter, user, fid)
        await db.execute(setup_filters.insert().values(setup_id=setup_id, filter_id=f.id))


@router.get("/setups", response_model=list[SetupOut])
async def list_setups(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = list(await db.scalars(select(Setup).where(Setup.user_id == user.id).order_by(Setup.created_at)))
    return [await _setup_out(db, s) for s in rows]


@router.post("/setups", response_model=SetupOut, status_code=201)
async def create_setup(
    body: SetupCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    scope = await _owned(db, Telescope, user, body.telescope_id)
    cam = await _owned(db, Camera, user, body.camera_id)
    s = Setup(user_id=user.id, name=body.name, telescope_id=scope.id, camera_id=cam.id)
    db.add(s)
    await db.flush()
    await _set_setup_filters(db, user, s.id, body.filter_ids)
    return await _setup_out(db, s)


@router.patch("/setups/{sid}", response_model=SetupOut)
async def update_setup(
    sid: str, body: SetupUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    s = await _owned(db, Setup, user, sid)
    if body.name is not None:
        s.name = body.name or None
    if body.filter_ids is not None:
        await _set_setup_filters(db, user, s.id, body.filter_ids)
    await db.flush()
    return await _setup_out(db, s)


@router.delete("/setups/{sid}", status_code=204)
async def delete_setup(sid: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await db.delete(await _owned(db, Setup, user, sid))


# ─── Shared ownership helper ───
async def _owned(db: AsyncSession, model, user: User, obj_id: str):
    try:
        oid = uuid.UUID(obj_id)
    except ValueError:
        raise HTTPException(404, "Nicht gefunden")
    obj = await db.scalar(select(model).where(model.id == oid, model.user_id == user.id))
    if not obj:
        raise HTTPException(404, "Nicht gefunden")
    return obj
