"""cloud_forecasts (gecachte meteoblue-Wolken via Vision-LLM)

Revision ID: 0015_cloud_forecasts
Revises: 0014_subframe_source_path
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0015_cloud_forecasts"
down_revision = "0014_subframe_source_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_forecasts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", UUID(as_uuid=True), sa.ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="meteoblue"),
        sa.Column("hours", JSONB, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cloud_forecasts_user_id", "cloud_forecasts", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_cloud_forecasts_user_id", table_name="cloud_forecasts")
    op.drop_table("cloud_forecasts")
