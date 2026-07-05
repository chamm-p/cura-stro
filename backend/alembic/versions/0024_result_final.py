"""ResultFile.is_final — markiert die finalen Ergebnisbilder (Slideshow).

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "result_files",
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("result_files", "is_final")
