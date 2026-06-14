"""Schemas für die Objektliste (Phase 3)."""

from pydantic import BaseModel


class TargetOut(BaseModel):
    id: str
    catalog: str
    ident: str
    name: str | None
    obj_type: str
    broadband: bool
    magnitude: float | None
    constellation: str | None
    ra_deg: float
    dec_deg: float
    size_major_arcmin: float | None
    size_minor_arcmin: float | None
    # Sichtbarkeit
    max_altitude: float | None
    best_time_local: str | None
    azimuth_at_best: float | None
    visible: bool
    altitude_track: list[float] = []
    # Bestes Aufnahmefenster (Höhe × Bewölkung)
    best_window_start: str | None = None
    best_window_end: str | None = None
    best_window_reason: str | None = None
    # Mondlicht
    moon_separation_deg: float | None = None
    moon_impact: str = "none"  # none | mild | strong
    moon_note: str | None = None
    # Verwaltungs-Status — abhängig vom Teleskop-Filter (None = nichts erfasst).
    status: str | None = None            # geplant | raw | entwickelt
    rating: int | None = None            # 1–5 (v.a. bei entwickelt)
    photographed: bool
    capture_count: int = 0
    telescopes: list[str] = []
    preview_url: str


class TargetListOut(BaseModel):
    location: dict
    date: str
    night_start: str
    night_end: str
    time_grid: list[str] = []
    magnitude_limit: float | None = None
    telescope: dict | None = None
    moon: dict | None = None
    weather: dict | None = None
    count: int
    targets: list[TargetOut]
