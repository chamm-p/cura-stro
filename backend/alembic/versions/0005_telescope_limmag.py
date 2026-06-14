"""telescope limiting_magnitude

Revision ID: 0005_telescope_limmag
Revises: 0004_catalog_observations
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_telescope_limmag"
down_revision = "0004_catalog_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telescopes", sa.Column("limiting_magnitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("telescopes", "limiting_magnitude")
