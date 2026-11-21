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
| Schnittstelle | Jedes Plugin trägt `is_real`; Schnittstellen sind bei Anlage **deaktiviert**. Aktivieren/Testen realer Schnittstellen nur mit `interfaces.activate_real`, im Echtbetrieb und mit Begründung; Wechsel in den Simulationsbetrieb deaktiviert sie automatisch | ✅ |
| Kern | Vor jedem Plugin-Aufruf prüft der Kern den Betriebsmodus; im Simulationsbetrieb wird ein reales Plugin nie aufgerufen (Umleitung + Protokoll), auch wenn es fälschlich aktiv ist | ✅ (Test) |
| KI-Training | Der KI-Anrufer ist fest an den Provider `SimulatedTelephony` gebunden. Der Trainingspfad hat keine Code-Verbindung zum SIP-Provider. Ein Test stellt das sicher (Import-Grenze) | Phase 7 |
| Polizei | Polizei ist eine Organisation mit `alarmable = false`, abgesichert durch einen Datenbank-Check-Constraint (✅). Polizeifahrzeuge können nicht angelegt oder importiert werden (✅). Polizei-Fahrzeuge und -Wachen werden zusätzlich bei AAO, Vorschau und Alarmierung abgewiesen. Es gibt keinen Alarmierungspfad, nur ein bestätigungspflichtiges Hinweisfenster, dessen Bestätigung im Einsatzverlauf steht | ✅ |
| Daten | Spalten `source` kennzeichnen simulierte Notrufe und Einsätze („SIM“ in der Oberfläche) | ✅ |
| Simulierte Anrufe | Erzeugung nur mit `simulation.control` und nur im Simulationsbetrieb (im Echtbetrieb 409) | ✅ |

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
- Berechtigungsanfragen (Kamera, Standort …) werden abgelehnt. Einzige Ausnahme: Mikrofon
  (nur Audio) für die eigene Oberfläche – für die Sprechtaste in Übungen; aufgenommen wird nur,
  solange die Taste gedrückt ist.
- Renderer über ein eigenes Schema `app://ils` statt `file://`.
- Single-Instance-Sperre.
- Geplant (Phase 8): Code-Signing des Installers, signierte Auto-Updates.

## 9. Datenschutz

- Gesprächsaufzeichnungen sind standardmäßig **aus**. Wenn aktiviert, gelten eine
  Aufbewahrungsfrist und eine automatische Löschung.
- Trainingsdaten enthalten fiktive Personen. Echte Personendaten fallen erst im
  Echtbetrieb an. Dafür sind ein Lösch- und Aufbewahrungskonzept und ein
  Verarbeitungsverzeichnis vorzusehen (Phase 8).
- KI-Dienste: Es werden nur Trainingsinhalte übertragen (Szenario und Gesprächsverlauf), und
  nur wenn ein Administrator den KI-Anrufer einschaltet. Szenarien sind mit fiktiven Daten zu
  füllen (Hinweis im Editor und in den KI-Einstellungen). Spracherkennung läuft lokal auf dem
  Server, Sprachausgabe lokal im Client.

## 10. Datensicherung

`deploy/scripts/backup.sh` erstellt einen PostgreSQL-Dump (Custom-Format, Prüfsumme,
Lesbarkeitstest, Aufbewahrungsfrist). `restore.sh` stellt in eine neue Datenbank wieder her
und tauscht erst nach Erfolg; der alte Stand bleibt als `ils_before_restore` erhalten. Die
`.env` (Schlüssel!) ist separat zu sichern. Details:
[betrieb/ubuntu-server.md](betrieb/ubuntu-server.md).

## Alarmierung (Phase 4)

- **Keine selbstständige Alarmierung:** Der Server alarmiert ausschließlich auf eine
  ausdrückliche Anfrage mit `confirmed: true`; die Vorschau ist schreibfrei.
- **Doppelalarmierung verhindert:** `Idempotency-Key` je bestätigtem Dialog, eindeutig je
  Einsatz in der Datenbank, zusammen mit einer Sperre des Einsatzes (vier parallele
  Anfragen → genau eine Alarmierung, getestet).
- **Geheimnisse:** API-Schlüssel nur verschlüsselt (Fernet) in `interfaces.secret_encrypted`;
  nie in API-Antworten, Audit-Einträgen, Events oder Logs (getestet).
- **Webhook-Ziele** müssen `https://` sein. Ziel-URLs legen nur berechtigte Administratoren
  fest; eine Allowlist für Zielhosts ist für Phase 8 vorgesehen.
- **Abhängigkeit:** `jsonschema` (Prüfung der Plugin-Konfiguration).

## Fahrzeuge, Karte und Simulation (Phase 6)

- **Keine Simulation im Echtbetrieb:** Der Simulationsdienst taktet nur im
  Simulationsbetrieb; beim Wechsel in den Echtbetrieb werden alle simulierten Fahrten
  beendet. Simulationssteuerung (Uhr, Verschieben, Ausfall, simulierte Statusmeldungen) nur
  mit `simulation.control` und nur im Simulationsbetrieb.
- **Nachvollziehbarkeit:** Jede Statusänderung steht unveränderbar in der Statushistorie
  (Quelle Disponent/Simulation, Person, Zeit) und im Änderungsprotokoll.
- **CSP:** ergänzt um `worker-src 'self' blob:` und `img-src … blob:` für den Karten-Worker
  (gebündelte Datei, kein Fremdskript) und dekodierte Kacheln. Kacheln werden per `fetch`
  geladen (`connect-src`); die Kachelquelle legt der Server fest.


## Ausbildung und KI-Anrufer (Phase 7)

- **Keine echten Leitungen:** Ein Übungsanruf ist ein Datensatz (`source = training`); der
  Trainingsbereich hat keinerlei Telefonie-Anbindung (`IS_REAL = False`). Übungen starten nur im
  Simulationsbetrieb; der Wechsel in den Echtbetrieb bricht laufende Übungen ab.
- **KI ohne Handlungsmacht:** Claude erhält keine Werkzeuge. Die Antwort ist nur Text im
  Übungsgespräch. Einsatzanlage, Stichwort und Alarmierung bleiben Handlungen des Disponenten.
- **Standardmäßig aus:** Der KI-Anrufer ist nach der Installation ausgeschaltet; nur
  Administratoren (`system.admin`) können ihn einschalten und den Schlüssel setzen.
- **API-Schlüssel:** verschlüsselt mit SecretBox in `system_settings`, nie im Quellcode, nie
  in Antworten, Protokollen oder Ereignissen (Test prüft Datenbank und Änderungsprotokoll).
  Alternativ `ILS_ANTHROPIC_API_KEY` in der `.env` des Servers. Die Zieladresse
  (`ILS_ANTHROPIC_BASE_URL`) wird ausdrücklich gesetzt und nicht aus Umgebungsvariablen des
  Prozesses übernommen.
- **Sichtbarkeit:** Echtzeit-Ereignisse einer Übung gehen nur an die übende Person und an
  Ausbilder der Leitstelle; verdeckte Regie und die Szenario-Lösung sieht die übende Person
  während der Übung nicht.
- **Nachvollziehbarkeit:** Start, Regie-Eingriffe, Auswertung und Änderungen an Szenarien
  und KI-Einstellungen stehen im Änderungsprotokoll.
