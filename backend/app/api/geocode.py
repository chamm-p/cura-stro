"""Geocoding-Proxy für die Auto-Ortung (Phase 2).

Reverse (Koordinaten → Ortsname) via OpenStreetMap Nominatim, Forward
(Suche) ebenfalls. Backend-seitig, damit der nötige User-Agent gesetzt
ist und keine CORS-Probleme im Browser entstehen. Höhe (elevation) via
Open-Meteo Elevation-API (kostenlos, kein Key).
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/api/geocode", tags=["geocode"])

_UA = {"User-Agent": "cura-stro/0.1 (astrophotography app)"}


@router.get("/reverse")
async def reverse(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    _: User = Depends(get_current_user),
):
    async with httpx.AsyncClient(timeout=10.0, headers=_UA) as client:
        try:
            r = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "json", "zoom": 12, "accept-language": "de"},
            )
            r.raise_for_status()
            data = r.json()
            elev = await _elevation(client, lat, lon)
        except httpx.HTTPError:
            raise HTTPException(502, "Geocoding-Dienst nicht erreichbar")

    addr = data.get("address", {})
    name = (
        addr.get("village")
        or addr.get("town")
        or addr.get("city")
        or addr.get("municipality")
        or addr.get("county")
        or data.get("display_name", "Mein Standort").split(",")[0]
    )
    return {"name": name, "latitude": lat, "longitude": lon, "elevation_m": elev}


@router.get("/search")
async def search(q: str = Query(..., min_length=2), _: User = Depends(get_current_user)):
    async with httpx.AsyncClient(timeout=10.0, headers=_UA) as client:
        try:
            r = await client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": q, "format": "json", "limit": 6, "accept-language": "de"},
            )
            r.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(502, "Geocoding-Dienst nicht erreichbar")
    out = []
    for item in r.json():
        out.append(
            {
                "name": item.get("display_name", "").split(",")[0],
                "display_name": item.get("display_name"),
                "latitude": float(item["lat"]),
                "longitude": float(item["lon"]),
            }
        )
    return out


async def _elevation(client: httpx.AsyncClient, lat: float, lon: float) -> float | None:
    try:
        r = await client.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": lat, "longitude": lon},
        )
        r.raise_for_status()
        vals = r.json().get("elevation")
        if isinstance(vals, list) and vals:
            return round(float(vals[0]), 1)
    except (httpx.HTTPError, KeyError, ValueError, TypeError):
        return None
    return None
