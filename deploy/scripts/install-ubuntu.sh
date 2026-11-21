#!/usr/bin/env bash
# ILS-Sim – Erstinstallation auf Ubuntu Server 22.04/24.04
#
#   sudo ./install-ubuntu.sh leitstelle-server.local
#
# 1. installiert Docker Engine + Compose-Plugin (falls nicht vorhanden)
# 2. erzeugt deploy/.env mit zufälligen Geheimnissen (nur wenn noch nicht vorhanden)
# 3. baut und startet alle Dienste
# 4. legt Berechtigungskatalog, Standardrollen und den ersten Administrator an
set -euo pipefail

SERVER_NAME="${1:-$(hostname -f)}"
DEPLOY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DEPLOY_DIR"

if [[ $EUID -ne 0 ]]; then echo "Bitte mit sudo ausführen." >&2; exit 1; fi

if ! command -v docker >/dev/null 2>&1; then
  echo ">> Installiere Docker Engine"
  apt-get update -qq
  apt-get install -y -qq ca-certificates curl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

if [[ ! -f .env ]]; then
  echo ">> Erzeuge .env mit neuen Geheimnissen"
  rand() { head -c "$1" /dev/urandom | base64 | tr -d '/+=\n' | head -c "$1"; }
  fernet=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_')
  umask 077
  cat > .env <<ENV
ILS_SERVER_NAME=${SERVER_NAME}
ILS_HTTPS_PORT=443
POSTGRES_PASSWORD=$(rand 32)
ILS_JWT_SECRET=$(rand 64)
ILS_ENCRYPTION_KEYS=${fernet}
ILS_WORKERS=2
ENV
  echo "   WICHTIG: .env sicher aufbewahren (ohne ILS_ENCRYPTION_KEYS sind gespeicherte API-Schlüssel nicht wiederherstellbar)."
fi

echo ">> Baue und starte Dienste"
docker compose up -d --build

echo ">> Warte auf API"
for _ in $(seq 1 60); do
  if docker compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')" 2>/dev/null; then break; fi
  sleep 2
done

echo ">> Bootstrap (Berechtigungen, Rollen, erster Administrator)"
docker compose exec -T api ils-admin bootstrap

cat <<INFO

Installation abgeschlossen.
  API:            https://${SERVER_NAME}/
  CA-Zertifikat:  docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./ils-root-ca.crt
                  -> auf allen Windows-Clients unter "Vertrauenswürdige Stammzertifizierungsstellen" importieren
  Backup:         ${DEPLOY_DIR}/scripts/backup.sh (z. B. täglich per cron)
INFO
