# Entwicklungsumgebung

## Voraussetzungen

- Python 3.12+ und [uv](https://docs.astral.sh/uv/)
- Node.js 22
- PostgreSQL 16 (lokal oder `docker run -p 5432:5432 -e POSTGRES_PASSWORD=ils_dev postgres:16`)
- Redis 7 (optional; ohne Redis arbeitet der Event-Bus im Prozess)

## Server starten

```bash
cd server
uv sync
# Datenbanken anlegen (einmalig):
#   CREATE USER ils WITH PASSWORD 'ils_dev' CREATEDB; CREATE DATABASE ils OWNER ils; CREATE DATABASE ils_test OWNER ils;
uv run alembic upgrade head
uv run ils-admin bootstrap              # Rechte, Rollen, Administrator "admin" (Initialpasswort wird ausgegeben)
uv run ils-admin seed-demo              # Demo-Leitstelle, -Benutzer, -Wachen, -Fahrzeuge (Passwort: Demo-Passwort-2026!)
uv run uvicorn app.main:app --reload    # http://localhost:8000, API-Doku: /docs
```

Demo-Benutzer: `admin.demo`, `lead.demo`, `dispo.demo`, `annahme.demo`,
`beobachter.demo`. Konfiguration erfolgt über Umgebungsvariablen mit Präfix `ILS_` (siehe
`server/app/core/config.py`), z. B. `ILS_REDIS_URL=redis://localhost:6379/0` oder
`ILS_OSRM_URL=http://localhost:5000` (Routing für Fahrzeiten; ohne Angabe werden Fahrzeiten
aus Luftlinie × Umwegfaktor geschätzt). `ILS_SIMULATION_TICK_SECONDS=0` schaltet den
Simulationstakt ab (Tests takten ihn mit einer steuerbaren Uhr selbst).

## Client starten

```bash
cd client
npm install
npm run dev        # Electron mit Hot-Reload
npm run dev:web    # nur Oberfläche im Browser (http://localhost:5173)
```

Die Serveradresse wird in der Anmeldemaske unter „Server“ eingestellt.

## Tests

```bash
cd server && uv run pytest -q                     # 156 Tests, echte PostgreSQL-Testdatenbank ils_test
cd server && uv run ruff check app tests && uv run ruff format --check app tests
cd client && npm run typecheck && npm test        # 56 Unit-Tests (vitest)
cd client && npm run build:web && npm run e2e     # 15 E2E-Tests (Server mit seed-demo, Simulationsbetrieb)
```

Die Tests des KI-Anrufers (`tests/test_training.py`) sprechen **nie** mit der echten
Claude-API: `ai_settings.make_client` wird durch einen Nachbau des SDK ersetzt. Die E2E-Tests
laufen mit dem regelbasierten Anrufer (KI aus).

Server-Tests legen das Schema über die Alembic-Migrationen an. Damit werden die Migrationen
mitgetestet. Die Testdatenbank wird bei jedem Lauf vollständig neu aufgebaut.

## Konventionen

- **Sprache:** Code, Bezeichner und Code-Kommentare auf Englisch; Oberfläche, Fehlermeldungen
  und Dokumentation auf Deutsch.
- **Server:** Router → Service → Modell. Schreibende Operationen nur über `UnitOfWork`
  (Audit + Events). Neue Berechtigungen nur in `core/permissions.py` (werden beim Bootstrap
  synchronisiert). Schemaänderungen nur per Alembic-Migration
  (`uv run alembic revision --autogenerate -m "..."`, danach prüfen!).
- **Neue Stammdaten:** Server: `CrudSpec` in `services/master_data.py` + `register_crud(...)`;
  Client: `EntityConfig` in `modules/masterdata/configs.tsx` – Liste, Formular, Konflikte,
  Protokoll und Echtzeit kommen automatisch.
- **Client:** Neue Fenster in `modules/registry.ts` registrieren und in `PanelHost.tsx`
  verdrahten. Serverdaten über TanStack Query; Echtzeit-Topics in `TOPIC_INVALIDATIONS`
  eintragen. Farben nur über die Design-Tokens in `theme/theme.css`.
- **Commits:** kleine, in sich geschlossene Schritte; Tests vor jedem Commit.
- **Simulation:** jede simulierte Funktion sichtbar kennzeichnen; reale Schnittstellen nur
  über Plugins mit `is_real`.
- **Neue Schnittstelle (Plugin):** Klasse mit `meta = PluginMeta(...)`, `test()` und
  `send_alarm()` (siehe `server/app/plugins/builtin/`), registrieren über den Entry-Point
  `ils_sim.plugins` im eigenen Paket. Simulationsbetrieb, Wiederholversuche, Protokoll und
  Geheimnisse übernimmt der Kern. Reale Plugins in Tests nur gegen `httpx.MockTransport`.

## Windows-Installer

`npm run dist:win` auf Windows (oder per CI-Job `windows-installer`) erzeugt
`client/release/ILS-Sim-Setup-<version>.exe` (NSIS, Installation pro Rechner). Für die
Verteilung ohne SmartScreen-Warnung ist ein Code-Signing-Zertifikat nötig (Phase 8).

## Beispieldaten für den Import

`docs/beispiele/` enthält eine Wachen-CSV und eine Fahrzeug-Excel passend zu den Demo-Daten.
