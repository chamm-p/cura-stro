"""setups (telescope + camera bundle)

Revision ID: 0009_setups
Revises: 0008_images
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_setups"
down_revision = "0008_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=True),
        sa.Column("telescope_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("telescopes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_setups_user_id", "setups", ["user_id"])


def downgrade() -> None:
    op.drop_table("setups")
