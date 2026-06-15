"""Objektliste — gute Astrofoto-Ziele für Standort + Nacht (Phase 3)."""

import uuid
from datetime import datetime
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.catalog import CatalogObject
from app.models.observation import Observation
from app.models.observing import Location, Telescope
from app.models.user import User
from app.schemas.targets import TargetListOut, TargetOut
from app.services import astro, cloud_vision, clouds, weather

router = APIRouter(prefix="/api/targets", tags=["targets"])

_HIPS2FITS = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"

# Grober Typ → Filtergruppe (bewusst nicht granular).
_TYPE_GROUP = {
    "galaxy": "galaxy",
    "open_cluster": "cluster",
    "globular_cluster": "cluster",
    "emission_nebula": "nebula",
    "reflection_nebula": "nebula",
    "planetary_nebula": "nebula",
    "supernova_remnant": "nebula",
    "cluster_nebulosity": "nebula",
    "nebula": "nebula",
    "planet": "planet",
}


def _preview_url(ra: float, dec: float, size_major_arcmin: float | None) -> str:
    # Bildfeld ~2× Objektgröße, geklemmt auf 0.3°–3°. Ohne Größe: 0.5°.
    if size_major_arcmin:
        fov = min(max(size_major_arcmin / 60.0 * 2.0, 0.3), 3.0)
    else:
        fov = 0.5
    q = urlencode(
        {
            "hips": "CDS/P/DSS2/color",
            "ra": round(ra, 5),
            "dec": round(dec, 5),
            "fov": round(fov, 4),
            "width": 320,
            "height": 320,
            "projection": "TAN",
            "format": "jpg",
        }
    )
    return f"{_HIPS2FITS}?{q}"


async def _resolve_location(db: AsyncSession, user: User, location_id: str | None) -> Location:
    q = select(Location).where(Location.user_id == user.id)
    if location_id:
        try:
            loc = await db.scalar(q.where(Location.id == uuid.UUID(location_id)))
        except ValueError:
            loc = None
    else:
        # Default-Location aus Settings, sonst is_default, sonst erste.
        pref = (user.settings or {}).get("default_location_id")
        loc = None
        if pref:
            try:
                loc = await db.scalar(q.where(Location.id == uuid.UUID(pref)))
            except ValueError:
                loc = None
        if not loc:
            loc = await db.scalar(q.where(Location.is_default.is_(True)))
        if not loc:
            loc = await db.scalar(q.order_by(Location.created_at))
    if not loc:
        raise HTTPException(400, "Kein Standort vorhanden. Bitte zuerst einen anlegen.")
    return loc


@router.get("/conditions")
async def conditions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    location_id: str | None = Query(default=None),
    date: str | None = Query(default=None),
):
    """Leichter Überblick fürs Dashboard: Mond + Astrowetter für die Nacht,
    ohne die (teure) Objektberechnung."""
    try:
        loc = await _resolve_location(db, user, location_id)
    except HTTPException:
        return {"available": False, "reason": "no_location"}
    tz = loc.timezone or "UTC"
    s = user.settings or {}
    night_start = s.get("night_start") or "22:00"
    night_end = s.get("night_end") or "05:00"
    if not date:
        date = datetime.now(ZoneInfo(tz)).date().isoformat()
    moon = astro.compute_moon(
        lat=loc.latitude, lon=loc.longitude, elevation_m=loc.elevation_m, tz=tz,
        date_str=date, night_start=night_start, night_end=night_end,
    )
    wx = await weather.fetch_night_weather(loc.latitude, loc.longitude, tz, date, night_start, night_end)

    # Bestes Fenster: Dunkelheit (Mond) UND Wetter (Wolken <50 %, kein Sturm).
    # Wolken bevorzugt aus meteoblue (Vision-LLM), sonst Open-Meteo.
    mb_row = await clouds.get_cached(db, loc.id)
    mb = clouds.night_lookup(mb_row.hours) if mb_row else {}
    cloud_source = "open-meteo"

    best_window = moon.get("best_window")
    grid_iso = moon.get("grid_iso") or []
    om_cloud = {c["time"][:13]: c["cloud"] for c in (wx.get("hourly_cloud") or [])} if wx.get("available") else {}
    gust_by_hour = {g["time"][:13]: g["gust"] for g in (wx.get("hourly_wind") or [])} if wx.get("available") else {}

    if grid_iso:
        weather_ok = []
        mb_eff, mb_low, mb_mid, mb_high = [], [], [], []
        used_mb = 0
        for iso in grid_iso:
            d, hr = iso[:10], int(iso[11:13])
            mbv = mb.get((d, hr))
            if mbv:
                cloud = mbv["eff"]; used_mb += 1
                mb_eff.append(mbv["eff"]); mb_low.append(mbv["low"]); mb_mid.append(mbv["mid"]); mb_high.append(mbv["high"])
            else:
                cloud = om_cloud.get(iso[:13])
            gust = gust_by_hour.get(iso[:13])
            ok = (cloud is None or cloud < weather.CLOUD_BAD) and (gust is None or gust < weather.STORM_GUST)
            weather_ok.append(ok)

        # meteoblue deckt die Nacht überwiegend ab → Anzeige + Verdict daraus.
        if used_mb >= max(1, len(grid_iso) // 2):
            cloud_source = "meteoblue"

            def _m(xs):
                return round(sum(xs) / len(xs), 1) if xs else None

            eff_mean = _m(mb_eff)
            wx = dict(wx)
            wx["available"] = True
            wx["cloud_cover"] = eff_mean
            wx["cloud_low"], wx["cloud_mid"], wx["cloud_high"] = _m(mb_low), _m(mb_mid), _m(mb_high)
            code, text = weather._verdict(eff_mean, wx.get("precip_probability"), wx.get("wind_gusts"))
            wx["verdict"], wx["verdict_text"] = code, text

        if wx.get("available") or used_mb:
            best_window = astro.best_night_window(moon.get("grid") or [], moon.get("track") or [], weather_ok)

    wx = dict(wx)
    wx["cloud_source"] = cloud_source
    wx["clouds_fetched_at"] = mb_row.fetched_at.isoformat() if (cloud_source == "meteoblue" and mb_row and mb_row.fetched_at) else None

    return {
        "available": True,
        "location": {"name": loc.name, "id": str(loc.id)},
        "clouds": {
            "source": cloud_source,
            "fetched_at": mb_row.fetched_at.isoformat() if (cloud_source == "meteoblue" and mb_row and mb_row.fetched_at) else None,
            "can_refresh": bool(loc.meteoblue_url and cloud_vision.is_enabled()),
        },
        "date": date,
        "night_start": night_start,
        "night_end": night_end,
        "moon": {
            "illumination_pct": moon["illumination_pct"], "phase_name": moon["phase_name"],
            "up": moon["up"], "best_window": best_window,
        },
        "weather": wx,
    }


@router.get("", response_model=TargetListOut)
async def list_targets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    location_id: str | None = Query(default=None),
    date: str | None = Query(default=None, description="YYYY-MM-DD (Abend-Datum)"),
    catalog: str | None = Query(default=None, description="Messier/NGC/IC/Other"),
    type_group: str = Query(default="all", pattern="^(all|galaxy|cluster|nebula|planet)$"),
    min_altitude: float = Query(default=30.0, ge=0, le=90),
    max_magnitude: float | None = Query(default=None),
    telescope_id: str | None = Query(default=None, description="Grenzgröße aus diesem Teleskop nutzen"),
    visible_only: bool = Query(default=True),
    sort: str = Query(default="magnitude", pattern="^(magnitude|altitude)$"),
    limit: int = Query(default=300, ge=1, le=1000),
):
    loc = await _resolve_location(db, user, location_id)
    tz = loc.timezone or "UTC"

    # Teleskop → Grenzgröße. Explizit gesetztes max_magnitude hat Vorrang.
    scope = None
    scope_meta = None
    if telescope_id:
        try:
            scope = await db.scalar(
                select(Telescope).where(Telescope.id == uuid.UUID(telescope_id), Telescope.user_id == user.id)
            )
        except ValueError:
            scope = None
        if scope:
            lim = scope.limiting_magnitude
            if lim is None and scope.aperture_mm:
                from app.api.equipment import suggested_limiting_magnitude

                lim = suggested_limiting_magnitude(scope.aperture_mm)
            if max_magnitude is None:
                max_magnitude = lim
            scope_meta = {"id": str(scope.id), "name": scope.name, "limiting_magnitude": lim}

    # Settings für Nachtfenster.
    s = user.settings or {}
    night_start = s.get("night_start") or "22:00"
    night_end = s.get("night_end") or "05:00"

    if not date:
        date = datetime.now(ZoneInfo(tz)).date().isoformat()

    # ── Einheitliche Einträge bauen: DSOs (aus dem Katalog) + Planeten ──
    entries: list[dict] = []

    # DSOs nur, wenn nicht ausschließlich Planeten gefragt sind.
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
            entries.append(
                {
                    "id": str(o.id), "uuid": o.id, "catalog": o.catalog, "ident": o.ident, "name": o.name,
                    "obj_type": o.obj_type, "broadband": o.broadband, "magnitude": o.magnitude,
                    "constellation": o.constellation, "ra_deg": o.ra_deg, "dec_deg": o.dec_deg,
                    "size_major_arcmin": o.size_major_arcmin, "size_minor_arcmin": o.size_minor_arcmin,
                    "is_planet": False,
                }
            )

    # Planeten hängen am Typ-Filter, NICHT am Katalog (sie sind kein
    # Katalogobjekt): bei Typ „all" oder „planet" dabei. Sichtbarkeit kommt
    # fertig aus compute_planets (topozentrisch pro Zeitpunkt) — nicht durch
    # die Fixstern-Engine, da Planeten sich bewegen.
    include_planets = type_group in ("all", "planet")
    planet_vis: list[dict] = []
    if include_planets:
        planet_vis = astro.compute_planets(
            lat=loc.latitude, lon=loc.longitude, elevation_m=loc.elevation_m, tz=tz,
            date_str=date, night_start=night_start, night_end=night_end, min_altitude=min_altitude,
        )

    # Verwaltungs-Status pro Objekt (alle Stati), inkl. Teleskop + Rating.
    # In der Liste wird – falls ein Teleskop gefiltert ist – NUR dessen Status
    # gezeigt (M11 mit E127 entwickelt → bei RC71 keine Markierung).
    obs_rows = await db.execute(
        select(
            Observation.catalog_object_id,
            Observation.status,
            Observation.telescope_id,
            Observation.rating,
        ).where(Observation.user_id == user.id, Observation.catalog_object_id.is_not(None))
    )
    obs_map: dict = {}
    for obj_id, st, tel_id, rating in obs_rows:
        obs_map.setdefault(obj_id, []).append({"status": st, "telescope_id": tel_id, "rating": rating})
    scope_names = {s.id: s.name for s in await db.scalars(select(Telescope).where(Telescope.user_id == user.id))}
    filter_scope_uuid = scope.id if scope else None
    _RANK = {"geplant": 1, "raw": 2, "entwickelt": 3}

    def _resolve_status(obj_uuid):
        lst = obs_map.get(obj_uuid, [])
        if filter_scope_uuid is not None:
            lst = [o for o in lst if o["telescope_id"] == filter_scope_uuid]
        if not lst:
            return None, None, False, 0, []
        best = max(lst, key=lambda o: (_RANK.get(o["status"], 0), o["rating"] or 0))
        shot = [o for o in lst if o["status"] in ("raw", "entwickelt")]
        scopes = sorted({scope_names[o["telescope_id"]] for o in shot if o["telescope_id"] in scope_names})
        return best["status"], best["rating"], len(shot) > 0, len(shot), scopes

    grid_labels, vis = astro.compute_visibility(
        lat=loc.latitude,
        lon=loc.longitude,
        elevation_m=loc.elevation_m,
        tz=tz,
        date_str=date,
        night_start=night_start,
        night_end=night_end,
        objects=[{"id": e["id"], "ra_deg": e["ra_deg"], "dec_deg": e["dec_deg"]} for e in entries],
        min_altitude=min_altitude,
    )

    # Mond + Mondabstände (für Breitband/Schmalband-Warnungen).
    moon = astro.compute_moon(
        lat=loc.latitude, lon=loc.longitude, elevation_m=loc.elevation_m, tz=tz,
        date_str=date, night_start=night_start, night_end=night_end,
    )
    sep_by_id: dict[str, float] = {}
    if entries:
        ra_arr = np.array([e["ra_deg"] for e in entries])
        dec_arr = np.array([e["dec_deg"] for e in entries])
        seps = astro.angular_separation_deg(moon["ra_deg"], moon["dec_deg"], ra_arr, dec_arr)
        sep_by_id = {e["id"]: float(seps[i]) for i, e in enumerate(entries)}

    # Wetter + stündliche Bewölkung auf das Höhen-Raster mappen, damit pro
    # Objekt ein „bestes Aufnahmefenster" (Höhe × klarer Himmel) berechenbar ist.
    wx = await weather.fetch_night_weather(loc.latitude, loc.longitude, tz, date, night_start, night_end)
    grid_local, _ = astro.night_grid(date, night_start, night_end, tz)
    cloud_by_hour = {h["time"][:13]: h["cloud"] for h in (wx.get("hourly_cloud") or [])}
    gust_by_hour = {h["time"][:13]: h["gust"] for h in (wx.get("hourly_wind") or [])}

    # Wolken bevorzugt aus meteoblue (Vision-LLM), sonst Open-Meteo.
    mb_row = await clouds.get_cached(db, loc.id)
    mb = clouds.night_lookup(mb_row.hours) if mb_row else {}
    clouds_grid: list[float | None] = []
    mb_eff, mb_low, mb_mid, mb_high = [], [], [], []
    for g in grid_local:
        mbv = mb.get((g.strftime("%Y-%m-%d"), g.hour))
        if mbv:
            clouds_grid.append(mbv["eff"])
            mb_eff.append(mbv["eff"]); mb_low.append(mbv["low"]); mb_mid.append(mbv["mid"]); mb_high.append(mbv["high"])
        else:
            clouds_grid.append(cloud_by_hour.get(g.strftime("%Y-%m-%dT%H")))

    wx = dict(wx)
    if len(mb_eff) >= max(1, len(grid_local) // 2):
        def _m(xs):
            return round(sum(xs) / len(xs), 1) if xs else None
        wx["available"] = True
        wx["cloud_cover"] = _m(mb_eff)
        wx["cloud_low"], wx["cloud_mid"], wx["cloud_high"] = _m(mb_low), _m(mb_mid), _m(mb_high)
        code, text = weather._verdict(_m(mb_eff), wx.get("precip_probability"), wx.get("wind_gusts"))
        wx["verdict"], wx["verdict_text"] = code, text
        wx["cloud_source"] = "meteoblue"
        wx["clouds_fetched_at"] = mb_row.fetched_at.isoformat() if mb_row and mb_row.fetched_at else None
    else:
        wx["cloud_source"] = "open-meteo"

    # Nacht-Bestfenster (Mond × klar × windstill) — auch fürs Objektbrowser-Bar.
    weather_ok = [
        (clouds_grid[i] is None or clouds_grid[i] < weather.CLOUD_BAD)
        and (gust_by_hour.get(g.strftime("%Y-%m-%dT%H")) is None or gust_by_hour.get(g.strftime("%Y-%m-%dT%H")) < weather.STORM_GUST)
        for i, g in enumerate(grid_local)
    ]
    moon = dict(moon)
    moon["best_window"] = astro.best_night_window(moon.get("grid") or [], moon.get("track") or [], weather_ok)

    def _window(track: list[float]) -> dict | None:
        return astro.recommend_window(track, grid_labels, clouds_grid, min_altitude)

    targets: list[TargetOut] = []
    for e in entries:
        v = vis[e["id"]]
        if visible_only and not v["visible"]:
            continue
        st, rating, photographed, cap_count, cap_scopes = _resolve_status(e["uuid"]) if e["uuid"] is not None else (None, None, False, 0, [])
        sep = sep_by_id.get(e["id"])
        impact, note = astro.moon_impact(e["broadband"], sep if sep is not None else 180.0, moon["illumination"], moon["up"])
        win = _window(v["track"])
        targets.append(
            TargetOut(
                id=e["id"],
                catalog=e["catalog"],
                ident=e["ident"],
                name=e["name"],
                obj_type=e["obj_type"],
                broadband=e["broadband"],
                magnitude=e["magnitude"],
                constellation=e["constellation"],
                ra_deg=e["ra_deg"],
                dec_deg=e["dec_deg"],
                size_major_arcmin=e["size_major_arcmin"],
                size_minor_arcmin=e["size_minor_arcmin"],
                max_altitude=v["max_altitude"],
                best_time_local=v["best_time_local"],
                azimuth_at_best=v["azimuth_at_best"],
                visible=v["visible"],
                altitude_track=v["track"],
                best_window_start=win["start"] if win else None,
                best_window_end=win["end"] if win else None,
                best_window_reason=win["reason"] if win else None,
                moon_separation_deg=round(sep, 1) if sep is not None else None,
                moon_impact=impact,
                moon_note=note,
                status=st,
                rating=rating,
                photographed=photographed,
                capture_count=cap_count,
                telescopes=cap_scopes,
                preview_url="" if e["is_planet"] else _preview_url(e["ra_deg"], e["dec_deg"], e["size_major_arcmin"]),
            )
        )

    # Planeten anhängen (eigene, topozentrische Sichtbarkeit).
    for p in planet_vis:
        if max_magnitude is not None and p["magnitude"] is not None and p["magnitude"] > max_magnitude:
            continue
        if visible_only and not p["visible"]:
            continue
        pwin = _window(p["track"])
        targets.append(
            TargetOut(
                id=p["id"], catalog="Planet", ident=p["ident"], name=p["name"],
                obj_type="planet", broadband=True, magnitude=p["magnitude"], constellation=None,
                ra_deg=0.0, dec_deg=0.0, size_major_arcmin=None, size_minor_arcmin=None,
                max_altitude=p["max_altitude"], best_time_local=p["best_time_local"],
                azimuth_at_best=p["azimuth_at_best"], visible=p["visible"], altitude_track=p["track"],
                best_window_start=pwin["start"] if pwin else None,
                best_window_end=pwin["end"] if pwin else None,
                best_window_reason=pwin["reason"] if pwin else None,
                photographed=False, capture_count=0, telescopes=[], preview_url="",
            )
        )

    if sort == "altitude":
        targets.sort(key=lambda t: (t.max_altitude is None, -(t.max_altitude or 0)))
    else:  # magnitude (hell → dunkel)
        targets.sort(key=lambda t: (t.magnitude is None, t.magnitude if t.magnitude is not None else 99))

    targets = targets[:limit]
    return TargetListOut(
        location={
            "id": str(loc.id),
            "name": loc.name,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "bortle": loc.bortle,
            "timezone": tz,
            "seeing_available": bool(loc.meteoblue_url),
        },
        date=date,
        night_start=night_start,
        night_end=night_end,
        time_grid=grid_labels,
        magnitude_limit=max_magnitude,
        telescope=scope_meta,
        moon=moon,
        weather=wx,
        count=len(targets),
        targets=targets,
    )
