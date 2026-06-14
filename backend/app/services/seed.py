"""Seed-Daten für einen neuen User: Default-Teleskope + Standard-Filter-Set."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.observing import Filter, Telescope

# E127/RC71 als Namen vorbelegt (Req 5). Optische Werte trägt der Nutzer
# in den Einstellungen nach — der Framing-Rechner (Phase 7) braucht sie.
_DEFAULT_TELESCOPES = [
    {"name": "E127", "aperture_mm": None, "focal_length_mm": None,
     "notes": "Bitte Öffnung/Brennweite ergänzen."},
    {"name": "RC71", "aperture_mm": None, "focal_length_mm": None,
     "notes": "Bitte Öffnung/Brennweite ergänzen."},
]

# Typisches, statisches Standard-Filter-Set. Breitband L/R/G/B ohne
# Bandbreite (≈ volles Band), Schmalband Ha/OIII/SII mit 7 nm (gängiger
# Default; in den Einstellungen editierbar, z. B. 3/6/12 nm).
_DEFAULT_FILTERS = [
    {"name": "L", "kind": "broadband", "bandwidth_nm": None},
    {"name": "R", "kind": "broadband", "bandwidth_nm": None},
    {"name": "G", "kind": "broadband", "bandwidth_nm": None},
    {"name": "B", "kind": "broadband", "bandwidth_nm": None},
    {"name": "Ha", "kind": "narrowband", "bandwidth_nm": 7.0},
    {"name": "OIII", "kind": "narrowband", "bandwidth_nm": 7.0},
    {"name": "SII", "kind": "narrowband", "bandwidth_nm": 7.0},
]


async def seed_default_equipment(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Legt Default-Teleskope + Standard-Filter an, falls noch keine da sind."""
    scope_count = await db.scalar(
        select(func.count()).select_from(Telescope).where(Telescope.user_id == user_id)
    )
    if not scope_count:
        for spec in _DEFAULT_TELESCOPES:
            db.add(Telescope(user_id=user_id, **spec))

    filter_count = await db.scalar(
        select(func.count()).select_from(Filter).where(Filter.user_id == user_id)
    )
    if not filter_count:
        for spec in _DEFAULT_FILTERS:
            db.add(Filter(user_id=user_id, **spec))
