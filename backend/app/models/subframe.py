"""Einzelne Subframes einer Aufnahme (V2 Phase A).

Jeder Sub gehört zu **einer** Observation (= ein Objekt + ein Gerät). Mehrere
Nächte, Belichtungen und Filter laufen unter demselben Eintrag zusammen — der
Verwaltungsschlüssel bleibt stabil (Objekt+Gerät), hier liegen nur die
Detailzahlen, die darunter aggregiert werden.

``verified`` markiert, dass die Datei nachweislich (Größe/Prüfsumme) im
Archiv liegt — Voraussetzung fürs sichere On-Demand-Aufräumen der ASIAir
(Phase B).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SubFrame(Base):
    __tablename__ = "sub_frames"
    __table_args__ = (
        # Dublettenschutz: derselbe Originaldateiname je Aufnahme nur einmal.
        UniqueConstraint("observation_id", "original_filename", name="uq_subframe_obs_filename"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    frame_type: Mapped[str] = mapped_column(String(16), default="Light", nullable=False)
    # Kanonischer Filtername (z. B. "Ha"), NULL bei OSC.
    filter_name: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exposure_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    binning: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gain: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Zielpfad im Archiv (NAS), sobald abgelegt.
    archive_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    # Quellpfad auf der ASIAir (UNC), für sicheres On-Demand-Cleanup.
    source_path: Mapped[str | None] = mapped_column(String(700), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Herkunft: "asiair" | "upload".
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
