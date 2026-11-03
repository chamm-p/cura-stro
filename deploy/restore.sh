#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# cura-stro — Restore (Gegenstück zu backup.sh)
#
# Stellt ein Backup auf DIESEM Rechner wieder her. Typischer Umzug:
#   1. Auf dem neuen Rechner:  git clone <repo> && cd cura-stro/deploy
#   2. Backup-Datei herkopieren (z. B. per scp)
#   3. ./restore.sh cura-stro-backup-<zeit>.tar.gz
#   4. Fertig — die App läuft mit allen Daten; das NAS-Foto-Archiv wird über
#      die bestehende App-Konfiguration (Einstellungen → Archiv) wieder
#      angesprochen (gleiche NAS-IP/Freigabe vorausgesetzt).
#
# Ablauf: .env wiederherstellen → DB-Container starten → DB einspielen →
#         outputs-Volume einspielen → alle Container starten (Backend führt
#         beim Start die Alembic-Migrationen aus; der Dump ist bereits auf
#         dem aktuellen Stand, also passiert dort nichts mehr).
#
# Usage:  ./restore.sh <backup.tar.gz> [--force]
#   --force  überschreibt eine bereits vorhandene .env ohne Rückfrage
# ──────────────────────────────────────────────────────────────────────────
set -euo pipefail
cd "$(dirname "$0")"

BAK="${1:?Usage: ./restore.sh <backup.tar.gz> [--force]}"
FORCE=0
[ "${2:-}" = "--force" ] && FORCE=1
[ -f "$BAK" ] || { echo "✗ Backup nicht gefunden: $BAK"; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
echo "→ Backup entpacken …"
tar xzf "$BAK" -C "$WORK"
[ -f "$WORK/db.sql" ] || { echo "✗ db.sql fehlt im Backup — ungültig?"; exit 1; }
[ -f "$WORK/MANIFEST.txt" ] && { echo "--- Manifest ---"; cat "$WORK/MANIFEST.txt"; echo "----------------"; }

# 1. .env
if [ -f .env ] && [ "$FORCE" != "1" ]; then
    echo "⚠ Es existiert bereits eine .env. Mit --force überschreiben, oder manuell abgleichen."
    echo "  (Backup-.env liegt unter: $WORK/env.backup)"
else
    cp "$WORK/env.backup" .env
    echo "→ .env wiederhergestellt"
fi
set -a; . ./.env; set +a
PG_DB="${POSTGRES_DB:-curastro}"
PG_USER="${POSTGRES_USER:-curastro}"

# 2. DB-Container starten und auf 'healthy' warten
echo "→ Datenbank-Container starten …"
docker compose up -d db
echo -n "  warte auf DB "
for _ in $(seq 1 60); do
    if docker compose exec -T db pg_isready -U "$PG_USER" >/dev/null 2>&1; then echo " ok"; break; fi
    echo -n "."; sleep 2
done

# 3. DB einspielen (der Dump hat --clean --if-exists → idempotent)
echo "→ Datenbank einspielen …"
docker compose exec -T db psql -v ON_ERROR_STOP=0 -U "$PG_USER" -d "$PG_DB" < "$WORK/db.sql" >/dev/null
echo "  DB eingespielt"

# 4. outputs-Volume einspielen (falls im Backup)
if [ -f "$WORK/outputs.tar" ]; then
    echo "→ outputs-Volume einspielen …"
    docker volume create deploy_outputs >/dev/null
    docker run --rm -v deploy_outputs:/data -v "$WORK":/bak alpine \
        sh -c "rm -rf /data/* 2>/dev/null; tar xf /bak/outputs.tar -C /data"
    echo "  outputs eingespielt"
fi

# 4b. optionales Archiv einspielen
if [ -f "$WORK/archive.tar" ]; then
    ARCH="${ARCHIVE_PATH:-../archive}"
    echo "→ lokales Archiv einspielen nach $ARCH …"
    mkdir -p "$ARCH"
    tar xf "$WORK/archive.tar" -C "$ARCH"
    echo "  Archiv eingespielt"
fi

# 5. Alle Container starten
echo "→ App starten …"
docker compose up -d
echo "✓ Restore abgeschlossen. Prüfe: docker compose ps  und  die App im Browser."
