"""Objekt-Detail inkl. Hintergrundinfos (Phase 3b)."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.catalog import CatalogObject
from app.models.user import User
from app.services import object_info as oi
from app.services import sky_preview

router = APIRouter(prefix="/api/objects", tags=["objects"])


def _preview_url(ra: float, dec: float, size_major_arcmin: float | None) -> str:
    fov = min(max((size_major_arcmin or 30) / 60.0 * 2.0, 0.3), 3.0)
    return sky_preview.build_url(ra, dec, fov, px=500)


@router.get("/{ident}")
async def object_detail(
    ident: str,
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj = await db.scalar(select(CatalogObject).where(CatalogObject.ident == ident))
    if not obj:
        raise HTTPException(404, "Objekt nicht gefunden")
    info = await oi.get_object_info(db, obj, refresh=refresh)
    return {
        "ident": obj.ident,
        "name": obj.name,
        "catalog": obj.catalog,
        "obj_type": obj.obj_type,
        "constellation": obj.constellation,
        "magnitude": obj.magnitude,
        "ra_deg": obj.ra_deg,
        "dec_deg": obj.dec_deg,
        "preview_url": _preview_url(obj.ra_deg, obj.dec_deg, obj.size_major_arcmin),
        "facts": info.facts or {},
        "background": {
            "source": info.source,
            "title": info.title,
            "text": info.text,
            "url": info.url,
        },
    }
