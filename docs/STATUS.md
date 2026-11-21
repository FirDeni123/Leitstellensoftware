# Projektstatus

**Stand:** 21.11.2026 · **Version:** 0.3.0 · **Aktuelle Phase:** 3 abgeschlossen, nächste: Phase 4 (Alarmierung)

**Testergebnis zuletzt:** Server 89/89 ✅ · Client-Unit 28/28 ✅ · E2E 6/6 ✅ · Ruff ✅ · TypeScript ✅ ·
`alembic check` ✅

## Phase 3 – Einsatzbearbeitung (umgesetzt und getestet)

| Bereich | Inhalt | Nachweis |
|---|---|---|
| Datenmodell | Migration `0003`: `keywords`, `emergency_calls`, `call_notes`, `incidents`, `incident_number_sequences`, `incident_events` (Trigger: unveränderbar), `incident_vehicles` (partieller Unique-Index) | Migration up/down, `alembic check` |
| Notrufannahme | Warteschlange (Priorität, Wartezeit), Signalton + Kopfzeilenanzeige, Annahme per Strg+Leertaste/Doppelklick, genau eine annehmende Person (Wettlauf → 409 mit Namen), Halten/Übernehmen, automatisches Halten beim Annehmen eines weiteren Gesprächs, Anruferdaten, Anruferstandort, Zuständigkeitsprüfung, W-Fragen als Rückfragen, Notizen, manuell erfasste Anrufe, laufende Telefonate | `test_operations.py`, E2E `phase3.spec.ts` |
| Einsätze | Anlegen aus Notruf (Datenübernahme) oder manuell, lückenlose Nummern je Leitstelle/Jahr (auch bei 10 parallelen Anlagen), Stichwort/Einsatzart/Priorität, Statusmodell mit Regeln (Abschluss nur aus „beendet“, ohne gebundene Fahrzeuge, mit `incidents.close`; Wiedereröffnen nur nach „beendet“), Optimistic Locking | dito |
| Fahrzeugzuordnung | Zuordnen, Freigeben, Umsetzen mit Rückfrage; ein Fahrzeug nur in einem Einsatz (Sperre + DB-Index, gleichzeitige Zuordnung → genau einmal erfolgreich); nicht verfügbare/fremde Fahrzeuge abgelehnt | dito |
| Einsatzverlauf | Jede Änderung mit Zeit und Person, unveränderbar (DB-Trigger), Dokumentationseinträge, Verknüpfung mehrerer Notrufe | dito |
| Stichworte | Katalog mit 16 Standardstichworten, Verwaltung im generischen Stammdaten-Panel | dito |
| Simulation | Zehn fiktive Szenarien mit Gesprächsprotokoll „auf Nachfrage“, Erzeugung nur mit `simulation.control` und nur im Simulationsbetrieb | `test_simulated_calls_are_refused_in_real_mode` |
| Bearbeitungsschutz | Gemeinsamer Hook `useEditBase` für Stammdaten, Benutzer, Leitstellen und Einsätze | E2E `concurrent edit` |

**Meilenstein M3 erreicht:** Zwei Disponenten arbeiten parallel; der zweite Notruf wird durch
eine Kollegin dem bestehenden Einsatz zugeordnet; der Einsatzverlauf enthält Anlage, beide
Notrufe, Fahrzeugzuordnung und Statuswechsel mit den handelnden Personen
(`test_m3_two_dispatchers_…` und E2E `M3: …`).

## Bei der Umsetzung gefundene und behobene Fehler

- **Eingaben im falschen Gespräch:** Hatte ein Disponent noch ein aktives Gespräch und nahm
  einen neuen Notruf an, zeigte die Maske bis zur Serverantwort das alte Gespräch. Jetzt wechselt
  die Ansicht sofort, und der Server hält das bisherige Gespräch automatisch (wie am Telefon).
- **Versionskonflikt durch eigene Notiz:** Eine gerade dokumentierte Rückfrage erhöhte die
  Version des Notrufs und blockierte das Speichern. Notrufe werden nur von der bearbeitenden
  Person geändert (serverseitig erzwungen) und brauchen keine Versionsprüfung.
- **Statusaktionen mit Versionsprüfung:** Annehmen/Halten/Beenden/Zuordnen prüfen jetzt den
  Zustand statt der Version – sonst unnötige Konflikte im Betrieb.

## In dieser Umgebung nicht verifizierbar (unverändert)

- Docker-Compose-Gesamtstack und Installationsskript, Windows-Installer (CI-Job), native
  Fensterleiste unter Windows.

## Bekannte offene Punkte

| Punkt | Geplant in |
|---|---|
| Status „Alarmiert“, „Anfahrt“, „Am Einsatzort“ automatisch aus Alarmierung/Fahrzeugstatus | Phase 4 / 6 (bis dahin manuell) |
| Einsatzort per Karte wählen, Adresssuche (Geokodierung) | Phase 6 |
| Gemeindeschlüssel-Bereiche bei der Zuständigkeitsprüfung auswerten | mit Adresssuche |
| Klingelnde Notrufe ohne Annahme nach Zeit als „verpasst“ markieren | Phase 7 (mit Telefonie) |
| Pop-out-Fenster für Mehrmonitorbetrieb | Phase 8 (zurückgestellt; Layouts sind je Arbeitsplatz frei anordenbar) |
| Rollen-Editor nutzt noch nicht den gemeinsamen Bearbeitungsschutz | Phase 4 |
| IP-basierte Ratenbegrenzung, Zertifikats-Pinning, Code-Signing, Auto-Update | Phase 8 |

## Nächster konkreter Schritt (Phase 4 – Alarmierung)

1. Migration `0004`: Stichwort-Erweiterung (`police_notice`, `police_notice_text`),
   `alarm_rules` + `alarm_rule_items` (Fahrzeugtyp × Anzahl, Wache, RIC, Alarmierungsgruppe,
   Schleife/Stufe, Zusatzalarmierung), `alarms` (mit `idempotency_key`), `alarm_targets`,
   `police_notices`, `interfaces`, `interface_events`.
2. Alarmierungsvorschau aus Stichwort + AAO + Zuordnungen (Fahrzeuge, Wachen, RICs), Bestätigung,
   Nachalarmierung; Alarmierung setzt `incident_vehicles.alarmed_at` und den Einsatzstatus
   „Alarmiert“.
3. Polizei-Hinweis als bestätigungspflichtiges Popup bei markierten Stichworten – ohne
   jegliche Zustellung an die Polizei; Bestätigung im Einsatzverlauf.
4. Plugin-System (`AlarmGateway`) mit Simulations-Gateway; reale Plugins nur im Echtbetrieb
   und mit `interfaces.activate_real`; Kern leitet im Simulationsbetrieb um (Test!).
5. Client: AAO-Editor, RIC-Zuordnung zu Stichworten, Alarmierungsvorschau/-bestätigung im
   Einsatz, Alarmierungsübersicht, Polizei-Popup, Schnittstellenverwaltung.
6. Abnahme M4 laut Roadmap.

## Annahmen und Entscheidungen

- Beispielregion für Demo-Daten: Raum Schwarzenbek (Schleswig-Holstein); alle Wachen,
  Fahrzeuge, RICs, Anrufer, Rufnummern (Block „0000“) und Adressen („Demostadt“) sind fiktiv.
- Einsatznummern: `JJJJ-NNNNNN`, Jahr nach Ortszeit (`ILS_TIMEZONE`, Standard Europe/Berlin).
- Disponenten dürfen im Simulationsbetrieb Statuswerte manuell setzen; ab Phase 4/6 werden
  diese aus Alarmierung und Fahrzeugstatus abgeleitet.
- Ohne Sprach-KI (Phase 7) enthält ein simulierter Notruf ein Gesprächsprotokoll mit den
  Antworten des Anrufers „auf Nachfrage“.
- In der Entwicklungsumgebung ist ein Zugang zu einer externen Alarmierungs-API hinterlegt. Er
  wurde **bewusst nicht angesprochen** (reale Alarmierungsschnittstelle). Anbindung frühestens
  in Phase 4 als Plugin, standardmäßig deaktiviert und nur im Echtbetrieb aktivierbar.
