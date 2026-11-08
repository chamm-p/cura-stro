"""Katalog-Vorschaubilder (DSS2) — serverseitiger Proxy mit Cache.

Liefert das Vorschaubild zu einer Himmelskoordinate aus. Holt es bei Bedarf
einmalig von CDS (mit Mirror-Fallback), cacht es im outputs-Volume und
bedient alle weiteren Aufrufe aus dem Cache. Siehe services/sky_preview.py.

Bewusst OHNE Auth: Es werden nur öffentliche Katalog-/Himmelsdaten geliefert
(wie zuvor die direkte CDS-URL), und das <img>-Tag im Frontend kann keinen
Bearer-Header mitschicken.
"""

import asyncio

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.services import sky_preview

router = APIRouter(prefix="/api/sky", tags=["sky"])


@router.get("/preview")
async def sky_preview_image(
    ra: float = Query(..., ge=0.0, le=360.0),
    dec: float = Query(..., ge=-90.0, le=90.0),
    fov: float = Query(0.5, gt=0.0, le=10.0),
    px: int = Query(400, ge=64, le=1000),
):
    try:
        path = await asyncio.to_thread(sky_preview.fetch_cached, ra, dec, fov, px)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Vorschau nicht verfügbar: {e}")
    # Lange cachen: Katalog-Objekte ändern sich nie. Der Graustufen-Notnagel nur
    # kurz, damit der Browser später das Farbbild holt.
    max_age = 3600 if path.name.endswith(".gray.jpg") else 604800
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": f"public, max-age={max_age}"})
