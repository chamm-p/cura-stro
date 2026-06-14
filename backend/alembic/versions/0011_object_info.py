"""object_info (Hintergrundinfos-Cache)

Revision ID: 0011_object_info
Revises: 0010_setup_filters
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_object_info"
down_revision = "0010_setup_filters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "object_info",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("catalog_object_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("catalog_objects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("url", sa.String(500), nullable=True),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("facts", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_object_info_catalog_object_id", "object_info", ["catalog_object_id"], unique=True)


def downgrade() -> None:
    op.drop_table("object_info")
