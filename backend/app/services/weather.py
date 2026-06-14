"""Astrowetter via Open-Meteo (kostenlos, kein API-Key).

Liefert Bewölkung (gesamt + low/mid/high), Niederschlagswahrscheinlichkeit,
Luftfeuchte und Wind für das Nachtfenster eines Datums und leitet ein
einfaches Urteil ab. Open-Meteo deckt nur ~16 Tage Vorhersage ab —
außerhalb gibt's ``available=False`` (Liste funktioniert trotzdem).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import httpx

logger = logging.getLogger(__name__)
_URL = "https://api.open-meteo.com/v1/forecast"


# Schwellen (Open-Meteo: km/h). Imaging-tauglich grob:
CLOUD_BAD = 50.0       # ab hier macht es keinen Sinn mehr (Nutzer-Vorgabe)
STORM_GUST = 50.0      # Böen ab ~50 km/h → unbrauchbar
WINDY_GUST = 38.0      # ab ~38 km/h böig (Warnung)


def _verdict(cloud: float | None, precip: float | None, gust: float | None) -> tuple[str, str]:
    """(Code, Klartext) aus Bewölkung + Niederschlag + Böen."""
    if cloud is None:
        return "unknown", "keine Daten"
    if precip is not None and precip >= 60:
        return "bad", "Niederschlag wahrscheinlich"
    if gust is not None and gust >= STORM_GUST:
        return "bad", "stürmisch (Wind)"
    if cloud >= CLOUD_BAD:
        return "bad", "stark bewölkt"
    if cloud < 20:
        return "excellent", "klar"
    if cloud < 40:
        return "good", "überwiegend klar"
    return "fair", "wechselnd bewölkt"


def _mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _max(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(max(vals), 1) if vals else None


async def fetch_night_weather(
    lat: float, lon: float, tz: str, date_str: str, night_start: str, night_end: str
) -> dict:
    """Mittelwerte der Wetterparameter über das Nachtfenster."""
    d = date.fromisoformat(date_str)
    end_d = d + timedelta(days=1)  # Fenster reicht über Mitternacht
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "cloudcover,cloudcover_low,cloudcover_mid,cloudcover_high,"
        "precipitation_probability,relative_humidity_2m,windspeed_10m,windgusts_10m",
        "timezone": tz or "auto",
        "start_date": d.isoformat(),
        "end_date": end_d.isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(_URL, params=params)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.info("Open-Meteo nicht verfügbar (%s)", e)
        return {"available": False, "note": "Wetterdaten nicht verfügbar (außerhalb Vorhersage?)."}

    hourly = data.get("hourly") or {}
    times: list[str] = hourly.get("time") or []
    if not times:
        return {"available": False, "note": "Keine stündlichen Daten."}

    # Indizes im Nachtfenster: date night_start..(date+1) night_end.
    sh = night_start
    eh = night_end
    start_key = f"{d.isoformat()}T{sh}"
    end_key = f"{end_d.isoformat()}T{eh}"

    def in_window(t: str) -> bool:
        return start_key <= t <= end_key

    idx = [i for i, t in enumerate(times) if in_window(t)]
    if not idx:
        return {"available": False, "note": "Nachtfenster außerhalb der Vorhersage."}

    def col(name: str) -> list:
        arr = hourly.get(name) or []
        return [arr[i] for i in idx if i < len(arr)]

    cloud = _mean(col("cloudcover"))
    precip = _mean(col("precipitation_probability"))
    gust = _max(col("windgusts_10m"))
    code, text = _verdict(cloud, precip, gust)

    cloud_series = hourly.get("cloudcover") or []
    gust_series = hourly.get("windgusts_10m") or []
    hourly_cloud = [
        {"time": times[i], "cloud": cloud_series[i]}
        for i in idx
        if i < len(cloud_series)
    ]
    hourly_wind = [
        {"time": times[i], "gust": gust_series[i]}
        for i in idx
        if i < len(gust_series)
    ]
    return {
        "available": True,
        "cloud_cover": cloud,
        "cloud_low": _mean(col("cloudcover_low")),
        "cloud_mid": _mean(col("cloudcover_mid")),
        "cloud_high": _mean(col("cloudcover_high")),
        "precip_probability": precip,
        "humidity": _mean(col("relative_humidity_2m")),
        "wind": _mean(col("windspeed_10m")),
        "wind_gusts": gust,
        "storm": bool(gust is not None and gust >= STORM_GUST),
        "windy": bool(gust is not None and gust >= WINDY_GUST),
        "verdict": code,
        "verdict_text": text,
        "hourly_cloud": hourly_cloud,
        "hourly_wind": hourly_wind,
    }
