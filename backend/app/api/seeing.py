"""meteoblue-Seeing: Proxy + Cache zum Playwright-Scraper (Phase 4).

Holt den Seeing-Tabellen-Screenshot vom weather-scraper-Sidecar und cacht
ihn pro Standort als PNG (TTL aus den Settings). Verhindert, dass jeder
Aufruf meteoblue neu lädt (Scrape dauert ~8–10 s)."""

import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import get_settings
from app.database import get_db
from app.models.observing import Location
from app.models.user import User

router = APIRouter(prefix="/api/seeing", tags=["seeing"])
settings = get_settings()
_CACHE_DIR = Path(settings.outputs_dir) / "seeing"


async def _resolve(db: AsyncSession, user: User, location_id: str) -> Location:
    try:
        loc = await db.scalar(
            select(Location).where(Location.id == uuid.UUID(location_id), Location.user_id == user.id)
        )
    except ValueError:
        loc = None
    if not loc:
        raise HTTPException(404, "Standort nicht gefunden")
    return loc


@router.get("")
async def seeing_status(
    location_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    loc = await _resolve(db, user, location_id)
    return {
        "available": bool(loc.meteoblue_url),
        "image_url": f"/api/seeing/image?location_id={location_id}" if loc.meteoblue_url else None,
        "source_url": loc.meteoblue_url,
    }


@router.get("/image")
async def seeing_image(
    location_id: str = Query(...),
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    loc = await _resolve(db, user, location_id)
    if not loc.meteoblue_url:
        raise HTTPException(404, "Kein meteoblue-Link für diesen Standort hinterlegt")

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = _CACHE_DIR / f"{loc.id}.png"
    ttl = settings.seeing_cache_ttl_min * 60
    if not refresh and cache.exists() and (time.time() - cache.stat().st_mtime) < ttl:
        return FileResponse(cache, media_type="image/png")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.get(
                f"{settings.seeing_scraper_url}/seeing", params={"url": loc.meteoblue_url}
            )
            r.raise_for_status()
            cache.write_bytes(r.content)
    except httpx.HTTPError as e:
        if cache.exists():  # Stale-Cache besser als nichts.
            return FileResponse(cache, media_type="image/png")
        raise HTTPException(502, f"Seeing-Scraper nicht erreichbar: {e}")
    return FileResponse(cache, media_type="image/png")
