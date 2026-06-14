"""catalog_objects + observations

Revision ID: 0004_catalog_observations
Revises: 0003_filter_bandwidth
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_catalog_observations"
down_revision = "0003_filter_bandwidth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("catalog", sa.String(16), nullable=False),
        sa.Column("ident", sa.String(32), nullable=False),
        sa.Column("name", sa.String(160), nullable=True),
        sa.Column("ra_deg", sa.Float(), nullable=False),
        sa.Column("dec_deg", sa.Float(), nullable=False),
        sa.Column("magnitude", sa.Float(), nullable=True),
        sa.Column("obj_type", sa.String(32), nullable=False),
        sa.Column("broadband", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("size_major_arcmin", sa.Float(), nullable=True),
        sa.Column("size_minor_arcmin", sa.Float(), nullable=True),
        sa.Column("constellation", sa.String(8), nullable=True),
        sa.Column("source_name", sa.String(64), nullable=True),
    )
    op.create_index("ix_catalog_objects_catalog", "catalog_objects", ["catalog"])
    op.create_index("ix_catalog_objects_ident", "catalog_objects", ["ident"], unique=True)
    op.create_index("ix_catalog_objects_magnitude", "catalog_objects", ["magnitude"])

    op.create_table(
        "observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("catalog_object_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("catalog_objects.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_label", sa.String(160), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="geplant"),
        sa.Column("telescope_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("telescopes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("planned_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_observations_user_id", "observations", ["user_id"])
    op.create_index("ix_observations_catalog_object_id", "observations", ["catalog_object_id"])


def downgrade() -> None:
    op.drop_table("observations")
    op.drop_table("catalog_objects")
