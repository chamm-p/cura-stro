"""asiair marker_id (Wiedererkennung per Marker-Datei trotz IP-Wechsel)

Revision ID: 0016_asiair_marker
Revises: 0015_cloud_forecasts
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_asiair_marker"
down_revision = "0015_cloud_forecasts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("asiair_rigs", sa.Column("marker_id", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("asiair_rigs", "marker_id")
