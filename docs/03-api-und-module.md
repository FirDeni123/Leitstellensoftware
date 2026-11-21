# 03 – API-Konzept und Modulschnittstellen

## 1. REST-Konventionen

- Basis: `https://<server>/api/v1`. Die interaktive OpenAPI-Doku liegt unter `/docs`
  (nur außerhalb der Produktion).
- JSON, UTF-8. IDs als UUID. Zeitstempel ISO 8601 in UTC.
- Authentifizierung: `Authorization: Bearer <access_token>` (Gültigkeit 15 min).
- **Fehlerformat** (alle Endpunkte):
  ```json
  {"error": {"code": "conflict", "message": "Der Benutzer wurde zwischenzeitlich …",
             "details": {"current_version": 4}, "request_id": "5f0c…"}}
  ```
  `code` ist stabil und maschinenlesbar, `message` ist deutscher UI-Text. Die `request_id`
  steht auch im Serverlog und im Antwortheader `X-Request-ID`.
- **Statuscodes:** 401 nicht angemeldet / Token abgelaufen (`details.reason`), 403 fehlende
  Berechtigung (`details.missing_permissions`), 404, 409 Konflikt (Version oder
  Eindeutigkeit), 422 Validierung, 423 Konto gesperrt.
- **Optimistic Locking:** `PATCH`/`PUT` auf versionierte Ressourcen erfordern
  `expected_version`.
- **Listen:** `limit`/`offset` mit `total` für Stammdaten; Keyset-Paginierung
  (`before_id`, `next_before_id`) für Protokolle.
- **Idempotenz** (ab Phase 4): kritische Aktionen (Alarmierung) mit Header
  `Idempotency-Key`.

## 2. Endpunkte

### Umgesetzt (Phase 1)

| Methode | Pfad | Berechtigung | Zweck |
|---|---|---|---|
| GET | `/health` | – | Liveness/Readiness (DB, Redis) |
| POST | `/auth/login` | – | Anmeldung → Access- und Refresh-Token |
| POST | `/auth/refresh` | – | Token-Rotation (Wiederverwendung → Sitzung gesperrt) |
| POST | `/auth/logout` | angemeldet | Sitzung beenden |
| GET | `/auth/me` | angemeldet | Profil, Rollen, effektive Rechte, Leitstellen |
| POST | `/auth/change-password` | angemeldet | Eigenes Passwort ändern (beendet andere Sitzungen) |
| GET | `/users` · `/users/{id}` | `users.read` | Benutzer (Suche, Filter) |
| POST | `/users` | `users.write` | Anlegen (Initialpasswort optional generiert) |
| PATCH | `/users/{id}` | `users.write` (+ `roles.write` für Rollen/Rechte) | Bearbeiten |
| PUT | `/users/{id}/active` | `users.write` | Aktivieren/Deaktivieren |
| POST | `/users/{id}/reset-password` · `/unlock` | `users.write` | Passwort zurücksetzen, Sperre aufheben |
| GET | `/login-events` | `login_log.read` | Anmeldeprotokoll |
| GET | `/permissions` · `/roles` | `users.read` | Katalog, Rollen |
| POST/PATCH/DELETE | `/roles…` | `roles.write` | Rollen verwalten |
| GET/POST/PATCH/DELETE | `/control-centers…` | `control_centers.read/write` (Löschen: + `system.admin`) | Leitstellen |
| GET | `/system/info` | angemeldet | Version, Betriebsmodus, Modulstatus |
| GET/PUT | `/system/operation-mode` | PUT: `system.mode.change` | Simulation ↔ Echtbetrieb (Bestätigung „ECHTBETRIEB“) |
| GET | `/audit` | `audit.read` | Änderungsprotokoll |
| GET/PUT/DELETE | `/me/layouts/{workstation}` | angemeldet | Fensterlayout |
| WS | `/ws` | Token in erster Nachricht | Echtzeit |

### Umgesetzt (Phase 2)

Alle Stammdaten-Endpunkte haben dieselbe Form: `GET` Liste (`control_center_id`, `q`, Filter),
`GET /{id}`, `POST`, `PATCH /{id}` (mit `expected_version`), `DELETE /{id}`. Lesen erfordert
`master_data.read` (Bereiche: `control_centers.read`), Schreiben die jeweilige Fachberechtigung.

| Pfad | Schreibrecht | Hinweise |
|---|---|---|
| `/organizations` | `organizations.write` | global; Polizei nie alarmierbar (422) |
| `/vehicle-types` | `organizations.write` | global; Filter `category` |
| `/vehicle-status-definitions` | `vehicles.write` | nur Lesen/Ändern (Codes 0–9 fest) |
| `/stations` | `stations.write` | `ric_ids`, Verfügbarkeit (immer / Zeitplan / nicht verfügbar) |
| `/vehicles` | `vehicles.write` | Filter `station_id`, `vehicle_type_id`, `organization_id`, `radio_group_id`; `position` abgeleitet |
| `/rics` | `rics.write` | `station_ids`, `vehicle_ids` |
| `/alarm-groups` | `rics.write` | `ric_ids` |
| `/radio-groups` | `radio_groups.write` | `station_ids`, `organization_ids`; Fahrzeuge lesend |
| `/control-center-areas` | `control_centers.write` | GeoJSON (Polygon/MultiPolygon) und/oder Gemeindeschlüssel |
| `/control-center-links` | `control_centers.write` | GET/POST/DELETE; Art: Nachbar, Rückfallebene, Kooperation |
| `GET /responsibility?latitude&longitude` | – | zuständige Leitstelle(n) nach Priorität |
| `/imports` | `data.import` + `vehicles.write`/`stations.write` | `POST` (multipart: `file`, `kind`, `control_center_id`), `PUT /{id}/mapping`, `POST /{id}/commit` (`skip_invalid`), `DELETE /{id}` |

### Umgesetzt (Phase 3)

| Methode | Pfad | Berechtigung | Zweck |
|---|---|---|---|
| GET/POST/PATCH/DELETE | `/keywords…` | lesen `master_data.read`, schreiben `keywords.write` | Stichwortkatalog |
| GET | `/calls` (`control_center_id`, `include_ended`) | `calls.handle` | Warteschlange nach Priorität und Eingang |
| POST | `/calls` | `calls.handle` | Anruf manuell erfassen (direkt angenommen) |
| PATCH | `/calls/{id}` | `calls.handle` (nur bearbeitende Person) | Anruferdaten, Einsatzort, Einsatzgrund, Priorität |
| POST | `/calls/{id}/answer` · `/hold` · `/resume` · `/end` | `calls.handle` | Lebenszyklus; Annahme genau einmal (409 mit Name); neues Gespräch hält das bisherige |
| POST | `/calls/{id}/notes` | `calls.handle` | Gesprächsnotiz oder Rückfrage (`kind=question`) |
| POST | `/calls/{id}/link` | `calls.handle` + `incidents.write` | Notruf einem bestehenden Einsatz zuordnen |
| GET | `/incidents` (`scope=open|closed|all`, `q`) · `/incidents/{id}` | `incidents.read` | Einsatzliste, Einsatzdetail (Fahrzeuge, Wachen, Notrufe) |
| POST | `/incidents` (optional `call_id`) | `incidents.write` | Einsatz anlegen, aus Notruf mit Datenübernahme |
| PATCH | `/incidents/{id}` | `incidents.write` | Einsatzdaten (Optimistic Locking, Verlaufseintrag mit Feldänderungen) |
| POST | `/incidents/{id}/status` | `incidents.write`; Abschließen/Wiedereröffnen `incidents.close` | Statusmodell mit Abschlussregeln |
| POST/DELETE | `/incidents/{id}/vehicles…` | `incidents.write` | Fahrzeuge zuordnen (`reassign` = umsetzen) / freigeben |
| GET/POST | `/incidents/{id}/events` · `/notes` | `incidents.read` / `incidents.write` | Einsatzverlauf, Dokumentation |
| GET | `/incidents/active-assignments` | `incidents.read` | aktuell gebundene Fahrzeuge |
| GET/POST | `/simulation/call-scenarios` · `/simulation/calls` | `simulation.control` | simulierte Notrufe (im Echtbetrieb gesperrt) |

### Phase 4 – Alarmierung (umgesetzt)

| Methode | Pfad | Recht | Zweck |
|---|---|---|---|
| GET/POST/PATCH/DELETE | `/alarm-rules` | lesen `master_data.read`, ändern `alarm_rules.write` | AAO je Leitstelle/Stichwort/Bereich, Zeilen werden beim PATCH vollständig ersetzt |
| POST | `/incidents/{id}/alarm-preview` | `incidents.read` | Vorschau aus AAO (`stage`, optional `selection`) – **löst nichts aus** |
| POST | `/incidents/{id}/alarms` | `alarm.trigger` | Alarmierung; Pflicht: `confirmed: true` und Header `Idempotency-Key` (8–80 Zeichen). Wiederholung mit gleichem Schlüssel → bestehende Alarmierung (HTTP 200), mit anderem Inhalt → 409 |
| GET | `/incidents/{id}/alarms` · `/alarms` · `/alarms/{id}` | `incidents.read` | Alarmierungsprotokoll mit Zustellstatus je Ziel |
| GET | `/police-notices` | `incidents.read` | offene (oder alle) Polizei-Hinweise |
| POST | `/police-notices/{id}/acknowledge` | `incidents.write` | Hinweis zur Kenntnis nehmen (mit Vermerk) – keine Übermittlung |
| GET | `/plugins` | `interfaces.read` | installierte Plugins mit JSON-Schema der Konfiguration |
| GET/POST/PATCH/DELETE | `/interfaces` | lesen `interfaces.read`, ändern `interfaces.write` | Schnittstellen; systemweite nur durch Administratoren |
| POST | `/interfaces/{id}/enabled` | `interfaces.write`; reale zusätzlich `interfaces.activate_real` + Echtbetrieb + Begründung | aktivieren/deaktivieren |
| POST | `/interfaces/{id}/test` | wie oben | Verbindungstest (reale nur im Echtbetrieb) |
| GET | `/interfaces/{id}/events` | `interfaces.read` | Ereignisprotokoll |

**Ablauf einer Alarmierung:** Vorschau → Disponent prüft/ändert → Bestätigung → Server
sperrt den Einsatz, prüft Idempotenz, ordnet neue Fahrzeuge zu, setzt `alarmed_at` und den
Status „Alarmiert“, schreibt Alarmierung, Ziele, Einsatzverlauf, ggf. Polizei-Hinweis und
Audit **in einer Transaktion**. Erst danach stellt ein Hintergrundauftrag an die
Schnittstellen zu (ohne offene Transaktion während Netzwerkzugriffen) und ergänzt das
Ergebnis im Einsatzverlauf. Nach einem Serverneustart unterbrochene Zustellungen werden als
fehlgeschlagen markiert und **nicht** automatisch wiederholt.

**Vorschlagslogik (bis Phase 5):** Stufen ≤ gewählter Stufe; bereits im Einsatz befindliche
Fahrzeuge decken den Bedarf zuerst; freie Fahrzeuge (verfügbar, Status zählt als frei, in
keinem Einsatz, alarmierbare Organisation) nach Luftlinie. RICs: eigene RICs des Fahrzeugs,
sonst die der Wache; dazu RICs von Wachen, RIC- und Gruppen-Einträgen. Schnittstellen:
systemweite und Leitstellen-Schnittstellen bei jeder Alarmierung, Wachen-Schnittstellen bei
Beteiligung der Wache (erhalten nur die eigenen Fahrzeuge), dazu AAO-Einträge.

### Phase 5 – Einsatzmittelvorschlag (umgesetzt)

| Methode | Pfad | Recht | Zweck |
|---|---|---|---|
| POST | `/incidents/{id}/proposal` | `incidents.write` | Vorschlag berechnen und speichern (`stage`, `extra` = Zusatzbedarf). **Ordnet nicht zu, alarmiert nicht** |
| GET | `/incidents/{id}/proposals` · `/proposals/{id}` | `incidents.read` | gespeicherte Vorschläge |
| POST | `/proposals/{id}/accept` | `incidents.write` | übernehmen = Fahrzeuge zuordnen (`vehicle_ids`, optional `reassign`); Einsatzverlauf nennt Übernommenes, Abgewähltes, gewählte Alternativen und manuelle Ergänzungen. Keine Alarmierung |
| GET/PUT | `/proposal-settings?control_center_id=` | lesen `master_data.read`, ändern `proposal_settings.write` | Regeln je Leitstelle, Optimistic Locking (`expected_version`, leer beim ersten Speichern) |

Die Alarmierungsvorschau (`/incidents/{id}/alarm-preview`) verwendet dieselbe Engine, damit
Vorschlag und Alarmierungsdialog identische Fahrzeuge und Begründungen zeigen.

### Phase 6 – Fahrzeuge, Karte, Simulation (umgesetzt)

| Methode | Pfad | Recht | Zweck |
|---|---|---|---|
| GET | `/fleet?control_center_id=` | `incidents.read` | alle Fahrzeuge mit Status, Position (Wache/vor Ort/fahrend mit ETA), Einsatz, Sprechwunsch, geplanter Abfahrt |
| POST | `/vehicles/{id}/status` | `vehicles.status.set` | FMS-Status setzen; 0/5 erzeugen einen Sprechwunsch. `simulate: true` (zusätzlich `simulation.control`, nur Simulationsbetrieb) = Statusmeldung des Fahrzeugs simulieren |
| GET | `/vehicles/{id}/status-history` | `incidents.read` | unveränderbare Statushistorie |
| GET/POST | `/talk-requests` · `/talk-requests/{id}/{accept,defer,reject,done}` | `radio.handle` | Sprechwünsche (Priorität 0 zuerst) |
| GET | `/movements?control_center_id=` | `incidents.read` | geplante/laufende Fahrten mit Route |
| GET | `/map/config` | angemeldet | Kachelquelle, Quellenangabe, Startausschnitt, Routing vorhanden |
| GET/PUT | `/simulation/clock` | lesen `incidents.read`, ändern `simulation.control` (nur Simulationsbetrieb) | Pause, Zeitfaktor 0,5×–30× |
| POST | `/simulation/vehicles/{id}/position` · `/breakdown` | `simulation.control` | Fahrzeug verschieben, Ausfall simulieren (Status 6) |

**Statusfolgen:** 3 → `s3_at`, Einsatz „Anfahrt“; 4 → `s4_at`, „Am Einsatzort“, Eintrag
„Ankunft“; 1/2 in einem Einsatz → Fahrzeug meldet frei und wird freigegeben; 6 → aus dem
Einsatz gelöst (Warnung im Verlauf). Im Simulationsbetrieb folgt das simulierte Fahrzeug
diesen Eingaben (3 = sofort losfahren, 4 = sofort am Ziel, 2 = auf die Wache, 1 = Rückfahrt).

**Simulationsdienst:** Nach der Alarmierung rücken Fahrzeuge nach der Ausrückzeit aus
(Status 2: Ausrückzeit aus den Vorschlagsregeln, Status 1: 15 s), fahren mit
Sonderrechten zum Einsatzort (Route aus OSRM, sonst gekennzeichnete Luftlinie), melden
Status 3 bei Abfahrt und 4 bei Ankunft. Nach dem Freigeben: Status 1, Rückfahrt ohne
Sonderrechte, Status 2 auf der Wache. Ein Prozess simuliert (PostgreSQL-Advisory-Lock),
Takt 1 s (`ILS_SIMULATION_TICK_SECONDS`), im Echtbetrieb keine Simulation.

### Phase 7 – Ausbildung und KI-Anrufer (umgesetzt)

| Methode und Pfad | Recht | Zweck |
|---|---|---|
| `GET/POST /training/scenarios`, `GET/PATCH /training/scenarios/{id}` | lesen: `training.participate` (ohne Lösung), sonst `training.instructor` | Szenarien |
| `GET /training/trainees?control_center_id=` | `training.instructor` | Übende Personen einer Leitstelle |
| `GET/POST /training/sessions` | `training.participate` (für andere: Ausbilder) | Übungen auflisten/starten – der Trainings-Notruf klingelt; nur Simulationsbetrieb |
| `GET /training/sessions/{id}` | Teilnehmer selbst oder Ausbilder | Verlauf, Auswertung; Regie und Lösung nur für Ausbilder (Lösung für Teilnehmer nach dem Ende) |
| `POST /training/sessions/{id}/messages` | nur die übende Person | Beitrag des Disponenten (202); die Antwort kommt per Echtzeit-Ereignis |
| `POST /training/sessions/{id}/speech` | nur die übende Person | Sprachaufnahme erkennen und senden (501 ohne faster-whisper) |
| `POST /training/sessions/{id}/instructions` | `training.instructor` | verdeckte Regieanweisung (`immediate` = Anrufer reagiert sofort) |
| `POST /training/sessions/{id}/notes` | `training.instructor` | Beobachtungsnotiz |
| `POST /training/sessions/{id}/end` | Teilnehmer oder Ausbilder | Auflegen (beendet den Trainings-Notruf) |
| `POST /training/sessions/{id}/evaluate` | Ausbilder (Teilnehmer nur, solange keine Auswertung existiert) | (Neu-)Auswertung |
| `GET/PUT /training/ai-settings`, `POST /training/ai-settings/test` | `system.admin` | KI ein/aus, Modell, Aufwand, Schlüssel (nie ausgegeben), Verbindungstest |

Annahme und Ende des Trainings-Notrufs laufen über die normalen `/calls/{id}/answer|end`;
in `GET /calls` erscheint ein Trainings-Notruf nur für die übende Person.
Echtzeit-Ereignisse: `training.session_changed`, `training.message`,
`training.caller_chunk` (Satz für Satz, `retract` bei verworfener Antwort),
`training.pending_changed` (nur Ausbilder), `training.scenario_changed`,
`training.ai_settings_changed`. Ereignisse gehen nur an die übende Person
(`user:<id>`) und an Ausbilder der Leitstelle – Regie nie an die übende Person.

## 3. WebSocket-Protokoll

```text
Client → {"type":"auth","token":"…"}                (erste Nachricht, innerhalb 5 s;
                                                      vor Ablauf erneut senden)
Server → {"type":"welcome","connection_id","user_id","server_time","channels"}
Server → {"type":"event","id","topic","ts","data"}
Client → {"type":"ping","ts":<ms>}  Server → {"type":"pong","ts","server_time"}
Server → {"type":"reauth_ok","expires_at"}
Server → {"type":"error","code","message"}
```

Schließcodes: `4001` Authentifizierung fehlgeschlagen/abgelaufen · `4002` Rechte geändert
(sofort neu verbinden) · `4003` Sitzung beendet · `4008` Überlast.

**Event-Themen** (`topic`), umgesetzt: `user.created`, `user.updated`, `me.changed`,
`role.changed`, `control_center.changed`, `audit.created`, `system.mode_changed`,
`layout.changed`, `master_data.changed` (`data.collection` nennt die betroffene Sammlung,
z. B. `vehicles`; zugestellt nur an Benutzer der betroffenen Leitstelle). `call.changed` (Aktion `ringing`, `answered`, `on_hold`, …), `incident.changed`, `alarm.changed`,
`police_notice.changed` (`for_user` = auslösender Disponent, bei ihm erscheint das Popup),
`interface.changed`, `vehicle.status_changed`, `movement.changed`, `talk_request.changed`,
`simulation.clock_changed` und `vehicle.positions` (ein Ereignis je Leitstelle und Takt mit
allen fahrenden Fahrzeugen: Position, Richtung, ETA). Der Client bündelt Invalidierungen je
Abfrage (kein Abbruch laufender Abfragen, höchstens ein Nachladen). Geplant: `training.*`.

Events enthalten nur IDs und Kerndaten. Der Client invalidiert damit seinen Cache und lädt
gezielt nach (`client/src/renderer/src/api/queries.ts`, `TOPIC_INVALIDATIONS`). Ausnahme
sind hochfrequente Fahrzeugpositionen: Sie werden vollständig im Event übertragen.

## 4. Interne Modulschnittstellen (Server)

Fachmodule hängen nur von Protokollen (`typing.Protocol`) ab, nicht von konkreten
Implementierungen. Echte und simulierte Implementierungen sind getrennte Klassen. Welche
aktiv ist, entscheidet die Konfiguration, nicht der Fachcode.

```python
class RoutingProvider(Protocol):          # OSRM, Valhalla, Luftlinie (Fallback, gekennzeichnet)
    async def route(self, start: LatLon, end: LatLon, profile: str) -> Route: ...
    async def table(self, sources: list[LatLon], targets: list[LatLon]) -> DurationMatrix: ...

class PositionSource(Protocol):           # SimulatedPositions (Simulationsdienst) | GpsFeed (Plugin)
    kind: Literal["simulation", "real"]
    async def stream(self) -> AsyncIterator[PositionUpdate]: ...

class AlarmGateway(Protocol):             # SimulatedAlarmGateway | Plugins (z. B. Zusatzalarmierungs-API)
    key: str
    is_real: bool
    async def send(self, alarm: AlarmMessage) -> DeliveryResult: ...

class TelephonyProvider(Protocol):        # SimulatedTelephony | SipTelephony (Asterisk ARI)
    is_real: bool
    async def calls(self) -> AsyncIterator[CallEvent]: ...
    async def answer(self, call_id: str, endpoint: AudioEndpoint) -> None: ...

class SpeechToText(Protocol):  async def transcribe(self, audio: AudioChunk) -> Transcript: ...
class TextToSpeech(Protocol):  async def synthesize(self, text: str, voice: Voice) -> AsyncIterator[AudioChunk]: ...
class CallerAgent(Protocol):   async def reply(self, state: ConversationState, utterance: str) -> AsyncIterator[str]: ...
class ProposalStrategy(Protocol):  def score(self, ctx: ProposalContext, vehicle: Candidate) -> ScoredCandidate: ...
```

## 5. Plugin-System für Schnittstellen (umgesetzt in Phase 4)

- **Vertrag** (`server/app/plugins/base.py`): `PluginMeta` (`key`, Name, Beschreibung,
  `is_real`, Scopes, JSON-Schema der Konfiguration, Bezeichnung des Schlüssels) sowie
  `test(config, secret)` und `send_alarm(config, secret, message)` → `DeliveryResult`.
  Die Nachricht (`AlarmMessage`) enthält Einsatznummer, Stichwort, Ort, Koordinaten,
  Fahrzeuge, Wachen, RICs und den Betriebsmodus.
- **Registrierung:** eingebaute Plugins plus Python-Pakete mit Entry-Point
  `ils_sim.plugins` (beim Start geladen; ein defektes Fremd-Plugin stoppt den Server nicht).
- **Eingebaut:** `simulation_receiver` (Simulations-Empfänger, `is_real = false`),
  `webhook` (HTTPS-POST mit JSON und optionalem Token, `is_real = true`) und
  `feuersoftware_connect` (Feuersoftware Connect, öffentliche Schnittstelle, `is_real = true`,
  siehe unten).
- **Konfiguration:** wird gegen das JSON-Schema des Plugins geprüft (`jsonschema`); der
  Client erzeugt daraus das Formular. **Geheimnisse** werden getrennt und verschlüsselt
  gespeichert (Fernet, Schlüssel außerhalb der Datenbank), die API liefert nur `••••1234`.
- **Sicherheitsregeln (im Kern erzwungen, nie im Plugin):**
  1. Neue Schnittstellen sind **deaktiviert**.
  2. Reale Plugins: Aktivieren und Testen nur im **Echtbetrieb**, mit
     `interfaces.activate_real` und Begründung (Audit). Ändern einer aktiven realen
     Schnittstelle erfordert ebenfalls `interfaces.activate_real`.
  3. Beim Wechsel in den Simulationsbetrieb werden alle realen Schnittstellen automatisch
     deaktiviert.
  4. Unmittelbar vor jedem Plugin-Aufruf prüft der Kern erneut den Betriebsmodus: im
     Simulationsbetrieb wird ein reales Plugin **nie** aufgerufen, sondern die Zustellung
     umgeleitet und protokolliert (Test: `test_m4_real_plugin_is_never_called_in_simulation_mode`).
  5. Zeitlimit je Versuch, drei Versuche mit Wartezeit, Status `ok`/`error` und
     Ereignisprotokoll je Schnittstelle; Plugin-Fehler brechen nie die Alarmierung ab.
     Meldet ein Plugin einen dauerhaften Fehler (`retryable = false`, z. B. ungültiger
     Schlüssel), wiederholt der Kern nicht.
- **Feuersoftware Connect** (`app/plugins/builtin/feuersoftware.py`): je bestätigter
  Alarmierung `POST https://connectapi.feuersoftware.com/interfaces/public/operation` mit
  `Authorization: Bearer <API-Token des Standorts>` und `updateStrategy=ByNumber` (Einsatznummer
  der Leitstelle; Nachalarmierungen und Wiederholungen aktualisieren denselben Einsatz).
  Felder: `Start` (Ortszeit mit Versatz), `Status` (New/Update), `Priority` (1→High, 2→Medium,
  3→Low), `AlarmEnabled` (einstellbar – aus = Einsatz ohne Alarm an die Handys), `Keyword`,
  `Number`, `Address` (Straße, Hausnummer, PLZ, Ort aus der Einsatzadresse), `Position`,
  `Facts` (Beschreibung, Ortshinweis), `Source`, `Properties` (alarmierte Fahrzeuge, Wachen,
  RICs, Stufe); `Ric` nur, wenn konfiguriert (Connect erlaubt höchstens 5 Zeichen). Test der
  Verbindung: nur lesend (`GET …/operation?onlyLatest=true`). Grundlage: offizielle Doku
  „Öffentliche Connect API“ (docsv2.feuersoftware.com, gelesen 21.11.2026); die Feldnamen in
  `Position`/`Properties` stehen dort nicht ausgeführt und folgen Community-Clients. **Gegen
  den echten Dienst nicht getestet** – nur gegen einen simulierten Endpunkt.
- **Nicht umgesetzt:** Funkalarmierung (POCSAG/TETRA), GPS-Feed, Fahrzeugstatus an
  Feuersoftware (`POST /vehicle/{radioId}/status` wäre möglich).

