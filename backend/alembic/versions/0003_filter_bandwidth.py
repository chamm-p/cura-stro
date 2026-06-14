"""filter bandwidth_nm

Revision ID: 0003_filter_bandwidth
Revises: 0002_observing
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_filter_bandwidth"
down_revision = "0002_observing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("filters", sa.Column("bandwidth_nm", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("filters", "bandwidth_nm")
