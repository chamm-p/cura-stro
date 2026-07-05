"""Kalibrier-Cache für den PixInsight Mac-Agent.

CalibFile — SHA-256-Fingerprint je Kalibrier-Datei auf dem NAS. Vermeidet,
dass bei jedem Job jede Datei neu vom NAS gelesen und gehasht werden muss:
solange Größe+mtime unverändert sind, gilt der gespeicherte Hash.

CalibMaster — fertig gerechnete Master-Frames (Bias/Dark/Flat), die nach dem
ersten Batch zurück aufs NAS geschrieben wurden (Calib/Masters/). Schlüssel
ist der set_hash: SHA-256 über die sortierten Datei-Hashes des Eingabe-Sets.
Ändert sich eine Quelldatei, ändert sich der set_hash → neuer Master.
"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CalibFile(Base):
    __tablename__ = "calib_files"
    __table_args__ = (
        UniqueConstraint("user_id", "path", name="uq_calib_file_user_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(700), nullable=False)  # relativ zum Archiv-Root
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mtime: Mapped[float] = mapped_column(Float, nullable=False)  # Unix-Epoch
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CalibMaster(Base):
    __tablename__ = "calib_masters"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "set_hash", name="uq_calib_master_set"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # bias | dark | flat
    set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_path: Mapped[str] = mapped_column(String(700), nullable=False)  # Calib/Masters/…
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
