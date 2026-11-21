# Projektstatus

**Stand:** 21.11.2026 · **Version:** 0.1.0 · **Aktuelle Phase:** 1 abgeschlossen, nächste: Phase 2

## Phase 1 – umgesetzt und getestet

| Bereich | Inhalt | Nachweis |
|---|---|---|
| Server-Grundgerüst | FastAPI, Konfiguration (Produktionsprüfung), JSON-Logging mit Request-ID, einheitliches Fehlerformat | Tests, Smoke-Test |
| Datenbank | 14 Tabellen, Alembic-Migration `0001` (up/down getestet), Optimistic Locking, unveränderbares Änderungsprotokoll (Trigger) | `test_audit_log_is_immutable_in_database`, Backup/Restore-Probe |
| Anmeldung | Argon2id, Passwortrichtlinie, Kontosperre, JWT + rotierende Refresh-Tokens mit Wiederverwendungserkennung, erzwungene Passwortänderung, sofortiger Token-Entzug | `tests/test_auth.py` (9 Tests) |
| Rechte | 29 Berechtigungen, 5 Systemrollen, eigene Rollen, grant/deny je Benutzer, Mandanten (Leitstellen), Schutz des letzten Administrators | `tests/test_users_roles.py` (13 Tests) |
| Leitstellen | Anlegen, Bearbeiten, Löschen, Sichtbarkeit je Benutzer | `tests/test_control_centers_system.py` |
| System | Betriebsmodus Simulation/Echtbetrieb (Standard Simulation), Modulstatus, Layouts je Benutzer/Arbeitsplatz | dito |
| Echtzeit | WebSocket mit Auth, Kanal-/Rechtefilter, Gegendruck, Trennung bei Rechte-/Sitzungsänderung, Redis-Bus für mehrere Instanzen | `tests/test_realtime.py` (6), `tests/test_redis_bus.py` |
| Windows-Client | Electron (gehärtet, `app://`-Schema), Anmeldung inkl. Passwortänderung, Arbeitsplätze F2–F6, andockbare Fenster mit Server-Layout, Statusleiste (Verbindung, Latenz), Serverzeit-Uhr, Systemmeldungen, Ereignisprotokoll (live), Modulstatus, Benutzerverwaltung, Leitstellenverwaltung, gekennzeichnete Platzhalter künftiger Module | 21 Unit-Tests, 3 E2E-Tests (inkl. Live-Synchronisation zweier Sitzungen), Electron-Start unter Xvfb geprüft |
| Betrieb | Dockerfile, Docker Compose (PostgreSQL, Redis, API, Caddy/TLS), Installationsskript, Backup/Restore-Skripte, CI-Workflow inkl. Windows-Installer-Job | Skript-Syntax geprüft, Backup/Restore-Kern gegen PostgreSQL getestet |

**Testergebnis zuletzt:** Server 51/51 ✅ · Client-Unit 21/21 ✅ · E2E 3/3 ✅ · Ruff ✅ · TypeScript ✅

## In dieser Umgebung nicht verifizierbar

- **Docker-Compose-Stack und Installationsskript:** In der Entwicklungsumgebung läuft kein
  Docker-Daemon. Die Einzelteile (Migrationen, Server, Backup/Restore-Befehle) sind getestet,
  der Gesamtstack noch nicht. → Erster Test auf dem Ubuntu-Server.
- **Windows-Installer (NSIS):** wird vom CI-Job `windows-installer` auf `windows-latest`
  gebaut. Lokal (Linux) wurde nur der Electron-Build erstellt und gestartet.
- **Fensterleiste unter Windows** (`titleBarOverlay` mit nativen Fensterknöpfen): unter Linux
  nicht sichtbar, auf Windows prüfen.

## Bekannte offene Punkte (bewusst verschoben)

| Punkt | Geplant in |
|---|---|
| IP-basierte Ratenbegrenzung für die Anmeldung (Kontosperre existiert) | Phase 8 |
| Zertifikats-Pinning im Client, Code-Signing, Auto-Update | Phase 8 |
| Mehrfenster über mehrere Monitore (Pop-out-Fenster von dockview) | Phase 3 |
| Rollen-Editor und Anmeldeprotokoll im Client (API vorhanden) | Phase 2 |
| Leitstellen-Verknüpfungen und Zuständigkeitsbereiche | Phase 2 |
| Auswahl der aktiven Leitstelle bei mehreren Zuordnungen (Kopfzeile zeigt die erste) | Phase 3 |

## Nächster konkreter Schritt (Phase 2)

1. Migration `0002`: `organizations`, `stations`, `vehicle_types`, `vehicles`, `rics`,
   `ric_assignments`, `alarm_groups`, `radio_groups` (+ Zuordnungen), `import_jobs`
   (Schema siehe [02-datenbank.md](02-datenbank.md)).
2. Services und Router analog zu `control_center_service.py`, mit Mandantenfilter und Audit.
3. Excel/CSV-Import: Upload → Spaltenerkennung (openpyxl/csv) → Zuordnungsvorschlag →
   Validierung mit zeilengenauen Fehlern → Vorschau → Bestätigung in einer Transaktion.
4. Client-Panels: Wachen, Fahrzeuge, RICs, Funkrufgruppen, Import-Assistent; Rollen-Editor,
   Anmeldeprotokoll.
5. Seed-Daten: Beispielwachen und -fahrzeuge der Demo-Region (fiktiv).

## Annahmen und Entscheidungen

- Beispielregion für Demo-Daten: Raum Schwarzenbek (Schleswig-Holstein); alle Namen und
  Daten sind fiktiv und leicht austauschbar (`server/app/cli.py`).
- Tokens werden im Client nur im Arbeitsspeicher gehalten (kein „angemeldet bleiben“).
  Grund: gemeinsam genutzte Leitstellenrechner.
- Keine Offline-Schreibwarteschlange (siehe Architektur, Abschnitt 6).
- In der Entwicklungsumgebung war ein Zugang zu einer externen Alarmierungs-API
  hinterlegt. Er wurde **bewusst nicht angesprochen**, weil es sich um eine reale
  Alarmierungsschnittstelle handelt. Anbindung frühestens in Phase 4 als Plugin,
  standardmäßig deaktiviert und nur im Echtbetrieb aktivierbar.
