"""meteoblue-Wolken-Cache + täglicher Refresh (V2).

Hält pro Standort die per Vision-LLM extrahierten Wolken-Schichten vor
(``cloud_forecasts``) und liefert eine Lookup-Funktion für die Wetterlogik.
Ein Hintergrund-Scheduler aktualisiert 1×/Tag (deckt ~3 Tage ab)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import get_settings
from app.database import async_session
from app.models.cloud_forecast import CloudForecast
from app.models.observing import Location
from app.services import cloud_vision

logger = logging.getLogger("uvicorn.error")
_cfg = get_settings()


async def get_cached(db, location_id) -> CloudForecast | None:
    return await db.scalar(select(CloudForecast).where(CloudForecast.location_id == location_id))


def night_lookup(hours: list[dict]) -> dict[tuple[str, int], dict]:
    """{(YYYY-MM-DD, hour): {low,mid,high,eff}} — eff = schlechteste Schicht."""
    out: dict[tuple[str, int], dict] = {}
    for h in hours or []:
        try:
            key = (h["date"], int(h["hour"]))
            low, mid, high = int(h.get("low", 0)), int(h.get("mid", 0)), int(h.get("high", 0))
            out[key] = {"low": low, "mid": mid, "high": high, "eff": max(low, mid, high)}
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def refresh_location(db, location: Location) -> int:
    """Wolken für einen Standort neu holen + cachen. Liefert Stundenzahl."""
    if not location.meteoblue_url or not cloud_vision.is_enabled():
        return 0
    hours = await cloud_vision.fetch_clouds(location.meteoblue_url)
    if not hours:
        logger.info("Wolken-Refresh %s: keine Daten", location.name)
        return 0
    row = await get_cached(db, location.id)
    now = datetime.now(timezone.utc)
    if row:
        row.hours = hours
        row.fetched_at = now
        row.source = "meteoblue"
    else:
        db.add(CloudForecast(user_id=location.user_id, location_id=location.id,
                             source="meteoblue", hours=hours, fetched_at=now))
    await db.flush()
    logger.info("Wolken-Refresh %s: %d Stunden", location.name, len(hours))
    return len(hours)


async def refresh_all() -> dict:
    """Alle Standorte mit meteoblue-URL aktualisieren (eigene Session)."""
    if not cloud_vision.is_enabled():
        return {"refreshed": 0, "skipped": "vision_disabled"}
    total = 0
    async with async_session() as db:
        locs = list(await db.scalars(select(Location).where(Location.meteoblue_url.is_not(None))))
        for loc in locs:
            try:
                total += await refresh_location(db, loc)
            except Exception as e:  # noqa: BLE001
                logger.warning("Wolken-Refresh %s fehlgeschlagen: %s", loc.name, e)
        await db.commit()
    return {"locations": len(locs) if cloud_vision.is_enabled() else 0, "hours": total}


async def daily_refresh_loop():
    """Hintergrund-Scheduler: beim Start (falls Cache fehlt/alt) + alle 24 h."""
    if not (_cfg.cloud_refresh_enabled and cloud_vision.is_enabled()):
        logger.info("Wolken-Scheduler aus (deaktiviert oder kein LLM).")
        return
    # Kurz warten, bis die App vollständig oben ist.
    await asyncio.sleep(20)
    while True:
        try:
            res = await refresh_all()
            logger.info("Wolken-Scheduler: %s", res)
        except Exception:  # noqa: BLE001
            logger.exception("Wolken-Scheduler-Lauf fehlgeschlagen")
        await asyncio.sleep(24 * 3600)
