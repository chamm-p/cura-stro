"""Gecachte meteoblue-Wolken (Vision-LLM) je Standort (V2).

Eine Zeile pro Standort; ``hours`` = Liste {date, hour, low, mid, high} über
die nächsten ~3 Tage. Täglich vom Scheduler aktualisiert."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CloudForecast(Base):
    __tablename__ = "cloud_forecasts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    source: Mapped[str] = mapped_column(String(32), default="meteoblue", nullable=False)
    hours: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
