#!/usr/bin/env bash
# ILS-Sim – Wiederherstellung einer Sicherung
#
#   ./restore.sh /var/backups/ils-sim/ils-20261121-021500.dump
#
# ACHTUNG: ersetzt den kompletten Datenbestand. Die API wird währenddessen gestoppt.
set -euo pipefail
DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${1:?Pfad zur .dump-Datei angeben}"
cd "$DEPLOY_DIR"

if [[ -f "${FILE}.sha256" ]]; then sha256sum -c "${FILE}.sha256"; fi
read -r -p "Datenbestand wirklich durch ${FILE} ersetzen? Tippe WIEDERHERSTELLEN: " answer
[[ "$answer" == "WIEDERHERSTELLEN" ]] || { echo "Abgebrochen."; exit 1; }

docker compose stop api
docker compose exec -T db psql -U ils -d postgres -c "DROP DATABASE IF EXISTS ils_restore;" -c "CREATE DATABASE ils_restore OWNER ils;"
docker compose exec -T db pg_restore -U ils -d ils_restore --no-owner --exit-on-error < "$FILE"
# Erst nach erfolgreichem Restore austauschen (alte DB bleibt als ils_before_restore erhalten).
docker compose exec -T db psql -U ils -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='ils';" \
  -c "DROP DATABASE IF EXISTS ils_before_restore;" \
  -c "ALTER DATABASE ils RENAME TO ils_before_restore;" \
  -c "ALTER DATABASE ils_restore RENAME TO ils;"
docker compose start api
echo "Wiederherstellung abgeschlossen. Vorheriger Stand: Datenbank ils_before_restore."
