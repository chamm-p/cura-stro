"""Deep-Sky-Katalog (gebündelt geseedet aus OpenNGC) — Phase 3."""

import uuid

from sqlalchemy import Boolean, Float, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CatalogObject(Base):
    __tablename__ = "catalog_objects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    catalog: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # Messier/NGC/IC/Other
    ident: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    ra_deg: Mapped[float] = mapped_column(Float, nullable=False)
    dec_deg: Mapped[float] = mapped_column(Float, nullable=False)
    magnitude: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    # galaxy/open_cluster/globular_cluster/planetary_nebula/emission_nebula/…
    obj_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # True = Breitband-Ziel (RGB/L, mondempfindlich); False = Schmalband-tauglich.
    broadband: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    size_major_arcmin: Mapped[float | None] = mapped_column(Float, nullable=True)
    size_minor_arcmin: Mapped[float | None] = mapped_column(Float, nullable=True)
    constellation: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
