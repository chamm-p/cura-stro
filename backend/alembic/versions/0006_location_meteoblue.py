"""location meteoblue_url

Revision ID: 0006_location_meteoblue
Revises: 0005_telescope_limmag
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_location_meteoblue"
down_revision = "0005_telescope_limmag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("locations", sa.Column("meteoblue_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("locations", "meteoblue_url")
