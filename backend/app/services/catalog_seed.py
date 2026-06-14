"""Seedet den gebündelten Deep-Sky-Katalog (app/data/catalog.json) in die DB,
falls die Tabelle leer ist. Läuft beim Backend-Start (idempotent)."""

import json
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogObject

logger = logging.getLogger(__name__)
_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.json"


async def seed_catalog(db: AsyncSession) -> None:
    count = await db.scalar(select(func.count()).select_from(CatalogObject))
    if count and count > 0:
        return
    if not _CATALOG_PATH.exists():
        logger.warning("Katalogdatei fehlt: %s", _CATALOG_PATH)
        return
    data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    for e in data:
        db.add(
            CatalogObject(
                catalog=e["catalog"],
                ident=e["ident"],
                name=e.get("name"),
                ra_deg=e["ra_deg"],
                dec_deg=e["dec_deg"],
                magnitude=e.get("magnitude"),
                obj_type=e["obj_type"],
                broadband=e.get("broadband", True),
                size_major_arcmin=e.get("size_major_arcmin"),
                size_minor_arcmin=e.get("size_minor_arcmin"),
                constellation=e.get("constellation"),
                source_name=e.get("source_name"),
            )
        )
    await db.commit()
    logger.info("✅ Katalog geseedet: %d Objekte", len(data))
