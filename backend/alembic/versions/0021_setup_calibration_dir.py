"""setup_calibration_dir

Fügt das Feld 'calibration_dir' zur Setups-Tabelle hinzu.
Pro Setup (Teleskop+Kamera) kann ein Pfad auf dem Mac hinterlegt werden,
wo Flats/Darks/Bias für PixInsight/WBPP liegen.

Revision ID: 0021_setup_calibration_dir
Revises: 0020_vorbereitet
Create Date: 2026-06-15
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_setup_calibration_dir"
down_revision = "0020_vorbereitet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("setups", sa.Column("calibration_dir", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("setups", "calibration_dir")
