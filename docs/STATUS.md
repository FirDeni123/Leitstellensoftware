# Projektstatus

**Stand:** 21.11.2026 · **Version:** 0.5.0 · **Aktuelle Phase:** 5 abgeschlossen, nächste: Phase 6 (Fahrzeuge, Karte, Navigation)

**Testergebnis zuletzt:** Server 122/122 ✅ · Client-Unit 40/40 ✅ · E2E 11/11 ✅ (dreimal in Folge) ·
Ruff ✅ · TypeScript ✅ · `alembic check` ✅

**Repository:** https://github.com/FirDeni123/Leitstellensoftware (Branch `main`).

## Phase 5 – Einsatzmittelvorschlag (umgesetzt und getestet)

| Bereich | Inhalt | Nachweis |
|---|---|---|
| Datenmodell | Migration `0005`: `proposal_settings` (je Leitstelle, versioniert), `proposals` (Eingaben, Ergebnis, Dauer, Übernahme); Recht `proposal_settings.write` (Leitung, Administration) | Migration up/down/up, `alembic check` |
| Bedarf | AAO der Leitstelle bzw. des Bereichs bis zur gewählten Stufe, Zusatzbedarf je Fahrzeugtyp; Fahrzeuge im Einsatz decken zuerst | `test_units_in_incident_cover_demand_first`, `test_accept_assigns_only_…` |
| Fahrzeit | Schätzung (Luftlinie × Umwegfaktor, Typgeschwindigkeit × Sonderrechtsfaktor) oder OSRM-`table` mit gekennzeichnetem Rückfall; Startpunkt Fahrzeugposition oder Wache | `test_estimate_and_formatting`, `test_routing_service_is_used_and_failure_falls_back` |
| Bewertung | gewichtete Fahrzeit = Fahrzeit + Ausrückzeit (Status 2) + Malus Ersatztyp − Bonus Wache laut AAO; maximale Fahrzeit; alles je Leitstelle einstellbar | `test_turnout_time_and_preferred_station_…`, `test_settings_permissions_versioning_and_effect` |
| Zuteilung | Greedy nach Bewertung, Ausgleichsschritt (kein unnötig offener Bedarf), bei Gleichstand passender Typ vor Ersatztyp | `test_balancing_keeps_all_demands_covered`, `test_equal_scores_prefer_matching_type_…` |
| Begründungen | je Fahrzeug lesbar (AAO-Position, Ersatz mit Malus, Status, Fahrzeit mit Quelle, Wachenbonus), Alternativen je Bedarf, Fehlbedarf mit Hinweis auf freie Fahrzeuge verknüpfter Nachbarleitstellen | `test_m5_b2_…`, `test_extra_demand_shortfall_and_neighbour_hint` |
| Bedienung | Fenster „Vorschlag …“ im Einsatz: Stufe wählen, Alternativen tauschen, abwählen, Zusatzbedarf, manuell ergänzen, neu berechnen, „Übernehmen“ (nur Zuordnung) oder „Übernehmen und alarmieren …“ (öffnet die Alarmierungsvorschau); Fenster „Vorschlagsregeln“ | E2E `phase5.spec.ts` |
| Alarmierungsvorschau | nutzt dieselbe Engine – Fahrzeiten und Begründungen im Alarmierungsdialog | `test_m4_preview_…` (angepasst) |

**Meilenstein M5 erreicht:** Für B2 entsteht in unter 1 s (gemessen 23–418 ms, Mittel 93 ms;
auch mit 300 zusätzlichen Fahrzeugen unter 1 s) ein Vorschlag mit nachvollziehbarer
Begründung je Fahrzeug. Weder Berechnung noch Übernahme alarmieren – das ist getestet
(keine `alarms`-Zeile, `alarmed_at` leer) und im Einsatzverlauf dokumentiert.

## Bei der Umsetzung von Phase 5 gefundene und behobene Fehler

- **Ersatztypen über Kreuz:** Bei gleicher Bewertung konnte die Zuteilung zwei Ersatztypen
  vergeben, obwohl passende Fahrzeuge frei waren. Jetzt gewinnt bei Gleichstand der passende
  Typ (Test).
- **Ungenaue Dokumentation der Übernahme:** Eine gewählte Alternative erschien im
  Einsatzverlauf als „manuell ergänzt“. Jetzt: „Alternative gewählt: …“.
- **Aufblitzende Konfliktwarnung nach eigenem Speichern:** Das Echtzeit-Ereignis kann vor der
  eigenen Serverantwort eintreffen. Die Warnung erscheint jetzt erst, wenn der Unterschied
  länger als 0,8 s besteht (gilt für alle Bearbeitungsmasken).
- **E2E-Selektoren:** Ein gespeichertes Layout mit dem neuen Fenster machte einen älteren
  Test mehrdeutig; Selektoren sind jetzt auf das jeweilige Fenster begrenzt.

## Phase 4 – Alarmierung (abgeschlossen, 0.4.0)

| Bereich | Inhalt | Nachweis |
|---|---|---|
| Datenmodell | Migration `0004`: Stichwort-Erweiterung (Polizei-Hinweis), `alarm_rules`, `alarm_rule_items`, `alarms` (Idempotenz-Schlüssel + Inhalts-Hash), `alarm_targets`, `police_notices`, `interfaces`, `interface_events` | Migration up/down/up, `alembic check` |
| AAO | Je Leitstelle und Stichwort, optional je Zuständigkeitsbereich (Bereich schlägt allgemeine Regel), Stufen 1–9, Einträge: Fahrzeugtyp × Anzahl, Fahrzeug, Wache, RIC, Alarmierungsgruppe, Schnittstelle; Editor im Client; 13 Demo-AAOs | `test_alarm_rule_validation_and_permissions`, `test_area_specific_rule_wins_inside_the_area` |
| Vorschau | Vorschlag aus AAO (bereits zugeordnete Fahrzeuge zuerst, freie nach Luftlinie), RICs (Fahrzeug, sonst Wache), zuständige Schnittstellen mit Wirkung (simuliert/umgeleitet/real/deaktiviert), Warnungen bei Fehlbestand, Polizei-Hinweis-Ankündigung; Fahrzeuge ab-/zuwählen, Stufe wählen | `test_m4_preview_for_b2_is_correct_and_triggers_nothing`, E2E |
| Alarmierung | Nur mit `confirmed: true` und `Idempotency-Key`; Erst- und Nachalarmierung; setzt Zuordnung, `alarmed_at`, Status „Alarmiert“; vollständiger Eintrag im Einsatzverlauf; Zustellung an Schnittstellen im Hintergrund mit Ergebnis im Verlauf | `test_m4_alarm_only_after_confirmation_and_idempotent`, `test_concurrent_requests_with_same_key_alarm_once`, E2E |
| Protokoll | Alarmierungen je Einsatz und Alarmierungsübersicht je Leitstelle mit Zustellstatus je Ziel, live bei allen Disponenten | E2E (zweiter Disponent) |
| Polizei | Bestätigungspflichtiges Informationsfenster beim auslösenden Disponenten, Vermerk, Dokumentation im Einsatzverlauf; Polizei-Fahrzeuge/-Wachen werden bei AAO, Vorschau und Alarmierung abgewiesen; keinerlei Übermittlung | `test_police_is_never_alarmed`, `test_m4_police_notice_popup_…`, E2E |
| Schnittstellen | Plugin-System (Entry-Points), Simulations-Empfänger und Webhook (real); Konfiguration per JSON-Schema mit generiertem Formular; Schlüssel verschlüsselt, nur maskiert sichtbar; Test, Ereignisprotokoll, Wiederholversuche | `test_interface_secret_is_encrypted_…`, `test_real_mode_delivery_retries_…` |
| Trennung Simulation/Echtbetrieb | Reale Schnittstellen nur im Echtbetrieb mit `interfaces.activate_real` und Begründung aktivierbar; automatische Deaktivierung beim Wechsel in den Simulationsbetrieb; Kern ruft reale Plugins im Simulationsbetrieb nie auf | `test_real_interface_activation_rules`, `test_m4_real_plugin_is_never_called_in_simulation_mode`, E2E |

**Meilenstein M4 erreicht:** B2 liefert die korrekte Vorschau (Fahrzeuge, Wachen, RICs,
Schnittstellen); alarmiert wird erst nach Bestätigung (simuliert); bei Stichworten mit
Polizei-Hinweis erscheint das Popup und die Bestätigung steht im Einsatzverlauf; ein reales
Plugin ist im Simulationsbetrieb nachweislich wirkungslos.

## Bei der Umsetzung von Phase 4 gefundene und behobene Fehler

- **Polizei-Hinweise bei Neuinstallation nicht gesetzt:** Die Markierung der Stichworte lief
  vor dem Speichern der neu angelegten Stichworte. Jetzt wird vorher gespeichert; ein
  Downgrade der Migration setzt die Markierung zurück.
- **Fehlermeldung nach Datenbank-Rollback:** Die Meldung „AAO existiert bereits“ griff auf
  bereits verworfene Objekte zu (500 statt 409). Behoben.
- **Polizei-Popup über dem Alarmierungsfenster:** Das Fenster schließt jetzt zuerst.

## Phase 3 – Einsatzbearbeitung (abgeschlossen, 0.3.0)

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

## Bekannte offene Punkte

| Punkt | Geplant in |
|---|---|
| OSRM-Dienst als Container bereitstellen (Anbindung ist fertig, aber nur gegen simulierten Endpunkt getestet) | Phase 6 |
| Ausrückzeit je Wache (z. B. Freiwillige Feuerwehr), Sonderrechtsfaktor je Fahrzeugtyp/Straßenklasse | später (Erweiterung der Vorschlagsregeln) |
| „Anfahrt“/„Am Einsatzort“ aus Fahrzeugstatus (S3/S4) | Phase 6 |
| Funkalarmierung (POCSAG/TETRA) – RICs werden im Echtbetrieb nur protokolliert („nicht zugestellt“) | späteres Plugin |
| Anbindung einer konkreten Feuerwehrsoftware (z. B. Feuersoftware Connect) | späteres Plugin, nach Schnittstellendoku und Testzugang |
| Einsatzort per Karte wählen, Adresssuche (Geokodierung) | Phase 6 |
| Gemeindeschlüssel-Bereiche bei Zuständigkeit und AAO-Bereichswahl auswerten (heute nur Geometrie) | mit Adresssuche |
| Klingelnde Notrufe ohne Annahme nach Zeit als „verpasst“ markieren | Phase 7 (mit Telefonie) |
| Pop-out-Fenster für Mehrmonitorbetrieb | Phase 8 |
| Allowlist für Webhook-Ziele, IP-basierte Ratenbegrenzung, Zertifikats-Pinning, Code-Signing, Auto-Update | Phase 8 |
| Rollen-Editor nutzt noch nicht den gemeinsamen Bearbeitungsschutz | Phase 6 |

## In dieser Umgebung nicht verifizierbar (unverändert)

- Docker-Compose-Gesamtstack und Installationsskript, Windows-Installer (CI-Job), native
  Fensterleiste unter Windows.

## Nächster konkreter Schritt (Phase 6 – Fahrzeuge, Karte, Navigation)

1. Statussystem im Betrieb: Statuswechsel je Fahrzeug (Disponent, Simulation), Statushistorie
   (`vehicle_status_history`), Sprechwünsche (Status 0/5) mit Annehmen/Zurückstellen.
2. Simulationsdienst: Alarmierung → Status 3 → Fahrt entlang der Route → Ankunft Status 4,
   Positionen gebündelt im 1-Hz-Takt an alle Clients; Einsatzstatus „Anfahrt“/„Am Einsatzort“
   automatisch.
3. Karte (MapLibre) mit Wachen, Fahrzeugen, Einsatzorten; Einsatzort per Klick wählen.
4. OSRM-Container in Docker Compose (Region aus OSM-Extrakt) – damit nutzt der
   Einsatzmittelvorschlag automatisch echte Straßenfahrzeiten.
5. Abnahme M6: 50 Fahrzeuge fahren gleichzeitig, alle Clients sehen identische Positionen.

## Annahmen und Entscheidungen

- Beispielregion für Demo-Daten: Raum Schwarzenbek (Schleswig-Holstein); alle Wachen,
  Fahrzeuge, RICs, Anrufer, Rufnummern (Block „0000“) und Adressen („Demostadt“) sind fiktiv.
- Einsatznummern: `JJJJ-NNNNNN`, Jahr nach Ortszeit (`ILS_TIMEZONE`, Standard Europe/Berlin).
- Disponenten dürfen im Simulationsbetrieb Statuswerte manuell setzen; ab Phase 4/6 werden
  diese aus Alarmierung und Fahrzeugstatus abgeleitet.
- Ohne Sprach-KI (Phase 7) enthält ein simulierter Notruf ein Gesprächsprotokoll mit den
  Antworten des Anrufers „auf Nachfrage“.
- In der Entwicklungsumgebung ist ein Zugang zu einer externen Alarmierungs-API hinterlegt. Er
  wurde **bewusst nicht angesprochen** (reale Alarmierungsschnittstelle). Ein passendes
  Plugin wird erst mit Schnittstellendokumentation und Testzugang gebaut – standardmäßig
  deaktiviert und nur im Echtbetrieb aktivierbar. Getestet werden reale Plugins nur gegen
  einen simulierten HTTP-Endpunkt (`httpx.MockTransport`).
- Die Alarmierung eines Fahrzeugs ordnet es dem Einsatz zu. „Wache“ in der AAO bedeutet
  Wachenalarm über deren RICs, nicht automatisch alle Fahrzeuge der Wache.
- Systemweite und Leitstellen-Schnittstellen erhalten jede Alarmierung der Leitstelle,
  Wachen-Schnittstellen nur Alarmierungen mit Beteiligung der Wache (Datensparsamkeit).
