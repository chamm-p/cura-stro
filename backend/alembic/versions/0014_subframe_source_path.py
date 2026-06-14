"""subframe source_path (ASIAir-Quellpfad für On-Demand-Cleanup)

Revision ID: 0014_subframe_source_path
Revises: 0013_v2_archive
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_subframe_source_path"
down_revision = "0013_v2_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sub_frames", sa.Column("source_path", sa.String(length=700), nullable=True))


def downgrade() -> None:
    op.drop_column("sub_frames", "source_path")
