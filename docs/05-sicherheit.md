# 05 – Sicherheitskonzept

## 1. Schutzziele

ILS-Sim ist zunächst ein Simulations- und Trainingssystem. Es soll aber von Beginn an so
gebaut sein, dass ein späterer Echtbetrieb keine Sicherheitsarchitektur-Änderung erfordert.
Wichtigstes Schutzziel ist: **Keine ungewollte reale Wirkung.** Keine Alarmierung, kein
Anruf, keine Nachricht verlässt das System ohne ausdrückliche, berechtigte und protokollierte
Freigabe.

## 2. Trennung Simulation / Echtbetrieb

| Ebene | Maßnahme | Stand |
|---|---|---|
| System | Betriebsmodus `simulation`/`real` in `system_settings`. Standard und Neuinstallation: **simulation**. Wechsel nur mit `system.mode.change` (nur Administratorrolle), Begründung und Bestätigungswort „ECHTBETRIEB“. Wird protokolliert und an alle Clients gemeldet | ✅ |
| Oberfläche | Dauerhaftes Banner „SIMULATIONSBETRIEB“ (gelb schraffiert) bzw. „ECHTBETRIEB“ (rot) auf jedem Arbeitsplatz und auf der Anmeldemaske | ✅ |
| Schnittstelle | Jede Schnittstelle trägt `is_real` und ist bei Anlage **deaktiviert**. Aktivierung realer Schnittstellen nur mit `interfaces.activate_real` und im Echtbetrieb | Phase 4 |
| Kern | Im Simulationsmodus leitet der Kern Aufrufe realer Plugins auf das Simulations-Gateway um, unabhängig vom Plugin-Code | Phase 4 |
| KI-Training | Der KI-Anrufer ist fest an den Provider `SimulatedTelephony` gebunden. Der Trainingspfad hat keine Code-Verbindung zum SIP-Provider. Ein Test stellt das sicher (Import-Grenze) | Phase 7 |
| Polizei | Polizei ist eine Organisation mit `alarmable = false`, abgesichert durch einen Datenbank-Check-Constraint (✅). Polizeifahrzeuge können nicht angelegt oder importiert werden (✅). Es gibt keinen Alarmierungspfad, nur ein bestätigungspflichtiges Hinweisfenster (Phase 4) | ✅ / Phase 4 |
| Daten | Spalten `mode`/`source` kennzeichnen simulierte Datensätze | ab Phase 3 |

## 3. Authentifizierung und Sitzungen (umgesetzt)

- **Passwörter:** Argon2id (argon2-cffi). Automatisches Rehashing bei geänderten Parametern.
  Bei unbekannten Benutzern läuft ein Ausgleichs-Hash, damit sich über die Antwortzeit nicht
  erkennen lässt, ob ein Benutzername existiert.
- **Richtlinie:** mindestens 10 Zeichen, drei Zeichenarten, darf den Benutzernamen nicht
  enthalten. Initial- und Reset-Passwörter werden generiert und **nur einmal** angezeigt.
  Die Änderung bei der ersten Anmeldung ist erzwungen.
- **Sperre:** nach 5 Fehlversuchen 15 Minuten (konfigurierbar). Aufhebung durch die
  Administration möglich. Alle Versuche stehen im Anmeldeprotokoll.
- **Tokens:**
  - Access-Token (JWT HS256, 15 min) enthält Benutzer, Sitzung und `token_version`.
  - Refresh-Token: zufällig (256 Bit), einmalig verwendbar, in der Datenbank nur als
    SHA-256-Hash. Bei jeder Erneuerung wird rotiert. **Wiederverwendung** eines
    verbrauchten Tokens (Diebstahl/Replay) sperrt die ganze Sitzung und trennt die
    Echtzeitverbindung.
- **Sofortiger Entzug:** Deaktivierung, Passwortänderung und Passwort-Reset erhöhen
  `token_version`. Alle ausgegebenen Tokens werden damit sofort ungültig, und offene
  WebSockets werden getrennt.
- **Client:** Tokens nur im Arbeitsspeicher, nie auf der Festplatte. Auf
  Leitstellenrechnern mit Schichtwechsel bleibt so keine Anmeldung zurück.

## 4. Autorisierung (umgesetzt)

- Rollenbasiert mit 29 feingranularen Berechtigungen (`server/app/core/permissions.py`).
  Rollen sind frei editierbar. Individuelle **grant/deny**-Ausnahmen je Benutzer sind
  möglich; deny hat Vorrang.
- Die Rechte werden bei **jeder** Anfrage aus der Datenbank ermittelt, nicht aus dem Token.
  Rechteänderungen wirken also sofort.
- **Mandanten:** Benutzer sehen nur ihre Leitstellen (`user_control_centers`). Nur
  `system.admin` sieht alle.
- **Schutzregeln:** Der letzte aktive Administrator kann nicht entfernt werden. Das eigene
  Konto kann nicht deaktiviert werden. Der Administratorrolle kann `system.admin` nicht
  entzogen werden.

## 5. Nachvollziehbarkeit (umgesetzt)

- Jede schreibende Aktion erzeugt in derselben Transaktion einen Eintrag im
  Änderungsprotokoll: wer, wann, was, Feldänderungen alt→neu und Anfrage-ID.
- Das Protokoll ist durch einen **Datenbank-Trigger unveränderbar** (kein UPDATE/DELETE,
  auch nicht per SQL). Getestet in `test_audit_log_is_immutable_in_database` und nach
  Backup/Restore.
- Strukturierte JSON-Logs mit Anfrage-ID. Passwörter, Tokens und Schlüssel werden nie
  geloggt.

## 5a. Datenimport (umgesetzt)

- Nur `.xlsx`/`.csv`, max. 5 MB und 5000 Zeilen, max. 60 Spalten. Beschädigte Dateien führen
  zu einer verständlichen Fehlermeldung, nicht zu einem Serverfehler.
- Excel wird schreibgeschützt und ohne Makros/Formeln gelesen (`read_only`, `data_only`).
- Nichts wird vor der ausdrücklichen Bestätigung geschrieben. Die Übernahme erfolgt in einer
  Transaktion (ganz oder gar nicht) mit Protokolleintrag je Datensatz. Die Rohdaten der Datei
  werden nach Übernahme oder Verwerfen gelöscht (Datenminimierung).
- Import erfordert `data.import` **und** das Schreibrecht für die Zielart.

## 6. Geheimnisse

- **API-Schlüssel** externer Schnittstellen werden mit Fernet (AES-128-CBC + HMAC-SHA256)
  verschlüsselt (`core/crypto.py`). Die Schlüssel liegen **außerhalb** der Datenbank
  (`ILS_ENCRYPTION_KEYS` in `.env`, Rechte 600). Schlüsselrotation ist möglich (mehrere
  Schlüssel, der erste verschlüsselt). Die API liefert nur maskierte Werte.
- Der Server verweigert den Start in der Produktion mit Entwicklungs-Standardgeheimnissen
  (JWT-Secret, Schlüssel, DB-Passwort).
- Im Quellcode stehen keine Geheimnisse. `.env` ist in `.gitignore` eingetragen.

## 7. Transport und Netzwerk

- TLS über Caddy, wahlweise mit eigener CA (`tls internal`) für interne Netze oder Let's
  Encrypt. HSTS ist gesetzt.
- Datenbank und Redis sind nur im internen Docker-Netz erreichbar. Nach außen ist nur
  Port 443 offen.
- CORS ist auf die Client-Herkunft `app://ils` beschränkt.
- Der Client warnt bei unverschlüsseltem `http://` zu entfernten Servern.
- Geplant (Phase 8): Zertifikats-Pinning im Client; IP-basierte Ratenbegrenzung für
  `/auth/login` (die kontobasierte Sperre existiert bereits).

## 8. Härtung des Windows-Clients (umgesetzt)

- `contextIsolation`, `sandbox`, kein `nodeIntegration`. Der Renderer hat nachweislich
  keinen Node-Zugriff (geprüft im Electron-Test).
- Minimale Preload-Brücke (Konfiguration lesen/schreiben mit Validierung, App-Info).
- Strikte Content-Security-Policy (keine fremden Skripte, kein `eval`).
- Navigation und neue Fenster blockiert. Externe https-Links öffnen im Systembrowser.
- Berechtigungsanfragen (Kamera, Mikrofon, Standort …) werden standardmäßig abgelehnt. Das
  Mikrofon wird in Phase 7 gezielt freigegeben.
- Renderer über ein eigenes Schema `app://ils` statt `file://`.
- Single-Instance-Sperre.
- Geplant (Phase 8): Code-Signing des Installers, signierte Auto-Updates.

## 9. Datenschutz

- Gesprächsaufzeichnungen sind standardmäßig **aus**. Wenn aktiviert, gelten eine
  Aufbewahrungsfrist und eine automatische Löschung.
- Trainingsdaten enthalten fiktive Personen. Echte Personendaten fallen erst im
  Echtbetrieb an. Dafür sind ein Lösch- und Aufbewahrungskonzept und ein
  Verarbeitungsverzeichnis vorzusehen (Phase 8).
- KI-Dienste: Es werden nur Trainingsinhalte übertragen. Für Cloud-KI ist der Anbieter in
  der Schnittstellenverwaltung zu konfigurieren; lokale Alternativen (STT/TTS) sind Standard.

## 10. Datensicherung

`deploy/scripts/backup.sh` erstellt einen PostgreSQL-Dump (Custom-Format, Prüfsumme,
Lesbarkeitstest, Aufbewahrungsfrist). `restore.sh` stellt in eine neue Datenbank wieder her
und tauscht erst nach Erfolg; der alte Stand bleibt als `ils_before_restore` erhalten. Die
`.env` (Schlüssel!) ist separat zu sichern. Details:
[betrieb/ubuntu-server.md](betrieb/ubuntu-server.md).
