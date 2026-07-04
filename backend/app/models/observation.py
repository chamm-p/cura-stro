"""Beobachtungen / fotografierte Objekte (Phase 5 — Tabelle hier vorgezogen,
damit Phase 3 das „schon fotografiert?"-Flag setzen kann)."""

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Status-Werte als String (keine PG-Enums → kein Casing-Gotcha):
#   geplant · raw · in_bearbeitung · vorbereitet · entwickelt
STATUSES = ("geplant", "raw", "in_bearbeitung", "vorbereitet", "entwickelt")


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    catalog_object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog_objects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Freitext-Ziel, falls kein Katalogobjekt (z. B. eigenes Mosaik).
    target_label: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="geplant", nullable=False)
    telescope_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telescopes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    planned_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Bewertung 1–5 (5 = super) — v.a. fürs entwickelte Foto relevant.
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Frisch aus der Objektliste eingeplant und noch nicht in der Verwaltung
    # bearbeitet (= „neu"). Wird bei jeder Mutation in der Verwaltung gelöscht.
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
