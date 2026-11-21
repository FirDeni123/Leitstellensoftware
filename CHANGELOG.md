# Änderungsprotokoll

## 0.2.0 – 21.11.2026 – Phase 2: Administration

### Hinzugefügt
- Stammdaten: Organisationen (Polizei technisch nie alarmierbar), Fahrzeugtypen,
  administrierbare FMS-Statusbezeichnungen, Wachen mit Verfügbarkeit (Zeitplan), Fahrzeuge,
  RICs (beidseitige Zuordnung zu Wachen/Fahrzeugen), Alarmierungsgruppen, Funkrufgruppen
  (Wachen, Organisationen, Fahrzeuge), Leitstellen-Verknüpfungen, Zuständigkeitsbereiche
  (GeoJSON, Gemeindeschlüssel, Abfrage der zuständigen Leitstelle).
- Excel/CSV-Import für Fahrzeuge und Wachen: Spaltenerkennung mit deutschen Synonymen,
  zeilengenaue Prüfung, Vorschau, Aktualisieren vorhandener Datensätze, Übernahme in einer
  Transaktion, Verwerfen; Beispieldateien in `docs/beispiele`.
- Client: generisches Stammdaten-Panel, Import-Assistent, Rollen-Editor, individuelle
  Rechte je Benutzer, Anmeldeprotokoll, Leitstellen-Umschalter in der Kopfzeile,
  neue Standardlayouts für Verwaltung und Administrator.
- Schutz ungespeicherter Eingaben bei gleichzeitiger Bearbeitung (Hinweis + Konflikt statt
  stillem Überschreiben).
- Rechtekatalog und Referenzdaten werden bei jedem Serverstart synchronisiert.
- Demo-Daten: fiktive Wachen, Fahrzeuge, RICs, Funkrufgruppen und Zuständigkeitsbereich.

### Geändert
- Neue Berechtigungen `master_data.read` und `organizations.write` (Systemrollen erhalten sie
  automatisch gemäß Standarddefinition).
- Standardlayouts (Schema 2): gespeicherte Layouts werden einmalig durch die neuen Standards ersetzt.

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
