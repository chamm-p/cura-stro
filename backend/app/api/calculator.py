"""Framing- & Belichtungs-Rechner (Phase 7).

Aus Teleskop (Öffnung/Brennweite) + Kamera (Pixelgröße/Auflösung) +
Standort-Bortle berechnet:
  • Bildmaßstab ("/px), Bildfeld (FoV), Sampling-Hinweis
  • Framing: wie groß ein Objekt im Sensorausschnitt erscheint (+ Preview)
  • Belichtungsempfehlung pro Filter (sky-/leserausch-limitiert, nach R. Glover)

Das Belichtungsmodell ist physikalisch motiviert, nutzt aber typische
Annahmen (QE, Leserauschen, Transmission) — die Sub-Längen sind Richtwerte,
deren Verhältnisse (Bortle, f-Verhältnis, Schmal-/Breitband) stimmen.
"""

import math
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.catalog import CatalogObject
from app.models.observing import Camera, Filter, Location, Setup, Telescope, setup_filters
from app.models.user import User

router = APIRouter(prefix="/api/calculator", tags=["calculator"])

# Bortle → Himmelshelligkeit (SQM, mag/arcsec²) — Näherung.
_BORTLE_SQM = {1: 22.0, 2: 21.7, 3: 21.5, 4: 21.3, 5: 20.5, 6: 19.5, 7: 18.7, 8: 18.2, 9: 17.8}

# Konstanten Belichtungsmodell.
_P0 = 1000.0      # Photonen/cm²/s/Å für mag 0 (V-Band, grob)
_TRANSMISSION = 0.5
_DEFAULT_QE = 0.8
_DEFAULT_RN = 2.0   # e- Leserauschen (moderne CMOS)
_C = 10.0           # Leserausch-Beitrag ~5% (Glover) → t = C·RN²/skyRate
_SUB_CAP = {"broadband": 300, "narrowband": 600}  # praktische Obergrenze (s)
# Standard-Belichtungsleiter (s) — krumme Optimalwerte werden hierauf gerundet.
_SUB_LADDER = [10, 15, 20, 30, 45, 60, 90, 120, 180, 240, 300, 420, 600]


def _snap_sub(t: float, cap: int) -> int:
    cands = [v for v in _SUB_LADDER if v <= cap] or [_SUB_LADDER[0]]
    return min(cands, key=lambda v: abs(v - min(t, cap)))


def _bandwidth_angstrom(f: Filter) -> float:
    if f.bandwidth_nm:
        return f.bandwidth_nm * 10.0
    # Breitband ohne Bandbreite: L ≈ 300 nm, RGB ≈ 100 nm.
    return 3000.0 if f.name.strip().upper() in ("L", "LUM", "CLEAR") else 1000.0


def _preview_url(ra: float, dec: float, fov_deg: float) -> str:
    fov = min(max(fov_deg, 0.05), 5.0)
    q = urlencode({
        "hips": "CDS/P/DSS2/color", "ra": round(ra, 5), "dec": round(dec, 5),
        "fov": round(fov, 4), "width": 360, "height": 360, "projection": "TAN", "format": "jpg",
    })
    return f"https://alasky.cds.unistra.fr/hips-image-services/hips2fits?{q}"


@router.get("")
async def calculate(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    setup_id: str | None = Query(default=None),
    telescope_id: str | None = Query(default=None),
    camera_id: str | None = Query(default=None),
    location_id: str | None = Query(default=None),
    object_ident: str | None = Query(default=None),
    bortle: int | None = Query(default=None, ge=1, le=9),
    read_noise: float = Query(default=_DEFAULT_RN, gt=0),
    qe: float = Query(default=_DEFAULT_QE, gt=0, le=1),
    max_sub_s: int | None = Query(default=None, ge=10, le=1200, description="Obergrenze Einzelbelichtung (s)"),
):
    async def _owned(model, oid):
        try:
            return await db.scalar(select(model).where(model.id == uuid.UUID(oid), model.user_id == user.id))
        except ValueError:
            return None

    # Setup (Teleskop+Kamera+Filter gebündelt) hat Vorrang.
    setup_filter_objs = None  # None = kein Setup; [] = Setup ohne Filter (OSC/One-Shot)
    if setup_id:
        setup = await _owned(Setup, setup_id)
        if not setup:
            raise HTTPException(404, "Setup nicht gefunden")
        telescope_id, camera_id = str(setup.telescope_id), str(setup.camera_id)
        setup_filter_objs = list(await db.scalars(
            select(Filter).join(setup_filters, setup_filters.c.filter_id == Filter.id)
            .where(setup_filters.c.setup_id == setup.id).order_by(Filter.name)
        ))
    if not telescope_id or not camera_id:
        raise HTTPException(400, "Setup oder Teleskop + Kamera erforderlich")

    scope = await _owned(Telescope, telescope_id)
    cam = await _owned(Camera, camera_id)
    if not scope:
        raise HTTPException(404, "Teleskop nicht gefunden")
    if not cam:
        raise HTTPException(404, "Kamera nicht gefunden")
    if not scope.focal_length_mm or not cam.pixel_size_um or not cam.res_x or not cam.res_y:
        raise HTTPException(400, "Teleskop-Brennweite und Kamera (Pixelgröße + Auflösung) erforderlich.")

    # Bortle bestimmen.
    if bortle is None and location_id:
        loc = await _owned(Location, location_id)
        if loc and loc.bortle:
            bortle = loc.bortle
    if bortle is None:
        loc = await db.scalar(select(Location).where(Location.user_id == user.id, Location.is_default.is_(True)))
        if loc and loc.bortle:
            bortle = loc.bortle
    bortle = bortle or 5

    # ── Framing ──
    focal = scope.focal_length_mm
    px = cam.pixel_size_um
    scale = 206.265 * px / focal  # "/px
    sensor_w_mm = cam.res_x * px / 1000.0
    sensor_h_mm = cam.res_y * px / 1000.0
    fov_w_deg = math.degrees(2 * math.atan(sensor_w_mm / (2 * focal)))
    fov_h_deg = math.degrees(2 * math.atan(sensor_h_mm / (2 * focal)))
    fov_w_arcmin, fov_h_arcmin = fov_w_deg * 60, fov_h_deg * 60

    if scale < 1.0:
        sampling = "fein abgetastet (für hohe Brennweite / gutes Seeing)"
    elif scale <= 2.0:
        sampling = "gut abgetastet (ideal ~1–2 \"/px)"
    else:
        sampling = "grob abgetastet (Weitfeld)"

    obj_info = None
    preview_url = None
    preview_fov_deg = None
    obj_broadband = None
    if object_ident:
        obj = await db.scalar(select(CatalogObject).where(CatalogObject.ident == object_ident))
        if obj:
            obj_broadband = obj.broadband
            # Preview weiter aufziehen als Sensor UND Objekt, damit man die
            # Objektgröße im (kleineren) Sensorrahmen ablesen kann.
            obj_long_deg = (obj.size_major_arcmin or 0) / 60.0
            sensor_long_deg = max(fov_w_deg, fov_h_deg)
            preview_fov_deg = round(min(max(max(obj_long_deg, sensor_long_deg) * 1.6, 0.1), 5.0), 4)
            preview_url = _preview_url(obj.ra_deg, obj.dec_deg, preview_fov_deg)
            framing_pct = None
            if obj.size_major_arcmin:
                framing_pct = round(obj.size_major_arcmin / max(fov_w_arcmin, fov_h_arcmin) * 100, 1)
            obj_info = {
                "ident": obj.ident, "name": obj.name,
                "size_major_arcmin": obj.size_major_arcmin, "size_minor_arcmin": obj.size_minor_arcmin,
                "framing_pct": framing_pct,
                "fits": (obj.size_major_arcmin or 0) < min(fov_w_arcmin, fov_h_arcmin) * 0.95,
            }

    # ── Belichtung (gruppiert, gleiche Sub-Anzahl je Filter) ──
    sqm = _BORTLE_SQM.get(bortle, 20.5)
    aperture_cm = (scope.aperture_mm or 0) / 10.0
    aperture_area = math.pi * (aperture_cm / 2.0) ** 2  # cm²
    can_expose = aperture_area > 0
    bortle_factor = 1 + max(0, bortle - 4) * 0.3

    # Filterauswahl: die des Setups; ohne Setup alle des Users.
    if setup_filter_objs is not None:
        filters = setup_filter_objs
    else:
        filters = list(await db.scalars(select(Filter).where(Filter.user_id == user.id).order_by(Filter.name)))
    oneshot = setup_filter_objs is not None and len(setup_filter_objs) == 0

    def _sub_for(bw_a: float, kind: str) -> tuple[int | None, int | None, bool]:
        if not can_expose:
            return None, None, False
        cap = _SUB_CAP["narrowband" if kind == "narrowband" else "broadband"]
        if max_sub_s:
            cap = min(cap, max_sub_s)
        e_sky = _P0 * 10 ** (-0.4 * sqm) * scale**2 * aperture_area * qe * bw_a * _TRANSMISSION
        if e_sky <= 0:
            return None, None, False
        opt = _C * read_noise**2 / e_sky
        rec = _snap_sub(opt, cap)
        return rec, round(opt), opt > rec * 1.15

    def _build_group(kind: str, label: str, target_total_h: float) -> dict | None:
        group = [f for f in filters if f.kind == kind]
        if not group or not can_expose:
            return None
        rows = []
        for f in group:
            rec, opt, capped = _sub_for(_bandwidth_angstrom(f), f.kind)
            rows.append({"name": f.name, "bandwidth_nm": f.bandwidth_nm,
                         "sub_length_s": rec, "sub_optimal_s": opt, "capped": capped})
        sum_len = sum(r["sub_length_s"] or 0 for r in rows)
        if sum_len <= 0:
            return None
        n = max(10, round(target_total_h * bortle_factor * 3600 / sum_len))
        for r in rows:
            r["subs"] = n
            r["total_min"] = round(n * (r["sub_length_s"] or 0) / 60)
        return {"band": kind, "label": label, "subs_per_filter": n,
                "total_min": round(n * sum_len / 60), "filters": rows}

    note = None
    if not can_expose:
        groups = []
    elif oneshot:
        # OSC / kein Filterrad: eine einzige Empfehlung, keine Wechsel.
        rec, opt, capped = _sub_for(3000.0, "broadband")
        n = max(10, round(5.0 * bortle_factor * 3600 / (rec or 1)))
        total = round(n * (rec or 0) / 60)
        groups = [{
            "band": "oneshot", "label": "Ohne Filter (One-Shot-Farbe)", "subs_per_filter": n,
            "total_min": total,
            "filters": [{"name": "Ohne Filter", "bandwidth_nm": None, "sub_length_s": rec,
                         "sub_optimal_s": opt, "capped": capped, "subs": n, "total_min": total}],
        }]
        if obj_broadband is False:
            note = "Color-Kamera ohne Schmalband: für Emissionsnebel einen Dual-Schmalband-Filter (z. B. Ha+OIII) verwenden."
    else:
        bb = _build_group("broadband", "Breitband (LRGB)", 5.0)
        nb = _build_group("narrowband", "Schmalband (SHO)", 9.0)
        # Nur die zum Objekt passende Gruppe; ohne Objekt beide.
        if obj_broadband is True:
            groups = [g for g in (bb,) if g]
        elif obj_broadband is False:
            groups = [g for g in (nb,) if g]
        else:
            groups = [g for g in (bb, nb) if g]
        if obj_broadband is False and not nb and bb:
            note = "Dieses Setup hat keine Schmalbandfilter — für Nebel sinnvoll zu ergänzen."
        elif obj_broadband is True and not bb and nb:
            note = "Dieses Setup hat keine Breitbandfilter (LRGB)."
    grand_total_min = sum(g["total_min"] for g in groups)

    return {
        "telescope": {"name": scope.name, "aperture_mm": scope.aperture_mm, "focal_length_mm": focal,
                      "focal_ratio": round(focal / scope.aperture_mm, 2) if scope.aperture_mm else None},
        "camera": {"name": cam.name, "pixel_size_um": px, "res_x": cam.res_x, "res_y": cam.res_y, "sensor_type": cam.sensor_type},
        "framing": {
            "image_scale": round(scale, 2),
            "fov_width_arcmin": round(fov_w_arcmin, 1), "fov_height_arcmin": round(fov_h_arcmin, 1),
            "fov_width_deg": round(fov_w_deg, 3), "fov_height_deg": round(fov_h_deg, 3),
            "sensor_aspect": round(cam.res_x / cam.res_y, 4),
            "sampling_note": sampling, "preview_url": preview_url, "preview_fov_deg": preview_fov_deg,
            "object": obj_info,
        },
        "exposure": {"bortle": bortle, "sqm": sqm, "read_noise": read_noise, "qe": qe,
                     "aperture_known": can_expose,
                     "recommended_band": ("broadband" if obj_broadband else "narrowband") if obj_broadband is not None else None,
                     "groups": groups, "grand_total_min": grand_total_min, "note": note},
    }
