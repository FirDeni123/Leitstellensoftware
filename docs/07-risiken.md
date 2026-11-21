# 07 – Technische Risiken und Abhängigkeiten

| # | Risiko | Auswirkung | Maßnahme |
|---|---|---|---|
| R1 | **Latenz der Sprach-KI** (STT + LLM + TTS) | Unnatürliche Gesprächspausen im Training | Streaming in allen Stufen, kurze Antworten, lokale STT/TTS, satzweise Ausgabe. Früh einen Prototyp mit Latenzmessung bauen (Beginn Phase 7). Textmodus als Rückfallebene |
| R2 | **Unvorhersehbares KI-Verhalten** (erfindet Fakten, fällt aus der Rolle) | Fehlerhafte Trainingssituation, unfaire Auswertung | Strukturierte Szenariofakten als Wahrheit, Zustandsobjekt, Auswertung gegen Fakten statt gegen KI-Text, Ausbilder kann eingreifen, Testsatz mit Beispielgesprächen |
| R3 | **KI-Kosten / externe Abhängigkeit** | Laufende Kosten, Ausfall des Dienstes | Modell konfigurierbar, Kostenanzeige je Training, Provider-Interface für Alternativen |
| R4 | **OSM-Kachelnutzung** | Sperrung bei Überlast, Verstoß gegen Nutzungsbedingungen | Eigene Kacheln für den Betrieb (PMTiles), OSM-Server nur in der Entwicklung, Namensnennung |
| R5 | **OSRM-Ressourcen und -Aktualität** | Speicher/CPU (Vorverarbeitung eines Bundeslandes: einige GB RAM), veraltete Straßen | Regionaler Extrakt, Vorverarbeitung einmalig/monatlich, Fallback Luftlinie (gekennzeichnet) |
| R6 | **Fahrzeugdaten aus OSM unzuverlässig** | Falsche Bestände | OSM nur für Standorte, Fahrzeuge aus Excel/manuell, Import mit Prüfung und Bestätigung |
| R7 | **Audio in Electron** (Geräteauswahl, Echo, Headsets) | Schlechte Spracherkennung | WebRTC-Audioverarbeitung (AEC/NS/AGC), Geräteauswahl im Client, Pegelanzeige, Test mit gängigen Headsets |
| R8 | **Echte Telefonie/Funk** – rechtliche und organisatorische Grenzen | Unzulässige Anbindung | Kein 112, kein BOS-Funk. VoIP nur über eigene Telefonanlage mit Testanschlüssen; reale Provider nur im Echtbetrieb |
| R9 | **Gleichzeitige Bearbeitung** | Verlorene Änderungen, Doppelzuordnung | Optimistic Locking (umgesetzt), fachliche Sperren per `FOR UPDATE`, Idempotenzschlüssel |
| R10 | **Skalierung der Echtzeit** bei vielen Clients und Positionsupdates | Verzögerte Anzeige | Gebündelte Positions-Events (1 Hz je Leitstelle), Warteschlangen mit Gegendruck (umgesetzt), Redis-Bus für mehrere Worker (umgesetzt), Lasttest in Phase 8 |
| R11 | **Windows-Verteilung** | SmartScreen-Warnungen, manuelle Updates | Code-Signing-Zertifikat beschaffen (Organisationsentscheidung), Auto-Update über eigenen Server (Phase 8) |
| R12 | **Interne TLS-CA** | Clients vertrauen dem Zertifikat nicht | CA-Zertifikat per Gruppenrichtlinie verteilen; alternativ öffentlicher DNS-Name + Let's Encrypt |
| R13 | **Sehr neue Werkzeugversionen** (TypeScript 7, Vite 8, Electron 45, dockview 8) | Inkompatibilitäten bei Updates | Exaktes Pinning, `package-lock.json`, Updates nur mit CI-Lauf |
| R14 | **Datenverlust** | Verlust von Protokollen/Einsätzen | Tägliches Backup mit Lesbarkeitsprüfung (umgesetzt), Restore-Test, `.env`-Sicherung, Volumes auf RAID |
| R15 | **Reale Wirkung aus der Simulation** | Fehlalarm | Mehrstufige Trennung Simulation/Echtbetrieb (siehe Sicherheitskonzept), Standard überall „aus“ |

## Externe Abhängigkeiten

| Abhängigkeit | Wofür | Ab Phase | Betrieb |
|---|---|---|---|
| PostgreSQL, Redis, Caddy | Kern | 1 | Docker (Server) |
| OSRM + OSM-Extrakt (Geofabrik) | Routing | 6 | Docker (Server), Daten-Download |
| Kachelquelle (PMTiles/Anbieter) | Karte | 6 | eigener Server oder Vertrag |
| faster-whisper, Piper | Sprache | 7 | Docker (Server), GPU optional |
| Anthropic API (Claude) | KI-Anrufer | 7 | API-Schlüssel (verschlüsselt gespeichert) |
| Asterisk | echte VoIP | später | eigener Server |
| Externe Alarmierungs-APIs | Zusatzalarmierung | 4 | Plugin, nur Echtbetrieb |
