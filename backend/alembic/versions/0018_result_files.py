"""result_files (PixInsight-Ergebnisbilder im Developer-Baum)

Revision ID: 0018_result_files
Revises: 0017_subframe_quality
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0018_result_files"
down_revision = "0017_subframe_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "result_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("observation_id", UUID(as_uuid=True), sa.ForeignKey("observations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("archive_path", sa.String(length=700), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("observation_id", "filename", name="uq_result_obs_filename"),
    )
    op.create_index("ix_result_files_user_id", "result_files", ["user_id"])
    op.create_index("ix_result_files_observation_id", "result_files", ["observation_id"])


def downgrade() -> None:
    op.drop_index("ix_result_files_observation_id", table_name="result_files")
    op.drop_index("ix_result_files_user_id", table_name="result_files")
    op.drop_table("result_files")
