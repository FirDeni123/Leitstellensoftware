# ILS-Sim – Leitstellen-Simulation

Professionelle, erweiterbare Simulation einer integrierten Leitstelle (Feuerwehr,
Rettungsdienst, Katastrophenschutz, technische Hilfe, Hilfsorganisationen; Polizei nur als
Informationshinweis) mit **Windows-Client** und **zentralem Ubuntu-Server** für mehrere
gleichzeitig arbeitende Disponenten.

> **Simulationssystem.** Alle Alarmierungen, Fahrzeuge und Anrufe sind simuliert. Reale
> Schnittstellen sind standardmäßig deaktiviert und nur im ausdrücklich freigeschalteten
> Echtbetrieb durch berechtigte Administratoren aktivierbar. Keine Anbindung an echte
> Notrufleitungen.

## Stand

**Phase 7 (Ausbildung, KI-Anrufer) ist umgesetzt** (Version 0.7.0): Übungsanrufe mit einem
KI-Anrufer (Claude, vom Administrator einzuschalten) oder einem regelbasierten Anrufer ohne KI,
Szenario-Editor, Ausbildermodus (live mitlesen, verdeckt eingreifen), automatische Auswertung
mit Checkliste und Kennzahlen, Sprachausgabe und optionale Spracherkennung. Der Meilenstein M7
ist mit dem regelbasierten Anrufer nachgewiesen; die Antwortzeit des KI-Anrufers ist noch mit
einem echten API-Schlüssel zu messen. Bereits vorhanden: Fahrzeuge und Karte mit Simulation,
Einsatzmittelvorschlag, Alarmierung mit AAO und Polizei-Hinweis (nur Information),
Schnittstellen-Plugins mit strikter Trennung von Simulation und Echtbetrieb, Notrufannahme,
Einsatzbearbeitung, Grundsystem und Stammdatenverwaltung. Details, Testergebnisse und nächste
Schritte: [docs/STATUS.md](docs/STATUS.md).

## Aufbau

```text
leitstelle/
├── server/          Python/FastAPI – API, Echtzeit, (später) Simulation
│   ├── app/         core · db · models · schemas · services · api · realtime · plugins
│   ├── alembic/     Datenbankmigrationen
│   └── tests/       pytest (gegen echte PostgreSQL)
├── client/          Electron + React + TypeScript – Windows-Client
│   ├── src/main     Electron-Hauptprozess (gehärtet)
│   ├── src/preload  minimale Brücke
│   ├── src/renderer Oberfläche (Arbeitsplätze, Module, Echtzeit)
│   ├── tests/       vitest
│   └── e2e/         Playwright
├── deploy/          Docker Compose, Caddy (TLS), Installations-/Backup-Skripte
├── docs/            Architektur, Datenbank, API, Roadmap, Sicherheit, Simulation, Risiken
└── .github/         CI (Tests, Windows-Installer)
```

## Schnellstart (Entwicklung)

Ausführlich in [docs/entwicklung.md](docs/entwicklung.md).

```bash
cd server && uv sync && uv run alembic upgrade head && uv run ils-admin bootstrap && uv run ils-admin seed-demo
uv run uvicorn app.main:app --reload
cd ../client && npm install && npm run dev
```

Anmeldung z. B. mit `dispo.demo` / `Demo-Passwort-2026!`.

## Dokumentation

| Dokument | Inhalt |
|---|---|
| [01-architektur.md](docs/01-architektur.md) | Systemarchitektur, Komponenten, Echtzeit, Technologieentscheidungen mit Begründung |
| [02-datenbank.md](docs/02-datenbank.md) | Tabellen (umgesetzt und geplant), Beziehungen |
| [03-api-und-module.md](docs/03-api-und-module.md) | REST- und WebSocket-API, Modulschnittstellen, Plugin-System |
| [04-roadmap.md](docs/04-roadmap.md) | Phasen 1–8 mit Meilensteinen und Abnahmekriterien |
| [05-sicherheit.md](docs/05-sicherheit.md) | Sicherheitskonzept, Trennung Simulation/Echtbetrieb |
| [06-simulation-und-kernfunktionen.md](docs/06-simulation-und-kernfunktionen.md) | GPS-Simulation und Routing, Einsatzmittelvorschlag, KI-Anrufsimulation, Telefonie |
| [07-risiken.md](docs/07-risiken.md) | Risiken und Abhängigkeiten |
| [betrieb/ubuntu-server.md](docs/betrieb/ubuntu-server.md) | Installation, TLS, Backup/Restore |
| [STATUS.md](docs/STATUS.md) | Aktueller Stand, offene Punkte, nächster Schritt |
