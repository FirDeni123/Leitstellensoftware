#!/usr/bin/env bash
# ILS-Sim – Datensicherung (PostgreSQL-Dump, komprimiert, mit Aufbewahrungsfrist)
#
#   ./backup.sh [ZIELVERZEICHNIS] [TAGE_AUFBEWAHREN]
#   cron: 15 2 * * * /opt/ils-sim/deploy/scripts/backup.sh /var/backups/ils-sim 30
#
# Der Dump enthält alle Daten inkl. Änderungsprotokoll. API-Schlüssel liegen darin nur
# verschlüsselt vor – zur Wiederherstellung wird zusätzlich ILS_ENCRYPTION_KEYS aus .env
# benötigt. .env daher getrennt und sicher sichern!
set -euo pipefail
DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:-/var/backups/ils-sim}"
KEEP_DAYS="${2:-30}"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="${TARGET}/ils-${STAMP}.dump"

mkdir -p "$TARGET"
chmod 700 "$TARGET"
cd "$DEPLOY_DIR"

# Custom format: komprimiert, selektiv wiederherstellbar, konsistenter Snapshot.
docker compose exec -T db pg_dump -U ils -d ils --format=custom --compress=9 > "${FILE}.part"
mv "${FILE}.part" "$FILE"
sha256sum "$FILE" > "${FILE}.sha256"

# Plausibilitätsprüfung: Dump muss lesbar sein.
docker compose exec -T db pg_restore --list < "$FILE" > /dev/null

find "$TARGET" -name 'ils-*.dump*' -mtime +"$KEEP_DAYS" -delete
echo "Sicherung erstellt: $FILE ($(du -h "$FILE" | cut -f1))"
