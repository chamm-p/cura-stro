"""subframe quality flag (ok/nok aus der Sichtung)

Revision ID: 0017_subframe_quality
Revises: 0016_asiair_marker
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_subframe_quality"
down_revision = "0016_asiair_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sub_frames", sa.Column("quality", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("sub_frames", "quality")
