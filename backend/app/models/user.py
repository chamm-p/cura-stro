"""User-Modell (lokal + OIDC). Vereinfacht ggü. curai (Single-User)."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class AuthMethod(str, enum.Enum):
    LOCAL = "local"
    OIDC = "oidc"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # values_callable: PG-Enum speichert den ``.value`` (klein), nicht den
    # Member-Namen — passend zu den in der Migration angelegten Werten.
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=UserRole.ADMIN,
        nullable=False,
    )
    auth_method: Mapped[AuthMethod] = mapped_column(
        SAEnum(
            AuthMethod,
            name="auth_method",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=AuthMethod.LOCAL,
        nullable=False,
    )
    oidc_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)

    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(256), nullable=True)

    settings: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    language: Mapped[str] = mapped_column(
        String(8), default="de", server_default="de", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
