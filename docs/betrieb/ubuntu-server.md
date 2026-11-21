# Betrieb: Ubuntu-Server

## Systemanforderungen (Phase 1–7)

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

## Routing (OSRM) und Kartenkacheln

Ohne Routing-Dienst schätzt das System Fahrzeiten (Luftlinie × Umwegfaktor) und simulierte
Fahrzeuge fahren gekennzeichnet auf der Luftlinie. Für straßengenaue Fahrten:

```bash
deploy/scripts/prepare-osrm.sh                      # Schleswig-Holstein, ca. 10–20 min, ~2 GB Platz
echo "ILS_OSRM_URL=http://osrm:5000" >> deploy/.env
docker compose -f deploy/docker-compose.yml --profile routing up -d
```

Ein anderes Gebiet: `deploy/scripts/prepare-osrm.sh europe/germany/hamburg`. Kartendaten
monatlich aktualisieren: Skript erneut ausführen, dann `docker compose restart osrm`.

**Kartenkacheln:** Standard sind die OpenStreetMap-Server – laut deren Nutzungsrichtlinie nur
für geringe Last. Für den Betrieb eigene Kacheln oder einen Anbieter in `ILS_MAP_TILE_URL`
(mit `{z}/{x}/{y}`) und `ILS_MAP_TILE_ATTRIBUTION` eintragen. Die Quellenangabe wird in der
Karte immer angezeigt.

> Hinweis: Compose-Dienst und Skript sind in der Entwicklungsumgebung nicht ausgeführt
> worden (kein Docker). Die OSRM-Anbindung des Servers ist gegen einen simulierten Endpunkt
> getestet.

## KI-Anrufer und Spracherkennung (Ausbildung)

Der KI-Anrufer ist ausgeschaltet, bis ein Administrator ihn im Fenster „KI-Einstellungen“
einschaltet. Voraussetzungen:

- ausgehende HTTPS-Verbindung des Servers zu `api.anthropic.com`;
- ein API-Schlüssel – entweder im Fenster „KI-Einstellungen“ (verschlüsselt gespeichert) oder
  in der `.env` als `ILS_ANTHROPIC_API_KEY=…` (dann `docker compose up -d`). Optional
  `ILS_ANTHROPIC_BASE_URL` (Standard `https://api.anthropic.com`) und
  `ILS_ANTHROPIC_TIMEOUT_SECONDS` (Standard 30).

Ohne KI läuft der regelbasierte Anrufer; Übungen funktionieren damit vollständig offline.

Spracherkennung für die Sprechtaste ist optional und groß (Modell 0,5–3 GB, CPU-intensiv):
Image mit `docker compose build --build-arg ILS_EXTRAS="--extra speech" api` bauen; Modell
und Gerät über `ILS_STT_MODEL` (Standard `small`) und `ILS_STT_DEVICE` (`cpu`/`cuda`). Das
Modell wird beim ersten Gebrauch heruntergeladen (Internetzugang nötig). Ohne das Paket bleibt
die Sprechtaste ausgegraut; Tippen geht immer.

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
