"""Astro-Bildverarbeitung (Phase 6).

Liest FITS (astropy), XISF (xisf) und TIFF (tifffile), extrahiert die
wichtigsten Aufnahme-Metadaten aus den Headern und erzeugt per STF-
Autostretch (Midtone Transfer Function, wie PixInsight ScreenTransferFunction)
ein ansehnliches 8-bit-JPG.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

# FITS-Keywords → freundliches Label (Reihenfolge = Anzeige).
_META_LABELS = {
    "OBJECT": "Objekt",
    "DATE-OBS": "Datum",
    "EXPTIME": "Belichtung (s)",
    "EXPOSURE": "Belichtung (s)",
    "FILTER": "Filter",
    "GAIN": "Gain",
    "EGAIN": "e-/ADU",
    "OFFSET": "Offset",
    "CCD-TEMP": "Sensor-Temp (°C)",
    "CCDTEMP": "Sensor-Temp (°C)",
    "XBINNING": "Binning X",
    "YBINNING": "Binning Y",
    "INSTRUME": "Kamera",
    "TELESCOP": "Teleskop",
    "FOCALLEN": "Brennweite (mm)",
    "XPIXSZ": "Pixelgröße (µm)",
    "IMAGETYP": "Bildtyp",
    "BAYERPAT": "Bayer-Muster",
}


def _mtf(m: float, x: np.ndarray) -> np.ndarray:
    """Midtone Transfer Function. Bildet [0,1]→[0,1], hebt schwache Signale an."""
    x = np.clip(x, 0.0, 1.0)
    denom = (2.0 * m - 1.0) * x - m
    out = (m - 1.0) * x
    # denom ist nur am Rand 0 (x=0 → -m); sicher dividieren.
    return np.divide(out, denom, out=np.zeros_like(x), where=denom != 0)


def _stretch_channel(ch: np.ndarray) -> np.ndarray:
    ch = np.nan_to_num(ch.astype(np.float32))
    lo, hi = float(ch.min()), float(ch.max())
    if hi <= lo:
        return np.zeros_like(ch)
    x = (ch - lo) / (hi - lo)
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med))) or 1e-6
    norm_mad = 1.4826 * mad
    shadow_clip, target_bkg = -2.8, 0.25
    c0 = min(max(med + shadow_clip * norm_mad, 0.0), 1.0)
    m = _mtf(target_bkg, np.array(med - c0)).item() if med - c0 > 0 else target_bkg
    y = np.clip((x - c0) / (1.0 - c0 + 1e-9), 0.0, 1.0)
    return _mtf(m, y)


def auto_stretch_to_uint8(data: np.ndarray) -> np.ndarray:
    """STF-Autostretch → uint8. Mono (H,W) oder Farbe (H,W,3); Farbkanäle
    werden einzeln gestreckt (neutraler Hintergrund)."""
    if data.ndim == 2:
        return (_stretch_channel(data) * 255).astype(np.uint8)
    out = np.zeros(data.shape, dtype=np.uint8)
    for c in range(data.shape[2]):
        out[..., c] = (_stretch_channel(data[..., c]) * 255).astype(np.uint8)
    return out


def _normalize_shape(data: np.ndarray) -> np.ndarray:
    """Bringt Astro-Arrays auf (H,W) oder (H,W,3)."""
    data = np.squeeze(data)
    if data.ndim == 3:
        # (3,H,W) → (H,W,3)
        if data.shape[0] == 3 and data.shape[2] != 3:
            data = np.moveaxis(data, 0, -1)
        # mehr als 3 Kanäle → nur die ersten 3
        if data.shape[2] > 3:
            data = data[..., :3]
    return data


# ─── Reader pro Format ───
def _read_fits(path: str):
    from astropy.io import fits

    with fits.open(path, memmap=False) as hdul:
        hdu = next((h for h in hdul if getattr(h, "data", None) is not None), None)
        if hdu is None:
            raise ValueError("FITS enthält keine Bilddaten")
        data = np.asarray(hdu.data)
        meta = {k: hdu.header[k] for k in hdu.header if k and not k.startswith("COMMENT")}
    return data, meta


def _read_xisf(path: str):
    from xisf import XISF

    x = XISF(path)
    data = np.asarray(x.read_image(0))
    meta: dict = {}
    try:
        md = x.get_images_metadata()[0]
        fitskw = md.get("FITSKeywords", {})
        for k, entries in fitskw.items():
            if entries:
                meta[k] = entries[0].get("value")
    except Exception:  # pragma: no cover - Metadaten optional
        pass
    return data, meta


def _read_tiff(path: str):
    import tifffile

    data = np.asarray(tifffile.imread(path))
    return data, {}


_READERS = {"fits": _read_fits, "xisf": _read_xisf, "tiff": _read_tiff}


def process(path: str, fmt: str, jpg_out: str) -> dict:
    """Liest die Datei, extrahiert Metadaten, schreibt das gestretchte JPG.

    Rückgabe: {width, height, channels, meta:{summary, raw}}."""
    from PIL import Image as PILImage

    reader = _READERS.get(fmt)
    if reader is None:
        raise ValueError(f"Format nicht unterstützt: {fmt}")

    raw_data, raw_meta = reader(path)
    data = _normalize_shape(raw_data)
    if data.ndim not in (2, 3):
        raise ValueError("Unerwartete Bilddimension")

    h, w = data.shape[0], data.shape[1]
    channels = 1 if data.ndim == 2 else data.shape[2]

    stretched = auto_stretch_to_uint8(data)
    mode = "L" if stretched.ndim == 2 else "RGB"
    PILImage.fromarray(stretched, mode=mode).save(jpg_out, "JPEG", quality=90)

    # Metadaten aufbereiten.
    raw_meta = {str(k): _coerce(v) for k, v in raw_meta.items()}
    summary = {}
    for key, label in _META_LABELS.items():
        if key in raw_meta and label not in summary:
            summary[label] = raw_meta[key]

    return {
        "width": int(w),
        "height": int(h),
        "channels": int(channels),
        "meta": {"summary": summary, "raw": raw_meta},
    }


def _coerce(v):
    """JSON-serialisierbar machen."""
    if isinstance(v, (bool, int, str)) or v is None:
        return v
    if isinstance(v, float):
        return round(v, 6)
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)
