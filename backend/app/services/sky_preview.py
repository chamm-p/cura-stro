"""Katalog-Vorschaubilder (DSS2) über einen serverseitigen Proxy + Cache.

Warum nicht direkt vom Browser laden?
  Früher baute das Backend eine hips2fits-URL zu CDS (Straßburg) und der
  Browser lud das Bild selbst. Das ist fragil: fällt CDS aus (kommt vor),
  bleiben alle Previews leer; außerdem gibt es Mixed-Content-Ärger, wenn die
  App über http:// läuft, und jeder Client belastet CDS neu.

Dieser Service holt das Bild EINMAL serverseitig (mit Mirror-Fallback),
legt es als JPG im outputs-Volume ab und liefert es danach aus dem Cache.
Katalog-Objekte ändern sich nie → ein geholtes Bild gilt dauerhaft und
übersteht spätere CDS-Ausfälle.

Öffentliche API:
  build_url(ra, dec, fov_deg, px)  → lokale URL "/api/sky/preview?..."
  fetch_cached(ra, dec, fov, px)   → Pfad zur gecachten JPG (lädt bei Bedarf)
"""

from __future__ import annotations

import hashlib
import io
import logging
import time
from pathlib import Path

import httpx

from app.config import get_settings

log = logging.getLogger("uvicorn.error")
_cfg = get_settings()

# Einfacher Circuit-Breaker: Ist CDS gerade nicht erreichbar, nicht bei JEDEM
# der (bis zu 300) Previews aufs Neue 3×4 s hineinlaufen — nach einem Fehlschlag
# CDS für _CDS_COOLDOWN Sekunden überspringen und direkt STScI nehmen.
_CDS_COOLDOWN = 300.0
_cds_down_until = 0.0

# CDS Straßburg (hips2fits) + Mirror. Alle sprechen dieselbe API, nur der
# Host unterscheidet sich. ACHTUNG: Die Mirror liegen in derselben CDS-
# Infrastruktur — bei einem kompletten CDS-Ausfall helfen sie nicht, deshalb
# gibt es zusätzlich STScI (siehe _fetch_stsci) als UNABHÄNGIGE Quelle.
_HIPS_HOSTS = [
    "https://alasky.cds.unistra.fr/hips-image-services/hips2fits",
    "https://alaskybis.cds.unistra.fr/hips-image-services/hips2fits",
    "https://alasky.u-strasbg.fr/hips-image-services/hips2fits",
]

# STScI/MAST Digitized Sky Survey — der ursprüngliche DSS-Herausgeber,
# unabhängig von CDS. Liefert GIF; wir rechnen nach JPG um.
_STSCI = "https://archive.stsci.edu/cgi-bin/dss_search"

_CACHE = Path(_cfg.outputs_dir) / "sky"


def _params(ra: float, dec: float, fov: float, px: int) -> dict:
    return {
        "hips": "CDS/P/DSS2/color",
        "ra": round(ra, 5),
        "dec": round(dec, 5),
        "fov": round(fov, 4),
        "width": px,
        "height": px,
        "projection": "TAN",
        "format": "jpg",
    }


def build_url(ra: float, dec: float, fov_deg: float, px: int = 400) -> str:
    """Lokale Proxy-URL fürs <img src>. Kein Auth nötig (Katalogdaten)."""
    from urllib.parse import urlencode
    q = urlencode({"ra": round(ra, 5), "dec": round(dec, 5),
                   "fov": round(fov_deg, 4), "px": px})
    return f"/api/sky/preview?{q}"


def _cache_path(ra: float, dec: float, fov: float, px: int) -> Path:
    key = f"{ra:.5f}_{dec:.5f}_{fov:.4f}_{px}"
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    return _CACHE / f"{h}.jpg"


def _to_jpeg(data: bytes, px: int) -> bytes:
    """Beliebiges Bild (JPG/GIF/PNG) → JPG, auf px skaliert."""
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if max(im.size) != px:
        im.thumbnail((px, px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _fetch_hips(ra: float, dec: float, fov: float, px: int) -> bytes | None:
    global _cds_down_until
    if time.time() < _cds_down_until:
        return None  # CDS kürzlich down → überspringen (Circuit-Breaker)

    params = _params(ra, dec, fov, px)
    # Kurzer Connect-Timeout: ist CDS down, soll die Kette SCHNELL zum
    # STScI-Fallback durchfallen (sonst 3×20 s = Request-Timeout/502).
    # Lese-Timeout großzügig, da das Rendern serverseitig dauern kann.
    to = httpx.Timeout(connect=4.0, read=20.0, write=10.0, pool=4.0)
    for base in _HIPS_HOSTS:
        try:
            with httpx.Client(timeout=to, follow_redirects=True) as c:
                r = c.get(base, params=params)
                r.raise_for_status()
                if "image" in r.headers.get("content-type", "") and r.content:
                    return r.content
        except Exception as e:  # noqa: BLE001
            log.warning("sky-preview: hips %s nicht erreichbar (%s)", base, e)
    # Kein CDS-Host lieferte → für eine Weile überspringen.
    _cds_down_until = time.time() + _CDS_COOLDOWN
    return None


def _fetch_stsci(ra: float, dec: float, fov: float, px: int) -> bytes | None:
    """STScI DSS (unabhängig von CDS). Feldgröße in Bogenminuten; GIF."""
    arcmin = max(min(fov * 60.0, 60.0), 2.0)  # STScI-Limit ~60'
    params = {"v": "poss2ukstu_red", "r": round(ra, 5), "d": round(dec, 5),
              "e": "J2000", "h": round(arcmin, 2), "w": round(arcmin, 2),
              "f": "gif", "c": "none"}
    to = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    try:
        with httpx.Client(timeout=to, follow_redirects=True) as c:
            r = c.get(_STSCI, params=params)
            r.raise_for_status()
            if "image" in r.headers.get("content-type", "") and r.content:
                return r.content
    except Exception as e:  # noqa: BLE001
        log.warning("sky-preview: STScI nicht erreichbar (%s)", e)
    return None


def fetch_cached(ra: float, dec: float, fov: float, px: int) -> Path:
    """Pfad zur gecachten JPG; lädt sie bei Bedarf. Quellen in Reihenfolge:
    CDS hips2fits (+Mirror) → STScI DSS (unabhängig). Alles wird als JPG
    normalisiert abgelegt. RuntimeError, wenn keine Quelle liefert."""
    dest = _cache_path(ra, dec, fov, px)
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    _CACHE.mkdir(parents=True, exist_ok=True)
    raw = _fetch_hips(ra, dec, fov, px) or _fetch_stsci(ra, dec, fov, px)
    if not raw:
        raise RuntimeError("Weder CDS noch STScI erreichbar")
    try:
        dest.write_bytes(_to_jpeg(raw, px))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Bild-Konvertierung fehlgeschlagen: {e}")
    return dest
