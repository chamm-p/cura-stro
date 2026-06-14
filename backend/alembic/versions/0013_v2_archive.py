"""v2 archive: asiair_rigs + sub_frames

Revision ID: 0013_v2_archive
Revises: 0012_observation_is_new
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0013_v2_archive"
down_revision = "0012_observation_is_new"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asiair_rigs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("share", sa.String(length=255), nullable=True),
        sa.Column("telescope_id", UUID(as_uuid=True), sa.ForeignKey("telescopes.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_asiair_rigs_user_id", "asiair_rigs", ["user_id"])

    op.create_table(
        "sub_frames",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_id", UUID(as_uuid=True), sa.ForeignKey("observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("frame_type", sa.String(length=16), nullable=False, server_default="Light"),
        sa.Column("filter_name", sa.String(length=16), nullable=True),
        sa.Column("exposure_s", sa.Float(), nullable=True),
        sa.Column("binning", sa.Integer(), nullable=True),
        sa.Column("gain", sa.Integer(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("archive_path", sa.String(length=700), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("observation_id", "original_filename", name="uq_subframe_obs_filename"),
    )
    op.create_index("ix_sub_frames_user_id", "sub_frames", ["user_id"])
    op.create_index("ix_sub_frames_observation_id", "sub_frames", ["observation_id"])


def downgrade() -> None:
    op.drop_index("ix_sub_frames_observation_id", table_name="sub_frames")
    op.drop_index("ix_sub_frames_user_id", table_name="sub_frames")
    op.drop_table("sub_frames")
    op.drop_index("ix_asiair_rigs_user_id", table_name="asiair_rigs")
    op.drop_table("asiair_rigs")
