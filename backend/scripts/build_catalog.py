#!/usr/bin/env python3
"""Erzeugt den gebündelten Deep-Sky-Katalog aus OpenNGC.

Quelle: OpenNGC (https://github.com/mattiaverga/OpenNGC), CC-BY-SA-4.0.
Lädt NGC.csv + addendum.csv (oder nutzt lokale Pfade) und schreibt einen
schlanken JSON-Katalog nach app/data/catalog.json: alle Messier-Objekte
plus helle NGC/IC (V/B-Magnitude ≤ 10.5), ohne Sterne/Duplikate.

Aufruf:
    python scripts/build_catalog.py [NGC.csv addendum.csv]
Ohne Argumente werden die Dateien von GitHub geladen.
"""

import csv
import json
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "app" / "data" / "catalog.json"
BASE = "https://raw.githubusercontent.com/mattiaverga/OpenNGC/master/database_files"
MAG_LIMIT = 10.5

# OpenNGC-Typ → (interner Typ, ist_breitband/mondempfindlich)
TYPE_MAP = {
    "G": ("galaxy", True),
    "GPair": ("galaxy", True),
    "GTrpl": ("galaxy", True),
    "GGroup": ("galaxy", True),
    "OCl": ("open_cluster", True),
    "GCl": ("globular_cluster", True),
    "Cl+N": ("cluster_nebulosity", True),
    "RfN": ("reflection_nebula", True),
    "PN": ("planetary_nebula", False),
    "HII": ("emission_nebula", False),
    "EmN": ("emission_nebula", False),
    "SNR": ("supernova_remnant", False),
    "Neb": ("nebula", False),
}
SKIP = {"*", "**", "*Ass", "Dup", "NonEx", "Nova", "Other"}


def _ra_deg(s: str) -> float | None:
    if not s:
        return None
    h, m, sec = s.split(":")
    return (float(h) + float(m) / 60 + float(sec) / 3600) * 15.0


def _dec_deg(s: str) -> float | None:
    if not s:
        return None
    sign = -1.0 if s.strip().startswith("-") else 1.0
    d, m, sec = s.replace("+", "").replace("-", "").split(":")
    return sign * (abs(float(d)) + float(m) / 60 + float(sec) / 3600)


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _load(path_or_url: str) -> list[dict]:
    if path_or_url.startswith("http"):
        with urllib.request.urlopen(path_or_url) as r:
            text = r.read().decode("utf-8")
    else:
        text = Path(path_or_url).read_text(encoding="utf-8")
    return list(csv.DictReader(text.splitlines(), delimiter=";"))


def _designation(row: dict) -> tuple[str, str]:
    """(catalog, ident) ableiten."""
    m = (row.get("M") or "").strip()
    if m:
        return "Messier", f"M{int(m)}"
    name = (row.get("Name") or "").strip()
    if name.startswith("NGC"):
        return "NGC", "NGC" + str(int(name[3:7])) + name[7:]
    if name.startswith("IC"):
        return "IC", "IC" + str(int(name[2:6])) + name[6:]
    return "Other", name


def build(sources: list[str]) -> None:
    seen: dict[str, dict] = {}
    for src in sources:
        for row in _load(src):
            t = (row.get("Type") or "").strip()
            if t in SKIP or t not in TYPE_MAP:
                continue
            ra = _ra_deg((row.get("RA") or "").strip())
            dec = _dec_deg((row.get("Dec") or "").strip())
            if ra is None or dec is None:
                continue
            mag = _num(row.get("V-Mag")) or _num(row.get("B-Mag"))
            catalog, ident = _designation(row)
            # Aufnahmekriterium: Messier immer, sonst nur hell genug.
            if catalog != "Messier" and (mag is None or mag > MAG_LIMIT):
                continue
            obj_type, broadband = TYPE_MAP[t]
            entry = {
                "catalog": catalog,
                "ident": ident,
                "name": (row.get("Common names") or "").split(",")[0].strip() or None,
                "ra_deg": round(ra, 5),
                "dec_deg": round(dec, 5),
                "magnitude": round(mag, 2) if mag is not None else None,
                "obj_type": obj_type,
                "broadband": broadband,
                "size_major_arcmin": _num(row.get("MajAx")),
                "size_minor_arcmin": _num(row.get("MinAx")),
                "constellation": (row.get("Const") or "").strip() or None,
                "source_name": (row.get("Name") or "").strip(),
            }
            # Dedup: Messier-Eintrag gewinnt über reinen NGC-Eintrag.
            key = entry["ident"]
            if key not in seen or (catalog == "Messier" and seen[key]["catalog"] != "Messier"):
                seen[key] = entry

    catalog = sorted(seen.values(), key=lambda e: (e["magnitude"] is None, e["magnitude"] or 99))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=0), encoding="utf-8")
    messier = sum(1 for e in catalog if e["catalog"] == "Messier")
    print(f"{len(catalog)} Objekte geschrieben ({messier} Messier) → {OUT}")


if __name__ == "__main__":
    args = sys.argv[1:]
    srcs = args if args else [f"{BASE}/NGC.csv", f"{BASE}/addendum.csv"]
    build(srcs)
