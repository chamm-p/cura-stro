"""ASIAir-Dateinamen verstehen + Archiv-Pfade bauen (V2 Phase A).

Der ASIAir benennt Subs nativ so:

    Light_IC 417_300.0s_Bin1_H_20250409-234734_0001.fit
    └typ─┘└obj──┘└─exp─┘└bin┘└f┘└──zeitstempel──┘└seq┘└ext┘

Wir parsen das deterministisch (reine Stdlib) und routen die Datei in den
verwalteten Archivbaum:

    <root>/RAW/<Objekt>/<Gerät>/        (Subs)
    <root>/Developer/<Objekt>/<Gerät>/  (PixInsight-Ergebnis)

Wichtig: der Parser erzeugt **keine** verwalteten Einträge. Er liefert nur
die Detaildaten (Filter, Belichtung, …), die unter dem *einen* Eintrag pro
Objekt+Gerät aggregiert werden. Filter/Belichtung leben im Dateinamen bzw.
in der Aggregat-Statistik, nicht im Verwaltungsschlüssel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

# Endungen, die wir als Astro-Subs/Master akzeptieren.
SUB_EXTS = {"fit", "fits", "fts", "xisf"}

# ASIAir-Filter-Slot-Kürzel → kanonischer Anzeigename (deckt gängige Räder ab).
FILTER_CANON: dict[str, str] = {
    "L": "L", "LUM": "L",
    "R": "R", "G": "G", "B": "B",
    "H": "Ha", "HA": "Ha", "HALPHA": "Ha",
    "S": "SII", "SII": "SII",
    "O": "OIII", "OIII": "OIII",
    "D": "Dual", "DUAL": "Dual", "LP": "LP", "UV": "UV/IR", "UVIR": "UV/IR",
}

# Frame-Typen, die der ASIAir vergibt. Nur „Light" wandert in Observations;
# Kalibrierframes erkennen wir, behandeln sie aber (vorerst) separat/optional.
LIGHT_TYPES = {"light"}
CALIBRATION_TYPES = {"dark", "flat", "bias", "darkflat", "dark flat"}
# Weitere bekannte Nicht-Light-Präfixe (ASIAir-Vorschauen/Stacks).
OTHER_TYPES = {"stacked", "preview", "snapshot", "master"}
_KNOWN_TYPES = (
    LIGHT_TYPES
    | {t.replace(" ", "") for t in CALIBRATION_TYPES}
    | OTHER_TYPES
)

# Dateiname-Muster. Filtergruppe optional (OSC ohne Filter):
#   Light_<obj>_<exp>s_Bin<n>[_<filter>]_<YYYYMMDD>-<HHMMSS>_<seq>[.<ext>]
_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z][A-Za-z ]*?)_"
    r"(?P<obj>.+?)_"
    r"(?P<exp>\d+(?:\.\d+)?)s_"
    r"Bin(?P<bin>\d+)_"
    r"(?:(?P<filter>[^_]+)_)?"
    r"(?P<date>\d{8})-(?P<time>\d{6})_"
    r"(?P<seq>\d+)"
    r"(?:\.(?P<ext>[A-Za-z0-9]+))?$"
)

# Fallback ohne Typ-Präfix: <obj>_<exp>s_Bin<n>[_<filter>]_<datum>-<zeit>_<seq>
# (manche Quellen/ältere Bestände lassen das 'Light_' weg) → zählt als Light.
_PATTERN_NOTYPE = re.compile(
    r"^(?P<obj>.+?)_"
    r"(?P<exp>\d+(?:\.\d+)?)s_"
    r"Bin(?P<bin>\d+)_"
    r"(?:(?P<filter>[^_]+)_)?"
    r"(?P<date>\d{8})-(?P<time>\d{6})_"
    r"(?P<seq>\d+)"
    r"(?:\.(?P<ext>[A-Za-z0-9]+))?$"
)


@dataclass
class ParsedFrame:
    frame_type: str          # "Light", "Dark", …
    object_name: str         # roh aus dem Dateinamen, z. B. "IC 417"
    exposure_s: float
    binning: int
    filter_letter: str | None   # roh, z. B. "H"
    filter_name: str | None     # kanonisch, z. B. "Ha"
    captured_at: datetime
    sequence: int
    ext: str                 # "fit"
    filename: str            # Originalname (mit Endung)

    @property
    def is_light(self) -> bool:
        return self.frame_type.lower() in LIGHT_TYPES

    @property
    def is_calibration(self) -> bool:
        return self.frame_type.lower().replace(" ", "") in {
            t.replace(" ", "") for t in CALIBRATION_TYPES
        }


def parse_frame_filename(filename: str) -> ParsedFrame | None:
    """Parst einen ASIAir-Dateinamen. ``None``, wenn er nicht passt.

    Robust gegen abweichende Namen: beginnt der Name mit einem Wort, das
    KEIN bekannter Frame-Typ ist (z. B. ``Pelican_IC5070_300.0s_…`` —
    die ASIAir setzt den eingetippten Zielnamen voran), gehört das Präfix
    zum Objektnamen und die Datei zählt als Light. Fehlt der Typ ganz
    (``IC5070_300.0s_…``), greift das Fallback-Muster — ebenfalls Light."""
    name = PurePosixPath(filename.strip()).name
    m = _PATTERN.match(name)
    ftype = None
    if m:
        g = m.groupdict()
        ftype = g["type"].strip()
        obj = g["obj"].strip()
        if ftype.lower().replace(" ", "") not in _KNOWN_TYPES:
            # Unbekanntes Präfix → Teil des Objektnamens, Frame ist ein Light.
            obj = f"{ftype}_{obj}"
            ftype = "Light"
    else:
        m = _PATTERN_NOTYPE.match(name)
        if not m:
            return None
        g = m.groupdict()
        obj = g["obj"].strip()
        if obj.lower().replace(" ", "") in _KNOWN_TYPES:
            # z. B. 'Dark_300.0s_Bin1_…' — Typ ohne Objektname (Calib-Frames)
            ftype = obj
            obj = ""
        else:
            ftype = "Light"
    try:
        captured = datetime.strptime(g["date"] + g["time"], "%Y%m%d%H%M%S")
    except ValueError:
        return None
    ext = (g["ext"] or "").lower()
    flt = g["filter"]
    return ParsedFrame(
        frame_type=ftype,
        object_name=obj,
        exposure_s=float(g["exp"]),
        binning=int(g["bin"]),
        filter_letter=flt,
        filter_name=canonical_filter(flt) if flt else None,
        captured_at=captured,
        sequence=int(g["seq"]),
        ext=ext,
        filename=name,
    )


def canonical_filter(letter: str | None) -> str | None:
    if not letter:
        return None
    return FILTER_CANON.get(letter.upper(), letter)


def normalize_object(name: str) -> str:
    """Vergleichsschlüssel für den Objektabgleich: Leerraum/Bindestriche raus,
    Großschreibung. ``"IC 417" → "IC417"``, ``"M 11" → "M11"``,
    ``"ngc_7000" → "NGC7000"``."""
    return re.sub(r"[\s_\-]+", "", name).upper()


def safe_component(value: str) -> str:
    """Macht ein Label sicher als Ordnername (kein Pfad-Trennzeichen,
    kein führender Punkt, kein Leerraum am Rand)."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", value).strip().strip(".")
    return cleaned or "Unbenannt"


def archive_dir(root: str, kind: str, object_label: str, device_label: str) -> PurePosixPath:
    """Zielverzeichnis im Archiv. ``kind`` ∈ {"RAW", "Developer"}.

    ``<root>/<kind>/<Objekt>/<Gerät>/`` — Filter/Belichtung stecken im
    Dateinamen, nicht im Pfad (eine Geräte-Ebene wie in deiner Struktur).
    """
    if kind not in ("RAW", "Developer"):
        raise ValueError(f"Ungültige Archiv-Art: {kind!r}")
    return (
        PurePosixPath(root)
        / kind
        / safe_component(object_label)
        / safe_component(device_label)
    )


def aggregate_frames(rows: list[dict]) -> dict:
    """Aggregiert Sub-Metadaten zu einer Zusammenfassung *pro Filter* —
    genau die „läuft alles unter einem Eintrag zusammen"-Sicht.

    ``rows``: Dicts mit ``filter_name``, ``exposure_s``. Liefert
    ``{"filters": [...], "total_subs", "total_integration_s"}``.
    """
    by_filter: dict[str, dict] = {}
    total_subs = 0
    total_int = 0.0
    for r in rows:
        f = r.get("filter_name") or "—"
        exp = float(r.get("exposure_s") or 0)
        slot = by_filter.setdefault(
            f, {"filter": f, "subs": 0, "integration_s": 0.0, "exposures_s": set()}
        )
        slot["subs"] += 1
        slot["integration_s"] += exp
        if exp:
            slot["exposures_s"].add(exp)
        total_subs += 1
        total_int += exp
    filters = []
    for slot in by_filter.values():
        filters.append({
            "filter": slot["filter"],
            "subs": slot["subs"],
            "integration_s": round(slot["integration_s"], 1),
            "exposures_s": sorted(slot["exposures_s"]),
        })
    # Stabile Reihenfolge: nach Filtername.
    filters.sort(key=lambda x: x["filter"])
    return {
        "filters": filters,
        "total_subs": total_subs,
        "total_integration_s": round(total_int, 1),
    }
