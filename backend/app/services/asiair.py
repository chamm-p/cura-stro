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

# Dateiname-Muster. Filtergruppe optional (OSC ohne Filter). Zwischen
# Zeitstempel und Sequenznummer können neuere ASIAir-Firmwares beliebige
# Extra-Tokens einschieben (z. B. '333deg' = Rotator-/PA-Winkel):
#   Light_<obj>_<exp>s_Bin<n>[_<filter>]_<YYYYMMDD>-<HHMMSS>[_<extra>…]_<seq>[.<ext>]
_PATTERN = re.compile(
    r"^(?P<type>[A-Za-z][A-Za-z ]*?)_"
    r"(?P<obj>.+?)_"
    r"(?P<exp>\d+(?:\.\d+)?)s_"
    r"Bin(?P<bin>\d+)_"
    r"(?:(?P<filter>[^_]+)_)?"
    r"(?P<date>\d{8})-(?P<time>\d{6})"
    r"(?:_[^_]+)*?"                       # optionale Extra-Tokens (z. B. 333deg)
    r"_(?P<seq>\d+)"
    r"(?:\.(?P<ext>[A-Za-z0-9]+))?$"
)

# Fallback ohne Typ-Präfix: <obj>_<exp>s_Bin<n>[_<filter>]_<datum>-<zeit>_<seq>
# (manche Quellen/ältere Bestände lassen das 'Light_' weg) → zählt als Light.
_PATTERN_NOTYPE = re.compile(
    r"^(?P<obj>.+?)_"
    r"(?P<exp>\d+(?:\.\d+)?)s_"
    r"Bin(?P<bin>\d+)_"
    r"(?:(?P<filter>[^_]+)_)?"
    r"(?P<date>\d{8})-(?P<time>\d{6})"
    r"(?:_[^_]+)*?"                       # optionale Extra-Tokens (z. B. 333deg)
    r"_(?P<seq>\d+)"
    r"(?:\.(?P<ext>[A-Za-z0-9]+))?$"
)

# Alternatives Schema (z. B. E127-Aufnahmesoftware): Objekt zuerst, Typ danach,
# Filter VOR der Belichtung, BIN groß, Datum/Zeit mit Unterstrich:
#   IC5070_LIGHT_H_300s_BIN1_-8C_006_20240829_015258_066_GA_0_OF_0_PA101.08_E.FIT
_PATTERN_ALT = re.compile(
    r"^(?P<obj>.+?)_"
    r"(?P<type>LIGHT|DARK FLAT|DARKFLAT|DARK|FLAT|BIAS)_"
    r"(?:(?P<filter>[A-Za-z][A-Za-z0-9]*)_)?"
    r"(?P<exp>\d+(?:\.\d+)?)s?_"
    r"BIN(?P<bin>\d+)"
    r"(?P<rest>_.*)?$",
    re.IGNORECASE,
)
# Datum/Zeit (+ optionale Sequenz) irgendwo im Rest: _YYYYMMDD_HHMMSS[_SEQ]
_ALT_DATETIME = re.compile(r"_(?P<date>\d{8})_(?P<time>\d{6})(?:_(?P<seq>\d+))?")


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
    """Parst einen Frame-Dateinamen. ``None``, wenn es keiner ist.

    Zweistufig:
      1. Präzise Muster für die bekannten Schemata (ASIAir, E127).
      2. Fällt das durch, ein heuristischer Parser, der die Bausteine an
         ihrer FORM erkennt (Belichtung ``…s``, Binning ``Bin…``,
         Zeitstempel, Sequenz = letzte Zahl) statt an fester Position.
         Dadurch überlebt der Import künftige ASIAir-Namensänderungen
         (zusätzliche/umsortierte Tokens) OHNE Code-Anpassung."""
    name = PurePosixPath(filename.strip()).name
    strict = _parse_strict(name)
    if strict is not None:
        return strict
    return _heuristic_parse(name)


def _parse_strict(name: str) -> ParsedFrame | None:
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
    elif (m_alt := _PATTERN_ALT.match(name)):
        # Alternatives Schema: Objekt_TYP_Filter_Belichtung_BINn_…
        g = m_alt.groupdict()
        ftype = g["type"].strip().capitalize()
        obj = g["obj"].strip()
        dt = _ALT_DATETIME.search(g["rest"] or "")
        ext = PurePosixPath(name).suffix.lstrip(".").lower()
        flt = g["filter"]
        try:
            captured = datetime.strptime(dt.group("date") + dt.group("time"), "%Y%m%d%H%M%S") if dt else None
        except ValueError:
            captured = None
        if captured is None:
            return None
        return ParsedFrame(
            frame_type=ftype,
            object_name=obj,
            exposure_s=float(g["exp"]),
            binning=int(g["bin"]),
            filter_letter=flt,
            filter_name=canonical_filter(flt) if flt else None,
            captured_at=captured,
            sequence=int(dt.group("seq")) if dt and dt.group("seq") else 0,
            ext=ext,
            filename=name,
        )
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


# ─── Heuristischer Fallback-Parser (form- statt positionsbasiert) ───
_H_EXP = re.compile(r"^(\d+(?:\.\d+)?)s$", re.I)     # 30.0s / 300s
_H_BIN = re.compile(r"^bin(\d+)$", re.I)             # Bin1 / BIN1
_H_DT1 = re.compile(r"^(\d{8})-(\d{6})$")            # 20260713-041225 (ASIAir)
_H_D8 = re.compile(r"^\d{8}$")
_H_T6 = re.compile(r"^\d{6}$")
_H_NUM = re.compile(r"^\d+$")
_H_TEMP = re.compile(r"^-?\d+C$", re.I)              # -10C (Sensortemperatur)
_H_DEG = re.compile(r"^\d+deg$", re.I)               # 333deg (Rotatorwinkel)


def _heuristic_parse(name: str) -> ParsedFrame | None:
    """Erkennt Frame-Bausteine an ihrer Form statt an fester Position — für
    unbekannte/künftige Namensschemata."""
    stem = name
    ext = ""
    dot = stem.rfind(".")
    if dot > 0:
        ext = stem[dot + 1:].lower()
        stem = stem[:dot]
    toks = stem.split("_")
    if len(toks) < 3:
        return None

    def _find(rx):
        for i, t in enumerate(toks):
            m = rx.match(t)
            if m:
                return i, m
        return None, None

    exp_idx, exp_m = _find(_H_EXP)
    bin_idx, bin_m = _find(_H_BIN)
    if exp_idx is None or bin_idx is None:
        return None  # ohne Belichtung UND Binning kein Frame-Dateiname

    # Zeitstempel: kombiniert (ASIAir) oder getrennt (E127)
    dt_idx = dt_span = None
    captured = None
    for i, t in enumerate(toks):
        m = _H_DT1.match(t)
        if m:
            dt_idx, dt_span = i, 1
            try:
                captured = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
            except ValueError:
                captured = None
            break
    if dt_idx is None:
        for i in range(len(toks) - 1):
            if _H_D8.match(toks[i]) and _H_T6.match(toks[i + 1]):
                dt_idx, dt_span = i, 2
                try:
                    captured = datetime.strptime(toks[i] + toks[i + 1], "%Y%m%d%H%M%S")
                except ValueError:
                    captured = None
                break
    if dt_idx is None or captured is None:
        return None

    # Frame-Typ: erstes Token, das ein bekannter Typ ist (sonst Light)
    type_idx = None
    ftype = "Light"
    for i, t in enumerate(toks):
        if t.lower().replace(" ", "") in _KNOWN_TYPES:
            type_idx, ftype = i, t.strip().capitalize()
            break

    # Sequenz: erstes reines Zahl-Token NACH dem Zeitstempel
    seq = 0
    for t in toks[dt_idx + dt_span:]:
        if _H_NUM.match(t):
            seq = int(t)
            break

    # Filter + Objekt je nach Layout
    flt = None
    if type_idx is not None and 0 < type_idx < exp_idx:
        # E127: <obj>_TYP_[filter]_<exp>s_…
        obj = "_".join(toks[:type_idx]).strip()
        between = toks[type_idx + 1:exp_idx]
    else:
        # ASIAir: TYP_<obj…>_<exp>s_Bin_[filter]_<datum>_…
        start = (type_idx + 1) if (type_idx is not None and type_idx < exp_idx) else 0
        obj = "_".join(toks[start:exp_idx]).strip()
        between = toks[bin_idx + 1:dt_idx]   # zwischen Bin und Datum
    for cand in between:
        if (_H_NUM.match(cand) or _H_EXP.match(cand) or _H_BIN.match(cand)
                or _H_TEMP.match(cand) or _H_DEG.match(cand)):
            continue
        flt = cand
        break

    return ParsedFrame(
        frame_type=ftype,
        object_name=obj,
        exposure_s=float(exp_m.group(1)),
        binning=int(bin_m.group(1)),
        filter_letter=flt,
        filter_name=canonical_filter(flt) if flt else None,
        captured_at=captured,
        sequence=seq,
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
