"""observing — locations, telescopes, cameras, filters

Revision ID: 0002_observing
Revises: 0001_initial
Create Date: 2026-06-13
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_observing"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _user_fk():
    return sa.Column(
        "user_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=True),
        sa.Column("bortle", sa.Integer(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_locations_user_id", "locations", ["user_id"])

    op.create_table(
        "telescopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("aperture_mm", sa.Float(), nullable=True),
        sa.Column("focal_length_mm", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_telescopes_user_id", "telescopes", ["user_id"])

    op.create_table(
        "cameras",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("pixel_size_um", sa.Float(), nullable=True),
        sa.Column("res_x", sa.Integer(), nullable=True),
        sa.Column("res_y", sa.Integer(), nullable=True),
        sa.Column("sensor_type", sa.String(10), nullable=False, server_default="color"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cameras_user_id", "cameras", ["user_id"])

    op.create_table(
        "filters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _user_fk(),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="broadband"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_filters_user_id", "filters", ["user_id"])


def downgrade() -> None:
    op.drop_table("filters")
    op.drop_table("cameras")
    op.drop_table("telescopes")
    op.drop_table("locations")
