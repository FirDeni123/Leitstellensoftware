# Änderungsprotokoll

## 0.1.0 – 21.11.2026 – Phase 1: Grundsystem

### Hinzugefügt
- Server: FastAPI-API mit PostgreSQL (SQLAlchemy 2, Alembic), Argon2id-Passwörtern,
  JWT + rotierenden Refresh-Tokens (Wiederverwendungserkennung), Kontosperre,
  erzwungener Passwortänderung, Rollen/Berechtigungen mit individuellen Ausnahmen,
  Leitstellen als Mandanten, Optimistic Locking, unveränderbarem Änderungsprotokoll,
  Betriebsmodus Simulation/Echtbetrieb, Modulstatus, Layout-Speicherung.
- Echtzeit: WebSocket mit Kanal- und Rechtefilter, Gegendruck, aktiver Trennung bei
  Rechte-/Sitzungsänderungen; Event-Bus In-Memory oder Redis (mehrere Instanzen).
- Windows-Client: Electron + React mit dunklem Leitstellen-Design, Arbeitsplätzen F2–F6,
  andockbaren Fenstern, Benutzer- und Leitstellenverwaltung, Ereignisprotokoll,
  Systemmeldungen, Modulstatus; gehärteter Hauptprozess (Sandbox, CSP, app://-Schema).
- Betrieb: Docker Compose (PostgreSQL, Redis, API, Caddy/TLS), Installations-, Backup- und
  Restore-Skripte, CI mit Windows-Installer-Build.
- Dokumentation: Architektur, Datenbank, API, Roadmap, Sicherheit, Simulation, Risiken.
