"""Sichtbarkeits-Engine (astropy) — Phase 3.

Berechnet für einen Standort, ein Datum und ein Nachtfenster die maximale
Höhe (Altitude) jedes Objekts über dem Horizont sowie den Zeitpunkt der
besten Beobachtung. Vektorisiert über ein Zeitraster.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import astropy.units as u
import numpy as np
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body, solar_system_ephemeris
from astropy.time import Time
from astropy.utils import iers

# Offline-Betrieb: keine IERS-Downloads, kein Abbruch bei „veralteten"
# Erdrotationsdaten — unsere Genauigkeit (Minuten/Grad) braucht das nicht.
iers.conf.auto_download = False
iers.conf.auto_max_age = None
iers.conf.iers_degraded_accuracy = "ignore"


def night_grid(date_str: str, night_start: str, night_end: str, tz: str, step_min: int = 15):
    """Liefert (lokale datetimes, astropy.Time in UTC) für das Nachtfenster.

    ``date_str`` = Abend-Datum (YYYY-MM-DD). Endet das Fenster „früher" als
    es beginnt (z. B. 22:00 → 05:00), liegt das Ende am Folgetag.
    """
    tzinfo = ZoneInfo(tz or "UTC")
    y, m, d = (int(x) for x in date_str.split("-"))
    sh, sm = (int(x) for x in night_start.split(":"))
    eh, em = (int(x) for x in night_end.split(":"))
    start = datetime(y, m, d, sh, sm, tzinfo=tzinfo)
    end = datetime(y, m, d, eh, em, tzinfo=tzinfo)
    if end <= start:
        end += timedelta(days=1)

    grid_local: list[datetime] = []
    t = start
    while t <= end:
        grid_local.append(t)
        t += timedelta(minutes=step_min)

    utc = [g.astimezone(timezone.utc).replace(tzinfo=None) for g in grid_local]
    return grid_local, Time(utc, scale="utc")


def max_possible_altitude(lat_deg: float, dec_deg: float) -> float:
    """Theoretische Kulminationshöhe — billiger Vorfilter."""
    return 90.0 - abs(lat_deg - dec_deg)


# Große Planeten mit grober typischer Helligkeit (nur Richtwert für den
# Magnitude-Filter — Planeten sind ohnehin hell genug für jedes Gerät).
_PLANETS = [
    ("mercury", "Merkur", 0.0),
    ("venus", "Venus", -4.0),
    ("mars", "Mars", 0.7),
    ("jupiter", "Jupiter", -2.2),
    ("saturn", "Saturn", 0.6),
    ("uranus", "Uranus", 5.7),
    ("neptune", "Neptun", 7.8),
]


def recommend_window(
    alts: list[float],
    grid_labels: list[str],
    clouds: list[float | None],
    min_altitude: float,
    cloud_threshold: float = 50.0,
) -> dict | None:
    """Bestes Aufnahmefenster: zusammenhängender Zeitraum, in dem das Objekt
    hoch genug steht UND der Himmel klar genug ist (Bewölkung ≤ Schwelle).

    Gewählt wird der nutzbare Abschnitt mit der größten Maximalhöhe. Ohne
    Wetterdaten (clouds=None) zählt nur die Höhe. Rückgabe: start/end/peak
    (HH:MM) + Grund, oder None wenn es kein brauchbares Fenster gibt."""
    n = len(alts)
    if n == 0:
        return None
    usable = [
        alts[i] >= min_altitude and (clouds[i] is None or clouds[i] <= cloud_threshold)
        for i in range(n)
    ]
    # Zusammenhängende Läufe finden.
    runs: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if usable[i]:
            j = i
            while j + 1 < n and usable[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    if not runs:
        return None
    s, e = max(runs, key=lambda r: max(alts[r[0] : r[1] + 1]))
    peak_i = s + int(np.argmax(alts[s : e + 1]))

    # Grund: wodurch wird das Fensterende begrenzt?
    if e >= n - 1:
        reason = "bis Nachtende"
    elif clouds[e + 1] is not None and clouds[e + 1] > cloud_threshold:
        reason = f"danach Wolken (ab {grid_labels[e + 1]})"
    elif alts[e + 1] < min_altitude:
        reason = "danach zu tief"
    else:
        reason = None
    return {
        "start": grid_labels[s],
        "end": grid_labels[e],
        "peak": grid_labels[peak_i],
        "reason": reason,
    }


def angular_separation_deg(ra1: float, dec1: float, ra2: np.ndarray, dec2: np.ndarray) -> np.ndarray:
    """Winkelabstand (Grad) zwischen einem Punkt und einem Array von Punkten
    (Haversine auf der Himmelskugel)."""
    r1, d1 = np.radians(ra1), np.radians(dec1)
    r2, d2 = np.radians(ra2), np.radians(dec2)
    s = np.sin((d2 - d1) / 2) ** 2 + np.cos(d1) * np.cos(d2) * np.sin((r2 - r1) / 2) ** 2
    return np.degrees(2 * np.arcsin(np.sqrt(np.clip(s, 0, 1))))


def compute_moon(
    *,
    lat: float,
    lon: float,
    elevation_m: float | None,
    tz: str,
    date_str: str,
    night_start: str,
    night_end: str,
    step_min: int = 15,
) -> dict:
    """Mond: Beleuchtungsgrad, Phasenname, Höhenverlauf und Position
    (Mitte des Fensters) — Basis für die Mondlicht-Warnungen."""
    from astroplan import moon_illumination

    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=(elevation_m or 0.0) * u.m)
    grid_local, times = night_grid(date_str, night_start, night_end, tz, step_min)
    mid = times[len(times) // 2]

    with solar_system_ephemeris.set("builtin"):
        moon = get_body("moon", times, loc)
        aa = moon.transform_to(AltAz(obstime=times, location=loc))
        alt = np.atleast_1d(aa.alt.deg)
        moon_mid = get_body("moon", mid, loc).icrs
        illum = float(moon_illumination(mid))
        illum_later = float(moon_illumination(times[min(len(times) - 1, len(times) // 2 + 4)]))

    waxing = illum_later >= illum
    max_alt = float(alt.max())
    labels = [g.strftime("%H:%M") for g in grid_local]
    track = [round(float(x), 1) for x in alt]
    return {
        "illumination": round(illum, 3),
        "illumination_pct": round(illum * 100),
        "phase_name": _moon_phase_name(illum, waxing),
        "max_altitude": round(max_alt, 1),
        "up": max_alt > 0,
        "track": track,
        "grid": labels,
        "grid_iso": [g.strftime("%Y-%m-%dT%H:%M") for g in grid_local],
        "best_window": best_night_window(labels, track),
        "ra_deg": float(moon_mid.ra.deg),
        "dec_deg": float(moon_mid.dec.deg),
    }


def _longest_run(mask: list[bool]) -> tuple[int, int, int] | None:
    """Längster zusammenhängender True-Lauf → (laenge, start, end)."""
    n = len(mask)
    best = None
    i = 0
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if best is None or (j - i) > best[0]:
                best = (j - i, i, j)
            i = j + 1
        else:
            i += 1
    return best


def _moon_only_window(labels: list[str], alt: list[float]) -> dict | None:
    n = len(alt)
    down = [a <= 0 for a in alt]
    best = _longest_run(down)
    if best is not None and best[0] >= 1 and best[0] < n * 0.9:
        return {"start": labels[best[1]], "end": labels[best[2]], "reason": "mondfrei"}
    if not any(down):
        k = min(range(n), key=lambda x: alt[x])
        s, e = max(0, k - 3), min(n - 1, k + 3)
        if e > s:
            return {"start": labels[s], "end": labels[e], "reason": "Mond am tiefsten"}
    s, e = max(0, round(n * 0.25)), min(n - 1, round(n * 0.75))
    if e <= s:
        return None
    return {"start": labels[s], "end": labels[e], "reason": "dunkle Nachtmitte"}


def best_night_window(labels: list[str], alt: list[float], weather_ok: list[bool] | None = None) -> dict | None:
    """Generisch-pauschal bestes Beobachtungsfenster der Nacht.

    Ohne ``weather_ok`` rein nach Mond (Dunkelheit). Mit ``weather_ok`` (je
    Rasterpunkt: Wetter brauchbar, d. h. < 50 % Wolken & kein Sturm) wird das
    Fenster auf „dunkel UND klar UND windstill" eingeschränkt; gibt es keins,
    kommt ``start=None`` mit Begründung zurück. ``labels`` = HH:MM je Punkt."""
    n = len(alt)
    if n < 2 or len(labels) != n:
        return None
    if weather_ok is None:
        return _moon_only_window(labels, alt)

    good = [(alt[i] <= 0) and bool(weather_ok[i]) for i in range(n)]
    run = _longest_run(good)
    if run is not None and run[0] >= 1:
        moon_ever_up = any(a > 0 for a in alt)
        return {
            "start": labels[run[1]], "end": labels[run[2]],
            "reason": "klar & mondfrei" if moon_ever_up else "klar",
        }
    # Kein brauchbares Fenster → Hauptgrund nennen.
    cloudy = sum(1 for ok in weather_ok if not ok)
    moonup = sum(1 for a in alt if a > 0)
    if cloudy >= n * 0.7:
        reason = "durchgehend bewölkt/stürmisch"
    elif moonup >= n * 0.9:
        reason = "Mond die ganze Nacht hell"
    else:
        reason = "kein klares, mondfreies Fenster"
    return {"start": None, "end": None, "reason": reason}


def _moon_phase_name(illum: float, waxing: bool) -> str:
    if illum < 0.03:
        return "Neumond"
    if illum > 0.97:
        return "Vollmond"
    wx = "zunehmend" if waxing else "abnehmend"
    if illum < 0.45:
        return f"{wx}e Sichel"
    if illum < 0.55:
        return "Erstes Viertel" if waxing else "Letztes Viertel"
    return f"{wx}er Mond"


def moon_impact(broadband: bool, sep_deg: float, illum: float, moon_up: bool) -> tuple[str, str | None]:
    """Bewertet den Mondlicht-Einfluss: ('none'|'mild'|'strong', Hinweis).

    Breitband (Galaxien/Sternhaufen/RGB-L) ist mondempfindlich; Schmalband
    (Emissionsnebel) ist gegen Mondlicht weitgehend immun."""
    if not moon_up or illum < 0.2:
        return "none", None
    pct = round(illum * 100)
    if broadband:
        if illum >= 0.5 and sep_deg < 45:
            return "strong", f"Heller Mond ({pct}%) nur {round(sep_deg)}° entfernt — Breitband stark beeinträchtigt."
        if illum >= 0.4:
            return "mild", f"Mond zu {pct}% beleuchtet — Breitband (RGB/L) beeinträchtigt."
        if sep_deg < 50:
            return "mild", f"Mond {round(sep_deg)}° entfernt — etwas Aufhellung."
        return "none", None
    # Schmalband
    if illum >= 0.85 and sep_deg < 25:
        return "mild", "Fast Vollmond sehr nah — selbst Schmalband leidet leicht."
    return "none", None


def compute_planets(
    *,
    lat: float,
    lon: float,
    elevation_m: float | None,
    tz: str,
    date_str: str,
    night_start: str,
    night_end: str,
    min_altitude: float = 30.0,
    step_min: int = 15,
) -> list[dict]:
    """Sichtbarkeit der großen Planeten — topozentrisch, pro Zeitpunkt
    (builtin-Ephemeride, offline). Anders als Fixsterne bewegen sich
    Planeten messbar, daher pro Rasterpunkt neu berechnet.

    Rückgabe je Planet: id/ident/name/obj_type/magnitude + Sichtbarkeit
    (max_altitude, best_time_local, azimuth_at_best, visible, track)."""
    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=(elevation_m or 0.0) * u.m)
    grid_local, times = night_grid(date_str, night_start, night_end, tz, step_min)
    frame = AltAz(obstime=times, location=loc)

    out: list[dict] = []
    with solar_system_ephemeris.set("builtin"):
        for key, name, mag in _PLANETS:
            body = get_body(key, times, loc)
            aa = body.transform_to(frame)
            alt = np.atleast_1d(aa.alt.deg)
            az = np.atleast_1d(aa.az.deg)
            bi = int(alt.argmax())
            ma = float(alt[bi])
            out.append(
                {
                    "id": f"planet:{key}",
                    "ident": name,
                    "name": name,
                    "obj_type": "planet",
                    "magnitude": mag,
                    "max_altitude": round(ma, 1),
                    "best_time_local": grid_local[bi].isoformat(),
                    "azimuth_at_best": round(float(az[bi]), 1),
                    "visible": ma >= min_altitude,
                    "track": [round(float(x), 1) for x in alt],
                }
            )
    return out


def compute_visibility(
    *,
    lat: float,
    lon: float,
    elevation_m: float | None,
    tz: str,
    date_str: str,
    night_start: str,
    night_end: str,
    objects: list[dict],
    min_altitude: float = 30.0,
    step_min: int = 15,
) -> tuple[list[str], dict[str, dict]]:
    """Berechnet Sichtbarkeit. ``objects`` = [{id, ra_deg, dec_deg}, …].

    Rückgabe: (zeitraster["HH:MM"], {id: {max_altitude, best_time_local(ISO),
    azimuth_at_best, visible(bool), track[float]}}). ``track`` ist die Höhe
    (°) je Rasterpunkt — Grundlage für die Höhenkurve im UI. Objekte, die
    rechnerisch nie ``min_altitude`` erreichen, werden vorab aussortiert.
    """
    loc = EarthLocation(lat=lat * u.deg, lon=lon * u.deg, height=(elevation_m or 0.0) * u.m)
    grid_local, times = night_grid(date_str, night_start, night_end, tz, step_min)
    grid_labels = [g.strftime("%H:%M") for g in grid_local]

    # Vorfilter nach Deklination.
    candidates = [o for o in objects if max_possible_altitude(lat, o["dec_deg"]) >= min_altitude]
    result: dict[str, dict] = {
        o["id"]: {
            "max_altitude": None, "best_time_local": None,
            "azimuth_at_best": None, "visible": False, "track": [],
        }
        for o in objects
    }
    if not candidates:
        return grid_labels, result

    ras = np.array([o["ra_deg"] for o in candidates])
    decs = np.array([o["dec_deg"] for o in candidates])
    coords = SkyCoord(ra=ras * u.deg, dec=decs * u.deg)

    frame = AltAz(obstime=times[np.newaxis, :], location=loc)
    aa = coords[:, np.newaxis].transform_to(frame)
    alt = np.atleast_2d(aa.alt.deg)  # (N, T)
    az = np.atleast_2d(aa.az.deg)

    best_idx = alt.argmax(axis=1)
    max_alt = alt.max(axis=1)
    rows = np.arange(len(candidates))
    az_best = az[rows, best_idx]

    for i, o in enumerate(candidates):
        ma = float(max_alt[i])
        result[o["id"]] = {
            "max_altitude": round(ma, 1),
            "best_time_local": grid_local[int(best_idx[i])].isoformat(),
            "azimuth_at_best": round(float(az_best[i]), 1),
            "visible": ma >= min_altitude,
            "track": [round(float(x), 1) for x in alt[i]],
        }
    return grid_labels, result
