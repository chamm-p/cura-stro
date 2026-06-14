"""observation is_new

Revision ID: 0012_observation_is_new
Revises: 0011_object_info
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_observation_is_new"
down_revision = "0011_object_info"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("observations", sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("observations", "is_new")
