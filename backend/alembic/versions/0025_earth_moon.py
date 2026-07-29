"""earth moon

Revision ID: 0025_earth_moon
Revises: d3648f0eacd8
Create Date: 2025-07-28 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = '0025_earth_moon'
down_revision = 'd3648f0eacd8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO solarsystem_objects (id, name, object_type, description, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :name, :otype, :desc, NOW(), NOW()) "
            "ON CONFLICT (name) DO NOTHING"
        ).bindparams(
            name="Erdenmond",
            otype="moon",
            desc="Einziger natürlicher Trabant der Erde. Durchmesser 3.474 km, Umlaufzeit 27,3 Tage.",
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM solarsystem_objects WHERE name = :name").bindparams(name="Erdenmond"))