"""Standort- und Equipment-Modelle (Phase 2).

Single-User, aber jede Zeile trägt ``user_id`` — sauber gescoped und
zukunftssicher. Gerätespezifikationen sind nullable: E127/RC71 werden mit
Namen geseedet, die optischen Werte trägt der Nutzer nach (Framing-Rechner
in Phase 7 nutzt sie dann).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# Welche Filter zu einem Setup gehören (Mono mit Filterrad: RGBL/Schmalband;
# OSC ohne Filter: keine Einträge).
setup_filters = Table(
    "setup_filters",
    Base.metadata,
    Column("setup_id", UUID(as_uuid=True), ForeignKey("setups.id", ondelete="CASCADE"), primary_key=True),
    Column("filter_id", UUID(as_uuid=True), ForeignKey("filters.id", ondelete="CASCADE"), primary_key=True),
)


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Bortle-Skala 1 (exzellent dunkel) – 9 (Innenstadt). Manuell gesetzt.
    bortle: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optionaler Link zur meteoblue Astronomy-Seeing-Seite dieses Standorts.
    meteoblue_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Telescope(Base):
    __tablename__ = "telescopes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    aperture_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    focal_length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Sinnvolle Grenzgröße (Magnitude) für die Objektliste. Wenn NULL, wird
    # bei Bedarf ein Vorschlag aus der Öffnung berechnet.
    limiting_magnitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    pixel_size_um: Mapped[float | None] = mapped_column(Float, nullable=True)
    res_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    res_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # "color" oder "mono"
    sensor_type: Mapped[str] = mapped_column(String(10), default="color", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Setup(Base):
    """Gebündelte optische Kette: Teleskop + Kamera (fest installiert)."""

    __tablename__ = "setups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    telescope_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("telescopes.id", ondelete="CASCADE"), nullable=False
    )
    camera_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Filter(Base):
    __tablename__ = "filters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # "broadband" (L/R/G/B) oder "narrowband" (Ha/OIII/SII)
    kind: Mapped[str] = mapped_column(String(16), default="broadband", nullable=False)
    # Bandbreite in nm — der entscheidende Parameter für Schmalband
    # (3/6/7/12 nm). Bei Breitband NULL (≈ volles sichtbares Band).
    bandwidth_nm: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
