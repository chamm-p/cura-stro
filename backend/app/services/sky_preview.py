"""Katalog-Vorschaubilder (DSS2) über einen serverseitigen Proxy + Cache.

Warum nicht direkt vom Browser laden?
  Früher baute das Backend eine hips2fits-URL zu CDS (Straßburg) und der
  Browser lud das Bild selbst. Das ist fragil: fällt CDS aus (kommt vor),
  bleiben alle Previews leer; außerdem gibt es Mixed-Content-Ärger, wenn die
  App über http:// läuft, und jeder Client belastet CDS neu.

Dieser Service holt das Bild EINMAL serverseitig, legt es als JPG im
outputs-Volume ab und liefert es danach aus dem Cache.

Quellen in Reihenfolge:
  1. HiPS-Kacheln von ESA/IRSA (Farb-DSS2, unabhängig von CDS) — der
     TAN-Ausschnitt wird hier selbst berechnet, also feldgetreu für jede FOV.
  2. CDS hips2fits (Farbe).
  3. STScI DSS (nur Graustufen, nur Notnagel) — maßstabsgetreu, aber nur kurz
     gecacht, damit das Bild beim nächsten Abruf wieder farbig werden kann.

Der Framing-Rahmen im Rechner wird relativ zur angefragten FOV gezeichnet: Das
Bild MUSS exakt diese FOV zeigen, sonst passt der Maßstab nicht mehr.

Öffentliche API:
  build_url(ra, dec, fov_deg, px)  → lokale URL "/api/sky/preview?..."
  fetch_cached(ra, dec, fov, px)   → Pfad zur gecachten JPG (lädt bei Bedarf)
"""

from __future__ import annotations

import hashlib
import io
import logging
import math
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import numpy as np
from PIL import Image

from app.config import get_settings

log = logging.getLogger("uvicorn.error")
_cfg = get_settings()

# Bei Änderungen an der Bilderzeugung hochzählen: steckt im Cache-Key UND in der
# URL, damit weder Server- noch Browser-Cache alte Bilder weiter ausliefern.
_VERSION = 2

# Einfacher Circuit-Breaker: Ist CDS gerade nicht erreichbar, nicht bei JEDEM
# Preview aufs Neue in die Timeouts laufen — nach einem Fehlschlag CDS für
# _CDS_COOLDOWN Sekunden überspringen.
_CDS_COOLDOWN = 300.0
_cds_down_until = 0.0

_HIPS_HOSTS = [
    "https://alasky.cds.unistra.fr/hips-image-services/hips2fits",
    "https://alaskybis.cds.unistra.fr/hips-image-services/hips2fits",
]

# Spiegel des HiPS "CDS/P/DSS2/color" (Order 9, 512-px-Kacheln, äquatorial).
_TILE_MIRRORS = [
    "https://skies.esac.esa.int/DSSColor",
    "https://irsa.ipac.caltech.edu/data/hips/CDS/DSS2/color",
]
_TILE_WIDTH = 512
_TILE_MAX_ORDER = 9
_SUPERSAMPLE = 2

# STScI/MAST Digitized Sky Survey. Liefert GIF, nur Graustufen.
_STSCI = "https://archive.stsci.edu/cgi-bin/dss_search"
# STScI liefert bis ~120', aber das sind ~14 MB GIF. Größere FOV werden
# maßstabsgetreu mit schwarzem Rand aufgefüllt (siehe _fetch_stsci).
_STSCI_MAX_ARCMIN = 75.0
_GRAY_TTL = 3600.0

_CACHE = Path(_cfg.outputs_dir) / "sky"


def build_url(ra: float, dec: float, fov_deg: float, px: int = 400) -> str:
    """Lokale Proxy-URL fürs <img src>. Kein Auth nötig (Katalogdaten)."""
    q = urlencode({"ra": round(ra, 5), "dec": round(dec, 5),
                   "fov": round(fov_deg, 4), "px": px, "v": _VERSION})
    return f"/api/sky/preview?{q}"


def _cache_path(ra: float, dec: float, fov: float, px: int) -> Path:
    key = f"v{_VERSION}_{ra:.5f}_{dec:.5f}_{fov:.4f}_{px}"
    h = hashlib.sha1(key.encode()).hexdigest()[:20]
    return _CACHE / f"{h}.jpg"


def _to_jpeg(data: bytes, px: int) -> bytes:
    """Beliebiges Bild (JPG/GIF/PNG) → quadratisches JPG mit px Kantenlänge."""
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.size != (px, px):
        im = im.resize((px, px), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _tan_grid(ra: float, dec: float, fov: float, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Gnomonisches Raster n×n (Nord oben, Ost links) → (phi, z=sin(dec))."""
    step = math.radians(fov) / n
    center = (n - 1) / 2
    col, row = np.meshgrid(np.arange(n), np.arange(n))
    x = -(col - center) * step
    y = -(row - center) * step
    ra0, dec0 = math.radians(ra), math.radians(dec)
    rho = np.hypot(x, y)
    c = np.arctan(rho)
    sin_c, cos_c = np.sin(c), np.cos(c)
    y_rho = np.divide(y, rho, out=np.zeros_like(y), where=rho > 0)
    z = cos_c * math.sin(dec0) + y_rho * sin_c * math.cos(dec0)
    phi = ra0 + np.arctan2(x * sin_c, rho * math.cos(dec0) * cos_c - y * math.sin(dec0) * sin_c)
    return np.mod(phi, 2 * math.pi), np.clip(z, -1.0, 1.0)


def _healpix_xyf(phi: np.ndarray, z: np.ndarray, nside: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Himmelsrichtung → HEALPix (Basisfläche, ix, iy), wie ang2pix_nest."""
    tt = np.mod(phi / (math.pi / 2), 4.0)
    za = np.abs(z)
    face, ix, iy = np.zeros(z.shape, int), np.zeros(z.shape, int), np.zeros(z.shape, int)

    eq = za <= 2 / 3
    t1, t2 = nside * (0.5 + tt[eq]), nside * z[eq] * 0.75
    jp, jm = (t1 - t2).astype(int), (t1 + t2).astype(int)
    ifp, ifm = jp // nside, jm // nside
    face[eq] = np.where(ifp == ifm, (ifp % 4) + 4, np.where(ifp < ifm, ifp % 4, (ifm % 4) + 8))
    ix[eq] = jm & (nside - 1)
    iy[eq] = nside - (jp & (nside - 1)) - 1

    pol = ~eq
    ntt = np.minimum(3, tt[pol].astype(int))
    tp = tt[pol] - ntt
    tmp = np.sqrt(3 * (1 - za[pol]))
    jp = np.minimum((nside * tp * tmp).astype(int), nside - 1)
    jm = np.minimum((nside * (1 - tp) * tmp).astype(int), nside - 1)
    north = z[pol] >= 0
    face[pol] = np.where(north, ntt, ntt + 8)
    ix[pol] = np.where(north, nside - jm - 1, jp)
    iy[pol] = np.where(north, nside - jp - 1, jm)
    return face, ix, iy


def _tile_npix(order: int, face: int, x: int, y: int) -> int:
    bits = sum(((x >> b) & 1) << (2 * b) | ((y >> b) & 1) << (2 * b + 1) for b in range(order))
    return face * 4 ** order + bits


def _fetch_tiles(ra: float, dec: float, fov: float, px: int) -> bytes | None:
    """Farb-DSS2 aus HiPS-Kacheln: exakt die angefragte FOV, als PNG."""
    # Order so wählen, dass die Kachelpixel mindestens so fein sind wie das Ziel.
    order = max(0, min(_TILE_MAX_ORDER, math.ceil(math.log2(58.63 / (fov / px))) - 9))
    n = px * _SUPERSAMPLE
    phi, z = _tan_grid(ra, dec, fov, n)
    face, ix, iy = _healpix_xyf(phi, z, _TILE_WIDTH << order)
    tx, ty = ix >> 9, iy >> 9
    u, v = ix & (_TILE_WIDTH - 1), iy & (_TILE_WIDTH - 1)
    tiles = np.unique(np.stack([face, tx, ty], -1).reshape(-1, 3), axis=0)

    to = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=5.0)
    for base in _TILE_MIRRORS:
        try:
            canvas = np.zeros((n, n, 3), np.uint8)
            with httpx.Client(timeout=to, follow_redirects=True) as c:
                for f, x, y in tiles:
                    npix = _tile_npix(order, int(f), int(x), int(y))
                    r = c.get(f"{base}/Norder{order}/Dir{npix // 10000 * 10000}/Npix{npix}.jpg")
                    r.raise_for_status()
                    tile = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"))
                    mask = (face == f) & (tx == x) & (ty == y)
                    # Pixelreihenfolge in HiPS-Kacheln: Spalte = iy, Zeile = ix.
                    canvas[mask] = tile[u[mask], v[mask]]
            buf = io.BytesIO()
            Image.fromarray(canvas).save(buf, "PNG")
            return buf.getvalue()
        except Exception as e:  # noqa: BLE001
            log.warning("sky-preview: Kacheln von %s nicht verfügbar (%s)", base, e)
    return None


def _fetch_hips2fits(ra: float, dec: float, fov: float, px: int) -> bytes | None:
    global _cds_down_until
    if time.time() < _cds_down_until:
        return None

    params = {"hips": "CDS/P/DSS2/color", "ra": round(ra, 5), "dec": round(dec, 5),
              "fov": round(fov, 4), "width": px, "height": px,
              "projection": "TAN", "format": "jpg"}
    # Kurze Timeouts: ist CDS down (auch "nimmt Verbindung an, antwortet aber
    # nicht"), soll die Kette SCHNELL weiterfallen.
    to = httpx.Timeout(connect=4.0, read=6.0, write=6.0, pool=4.0)
    for base in _HIPS_HOSTS:
        try:
            with httpx.Client(timeout=to, follow_redirects=True) as c:
                r = c.get(base, params=params)
                r.raise_for_status()
                if "image" in r.headers.get("content-type", "") and r.content:
                    return r.content
        except Exception as e:  # noqa: BLE001
            log.warning("sky-preview: hips2fits %s nicht erreichbar (%s)", base, e)
    _cds_down_until = time.time() + _CDS_COOLDOWN
    return None


def _fetch_stsci(ra: float, dec: float, fov: float, px: int) -> bytes | None:
    """STScI DSS als Notnagel (Graustufen). Immer maßstabsgetreu: ist die FOV
    größer als das holbare Feld, sitzt das Bild verkleinert auf schwarzem Grund."""
    arcmin = min(fov * 60.0, _STSCI_MAX_ARCMIN)
    to = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
    # POSS2/UKSTU_red ist feiner, deckt aber nicht den ganzen Himmel (STScI
    # liefert dann HTTP 200 mit HTML-Fehlerseite). POSS1_red als Fallback.
    for plate in ("poss2ukstu_red", "poss1_red"):
        params = {"v": plate, "r": round(ra, 5), "d": round(dec, 5),
                  "e": "J2000", "h": round(arcmin, 2), "w": round(arcmin, 2),
                  "f": "gif", "c": "none"}
        try:
            with httpx.Client(timeout=to, follow_redirects=True) as c:
                r = c.get(_STSCI, params=params)
                r.raise_for_status()
            if "image" not in r.headers.get("content-type", "") or not r.content:
                continue
            inner = round(px * arcmin / (fov * 60.0))
            im = Image.open(io.BytesIO(r.content)).convert("RGB").resize((inner, inner), Image.LANCZOS)
            canvas = Image.new("RGB", (px, px))
            canvas.paste(im, ((px - inner) // 2, (px - inner) // 2))
            buf = io.BytesIO()
            canvas.save(buf, "PNG")
            return buf.getvalue()
        except Exception as e:  # noqa: BLE001
            log.warning("sky-preview: STScI (%s) nicht erreichbar (%s)", plate, e)
    return None


def fetch_cached(ra: float, dec: float, fov: float, px: int) -> Path:
    """Pfad zur gecachten JPG; lädt sie bei Bedarf. Farbbilder gelten dauerhaft,
    der Graustufen-Notnagel nur _GRAY_TTL. RuntimeError, wenn nichts liefert."""
    dest = _cache_path(ra, dec, fov, px)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    gray = dest.with_suffix(".gray.jpg")
    if gray.exists() and time.time() - gray.stat().st_mtime < _GRAY_TTL:
        return gray

    _CACHE.mkdir(parents=True, exist_ok=True)
    raw = _fetch_tiles(ra, dec, fov, px) or _fetch_hips2fits(ra, dec, fov, px)
    target = dest
    if not raw:
        raw = _fetch_stsci(ra, dec, fov, px)
        target = gray
    if not raw:
        if gray.exists():
            return gray
        raise RuntimeError("Weder ESA/IRSA noch CDS oder STScI erreichbar")
    try:
        target.write_bytes(_to_jpeg(raw, px))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Bild-Konvertierung fehlgeschlagen: {e}")
    return target
