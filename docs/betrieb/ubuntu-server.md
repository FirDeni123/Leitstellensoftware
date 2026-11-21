# Betrieb: Ubuntu-Server

## Systemanforderungen (Phase 1–5)

- Ubuntu Server 22.04 oder 24.04 LTS, 2 vCPU, 4 GB RAM, 40 GB SSD
- Ab Phase 6 (OSRM, ein Bundesland): +4 GB RAM. Ab Phase 7 (lokale Sprachmodelle): 8+ GB
  RAM, GPU optional
- Netzwerk: Port 443/TCP von den Arbeitsplätzen erreichbar

## Installation

```bash
sudo git clone <repository> /opt/ils-sim
cd /opt/ils-sim/deploy
sudo ./scripts/install-ubuntu.sh leitstelle-server.local
```

Das Skript installiert Docker, erzeugt `deploy/.env` mit zufälligen Geheimnissen (Rechte 600),
startet PostgreSQL, Redis, die API und Caddy und legt den ersten Administrator an. **Das
ausgegebene Initialpasswort notieren**; es muss bei der ersten Anmeldung geändert werden.

## TLS-Zertifikat für die Clients

Bei `tls internal` (Standard) erzeugt Caddy eine eigene Zertifizierungsstelle:

```bash
cd /opt/ils-sim/deploy
docker compose cp proxy:/data/caddy/pki/authorities/local/root.crt ./ils-root-ca.crt
```

`ils-root-ca.crt` auf allen Windows-Arbeitsplätzen in „Vertrauenswürdige
Stammzertifizierungsstellen“ importieren, bevorzugt per Gruppenrichtlinie, sonst per
`certutil -addstore -f Root ils-root-ca.crt`. Hat der Server einen öffentlichen DNS-Namen,
`tls internal` im `caddy/Caddyfile` entfernen. Caddy holt dann ein Let's-Encrypt-Zertifikat.

Im Client unter „Server“ die Adresse `https://leitstelle-server.local` eintragen und
„Verbindung testen“ klicken.

## Betrieb

```bash
docker compose ps                     # Status
docker compose logs -f api            # Logs (JSON, mit request_id)
docker compose exec api ils-admin create-user m.muster "Max Muster" --role dispatcher
```

**Update:** `git pull && docker compose up -d --build`. Migrationen laufen beim Start der API
automatisch (`alembic upgrade head`). Vorher eine Sicherung erstellen.

## Datensicherung und Wiederherstellung

```bash
# Sicherung (täglich per cron empfohlen)
sudo crontab -e
15 2 * * * /opt/ils-sim/deploy/scripts/backup.sh /var/backups/ils-sim 30

# Wiederherstellung (API wird kurz gestoppt; alter Stand bleibt als ils_before_restore)
sudo /opt/ils-sim/deploy/scripts/restore.sh /var/backups/ils-sim/ils-20261121-021500.dump
```

- Sicherungen außerhalb des Servers ablegen (Netzlaufwerk, zweiter Standort).
- **`deploy/.env` separat und sicher sichern.** Ohne `ILS_ENCRYPTION_KEYS` lassen sich
  gespeicherte API-Schlüssel nicht entschlüsseln; ohne `ILS_JWT_SECRET` werden nur alle
  Anmeldungen ungültig.
- Restore regelmäßig testen (Phase 8: dokumentierter Restore-Test, Ziel unter 15 min).

## Schlüsselrotation

```bash
docker compose exec api ils-admin generate-key
# neuen Schlüssel VORNE in ILS_ENCRYPTION_KEYS einfügen (kommagetrennt), alten behalten
docker compose up -d api
```

Neue Geheimnisse werden mit dem neuen Schlüssel verschlüsselt, alte bleiben lesbar.
