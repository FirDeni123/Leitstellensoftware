# Projektstatus

**Stand:** 21.11.2026 · **Version:** 0.7.0 · **Aktuelle Phase:** 7 umgesetzt (M7 mit
regelbasiertem Anrufer nachgewiesen, Claude-Latenz noch zu messen), nächste: Phase 8
(Stabilisierung)

**Testergebnis zuletzt:** Server 155/155 ✅ · Client-Unit 56/56 ✅ · E2E 15/15 ✅ (zweimal in Folge) ·
Ruff ✅ · TypeScript ✅ · `alembic check` ✅

**Repository:** https://github.com/FirDeni123/Leitstellensoftware (Branch `main`).

## Phase 7 – Ausbildung und KI-Anrufer (umgesetzt)

| Bereich | Inhalt | Nachweis |
|---|---|---|
| Datenmodell | Migration `0007`: `training_scenarios` (versioniert), `training_sessions` (Szenario-Schnappschuss, Anrufer-Modus, Modell, verdeckte Regieanweisungen), `training_messages`, `training_evaluations`; neue Standardrolle „Ausbilder“ | Migration up/down/up, `alembic check` |
| Übungsablauf | Übung starten → Trainings-Notruf (`source = training`) klingelt in der normalen Notrufannahme; nur die übende Person darf annehmen/fortsetzen; Annahme spielt den Eröffnungssatz; Auflegen beendet die Übung, nicht angenommen = abgebrochen; nur im Simulationsbetrieb, Wechsel in den Echtbetrieb bricht ab | `test_exercise_without_ai_end_to_end`, `test_permissions_and_visibility`, `test_exercises_only_in_simulation_mode`, `test_unanswered_…` |
| KI-Anrufer | Claude über das offizielle SDK: Streaming, Antwort satzweise sofort an Client (Anzeige + Sprachausgabe), Aufwand „niedrig“, Prompt-Caching, serverseitiges Ausweichmodell bei Ablehnung, Regieanweisungen als Systemnachricht im Gespräch; Schlüssel verschlüsselt; standardmäßig aus | `test_claude_caller_streams_sentences`, `test_instructor_interventions_…` (gegen einen SDK-Nachbau, siehe unten) |
| Regelbasierter Anrufer | Antworten aus den Szenario-Fakten per Schlüsselwort; Rückfall bei KI-Fehlern, Ablehnung oder fehlendem Schlüssel – im Verlauf sichtbar gekennzeichnet | `test_ai_failures_fall_back_to_rules_visibly`, E2E |
| Reihenfolge, mehrere Server-Prozesse | Antworten je Übung über eine PostgreSQL-Sperre serialisiert; eine Nachricht, die während der Antwort eintrifft, bekommt eine eigene Antwort; doppelte Auslösung erzeugt nur eine Antwort | `test_message_during_reply_gets_its_own_answer` |
| Ausbildermodus | Übung für Teilnehmer starten, live mitlesen, verdeckte Regie (mit nächster Antwort oder sofort), Notizen, beenden, neu auswerten; Teilnehmer sehen weder Regie noch Lösung während der Übung | `test_instructor_interventions_reach_only_the_caller`, E2E |
| Auswertung | automatisch nach dem Auflegen: Einsatz angelegt, Stichwort, Einsatzort (≤ 300 m oder Adresse), Alarmierung direkt aus den Systemdaten; Gesprächspunkte per Claude (strukturierte Ausgabe) oder Schlüsselwörtern; Kennzahlen, Stärken, Verbesserungen; Ergebnis = Anteil erfüllter Pflichtpunkte | `test_claude_evaluation_uses_structured_output`, `test_exercise_without_ai_end_to_end`, E2E |
| Sprache | Sprachausgabe mit Windows-Stimmen (Web Speech API, satzweise); Sprechtaste mit Spracherkennung auf dem Server (faster-whisper, optionales Paket, Docker-Build-Argument) | Endpunkt mit Erkennungs-Nachbau getestet; faster-whisper selbst hier nicht installiert |
| Fenster | Übungsgespräch, Ausbildung (Beobachten), Übungsszenarien (Editor), Übungsberichte, KI-Einstellungen; Arbeitsplatz „Ausbildung“ (F7); Übungsanrufe in der Notrufannahme als „ÜBUNG“ markiert | E2E `phase7.spec.ts`, Unit-Tests `training.test.ts` |
| Demo | vier fiktive Szenarien (Pkw-Brand leicht, VU eingeklemmt mittel, Brustschmerz RD2 mittel, Küchenbrand mit Menschenleben in Gefahr schwer), Benutzer `ausbilder.demo` | `test_demo_scenarios_are_valid_and_seeded_once` |

Screenshots: `docs/screenshots/70-m7-uebungsgespraech.png`, `71-m7-ausbilder.png`,
`72-m7-auswertung.png`, `73-ki-einstellungen.png`.

**Meilenstein M7 – ehrlicher Stand:**

- **Nachgewiesen (E2E, regelbasierter Anrufer):** Übungsanruf annehmen, Gespräch führen,
  währenddessen den Einsatz mit Stichwort und Ort anlegen, auflegen, Auswertung mit
  Checkliste erhalten; der Ausbilder liest live mit und steuert den Anrufer verdeckt.
- **Gemessen:** Eigenanteil des Servers an der Antwortzeit (Nachricht speichern bis erster
  Satz veröffentlicht) 14–25 ms (`test_server_overhead_of_a_reply_is_small`).
- **Nicht gemessen:** Antwortzeit mit dem echten Claude-Modell. In dieser Umgebung ist kein
  API-Schlüssel vorhanden; der Claude-Weg ist gegen einen Nachbau des SDK getestet
  (Parameter, Nachrichtenfolge, Streaming, Fehler- und Ablehnungsfälle). Ob 2,5 s
  eingehalten werden, zeigt erst ein Test mit Schlüssel (Messwert steht danach in jeder
  Antwort im Verlauf).
- **Sprachgespräch nur teilweise:** Sprachausgabe im Client vorhanden; Spracherkennung
  verlangt das optionale Paket auf dem Server (hier nicht installiert, Modell-Download nötig).
  Piper-Stimmen, Audio-Streaming per WebSocket, Sprechpausenerkennung und Unterbrechen sind
  **nicht** umgesetzt.

## Bei der Umsetzung von Phase 7 gefundene und behobene Fehler

- **Fenster verschwand:** Ein Fenster, das geöffnet wurde, während das gespeicherte Layout
  noch lud, wurde vom Layout überschrieben (im E2E-Test gefunden). Das Öffnen wird jetzt nach
  dem Laden nachgeholt.
- **Unbeantwortete Nachricht:** Schrieb der Disponent, während der Anrufer schon antwortete,
  landete die Antwort hinter der neuen Nachricht – diese blieb unbeantwortet. Beiträge sind
  jetzt nach dem Zeitpunkt des Sprechens geordnet (Test).
- **Veraltete Live-Liste unter Last:** Traf ein Echtzeit-Ereignis ein, während eine Liste
  gerade noch mit altem Stand geladen wurde (z. B. ein eben geöffnetes Fenster), hängte sich
  die Aktualisierung an diesen Ladevorgang – die Liste blieb veraltet (im E2E-Gesamtlauf
  gefunden, betrifft alle Live-Listen). Die Aktualisierung wartet jetzt, bis der laufende
  Ladevorgang fertig ist, und lädt dann neu (Unit-Test).
- **Übungsanruf klingelte bei allen:** Ein Trainings-Notruf erschien mit Signalton in der
  Warteschlange aller Disponenten der Leitstelle, obwohl nur die übende Person annehmen darf.
  Er erscheint jetzt nur bei ihr (Test).
- **`seed-demo` nach Update:** Neue Standardrollen fehlten, bis der Server einmal gestartet
  war. `seed-demo` gleicht den Rollenkatalog jetzt selbst ab.

## Phase 6 – Fahrzeuge, Karte, Simulation (abgeschlossen, 0.6.0)

| Bereich | Inhalt | Nachweis |
|---|---|---|
| Datenmodell | Migration `0006`: `vehicle_status_history` (unveränderbar, Trigger), `talk_requests`, `vehicle_movements` (Route + Zeitprofil in Simulationssekunden); Simulationsuhr in `system_settings` | Migration up/down/up, `alembic check`, `test_status_effects_…` (UPDATE abgewiesen) |
| Fahrzeugstatus | FMS-Status mit Folgen: 3/4 → Einsatz „Anfahrt“/„Am Einsatzort“ mit Zeiten und Verlauf; 1/2 → freigemeldet und freigegeben; 6 → aus dem Einsatz gelöst; 0/5 → Sprechwunsch; Statushistorie je Fahrzeug | `test_status_effects_history_and_permissions`, `test_out_of_service_…` |
| Sprechwünsche | Warteschlange (0 vor 5, dann Zeit), Hochstufen 5 → 0, Sprechaufforderung, zurückstellen, ablehnen, erledigt mit Vermerk im Einsatzverlauf, Signalton bei Status 0 | `test_talk_requests_workflow`, E2E |
| Simulation | Ausrücken nach Ausrückzeit, Fahrt mit Sonderrechten (OSRM-Route oder gekennzeichnete Luftlinie), S3 bei Abfahrt, S4 bei Ankunft, Rückfahrt S1 → S2 nach Freigabe, Ausfall, Verschieben, Pause und Zeitraffer, keine Simulation im Echtbetrieb, ein simulierender Prozess (Advisory-Lock), neustartsicher | `test_m6_…`, `test_release_drives_back_…`, `test_clock_pause_factor_and_real_mode`, `test_breakdown_…`, `test_single_simulation_leader`, `test_movements_survive_a_restart` |
| Echtzeit | ein `vehicle.positions`-Ereignis je Leitstelle und Takt; alle Clients erhalten identische Daten | `test_m6_all_clients_see_identical_positions` (zwei echte WebSocket-Verbindungen) |
| Karte | MapLibre: Wachen, Fahrzeuge (Statusfarbe, live), Einsätze, Routen, Quellenangabe; Einsatzort per Klick; Fahrzeug verschieben (Simulation); Simulationsuhr | E2E `phase6.spec.ts`; Kachelanzeige unter CSP mit lokalem Testkachelserver geprüft |
| Fenster | Fahrzeugübersicht (Status setzen, Historie, Ausfall), Statusübersicht (nach Wache, Funkrufgruppe, Organisation), Sprechwünsche; im Einsatz Status, S3/S4-Zeiten, Live-ETA | E2E |
| Betrieb | optionaler OSRM-Dienst in Docker Compose (Profil „routing“) und `prepare-osrm.sh` | nur Syntax geprüft (kein Docker hier) |

**Meilenstein M6 erreicht:** 50 Fahrzeuge fahren gleichzeitig (laufender Takt 42 ms), alle
Clients erhalten identische Positionen im 1-Hz-Takt, die Ankunft setzt Status 4 und schreibt
den Einsatzverlauf. „Straßengenau“ setzt den OSRM-Dienst voraus: Die Anbindung ist gegen einen
simulierten OSRM-Endpunkt getestet; ohne Routing fahren die Fahrzeuge gekennzeichnet auf der
Luftlinie.

## Bei der Umsetzung von Phase 6 gefundene und behobene Fehler

- **Abfragesturm bei vielen Sitzungen:** Jede Statusänderung ließ jeden Client die Flotte neu
  laden und brach laufende Abfragen ab – bei vielen gleichzeitigen Sitzungen kam die
  Aktualisierung nie an (Karte blieb auf altem Stand). Invalidierungen werden jetzt je
  Abfrage gebündelt, laufende Abfragen nicht mehr abgebrochen (Unit-Tests). Gilt für alle
  Echtzeit-Aktualisierungen; die E2E-Laufzeit sank von ca. 1,7 auf 1,3 min.
- **Simulations-Sperre blieb im Verbindungspool:** Beim Abgeben der Leitung kehrte die
  Datenbankverbindung mit gehaltener Sperre in den Pool zurück – ein anderer Prozess hätte
  nie übernehmen können. Die Sperre wird jetzt ausdrücklich freigegeben (Test).
- **Karte mit Höhe 0:** Das MapLibre-Stylesheet überschrieb die Größenregel des Containers;
  der E2E-Test prüft jetzt, dass Marker innerhalb der sichtbaren Karte liegen.
- **Migration:** asyncpg erlaubt nur eine Anweisung je Aufruf – Trigger und Funktion getrennt.

## Phase 5 – Einsatzmittelvorschlag (abgeschlossen, 0.5.0)

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
| OSRM-Dienst und OSM-Kacheln in einer Umgebung mit Docker/Internet prüfen | Betrieb (Anbindung fertig) |
| Bündelung (Clustering) überlappender Fahrzeugmarker an einer Wache | Phase 8 |
| Zurückgelegte Strecken (Tracks) speichern und anzeigen | Phase 8 |
| Sonderrechtsfaktor je Fahrzeugtyp/Straßenklasse, Ausrückzeit je Wache | spätere Erweiterung der Vorschlagsregeln |
| Reale FMS-/TETRA-Statusanbindung und GPS-Ortung (Plugins `PositionSource`) | spätere Plugins |
| Funkalarmierung (POCSAG/TETRA) | späteres Plugin |
| Anbindung einer konkreten Feuerwehrsoftware (z. B. Feuersoftware Connect) | späteres Plugin, nach Schnittstellendoku und Testzugang |
| Adresssuche (Geokodierung) für den Einsatzort | Phase 8 |
| Gemeindeschlüssel-Bereiche bei Zuständigkeit und AAO-Bereichswahl auswerten (heute nur Geometrie) | mit Adresssuche |
| Claude-Antwortzeit mit echtem API-Schlüssel messen (M7 vollständig abnehmen) | sobald ein Schlüssel hinterlegt ist |
| Sprachpipeline: Piper-Stimmen auf dem Server, Audio-Streaming per WebSocket, Sprechpausenerkennung, Unterbrechen | Phase 7b / 8 |
| faster-whisper in einer Umgebung mit Modell-Download prüfen (Sprechtaste) | Betrieb |
| Zufallsgenerator für Szenarien, zulässige Alternativ-Stichworte, Export der Übungsberichte, optionale Gesprächsaufzeichnung | Phase 7b / 8 |
| Klingelnde Notrufe ohne Annahme nach Zeit als „verpasst“ markieren | Phase 8 |
| Rollen-Editor nutzt noch nicht den gemeinsamen Bearbeitungsschutz | Phase 8 |
| Pop-out-Fenster für Mehrmonitorbetrieb | Phase 8 |
| Allowlist für Webhook-Ziele, IP-basierte Ratenbegrenzung, Zertifikats-Pinning, Code-Signing, Auto-Update | Phase 8 |
| Electron: Karten-Worker über das `app://`-Protokoll im echten Windows-Client prüfen (Web-Build geprüft) | Windows-CI |

## In dieser Umgebung nicht verifizierbar (unverändert)

- Docker-Compose-Gesamtstack und Installationsskript, Windows-Installer (CI-Job), native
  Fensterleiste unter Windows.

## Nächster konkreter Schritt

1. **M7 abschließen (benötigt eine Entscheidung des Betreibers):** einen Claude-API-Schlüssel
   hinterlegen – im Fenster „KI-Einstellungen“ (verschlüsselt in der Datenbank) oder als
   Umgebungsvariable `ILS_ANTHROPIC_API_KEY` auf dem Server –, KI-Anrufer einschalten,
   „Verbindung testen“ und eine Übung führen. Die Antwortzeit steht je Antwort im Verlauf
   und als Mittel/Maximum in der Auswertung.
2. Phase 8 (Stabilisierung): Sicherheits- und Lasttests (20 Arbeitsplätze), signierter
   Installer, Auto-Update, Backup/Restore-Test, Betriebs- und Benutzerdokumentation; dazu die
   offenen Punkte oben.

## Annahmen und Entscheidungen

- Beispielregion für Demo-Daten: Raum Schwarzenbek (Schleswig-Holstein); alle Wachen,
  Fahrzeuge, RICs, Anrufer, Rufnummern (Block „0000“) und Adressen („Demostadt“) sind fiktiv.
- Einsatznummern: `JJJJ-NNNNNN`, Jahr nach Ortszeit (`ILS_TIMEZONE`, Standard Europe/Berlin).
- Disponenten dürfen im Simulationsbetrieb Statuswerte manuell setzen; ab Phase 4/6 werden
  diese aus Alarmierung und Fahrzeugstatus abgeleitet.
- Simulierte Notrufe aus Phase 3 enthalten weiterhin ein festes Gesprächsprotokoll; das
  freie Gespräch gibt es in Übungen (Phase 7).
- KI-Anrufer: Standardmodell `claude-opus-5-5` mit Aufwand „niedrig“ im Gespräch und
  „mittel“ bei der Auswertung; der Administrator kann beides ändern. Die KI spielt nur den
  Anrufer und hat keine Werkzeuge – sie kann nichts anlegen, alarmieren oder anrufen.
- Übungsinhalte gehen bei eingeschalteter KI an die Claude-API (Anthropic). Deshalb sind
  Szenarien ausdrücklich nur mit fiktiven Daten zu füllen; ohne Einschalten verlässt nichts
  den Server.
- In der Entwicklungsumgebung ist ein Zugang zu einer externen Alarmierungs-API hinterlegt. Er
  wurde **bewusst nicht angesprochen** (reale Alarmierungsschnittstelle). Ein passendes
  Plugin wird erst mit Schnittstellendokumentation und Testzugang gebaut – standardmäßig
  deaktiviert und nur im Echtbetrieb aktivierbar. Getestet werden reale Plugins nur gegen
  einen simulierten HTTP-Endpunkt (`httpx.MockTransport`).
- Die Alarmierung eines Fahrzeugs ordnet es dem Einsatz zu. „Wache“ in der AAO bedeutet
  Wachenalarm über deren RICs, nicht automatisch alle Fahrzeuge der Wache.
- Systemweite und Leitstellen-Schnittstellen erhalten jede Alarmierung der Leitstelle,
  Wachen-Schnittstellen nur Alarmierungen mit Beteiligung der Wache (Datensparsamkeit).
