"""Verwaltung der Beobachtungen / Aufnahmen (Phase 5).

Jede Zeile = eine Aufnahme eines Objekts mit einem Teleskop in einer Nacht,
Status geplant → raw → entwickelt. Ein Objekt kann mehrere Aufnahmen haben
(verschiedene Geräte/Nächte)."""

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.services import archive
from app.models.catalog import CatalogObject
from app.models.image import Image
from app.models.observation import Observation
from app.models.observing import Telescope
from app.models.result_file import ResultFile
from app.models.subframe import SubFrame
from app.models.user import User
from app.schemas.observation import ObservationCreate, ObservationOut, ObservationUpdate, PlanRequest
from sqlalchemy import func

router = APIRouter(prefix="/api/observations", tags=["observations"])


def _out(
    o: Observation,
    obj: CatalogObject | None,
    scope: Telescope | None,
    image_count: int = 0,
    subframe_count: int = 0,
    integration_s: float = 0.0,
    result_count: int = 0,
) -> ObservationOut:
    label = (obj.ident if obj else None) or o.target_label or "—"
    return ObservationOut(
        id=str(o.id),
        catalog_object_id=str(o.catalog_object_id) if o.catalog_object_id else None,
        object_ident=obj.ident if obj else None,
        object_name=obj.name if obj else None,
        object_type=obj.obj_type if obj else None,
        object_catalog=obj.catalog if obj else None,
        target_label=o.target_label,
        display_label=label,
        status=o.status,
        telescope_id=str(o.telescope_id) if o.telescope_id else None,
        telescope_name=scope.name if scope else None,
        planned_date=o.planned_date,
        rating=o.rating,
        notes=o.notes,
        is_new=o.is_new,
        created_at=o.created_at.isoformat() if o.created_at else None,
        image_count=image_count,
        subframe_count=subframe_count,
        integration_s=integration_s,
        result_count=result_count,
    )


@router.get("", response_model=list[ObservationOut])
async def list_observations(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(Observation, CatalogObject, Telescope)
        .outerjoin(CatalogObject, CatalogObject.id == Observation.catalog_object_id)
        .outerjoin(Telescope, Telescope.id == Observation.telescope_id)
        .where(Observation.user_id == user.id)
        .order_by(Observation.created_at.desc())
    )
    counts = dict(
        (oid, n)
        for oid, n in await db.execute(
            select(Image.observation_id, func.count()).where(Image.user_id == user.id).group_by(Image.observation_id)
        )
    )
    sub_stats = {
        oid: (n, integ or 0.0)
        for oid, n, integ in await db.execute(
            select(SubFrame.observation_id, func.count(), func.coalesce(func.sum(SubFrame.exposure_s), 0.0))
            .where(SubFrame.user_id == user.id)
            .group_by(SubFrame.observation_id)
        )
    }
    res_counts = dict(
        (oid, n)
        for oid, n in await db.execute(
            select(ResultFile.observation_id, func.count()).where(ResultFile.user_id == user.id).group_by(ResultFile.observation_id)
        )
    )
    return [
        _out(o, obj, scope, counts.get(o.id, 0), *sub_stats.get(o.id, (0, 0.0)), res_counts.get(o.id, 0))
        for o, obj, scope in rows
    ]


async def _uuid_or_none(val: str | None) -> uuid.UUID | None:
    if not val:
        return None
    try:
        return uuid.UUID(val)
    except ValueError:
        raise HTTPException(400, "Ungültige ID")


@router.post("", response_model=ObservationOut, status_code=201)
async def create_observation(
    body: ObservationCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    cat_id = await _uuid_or_none(body.catalog_object_id)
    scope_id = await _uuid_or_none(body.telescope_id)
    if not cat_id and not body.target_label:
        raise HTTPException(400, "Katalogobjekt oder Freitext-Ziel erforderlich")

    obj = await db.get(CatalogObject, cat_id) if cat_id else None
    if cat_id and not obj:
        raise HTTPException(404, "Katalogobjekt nicht gefunden")
    scope = None
    if scope_id:
        scope = await db.scalar(select(Telescope).where(Telescope.id == scope_id, Telescope.user_id == user.id))
        if not scope:
            raise HTTPException(404, "Teleskop nicht gefunden")

    o = Observation(
        user_id=user.id,
        catalog_object_id=cat_id,
        target_label=body.target_label,
        status=body.status,
        telescope_id=scope_id,
        planned_date=body.planned_date,
        rating=body.rating,
        notes=body.notes,
    )
    db.add(o)
    await db.flush()
    return _out(o, obj, scope)


@router.post("/plan", response_model=ObservationOut, status_code=201)
async def plan_observation(
    body: PlanRequest, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """„Einplanen" aus der Objektliste. Existiert das Objekt für dieses
    Teleskop schon, wird kein Duplikat erzeugt: Status zurück auf „geplant",
    Rating/Bilder bleiben erhalten (es wird darauf aufgebaut). In beiden
    Fällen als „neu" markiert."""
    cat_id = await _uuid_or_none(body.catalog_object_id)
    scope_id = await _uuid_or_none(body.telescope_id)
    if not cat_id and not body.target_label:
        raise HTTPException(400, "Objekt erforderlich")

    obj = await db.get(CatalogObject, cat_id) if cat_id else None
    if cat_id and not obj:
        raise HTTPException(404, "Katalogobjekt nicht gefunden")
    scope = None
    if scope_id:
        scope = await db.scalar(select(Telescope).where(Telescope.id == scope_id, Telescope.user_id == user.id))
        if not scope:
            raise HTTPException(404, "Teleskop nicht gefunden")

    # Bestehenden Eintrag (Objekt + Teleskop) suchen.
    q = select(Observation).where(Observation.user_id == user.id)
    if cat_id:
        q = q.where(Observation.catalog_object_id == cat_id)
    else:
        q = q.where(Observation.target_label == body.target_label, Observation.catalog_object_id.is_(None))
    q = q.where(Observation.telescope_id.is_(None) if scope_id is None else Observation.telescope_id == scope_id)
    o = await db.scalar(q)

    if o:
        o.status = "geplant"   # zurück auf Planung; Rating/Bilder bleiben.
        o.is_new = True
    else:
        o = Observation(
            user_id=user.id, catalog_object_id=cat_id, target_label=body.target_label,
            status="geplant", telescope_id=scope_id, is_new=True,
        )
        db.add(o)
    await db.flush()
    n = await db.scalar(select(func.count()).select_from(Image).where(Image.observation_id == o.id))
    return _out(o, obj, scope, n or 0)


async def _owned(db: AsyncSession, user: User, obs_id: str) -> Observation:
    oid = await _uuid_or_none(obs_id)
    o = await db.scalar(select(Observation).where(Observation.id == oid, Observation.user_id == user.id))
    if not o:
        raise HTTPException(404, "Aufnahme nicht gefunden")
    return o


@router.patch("/{obs_id}", response_model=ObservationOut)
async def update_observation(
    obs_id: str, body: ObservationUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    o = await _owned(db, user, obs_id)
    data = body.model_dump(exclude_unset=True)
    if "telescope_id" in data:
        sid = await _uuid_or_none(data["telescope_id"])
        if sid:
            scope = await db.scalar(select(Telescope).where(Telescope.id == sid, Telescope.user_id == user.id))
            if not scope:
                raise HTTPException(404, "Teleskop nicht gefunden")
        o.telescope_id = sid
        data.pop("telescope_id")
    for k, v in data.items():
        setattr(o, k, v)
    o.is_new = False  # Bearbeitung in der Verwaltung → nicht mehr „neu".
    await db.flush()

    obj = await db.get(CatalogObject, o.catalog_object_id) if o.catalog_object_id else None
    scope = await db.get(Telescope, o.telescope_id) if o.telescope_id else None
    return _out(o, obj, scope)


@router.delete("/{obs_id}", status_code=204)
async def delete_observation(obs_id: str, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    o = await _owned(db, user, obs_id)
    # Zugehörige (lokale) Bilddateien entfernen (DB-Cascade löscht nur Zeilen).
    imgs = await db.scalars(select(Image).where(Image.observation_id == o.id))
    for img in imgs:
        for p in (img.file_path, img.jpg_path):
            if p:
                Path(p).unlink(missing_ok=True)

    # Subframe-Dateien im Archiv (lokal ODER NAS) über die Storage-Schicht
    # löschen — UNC-Pfade kann Path.unlink nicht; daher rel rekonstruieren.
    subs = list(await db.scalars(select(SubFrame).where(SubFrame.observation_id == o.id)))
    if subs:
        storage = archive.get_storage(user)
        base = archive.reldir(archive.folder_name(user, "RAW"),
                              await archive.object_label(db, o), await archive.device_label(db, o))
        prev_dir = Path(get_settings().outputs_dir) / "subprev"
        for s in subs:
            try:
                await asyncio.to_thread(storage.delete, f"{base}/{s.original_filename}")
            except Exception:  # noqa: BLE001
                pass
            (prev_dir / f"{s.id}.jpg").unlink(missing_ok=True)  # Vorschau-Cache
    await db.delete(o)
