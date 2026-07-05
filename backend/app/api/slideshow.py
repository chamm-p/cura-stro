"""Slideshow — beste Astrofotos.

Primärquelle: Ergebnisbilder, die im Ergebnis-Modal als FINAL markiert
wurden (Häkchen — das sind die fertig entwickelten Endergebnisse, n pro
Aufnahme möglich).

Legacy-Fallback: für (Objekt, Teleskop)-Gruppen OHNE finale Ergebnisse
gilt weiter die alte Regel — das Phase-6-Upload-Bild der höchstbewerteten
Aufnahme mit Rating ≥ 3.
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
from app.models.result_file import ResultFile
from app.models.user import User

router = APIRouter(prefix="/api/slideshow", tags=["slideshow"])

_MIN_RATING = 3


def _group_key(o: Observation) -> tuple[str, str]:
    return (
        str(o.catalog_object_id) if o.catalog_object_id else f"label:{o.target_label}",
        str(o.telescope_id),
    )


@router.get("")
async def slideshow(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    slides = []

    # 1. Finale Ergebnisbilder (explizit markiert → keine Rating-Hürde).
    final_rows = await db.execute(
        select(ResultFile, Observation, CatalogObject, Telescope)
        .join(Observation, Observation.id == ResultFile.observation_id)
        .outerjoin(CatalogObject, CatalogObject.id == Observation.catalog_object_id)
        .outerjoin(Telescope, Telescope.id == Observation.telescope_id)
        .where(ResultFile.user_id == user.id, ResultFile.is_final.is_(True))
    )
    final_keys: set[tuple[str, str]] = set()
    for r, o, obj, scope in final_rows:
        final_keys.add(_group_key(o))
        label = (obj.ident if obj else None) or o.target_label or "—"
        slides.append({
            "image_id": f"res:{r.id}",
            "jpg_url": f"/api/results/{r.id}/preview",
            "label": label,
            "name": obj.name if obj else None,
            "telescope": scope.name if scope else None,
            "rating": o.rating or 0,
        })

    # 2. Legacy: Gruppen ohne finale Ergebnisse — höchstbewertete Aufnahme
    #    (Rating ≥ 3) mit Phase-6-Upload-Bild.
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
    best: dict = {}
    for o, obj, scope in rows:
        key = _group_key(o)
        if key in final_keys:
            continue
        cur = best.get(key)
        if cur is None or o.rating > cur["rating"]:
            best[key] = {"obs": o, "obj": obj, "scope": scope, "rating": o.rating}

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
