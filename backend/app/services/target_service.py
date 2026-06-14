"""Kernlogik der Objektliste — entkoppelt vom Web-Endpoint, damit sie auch
vom MCP-Server (Phase 8) genutzt werden kann. Ohne Teleskop-/Observations-
Scoping (das braucht der externe Abruf nicht)."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogObject
from app.models.observing import Location
from app.models.user import User
from app.services import astro, weather

_TYPE_GROUP = {
    "galaxy": "galaxy", "open_cluster": "cluster", "globular_cluster": "cluster",
    "emission_nebula": "nebula", "reflection_nebula": "nebula", "planetary_nebula": "nebula",
    "supernova_remnant": "nebula", "cluster_nebulosity": "nebula", "nebula": "nebula",
    "planet": "planet",
}
_TYPE_DE = {
    "galaxy": "Galaxie", "open_cluster": "Offener Sternhaufen", "globular_cluster": "Kugelsternhaufen",
    "planetary_nebula": "Planetarischer Nebel", "emission_nebula": "Emissionsnebel",
    "reflection_nebula": "Reflexionsnebel", "supernova_remnant": "Supernova-Überrest",
    "cluster_nebulosity": "Sternhaufen mit Nebel", "nebula": "Nebel", "planet": "Planet",
}


async def resolve_location(db: AsyncSession, user: User, location_name: str | None) -> Location | None:
    q = select(Location).where(Location.user_id == user.id)
    if location_name:
        rows = list(await db.scalars(q))
        for loc in rows:
            if loc.name.lower() == location_name.lower():
                return loc
        for loc in rows:
            if location_name.lower() in loc.name.lower():
                return loc
    pref = (user.settings or {}).get("default_location_id")
    if pref:
        try:
            loc = await db.scalar(q.where(Location.id == uuid.UUID(pref)))
            if loc:
                return loc
        except ValueError:
            pass
    loc = await db.scalar(q.where(Location.is_default.is_(True)))
    return loc or await db.scalar(q.order_by(Location.created_at))


async def good_targets(
    db: AsyncSession,
    user: User,
    *,
    date: str | None = None,
    location_name: str | None = None,
    catalog: str | None = None,
    type_group: str = "all",
    min_altitude: float = 30.0,
    max_magnitude: float | None = None,
    sort: str = "magnitude",
    limit: int = 15,
) -> dict:
    loc = await resolve_location(db, user, location_name)
    if not loc:
        return {"error": "Kein Standort vorhanden."}
    tz = loc.timezone or "UTC"
    s = user.settings or {}
    night_start = s.get("night_start") or "22:00"
    night_end = s.get("night_end") or "05:00"
    if not date:
        date = datetime.now(ZoneInfo(tz)).date().isoformat()

    # DSO-Einträge
    entries: list[dict] = []
    if type_group != "planet":
        groups = [g for g, v in _TYPE_GROUP.items() if v == type_group] if type_group != "all" else None
        q = select(CatalogObject)
        if catalog and catalog.lower() != "all":
            q = q.where(CatalogObject.catalog == catalog)
        if groups is not None:
            q = q.where(CatalogObject.obj_type.in_(groups))
        if max_magnitude is not None:
            q = q.where(CatalogObject.magnitude.is_not(None), CatalogObject.magnitude <= max_magnitude)
        for o in await db.scalars(q):
            entries.append({
                "id": str(o.id), "catalog": o.catalog, "ident": o.ident, "name": o.name,
                "obj_type": o.obj_type, "broadband": o.broadband, "magnitude": o.magnitude,
                "constellation": o.constellation, "ra_deg": o.ra_deg, "dec_deg": o.dec_deg,
            })

    grid_labels, vis = astro.compute_visibility(
        lat=loc.latitude, lon=loc.longitude, elevation_m=loc.elevation_m, tz=tz,
        date_str=date, night_start=night_start, night_end=night_end,
        objects=[{"id": e["id"], "ra_deg": e["ra_deg"], "dec_deg": e["dec_deg"]} for e in entries],
        min_altitude=min_altitude,
    )
    moon = astro.compute_moon(lat=loc.latitude, lon=loc.longitude, elevation_m=loc.elevation_m,
                              tz=tz, date_str=date, night_start=night_start, night_end=night_end)
    wx = await weather.fetch_night_weather(loc.latitude, loc.longitude, tz, date, night_start, night_end)
    grid_local, _ = astro.night_grid(date, night_start, night_end, tz)
    cloud_by_hour = {h["time"][:13]: h["cloud"] for h in (wx.get("hourly_cloud") or [])}
    clouds_grid = [cloud_by_hour.get(g.strftime("%Y-%m-%dT%H")) for g in grid_local]

    sep_by_id = {}
    if entries:
        ras = np.array([e["ra_deg"] for e in entries]); decs = np.array([e["dec_deg"] for e in entries])
        seps = astro.angular_separation_deg(moon["ra_deg"], moon["dec_deg"], ras, decs)
        sep_by_id = {e["id"]: float(seps[i]) for i, e in enumerate(entries)}

    out: list[dict] = []
    for e in entries:
        v = vis[e["id"]]
        if not v["visible"]:
            continue
        sep = sep_by_id.get(e["id"], 180.0)
        impact, note = astro.moon_impact(e["broadband"], sep, moon["illumination"], moon["up"])
        win = astro.recommend_window(v["track"], grid_labels, clouds_grid, min_altitude)
        out.append({
            "ident": e["ident"], "name": e["name"], "type": _TYPE_DE.get(e["obj_type"], e["obj_type"]),
            "catalog": e["catalog"], "magnitude": e["magnitude"], "constellation": e["constellation"],
            "max_altitude_deg": v["max_altitude"], "best_time": v["best_time_local"][11:16] if v["best_time_local"] else None,
            "best_window": f"{win['start']}–{win['end']}" if win else None,
            "filter_class": "Breitband" if e["broadband"] else "Schmalband",
            "moon_impact": impact, "moon_note": note,
        })

    # Planeten
    if type_group in ("all", "planet"):
        for p in astro.compute_planets(lat=loc.latitude, lon=loc.longitude, elevation_m=loc.elevation_m,
                                       tz=tz, date_str=date, night_start=night_start, night_end=night_end,
                                       min_altitude=min_altitude):
            if not p["visible"]:
                continue
            if max_magnitude is not None and p["magnitude"] is not None and p["magnitude"] > max_magnitude:
                continue
            win = astro.recommend_window(p["track"], grid_labels, clouds_grid, min_altitude)
            out.append({
                "ident": p["ident"], "name": p["name"], "type": "Planet", "catalog": "Planet",
                "magnitude": p["magnitude"], "constellation": None,
                "max_altitude_deg": p["max_altitude"], "best_time": p["best_time_local"][11:16],
                "best_window": f"{win['start']}–{win['end']}" if win else None,
                "filter_class": "Breitband", "moon_impact": "none", "moon_note": None,
            })

    if sort == "altitude":
        out.sort(key=lambda t: (t["max_altitude_deg"] is None, -(t["max_altitude_deg"] or 0)))
    else:
        out.sort(key=lambda t: (t["magnitude"] is None, t["magnitude"] if t["magnitude"] is not None else 99))
    out = out[:limit]

    return {
        "location": loc.name, "date": date, "night": f"{night_start}–{night_end}",
        "moon": {"phase": moon["phase_name"], "illumination_pct": moon["illumination_pct"], "up": moon["up"]},
        "weather": {"available": wx.get("available", False), "verdict": wx.get("verdict_text"),
                    "cloud_cover_pct": wx.get("cloud_cover")},
        "count": len(out), "targets": out,
    }


async def astro_weather(db: AsyncSession, user: User, *, date: str | None = None, location_name: str | None = None) -> dict:
    loc = await resolve_location(db, user, location_name)
    if not loc:
        return {"error": "Kein Standort vorhanden."}
    tz = loc.timezone or "UTC"
    s = user.settings or {}
    night_start = s.get("night_start") or "22:00"
    night_end = s.get("night_end") or "05:00"
    if not date:
        date = datetime.now(ZoneInfo(tz)).date().isoformat()
    moon = astro.compute_moon(lat=loc.latitude, lon=loc.longitude, elevation_m=loc.elevation_m,
                              tz=tz, date_str=date, night_start=night_start, night_end=night_end)
    wx = await weather.fetch_night_weather(loc.latitude, loc.longitude, tz, date, night_start, night_end)
    return {
        "location": loc.name, "date": date, "night": f"{night_start}–{night_end}",
        "bortle": loc.bortle,
        "moon": {"phase": moon["phase_name"], "illumination_pct": moon["illumination_pct"],
                 "up": moon["up"], "max_altitude_deg": moon["max_altitude"]},
        "weather": wx,
    }
