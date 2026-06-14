"""observation rating

Revision ID: 0007_observation_rating
Revises: 0006_location_meteoblue
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_observation_rating"
down_revision = "0006_location_meteoblue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("observations", sa.Column("rating", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("observations", "rating")
