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

### Geplant

| Phase | Ressourcen |
|---|---|
| 4 | `/keywords`, `/alarm-rules`, `/incidents/{id}/alarm-preview`, `/incidents/{id}/alarms` (mit Idempotency-Key), `/police-notices/{id}/acknowledge`, `/interfaces` (+ `/test`, `/events`), `/plugins` |
| 5 | `/incidents/{id}/proposal` (berechnen, mit Begründungen), `/proposal-settings` |
| 6 | `/vehicles/{id}/status`, `/talk-requests` (annehmen, zurückstellen, ablehnen), `/simulation/vehicles/{id}/move`, `/simulation/control` (Ausfall, Pause), `/routing/route` |
| 7 | `/training/scenarios`, `/training/sessions` (Start, Ende, Beobachtung), `/training/sessions/{id}/evaluation`, Audio-WebSocket `/training/sessions/{id}/audio` |

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
z. B. `vehicles`; zugestellt nur an Benutzer der betroffenen Leitstelle). `call.changed` (Aktion `ringing`, `answered`, `on_hold`, …), `incident.changed`. Geplant: `alarm.*`, `police_notice.created`,
`vehicle.status`, `vehicle.positions` (gebündelt je Takt), `talk_request.*`,
`interface.status`, `training.*`.

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

## 5. Plugin-System für Schnittstellen (Phase 4)

- Plugins sind Python-Pakete mit Entry-Point `ils_sim.plugins`. Das Kernsystem lädt sie beim
  Start, ein Umbau des Kerns ist nicht nötig.
- Jedes Plugin liefert **Metadaten** (`key`, Name, Version, `is_real`, unterstützte Scopes),
  ein **JSON-Schema seiner Konfiguration** (daraus erzeugt der Client das
  Administrationsformular), `test_connection()` und die Implementierung eines oder mehrerer
  Protokolle (z. B. `AlarmGateway`).
- **Geheimnisse** (API-Schlüssel) werden getrennt von der Konfiguration verschlüsselt
  gespeichert (`interfaces.secret_encrypted`, Fernet). Die API gibt sie nie im Klartext
  zurück, nur maskiert (`••••1234`).
- **Laufzeit:** Ein Supervisor je Schnittstelle übernimmt Statusüberwachung (`ok`,
  `degraded`, `error`), automatische Wiederverbindung mit Backoff und Ereignisprotokoll
  (`interface_events`). Statusänderungen gehen als Event an die Clients.
- **Sicherheitsregeln** (im Kern erzwungen, nicht im Plugin):
  1. Neue Schnittstellen sind **deaktiviert**.
  2. Plugins mit `is_real = true` lassen sich nur aktivieren, wenn der Benutzer
     `interfaces.activate_real` hat **und** das System im Betriebsmodus „Echtbetrieb“ läuft.
  3. Im Simulationsmodus leitet der Kern jeden Aufruf an ein reales Plugin auf das
     Simulations-Gateway um und protokolliert das, auch wenn die Schnittstelle aktiviert ist.
- **Beispiel-Plugins:** Simulations-Gateway (immer vorhanden); Zusatzalarmierung über eine
  externe Alarmierungs-API (z. B. Feuersoftware Connect); GPS-Feed; Kartendienst;
  Fahrzeugdatenbank-Import.
