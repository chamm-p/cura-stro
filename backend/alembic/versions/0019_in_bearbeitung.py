"""observation_status_in_bearbeitung

Erlaubt den Status 'in_bearbeitung' für Observations (PixInsight-Batch läuft).
Da der Status als String gespeichert wird (kein PG-Enum), ist keine
Schema-Änderung nötig — diese Migration ist ein Platzhalter für die
Dokumentation und eventuelle spätere Constraints.

Revision ID: 0019_in_bearbeitung
Revises: 0018_result_files
Create Date: 2026-06-20
"""
from alembic import op

revision = "0019_in_bearbeitung"
down_revision = "0018_result_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Status ist ein String-Feld (String(16)), kein Enum — keine Änderung nötig.
    # Neue Status-Werte: geplant · raw · in_bearbeitung · entwickelt
    pass


def downgrade() -> None:
    pass
