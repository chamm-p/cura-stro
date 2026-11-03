#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# cura-stro — Backup (für Umzug auf einen anderen Rechner / Disaster-Recovery)
#
# Sichert die DATEN, nicht den Code (der liegt in git):
#   1. PostgreSQL-Datenbank  (pg_dump — portabel, architektur-unabhängig)
#   2. .env                  (Secrets/Config: DB-Passwort, OIDC, LLM-Token …)
#   3. outputs-Volume        (Vorschau-JPGs / Seeing-Cache — klein)
#   4. lokales Archiv        (NUR mit --archive; die NAS-Fotos liegen extern
#                             und bleiben für den neuen Host über SMB erreichbar)
#
# Ergebnis: ein einzelnes cura-stro-backup-<zeit>.tar.gz
#
# Usage:
#   ./backup.sh                 → Backup nach ./backups/
#   ./backup.sh /pfad/zum/ziel  → Backup in ein anderes Verzeichnis
#   ./backup.sh --archive       → zusätzlich das LOKALE ./archive mitsichern
#   ./backup.sh --keep 7        → nur die letzten 7 Backups behalten (Rotation)
#
# Wiederherstellen: ./restore.sh <backup.tar.gz>  (siehe restore.sh)
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"   # ins deploy/-Verzeichnis

OUT_DIR="./backups"
WITH_ARCHIVE=0
KEEP=0
while [ $# -gt 0 ]; do
    case "$1" in
        --archive) WITH_ARCHIVE=1 ;;
        --keep)    KEEP="${2:?--keep braucht eine Zahl}"; shift ;;
        -*)        echo "Unbekannte Option: $1"; exit 1 ;;
        *)         OUT_DIR="$1" ;;
    esac
    shift
done

[ -f .env ] || { echo "✗ .env nicht gefunden (im deploy/-Verzeichnis ausführen)"; exit 1; }
set -a; . ./.env; set +a
PG_DB="${POSTGRES_DB:-curastro}"
PG_USER="${POSTGRES_USER:-curastro}"

# Volume-Namen (in docker-compose.yml auf deploy_* gepinnt)
VOL_OUTPUTS="deploy_outputs"

STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT_DIR"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "→ Datenbank sichern (pg_dump) …"
docker compose exec -T db pg_dump -U "$PG_USER" -d "$PG_DB" \
    --clean --if-exists --no-owner --no-privileges > "$WORK/db.sql"
echo "  DB-Dump: $(du -h "$WORK/db.sql" | cut -f1)"

echo "→ .env sichern …"
cp .env "$WORK/env.backup"

echo "→ outputs-Volume sichern …"
if docker volume inspect "$VOL_OUTPUTS" >/dev/null 2>&1; then
    docker run --rm -v "$VOL_OUTPUTS":/data:ro -v "$WORK":/bak alpine \
        tar cf /bak/outputs.tar -C /data . 2>/dev/null \
        && echo "  outputs: $(du -h "$WORK/outputs.tar" | cut -f1)" \
        || echo "  (outputs leer)"
else
    echo "  (Volume $VOL_OUTPUTS nicht vorhanden — übersprungen)"
fi

if [ "$WITH_ARCHIVE" = "1" ]; then
    ARCH="${ARCHIVE_PATH:-../archive}"
    if [ -d "$ARCH" ]; then
        echo "→ lokales Archiv sichern ($ARCH) — kann groß sein …"
        tar cf "$WORK/archive.tar" -C "$ARCH" . 2>/dev/null \
            && echo "  archive: $(du -h "$WORK/archive.tar" | cut -f1)"
    else
        echo "  (Archiv-Pfad $ARCH nicht vorhanden)"
    fi
fi

# Manifest fürs schnelle Nachschlagen
{
    echo "cura-stro Backup"
    echo "erstellt:   $(date -Iseconds)"
    echo "host:       $(hostname)"
    echo "git-commit: $(git -C .. rev-parse --short HEAD 2>/dev/null || echo '?')"
    echo "db:         $PG_DB (user $PG_USER)"
    echo "enthält:    db.sql env.backup$( [ -f "$WORK/outputs.tar" ] && echo ' outputs.tar')$( [ -f "$WORK/archive.tar" ] && echo ' archive.tar')"
} > "$WORK/MANIFEST.txt"

TARBALL="$OUT_DIR/cura-stro-backup-$STAMP.tar.gz"
tar czf "$TARBALL" -C "$WORK" .
echo "✓ Backup erstellt: $TARBALL ($(du -h "$TARBALL" | cut -f1))"

if [ "$KEEP" -gt 0 ]; then
    # Älteste über das Limit hinaus löschen
    ls -1t "$OUT_DIR"/cura-stro-backup-*.tar.gz 2>/dev/null | tail -n "+$((KEEP+1))" | while read -r old; do
        rm -f "$old" && echo "  Rotation: alt entfernt $(basename "$old")"
    done
fi
