"""Datenbank-Setup — sync Engine für Alembic/Tests + async für die App."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

# sync Engine für Alembic und Tests (inspect(engine) funktioniert)
engine = create_engine(
    settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
    echo=settings.debug,
)

# sync Session für Tests
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """Basisklasse für alle ORM-Modelle."""


def get_db():
    """Dependency: liefert eine sync DB-Session."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()