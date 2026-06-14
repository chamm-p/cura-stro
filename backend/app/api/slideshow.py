"""Slideshow (Backlog) — beste Astrofotos.

Pro Objekt + Geräte-Gruppe (z. B. M11 + E127) das Bild der höchstbewerteten
Aufnahme; nur Aufnahmen mit Rating ≥ 3 werden gezeigt.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.catalog import CatalogObject
from app.models.image import Image
from app.models.observation import Observation
from app.models.observing import Telescope
from app.models.user import User

router = APIRouter(prefix="/api/slideshow", tags=["slideshow"])

_MIN_RATING = 3


@router.get("")
async def slideshow(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    rows = await db.execute(
        select(Observation, CatalogObject, Telescope)
        .outerjoin(CatalogObject, CatalogObject.id == Observation.catalog_object_id)
        .outerjoin(Telescope, Telescope.id == Observation.telescope_id)
        .where(
            Observation.user_id == user.id,
            Observation.rating.is_not(None),
            Observation.rating >= _MIN_RATING,
        )
    )
    # Pro (Objekt, Teleskop) die höchstbewertete Aufnahme behalten.
    best: dict = {}
    for o, obj, scope in rows:
        key = (str(o.catalog_object_id) if o.catalog_object_id else f"label:{o.target_label}", str(o.telescope_id))
        cur = best.get(key)
        if cur is None or o.rating > cur["rating"]:
            best[key] = {"obs": o, "obj": obj, "scope": scope, "rating": o.rating}

    slides = []
    for v in best.values():
        img = await db.scalar(
            select(Image).where(Image.observation_id == v["obs"].id).order_by(Image.created_at.desc())
        )
        if not img:
            continue
        label = (v["obj"].ident if v["obj"] else None) or v["obs"].target_label or "—"
        slides.append({
            "image_id": str(img.id),
            "jpg_url": f"/api/images/{img.id}/jpg",
            "label": label,
            "name": v["obj"].name if v["obj"] else None,
            "telescope": v["scope"].name if v["scope"] else None,
            "rating": v["rating"],
        })
    slides.sort(key=lambda s: s["label"])
    return {"count": len(slides), "slides": slides}
