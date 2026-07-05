"""PixInsight-Ergebnisbilder (V2 Phase C) — pro Aufnahme.

Liegt im NAS-Archiv unter ``Developer/<Objekt>/<Gerät>/``. Entweder hochgeladen
(``source="upload"``) oder vom Watch-Folder dort gefunden (``source="watch"``).
Eine JPG-Vorschau wird lokal gecacht (outputs/resultprev)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ResultFile(Base):
    __tablename__ = "result_files"
    __table_args__ = (
        UniqueConstraint("observation_id", "filename", name="uq_result_obs_filename"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("observations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    archive_path: Mapped[str | None] = mapped_column(String(700), nullable=True)  # Voller Pfad im Developer-Baum
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)  # upload | watch | batch
    # Final-Markierung (Häkchen im UI): DAS fertige Bild / die fertigen Bilder
    # der Aufnahme — nur diese erscheinen in der Slideshow.
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
