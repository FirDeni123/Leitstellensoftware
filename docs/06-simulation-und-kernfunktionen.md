# 06 – Simulationskonzept und die drei Kernfunktionen

Dieses Dokument plant die drei zusätzlichen Kernfunktionen (Einsatzmittelvorschlag,
KI-Anrufsimulation, Navigation/GPS-Simulation) sowie Telefonie und Sprache. Der
**Einsatzmittelvorschlag ist seit 0.5.0 umgesetzt** (Abschnitt 3), **Navigation und
Bewegungssimulation seit 0.6.0** (Abschnitt 2, jeweils mit Umsetzungsstand); KI-Anrufsimulation
und Sprache folgen in Phase 7. Die Architektur aus Phase 1 (Event-Bus,
Unit of Work, Provider-Interfaces, Modul-Registry) ist darauf ausgelegt.

## 1. Simulationsgrundsätze

1. **Zentral:** Simulationszustände (Positionen, Status, simulierte Anrufe) entstehen nur im
   Simulationsdienst auf dem Server. Clients zeigen an, sie simulieren nicht selbst.
2. **Gleiche Wege:** Simulierte Ereignisse laufen durch dieselbe Service-Schicht wie
   Disponentenaktionen, mit Audit, Events und Rechteprüfung über einen technischen
   Simulationsbenutzer. Es gibt keine Abkürzungen an der Fachlogik vorbei.
3. **Gekennzeichnet:** Jede simulierte Quelle trägt `source = sim` bzw. `mode = sim`. Die
   Oberfläche zeigt Simulation sichtbar an (Banner, Marker „SIM“ an Positionen und
   Anrufen).
4. **Austauschbar:** Die Simulation implementiert dieselben Protokolle wie spätere echte
   Quellen (`PositionSource`, `TelephonyProvider`, `AlarmGateway`). Der Fachcode kennt den
   Unterschied nicht, die Konfiguration entscheidet.

## 2. Navigation und GPS-Simulation (Phase 6)

### Routing

- **OSRM** als eigener Container. Datengrundlage ist ein OSM-Extrakt der Region von
  Geofabrik (z. B. Schleswig-Holstein, rund 200 MB PBF), vorverarbeitet mit dem
  Autoprofil (MLD). Ein monatliches Update der Daten erfolgt per Skript.
- Benötigte Dienste: `route` (Geometrie, Distanz, Dauer, Schritte) und `table`
  (Fahrzeitmatrix vieler Fahrzeuge zu einem Einsatzort, für den Vorschlag).
- **Einsatzfahrten:** Das OSRM-Autoprofil kennt keine Sonderrechte. Deshalb gibt es einen
  konfigurierbaren Faktor je Fahrzeugtyp, Straßenklasse und Sonderrechtsfahrt (z. B. 1,15
  innerorts), angewendet auf die Teilstrecken. Optional kommt später ein eigenes
  OSRM-Profil hinzu.
- **Ausfall:** Ist OSRM nicht erreichbar, fällt das System auf Luftlinie × Umwegfaktor
  zurück. Das ist in der Oberfläche als „Schätzung“ gekennzeichnet, nie stillschweigend.

### Bewegungssimulation

```text
Disponent alarmiert → Fahrzeug Status 3 (Service)
   → Simulationsdienst: Route Wache→Einsatzort berechnen (OSRM)
   → vehicle_movements anlegen (Geometrie, Dauer, ETA)
   → Takt 1 s: Position = Interpolation entlang der Geometrie nach verstrichener Zeit
               (Geschwindigkeit je Teilstrecke aus OSRM-Annotationen × Fahrzeugfaktor
                × individuelle Simulationsgeschwindigkeit)
   → gebündeltes Event vehicle.positions (alle bewegten Fahrzeuge einer Leitstelle)
   → Ziel erreicht: Status 4 (Service), Einsatzverlauf „Ankunft“, Track speichern
```

- **Viele Fahrzeuge:** Die Interpolation ist reine Rechenarbeit (O(n) je Takt). 500
  Fahrzeuge im 1-Hz-Takt sind unkritisch. Positionen werden als ein Event je Leitstelle
  und Takt verteilt.
- **Lange Strecken:** Dauer und Geometrie stammen aus OSRM. Es gibt keine Begrenzung außer
  der Kartengrundlage.
- **Neustart-sicher:** Fahrten liegen in der Datenbank (`started_at` + Route). Nach einem
  Neustart des Dienstes wird die Position aus der Zeit rekonstruiert.
- **Steuerung** (Recht `simulation.control`): Fahrzeug manuell verschieben (Karte, Drag),
  Ausfall simulieren (Status 6, Fahrt abbrechen), Simulationsgeschwindigkeit,
  Pause/Fortsetzen je Übung.
- **Echte GPS-Daten später:** Ein Plugin implementiert `PositionSource` (z. B. für
  Fahrzeugortung über eine Flottenmanagement-API). Je Fahrzeug wird `position_source`
  festgelegt, und der Simulationsdienst bewegt nur Fahrzeuge mit `sim`.

### Umsetzungsstand (0.6.0)

- **Umgesetzt:** OSRM-Anbindung (`route` für Fahrten, `table` für den Vorschlag) mit
  gekennzeichnetem Rückfall auf die Luftlinie; Sonderrechtsfaktor (global je Leitstelle);
  Bewegung als Interpolation entlang der Route mit Zeitprofil je Teilstück; Simulationsuhr
  mit Pause und Zeitraffer; gebündeltes `vehicle.positions`-Ereignis je Leitstelle im
  1-Hz-Takt; neustartsicher (Position = Funktion aus Route und Simulationszeit); Leader-Lock;
  Ausrücken nach Alarmierung (Ausrückzeit), Ankunft S4 mit Einsatzverlauf, Rückfahrt S1→S2;
  Ausfall (S6), Verschieben; Karte (MapLibre) mit Wachen, Fahrzeugen, Einsätzen, Routen
  (Luftlinie gestrichelt) und Einsatzort per Klick.
- **Abweichungen:** Die Route wird erst bei Abfahrt berechnet (vom dann aktuellen Standort);
  der Sonderrechtsfaktor gilt einheitlich (noch nicht je Fahrzeugtyp/Straßenklasse); Fahrzeug-
  und Wachenmarker sind HTML-Marker (bei sehr vielen Fahrzeugen an einer Wache überlagern
  sich Beschriftungen – Bündelung folgt); zurückgelegte Strecken werden nicht gespeichert.
- **Messwerte (Testumgebung):** laufender Takt mit 50 fahrenden Fahrzeugen 42 ms;
  50 gleichzeitige Abfahrten in einem Takt ca. 1,1 s (Statuswechsel, Historie,
  Einsatzverlauf je Fahrzeug – einmalig, der Takt verzögert sich dann kurz).
- **Nicht in dieser Umgebung geprüft:** ein echter OSRM-Dienst (kein Docker) und die
  OSM-Kachelserver (kein Zugriff); die Kachelanzeige ist mit einem lokalen Testkachelserver
  unter der strengen CSP geprüft.

### Karte

- MapLibre GL JS im Client mit den Ebenen Wachen, Fahrzeuge (Statusfarbe, Funkrufname),
  Einsatzorte, geplante Route (gestrichelt), zurückgelegte Strecke, ETA-Anzeige,
  Koordinatenanzeige und Ortsauswahl per Klick.
- **Kartenansichten:** Straße, hell/dunkel, Satellit (nur mit lizenzierter Quelle).
- **Nutzungsbedingungen:** Die Standard-Kachelserver von OpenStreetMap
  (`tile.openstreetmap.org`) sind für geringe Last gedacht und verbieten intensive Nutzung
  durch Anwendungen. Deshalb gilt:
  1. Entwicklung: OSM-Standardkacheln mit Namensnennung „© OpenStreetMap-Mitwirkende“ und
     korrektem User-Agent.
  2. Betrieb: eigene Vektorkacheln (z. B. Protomaps-PMTiles-Extrakt der Region,
     ausgeliefert vom eigenen Server) oder ein kommerzieller Kachelanbieter.
  Die Kachelquelle ist in der Schnittstellenverwaltung konfigurierbar. Die CSP wird
  entsprechend gezielt erweitert.

## 3. Automatischer Einsatzmittelvorschlag (Phase 5)

**Grundsatz:** Der Vorschlag ist eine Entscheidungshilfe. Er löst **niemals** selbst eine
Alarmierung aus. Die Alarmierung ist ein separater API-Aufruf mit eigener Berechtigung
(`alarm.trigger`) und erfordert eine ausdrückliche Bestätigung im Client.

### Ablauf

1. **Bedarf ermitteln:** aus der AAO des Stichworts für die Leitstelle oder den Bereich,
   z. B. B2 = 2 × HLF, 1 × DLK, 1 × ELW, 1 × RTW. Dazu kommen Zusatzanforderungen des
   Einsatzes (z. B. „Menschenleben in Gefahr“ → zusätzlich RTW).
2. **Kandidaten filtern:** Fahrzeuge der passenden Typen/Fähigkeiten mit verfügbarem Status
   (laut `vehicle_status_definitions.counts_as_available`), verfügbar und nicht gebunden;
   Organisation alarmierbar.
3. **Fahrzeit:** Luftlinie als Vorfilter auf die 3 × n nächsten Kandidaten je Bedarf, dann
   die OSRM-`table`-Anfrage. Ergebnis ist die Fahrzeit in Sekunden ab der aktuellen
   Position bzw. Wache.
4. **Bewerten** (administrierbare Gewichte): Fahrzeit (dominant), Wachenzugehörigkeit laut
   AAO (Ausrückebereich), Status 2 vs. 1 (auf Wache: Ausrückezeit addieren), Typ exakt vs.
   Ersatztyp (z. B. LF statt HLF mit Malus), Vorrang eigener Organisation/Leitstelle.
5. **Zuteilen:** Je Bedarfsposition werden die bestbewerteten Fahrzeuge gewählt, ohne
   Doppelvergabe (Greedy nach Fahrzeit, danach Ausgleich).
6. **Begründen:** Jedes vorgeschlagene Fahrzeug trägt eine Liste lesbarer Gründe, z. B.
   „HLF 20 laut AAO B2 (Bedarf 2/2) · Status 2 auf Wache · Fahrzeit 6:40 min (OSRM) ·
   Ausrückebereich Wache Nord“. Nicht erfüllbare Bedarfe werden ausdrücklich gemeldet
   („DLK: kein Fahrzeug verfügbar – Nachbarleitstelle anfragen“).

### Bedienung

Die Vorschlagsliste erscheint im Einsatz mit Kontrollkästchen. Der Disponent kann alle
übernehmen, einzelne abwählen, manuell ergänzen (Suche) oder neu berechnen. Eine Übernahme
setzt nur die Zuordnung. Erst die anschließende Alarmierungsvorschau mit Bestätigung
alarmiert. Der Vorschlag wird mit Eingaben und Ergebnis gespeichert (`proposals`).

**Erweiterbarkeit:** Bewertungskriterien sind `ProposalStrategy`-Komponenten. Neue
Kriterien (z. B. Besatzungsstärke, Sonderfähigkeiten) kommen hinzu, ohne den Ablauf zu
ändern.

### Umsetzungsstand (0.5.0)

- **Umgesetzt wie oben:** Bedarf aus AAO (Stufen ≤ gewählte Stufe) plus Zusatzbedarf;
  Fahrzeuge im Einsatz decken zuerst (passender Typ vor Ersatztyp); Kandidatenfilter
  (verfügbar, Status zählt als frei, ungebunden, alarmierbare Organisation, aktive Wache);
  Vorfilter nach Luftlinie (n × Bedarf); Fahrzeit über OSRM `table` (falls `ILS_OSRM_URL`
  gesetzt und je Leitstelle aktiviert) mit gekennzeichnetem Rückfall auf die Schätzung;
  Bewertung in Sekunden („gewichtete Fahrzeit“); Greedy-Zuteilung mit Ausgleichsschritt;
  lesbare Begründungen, Alternativen, Fehlbedarf mit Hinweis auf verknüpfte
  Nachbarleitstellen und deren freie Fahrzeuge; Speicherung in `proposals`; Übernahme ordnet
  nur zu.
- **Vereinfachungen:** Ein globaler Sonderrechtsfaktor (statt je Fahrzeugtyp und
  Straßenklasse); Ausrückzeit einheitlich je Leitstelle (noch nicht je Wache, z. B.
  Freiwillige Feuerwehr); „Ausrückebereich“ = Wachen-Einträge der AAO; Kriterien sind
  Funktionen der Engine (`app/proposal/engine.py`), noch keine austauschbaren
  `ProposalStrategy`-Komponenten.
- **Nicht in dieser Umgebung getestet:** ein echter OSRM-Dienst (die Anbindung ist gegen
  einen simulierten Endpunkt getestet; der OSRM-Container folgt mit Phase 6).
- **Messwert M5:** 22 Vorschläge auf den Demo-Daten: 23–418 ms, im Mittel 93 ms
  (Entwicklungsumgebung, Schätzung ohne OSRM). Mit 300 zusätzlichen Fahrzeugen bleibt die
  Berechnung unter 1 s (automatischer Test).

## 4. KI-gestützte Anrufsimulation (Phase 7)

**Nur für Training.** Der KI-Anrufer hat technisch keinen Zugang zu echter Telefonie (siehe
[05-sicherheit.md](05-sicherheit.md)).

### Sprachpipeline

```text
Mikrofon (Client, getUserMedia, Echo-/Rauschunterdrückung)
  → Audio-WebSocket (Opus/PCM 16 kHz) → Server
  → VAD (Sprechpausen erkennen, Unterbrechungen/„barge-in“)
  → STT: faster-whisper (Deutsch, lokal; GPU optional)
  → CallerAgent (Claude, Streaming) mit Szenario-Zustand
  → TTS: Piper (deutsche Stimmen, lokal), satzweise gestreamt
  → Audio-WebSocket → Lautsprecher (Client)
```

Ziel-Latenz vom Satzende bis zum Beginn der Antwort: unter 2,5 s. Das wird erreicht durch
Streaming in allen Stufen, kurze Anruferantworten (1–2 Sätze, wie echte Anrufer) und
satzweise TTS.

### Dynamischer Anrufer

- **Szenario = Wahrheit:** Ein Szenario enthält strukturierte Fakten (Ort, Lage, Verletzte,
  Gefahren, Rückrufnummer …), die Persona (Name, Alter, Stimme, Emotion: aufgeregt,
  verwirrt, ruhig; Sprachstil, Ortskenntnis) und Verhaltensregeln (welche Fakten nur auf
  Nachfrage, welche gar nicht bekannt sind).
- **Zufallsgenerator:** Er erzeugt Einsatzorte aus realen Adressen der Region (OSM) und
  variiert Details nach Schwierigkeitsgrad.
- **Gesprächsführung durch das Modell:** Der Systemprompt enthält Persona und Fakten. Die
  KI soll nur preisgeben, was gefragt wird, und keine Fakten erfinden, die dem Szenario
  widersprechen. Die Antworten werden gestreamt. Ein **Zustandsobjekt** hält fest, welche
  Fakten bereits genannt wurden; das ist zugleich die Grundlage der Auswertung.
- **Modell:** Claude über das Anthropic Python SDK, Standard `claude-opus-5-5` mit
  niedrigem Effort für kurze Antwortzeiten. Das Modell ist in der
  Schnittstellenverwaltung konfigurierbar (ein schnelleres oder günstigeres Modell kann die
  Administration wählen). Ein serverseitiger Fallback bei Ablehnungen ist aktiviert. Die
  KI-Anbindung ist ein `CallerAgent`-Provider und damit austauschbar.
- **Ohne Sprache:** Ein Textmodus (Chat) dient zum Testen und für Arbeitsplätze ohne
  Headset.

### Verbindung zur Einsatzbearbeitung

Während des Trainingsanrufs arbeitet der Disponent im normalen Notrufannahme-Panel. Der
Anruf ist ein `emergency_call` mit `source = training`. Einsatz anlegen, Stichwort wählen,
Ort erfassen, Notizen, Anruf beenden und Übergabe an die Disposition nutzen exakt die
regulären Funktionen.

### Auswertung

Nach dem Gespräch vergleicht die Auswertung:

| Kriterium | Methode |
|---|---|
| Pflichtfragen gestellt (Wo? Was? Wie viele Verletzte? Rückrufnummer? …) | Szenario-Checkliste ↔ Gesprächsverlauf (KI-Klassifikation, strukturierte Ausgabe) |
| Einsatzort korrekt | Erfasste Koordinate ↔ Szenario-Ort (Distanz, Adressabgleich) |
| Stichwort korrekt | Gewähltes ↔ erwartetes Stichwort (inkl. zulässiger Alternativen) |
| Alarmierung veranlasst | Alarmierung/Übergabe im Einsatz vorhanden |
| Gesprächsdauer, Zeit bis zur Einsatzanlage | Zeitstempel |
| Übersehene Informationen | Fakten, die der Anrufer kannte, nach denen aber nicht gefragt wurde |

Daraus entsteht ein Trainingsbericht (Punkte, Erläuterungen, Verlauf). Er kann für den
Ausbilder exportiert werden.

### Ausbildermodus

Recht `training.instructor`. Der Ausbilder kann Szenarien auswählen oder erstellen
(Formular + Faktenliste), den Schwierigkeitsgrad festlegen, Teilnehmer zuweisen, das
Gespräch live mitverfolgen (Transkript per Echtzeit-Event), Ereignisse einspielen (z. B.
„Anrufer wird panisch“), die Auswertung ergänzen und Berichte erstellen.

## 5. Telefonie (Phase 3 Simulation, Phase 7 Sprache, später VoIP)

| Provider | Zweck | Umsetzung |
|---|---|---|
| `SimulatedTelephony` | Simulierte Notrufe (Text/Daten, später Audio über den Server) | Phase 3 (ohne Audio), Phase 7 (Audio) |
| `SipTelephony` | Echte VoIP-Anrufe von einer Asterisk-Telefonanlage | Später. Asterisk mit PJSIP + WebRTC, Client per SIP.js über WSS; Anrufsteuerung über Asterisk ARI. `is_real = true` → nur im Echtbetrieb aktivierbar |

Beide liefern dieselben `CallEvent`s an die Notrufannahme. **Nicht vorgesehen:** Anbindung
an echte Notrufleitungen (112) oder an den BOS-Digitalfunk. Sprechwünsche und Funkgespräche
werden ausschließlich simuliert (Statusmeldung über die Simulation, Sprachausgabe über TTS).
