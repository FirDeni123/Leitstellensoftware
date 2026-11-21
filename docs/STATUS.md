# Projektstatus

**Stand:** 21.11.2026 · **Version:** 0.2.0 · **Aktuelle Phase:** 2 abgeschlossen, nächste: Phase 3 (Einsatzbearbeitung)

**Testergebnis zuletzt:** Server 74/74 ✅ · Client-Unit 28/28 ✅ · E2E 5/5 ✅ · Ruff ✅ · TypeScript ✅ ·
`alembic check` ✅ · Electron-Start und Datei-Upload unter Xvfb ✅

## Phase 2 – Administration (umgesetzt und getestet)

| Bereich | Inhalt | Nachweis |
|---|---|---|
| Datenmodell | Migration `0002` (16 Tabellen), up/down getestet, Modell = Migration (`alembic check`) | Migrationstest beim Testlauf |
| Organisationen, Fahrzeugtypen | Globale Kataloge mit Standardwerten (10 Organisationen, 18 Fahrzeugtypen), editierbar; Polizei per DB-Constraint nie alarmierbar | `test_master_data.py` |
| Statusbezeichnungen | FMS 0–9 administrierbar (Bezeichnung, Kurztext, Farbe, „gilt als verfügbar“) | dito |
| Wachen | Organisation, Standort (GPS), Verfügbarkeit (immer/Zeitplan/nicht), RICs, Funkrufgruppen | dito |
| Fahrzeuge | Funkrufname (eindeutig je Leitstelle), Kennzeichen, Typ, Organisation, Wache, Funkrufgruppe, RICs, Verfügbarkeit, Besatzung, Beschreibung, Simulationsgeschwindigkeit; Position aus der Wache abgeleitet | dito |
| RICs, Alarmierungsgruppen | RIC + Subadresse A–D, beidseitige Zuordnung zu Wachen/Fahrzeugen, Gruppen aus RICs | dito |
| Funkrufgruppen | Zuordnung zu Wachen, Organisationen, Fahrzeugen | dito |
| Leitstellen | Verknüpfungen (Nachbar, Rückfallebene, Kooperation), Zuständigkeitsbereiche (GeoJSON / Gemeindeschlüssel), Abfrage der zuständigen Leitstelle je Koordinate | dito |
| Datenimport | `.xlsx`/`.csv`, Spaltenerkennung, zeilengenaue Prüfung, Vorschau, Aktualisieren, Übernahme in einer Transaktion, Verwerfen, Datenminimierung | `test_import.py` (M2: 200 Fahrzeuge), E2E |
| Benutzerverwaltung | Rollen-Editor (Rechte nach Bereichen), individuelle Rechte (gewähren/entziehen), Anmeldeprotokoll | UI, E2E-Rundgang |
| Mandanten & Echtzeit | Alle Stammdaten je Leitstelle gefiltert; Änderungen live nur an Benutzer der betroffenen Leitstelle | `test_tenant_scoping…`, `test_master_data_events_are_scoped…` |
| Gleichzeitige Bearbeitung | Ungespeicherte Eingaben bleiben bei fremden Änderungen erhalten, Hinweis, Speichern → Konflikt, „Neu laden“ | E2E `concurrent edit` |

**Meilenstein M2 erreicht:** 200 Fahrzeuge aus `.xlsx` mit abweichenden Spaltennamen,
zeilengenaue Fehler vor der Bestätigung, jeder Datensatz im Änderungsprotokoll
(`test_m2_import_200_vehicles_from_xlsx`).

## Bei der Umsetzung gefundene und behobene Fehler

- Eine beschädigte `.xlsx` erzeugte einen Serverfehler (500) statt einer Meldung → abgefangen.
- Beim Aktualisieren per Import hätte ein in Kleinbuchstaben geschriebener Funkrufname die
  vorhandene Schreibweise überschrieben → der Abgleichsschlüssel bleibt unverändert.
- Bei gleichzeitiger Bearbeitung wurde das Formular durch Echtzeit-Updates neu aufgebaut und
  ungespeicherte Eingaben gingen verloren → Schutz im generischen Editor (siehe oben).

## In dieser Umgebung nicht verifizierbar (unverändert)

- Docker-Compose-Gesamtstack und Installationsskript (kein Docker-Daemon), Windows-Installer
  (CI-Job auf `windows-latest`), native Fensterleiste unter Windows.

## Bekannte offene Punkte

| Punkt | Geplant in |
|---|---|
| Benutzer- und Leitstellen-Panel aus Phase 1 bauen das Formular bei fremden Änderungen noch neu auf (Muster des generischen Editors übernehmen) | Phase 3 |
| Zuständigkeitsbereiche auf der Karte zeichnen; Gemeindeschlüssel automatisch auflösen | Phase 6 / Phase 3 (Adresssuche) |
| Schnittstellen je Wache (Feuerwehrsoftware, Zusatzalarmierung) | Phase 4 |
| RICs ↔ Einsatzstichworte, Alarmierungsketten, Zusatzalarmierung | Phase 4 |
| Statuswechsel im Betrieb, Statushistorie | Phase 6 |
| Wachen-Import aus OpenStreetMap (Overpass → gleiche Prüfvorschau) | später (Pipeline vorbereitet: `import_files.ParsedTable`) |
| IP-basierte Ratenbegrenzung der Anmeldung, Zertifikats-Pinning, Code-Signing, Auto-Update | Phase 8 |
| Pop-out-Fenster für Mehrmonitorbetrieb | Phase 3 |

## Nächster konkreter Schritt (Phase 3 – Einsatzbearbeitung)

1. Migration `0003`: `emergency_calls`, `call_notes`, `incidents`, `incident_number_sequences`,
   `incident_events`, `incident_vehicles`, `incident_stations` (Schema: [02-datenbank.md](02-datenbank.md)).
2. Einsatznummern lückenlos je Leitstelle und Jahr (Sequenztabelle mit `FOR UPDATE`).
3. Services: Notruf annehmen/halten/beenden/zuordnen, Einsatz anlegen aus Notruf, Statusmodell
   der Einsätze (Neu → … → Abgeschlossen) mit erlaubten Übergängen, Fahrzeuge zuordnen,
   abziehen, umsetzen (mit fachlicher Sperre: ein Fahrzeug nur in einem Einsatz),
   Einsatzverlauf append-only.
4. Simulierte Anrufe (Provider `SimulatedTelephony`, ohne Audio) zum Testen der Notrufannahme.
5. Client: Panels „Neue Notrufe“, „Aktuelle Einsätze“, Einsatzdetail mit Verlauf,
   Tastaturbedienung für die Notrufannahme; Bearbeitungsschutz aus dem generischen Editor.
6. Abnahme M3: zwei Disponenten parallel, Notruf → bestehender Einsatz, lückenloser Verlauf.

## Annahmen und Entscheidungen

- Beispielregion für Demo-Daten: Raum Schwarzenbek (Schleswig-Holstein); alle Wachen,
  Fahrzeuge und RICs sind fiktiv und als „(Demo)“ gekennzeichnet (`server/app/demo_data.py`).
- Organisationen und Fahrzeugtypen sind leitstellenübergreifende Kataloge; Wachen, Fahrzeuge,
  RICs, Gruppen und Bereiche gehören genau einer Leitstelle.
- Leere Zellen ändern beim Import vorhandene Werte nicht; Fehlerzeilen werden nur auf
  ausdrücklichen Wunsch übersprungen.
- Tokens nur im Arbeitsspeicher des Clients; keine Offline-Schreibwarteschlange.
- In der Entwicklungsumgebung ist ein Zugang zu einer externen Alarmierungs-API hinterlegt. Er
  wurde **bewusst nicht angesprochen** (reale Alarmierungsschnittstelle). Anbindung frühestens
  in Phase 4 als Plugin, standardmäßig deaktiviert und nur im Echtbetrieb aktivierbar.
