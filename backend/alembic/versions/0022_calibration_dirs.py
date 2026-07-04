"""Separate Calibration-Dirs für Flats, Darks, Bias.

Revision ID: 0022
Revises: 0021
Create Date: 2025-01-22
"""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("setups", sa.Column("flats_dir", sa.String(500), nullable=True))
    op.add_column("setups", sa.Column("darks_dir", sa.String(500), nullable=True))
    op.add_column("setups", sa.Column("bias_dir", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("setups", "bias_dir")
    op.drop_column("setups", "darks_dir")
    op.drop_column("setups", "flats_dir")
