# 04 – Entwicklungs-Roadmap

Jede Phase endet mit einem Meilenstein. Er gilt erst als erreicht, wenn die
Abnahmekriterien erfüllt sind: automatisierte Tests grün, Dokumentation aktualisiert, keine
Regression in früheren Phasen (CI). Der aktuelle Stand steht in [STATUS.md](STATUS.md).

| Phase | Inhalt | Meilenstein / Abnahmekriterien | Stand |
|---|---|---|---|
| **1 Grundsystem** | Projektstruktur, Server, Datenbank, Anmeldung, Rechte, Audit, Echtzeit, Windows-Client mit Shell und Arbeitsplätzen, Deployment | **M1:** Mehrere Benutzer melden sich gleichzeitig an. Änderungen erscheinen live bei allen. Rechte und Mandanten greifen. Layout wird gespeichert. Server läuft per Docker Compose. Tests: Server 51, Client 21 Unit- und 3 E2E-Tests | ✅ abgeschlossen |
| **2 Administration** | Organisationen, Wachen, Fahrzeugtypen, Fahrzeuge, RICs, Alarmgruppen, Funkrufgruppen, Leitstellen-Verknüpfungen und -Zuständigkeiten, Excel/CSV-Import mit Spaltenzuordnung, Vorschau und Bestätigung, Benutzerverwaltung (Rollen-Editor, Anmeldeprotokoll-Ansicht) | **M2:** Ein Administrator importiert 200 Fahrzeuge aus einer `.xlsx` mit eigener Spaltenzuordnung, sieht Fehler zeilengenau vor der Bestätigung, und jede Änderung steht im Protokoll | ✅ abgeschlossen (0.2.0) |
| **3 Einsatzbearbeitung** | Notrufannahme (simulierte Anrufe), Anruferdaten, Notizen, Priorisierung, Einsatz anlegen/zuordnen, Einsatznummern, Einsatzstatus, Einsatzverlauf, Dokumentation, Einsatzliste und -detail | **M3:** Zwei Disponenten bearbeiten gleichzeitig verschiedene Einsätze. Ein Notruf wird einem bestehenden Einsatz zugeordnet. Der Einsatzverlauf ist lückenlos | ⏭ nächste Phase |
| **4 Alarmierung** | Stichwortverwaltung, AAO-Regeln (mehrere Schleifen, Zusatzalarmierung), RIC-Zuordnung, Alarmierungsvorschau und -bestätigung, Nachalarmierung, Alarmierungsprotokoll, Polizei-Hinweisfenster (nur Information), Schnittstellen- und Plugin-System | **M4:** B2 zeigt die korrekte Vorschau (Fahrzeuge, Wachen, RICs). Erst nach Bestätigung wird alarmiert (simuliert). Bei Stichworten mit Polizei-Hinweis erscheint das Popup und wird protokolliert. Ein reales Plugin ist im Simulationsmodus nachweislich wirkungslos | geplant |
| **5 Einsatzmittelvorschlag** | Fahrzeugbewertung (AAO, Typ, Status, Verfügbarkeit, Fahrzeit), Begründungen, Übernehmen/Abwählen/Ergänzen/Neu berechnen, administrierbare Gewichtung | **M5:** Für B2 entsteht in unter 1 s ein Vorschlag mit nachvollziehbarer Begründung je Fahrzeug. Es gibt **keine** automatische Alarmierung | geplant |
| **6 Fahrzeuge und Navigation** | Statussystem (administrierbar), Statushistorie, Sprechwünsche, Funkgruppen-Ansicht, Karte (MapLibre), OSRM-Routing, Simulationsdienst (Bewegung, ETA, Ankunft → S4), manuelles Verschieben, Ausfälle | **M6:** 50 Fahrzeuge fahren gleichzeitig straßengenau, alle Clients sehen identische Positionen (1-Hz-Takt). Ankunft setzt S4 und schreibt den Einsatzverlauf | geplant |
| **7 Telefonie und KI** | Simulierte Telefonie mit Audio, STT (faster-whisper), TTS (Piper), KI-Anrufer (Claude) mit Personas und Schwierigkeitsgraden, Szenario-Editor, Ausbildermodus (Beobachten), automatische Auswertung, Trainingsberichte, optionale Aufzeichnung | **M7:** Ein Disponent führt ein Sprachgespräch mit einem KI-Anrufer (Antwortlatenz unter 2,5 s), legt währenddessen den Einsatz an und erhält danach eine Auswertung mit Checkliste | geplant |
| **8 Stabilisierung** | Sicherheitstests (Pentest-Checkliste, Abhängigkeits-Scan), Last- und Mehrbenutzertests, Fehlerbehebung, signierter Windows-Installer, Auto-Update, Serverinstallation, Backup-Konzept (Restore-Test), Betriebs- und Benutzerdokumentation | **M8:** Release 1.0. 20 gleichzeitige Arbeitsplätze im Lasttest, Restore in unter 15 min, Installer signiert | geplant |

## Arbeitsweise je Phase

1. Datenmodell und Migration → 2. Service mit Tests → 3. API mit Tests → 4. Echtzeit-Events
→ 5. Client-Panel → 6. E2E-Test des Hauptablaufs → 7. Doku und `STATUS.md` aktualisieren →
8. Commit.

## Bewusst nicht im Umfang der ersten Version

- Echte Anbindung an Notrufleitungen (112) oder BOS-Funk: rechtlich und organisatorisch
  ausgeschlossen. Nur Simulation; reale VoIP nur für interne Testanschlüsse.
- Weitere Großprojekte (z. B. Statistik/BI, Dienstplanung, mobile Apps).
