"""Schemas für Beobachtungen / Aufnahmen (Phase 5)."""

from datetime import date

from pydantic import BaseModel, Field


class ObservationCreate(BaseModel):
    catalog_object_id: str | None = None
    target_label: str | None = Field(default=None, max_length=160)
    status: str = Field(default="geplant", pattern="^(geplant|raw|entwickelt)$")
    telescope_id: str | None = None
    planned_date: date | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)


class PlanRequest(BaseModel):
    """„Einplanen" aus der Objektliste — Upsert nach Objekt + Teleskop."""
    catalog_object_id: str | None = None
    target_label: str | None = Field(default=None, max_length=160)
    telescope_id: str | None = None


class ObservationUpdate(BaseModel):
    target_label: str | None = Field(default=None, max_length=160)
    status: str | None = Field(default=None, pattern="^(geplant|raw|entwickelt)$")
    telescope_id: str | None = None
    planned_date: date | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)


class ObservationOut(BaseModel):
    id: str
    catalog_object_id: str | None
    # angereicherte Objektinfos (falls Katalogobjekt)
    object_ident: str | None
    object_name: str | None
    object_type: str | None
    object_catalog: str | None
    target_label: str | None
    display_label: str
    status: str
    telescope_id: str | None
    telescope_name: str | None
    planned_date: date | None
    rating: int | None
    notes: str | None
    is_new: bool = False
    created_at: str | None
    image_count: int = 0
    subframe_count: int = 0
    integration_s: float = 0.0
    result_count: int = 0
