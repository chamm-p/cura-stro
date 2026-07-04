"""observation_status_vorbereitet

Fügt den Status 'vorbereitet' für Observations hinzu. Dieser Status wird
gesetzt, nachdem der automatische WBPP-Batch (PixInsight) abgeschlossen ist
und die Master-Files im Prepared/-Ordner liegen. Der Nutzer kann dann in
PixInsight manuell weiterentwickeln; das fertige Bild wird in den Developer/-
Ordner gelegt → Watch-Loop → Status 'entwickelt'.

Da der Status als String gespeichert wird (kein PG-Enum), ist keine
Schema-Änderung nötig — diese Migration dokumentiert den neuen Status-Wert.

Status-Fluss:
    geplant → raw → in_bearbeitung → vorbereitet → entwickelt

Revision ID: 0020_vorbereitet
Revises: 0019_in_bearbeitung
Create Date: 2026-06-21
"""
from alembic import op

revision = "0020_vorbereitet"
down_revision = "0019_in_bearbeitung"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Status ist ein String-Feld (String(16)), kein Enum — keine Änderung nötig.
    # Neue Status-Werte: geplant · raw · in_bearbeitung · vorbereitet · entwickelt
    pass


def downgrade() -> None:
    pass
