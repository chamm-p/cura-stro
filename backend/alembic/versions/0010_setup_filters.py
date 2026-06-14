"""setup_filters (welche Filter zu einem Setup)

Revision ID: 0010_setup_filters
Revises: 0009_setups
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_setup_filters"
down_revision = "0009_setups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setup_filters",
        sa.Column("setup_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("setups.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("filter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("filters.id", ondelete="CASCADE"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("setup_filters")
