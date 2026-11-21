# Änderungsprotokoll

## 0.7.0 – 21.11.2026 – Phase 7: Ausbildung und KI-Anrufer

### Hinzugefügt
- Übungsanrufe: Ein Übungsszenario lässt einen Trainings-Notruf in der normalen
  Notrufannahme klingeln; nur die übende Person kann ihn annehmen. Einsatz, Stichwort und
  Alarmierung laufen über die regulären Funktionen.
- KI-Anrufer mit Claude (Standardmodell `claude-opus-5-5`, Modell und Aufwand einstellbar):
  Antworten werden satzweise gestreamt und sofort angezeigt und vorgelesen, Prompt-Caching,
  serverseitiges Ausweichmodell bei Ablehnung. Standardmäßig **aus**; ohne KI antwortet ein
  regelbasierter Anrufer aus den Szenario-Fakten. Fällt die KI aus, antwortet der
  regelbasierte Anrufer – sichtbar gekennzeichnet.
- Szenario-Editor (Persona, tatsächliche Lage, Eröffnungssatz, Schwierigkeit, erwartetes
  Stichwort, Checkliste) und vier fiktive Demo-Szenarien.
- Ausbildermodus: Übungen für Teilnehmer starten, Gespräch live mitlesen, verdeckte
  Regieanweisungen an den Anrufer (mit der nächsten Antwort oder sofort), Beobachtungsnotizen,
  Übung beenden; neue Standardrolle „Ausbilder“.
- Automatische Auswertung nach dem Auflegen: Handlungen im System (Einsatz angelegt,
  Stichwort, Einsatzort ≤ 300 m oder Adresse, Alarmierung) direkt geprüft, Gesprächspunkte
  durch Claude (strukturierte Ausgabe) oder regelbasiert; Kennzahlen (Zeiten, Antwortlatenz),
  Stärken und Verbesserungsvorschläge; Übungsberichte.
- Sprache: Sprachausgabe mit den Stimmen des Betriebssystems; Sprechtaste mit
  Spracherkennung auf dem Server (optionales Paket faster-whisper).
- KI-Einstellungen für Administratoren (Schlüssel verschlüsselt, nie wieder angezeigt,
  Verbindungstest), Arbeitsplatz „Ausbildung“ (F7).

### Geändert
- Mikrofonfreigabe im Windows-Client nur für die eigene Oberfläche und nur Audio.
- Wechsel in den Echtbetrieb bricht laufende Übungen ab; Übungen starten nur im
  Simulationsbetrieb.
- `seed-demo` legt fehlende Standardrollen selbst an und lässt sich auf reinen Test- und
  Schulungsservern im Produktionsmodus mit `--allow-production` ausführen.

### Behoben (während der Entwicklung gefunden)
- Live-Listen konnten veraltet bleiben, wenn ein Ereignis während eines laufenden
  Ladevorgangs eintraf.
- Übungsanrufe erschienen (mit Signalton) bei allen Disponenten der Leitstelle – jetzt nur bei
  der übenden Person.
- Ein Fenster, das während des Ladens des gespeicherten Layouts geöffnet wurde, wurde vom
  Layout überschrieben.
- Eine Nachricht, die gesendet wurde, während der Anrufer schon sprach, blieb unbeantwortet
  (Gesprächsreihenfolge jetzt nach Zeitpunkt des Sprechens).

## 0.6.0 – 21.11.2026 – Phase 6: Fahrzeuge, Karte, Simulation

### Hinzugefügt
- Fahrzeugstatus (FMS) mit Folgen für den Einsatz (Anfahrt, Am Einsatzort, Freimeldung,
  Außer Dienst) und unveränderbarer Statushistorie.
- Sprechwünsche (Status 5 und priorisiert 0) mit Warteschlange, Sprechaufforderung,
  Zurückstellen, Ablehnen, Erledigt mit Vermerk und Signalton.
- Simulationsdienst: Ausrücken nach der Alarmierung, Fahrten mit Sonderrechten, Ankunft
  (Status 4), Rückfahrt (1 → 2), Ausfall, Verschieben, Pause und Zeitraffer; neustartsicher,
  ein simulierender Prozess, keine Simulation im Echtbetrieb.
- Routing über OSRM (optionaler Compose-Dienst, Aufbereitungsskript) mit gekennzeichnetem
  Rückfall auf die Luftlinie.
- Karte (MapLibre) mit Wachen, Fahrzeugen in Statusfarbe (live), Einsätzen und Routen;
  Einsatzort per Klick; Fenster Fahrzeugübersicht, Statusübersicht und Sprechwünsche.
- Im Einsatz: Status, S3/S4-Zeiten und Live-ETA je Fahrzeug.

### Geändert
- Echtzeit-Aktualisierungen werden je Abfrage gebündelt; laufende Abfragen werden nicht
  mehr abgebrochen.
- CSP um Karten-Worker und Kachelbilder ergänzt.
- Einsatzliste liefert Koordinaten.

### Behoben (während der Entwicklung gefunden)
- Bei vielen gleichzeitigen Sitzungen kamen Aktualisierungen nicht an (Abfragesturm).
- Die Simulations-Sperre blieb nach dem Abgeben im Verbindungspool bestehen.
- Kartenfenster mit Höhe 0 durch das MapLibre-Stylesheet.

## 0.5.0 – 21.11.2026 – Phase 5: Einsatzmittelvorschlag

### Hinzugefügt
- Einsatzmittelvorschlag im Einsatz („Vorschlag …“): Bedarf aus der AAO (bis zur gewählten
  Stufe) und Zusatzbedarf, Bewertung nach Fahrzeit, Ausrückzeit, Ersatztyp und Wache laut
  AAO, Zuteilung ohne Doppelvergabe mit Ausgleich, Begründung je Fahrzeug, Alternativen,
  Fehlbedarf mit Hinweis auf freie Fahrzeuge verknüpfter Nachbarleitstellen.
- „Übernehmen“ ordnet nur zu (dokumentiert im Einsatzverlauf); „Übernehmen und alarmieren …“
  öffnet anschließend die bestätigungspflichtige Alarmierungsvorschau.
- Fahrzeiten: Schätzung (Luftlinie × Umwegfaktor) oder OSRM-Routing (`ILS_OSRM_URL`) mit
  gekennzeichnetem Rückfall.
- Fenster „Vorschlagsregeln“ je Leitstelle (Gewichte, maximale Fahrzeit, Ersatztypen);
  Recht `proposal_settings.write`.
- Gespeicherte Vorschläge zur Nachvollziehbarkeit (Eingaben, Ergebnis, Dauer, Übernahme).

### Geändert
- Die Alarmierungsvorschau nutzt die neue Engine und zeigt Fahrzeiten statt Entfernungen.
- Konfliktwarnung beim gleichzeitigen Bearbeiten erscheint erst nach 0,8 s (kein Aufblitzen
  nach dem eigenen Speichern).
- Standardlayouts (Schema 6) mit dem Fenster „Vorschlagsregeln“.

### Behoben (während der Entwicklung gefunden)
- Bei gleicher Bewertung konnten Ersatztypen über Kreuz vergeben werden.
- Gewählte Alternativen wurden im Einsatzverlauf als „manuell ergänzt“ dokumentiert.

## 0.4.0 – 21.11.2026 – Phase 4: Alarmierung

### Hinzugefügt
- Alarm- und Ausrückeordnung (AAO) je Leitstelle und Stichwort, optional je
  Zuständigkeitsbereich, mit Stufen und Einträgen für Fahrzeugtypen (mit Anzahl), Fahrzeuge,
  Wachen, RICs, Alarmierungsgruppen und Schnittstellen; Editor „Alarmierungsregeln (AAO)“.
- Alarmierungsvorschau im Einsatz („Alarmieren …“): Vorschlag aus der AAO, Fahrzeuge
  ab-/zuwählen, Stufe wählen, ausgelöste RICs und Schnittstellen mit ihrer Wirkung,
  Warnungen bei fehlenden Einsatzmitteln.
- Alarmierung erst nach Bestätigung, Erst- und Nachalarmierung, Schutz vor
  Doppelalarmierung (Idempotency-Key), Status „Alarmiert“, Alarmierungsprotokoll je Einsatz
  und Fenster „Alarmierungsübersicht“.
- Hinweis „Polizei informieren“ als bestätigungspflichtiges Informationsfenster mit Vermerk
  und Dokumentation im Einsatzverlauf; Stichwort-Felder dafür; Standard für sechs
  Stichworte. Die Polizei wird nie durch das System alarmiert.
- Plugin-System für Schnittstellen mit Simulations-Empfänger und Webhook (real);
  Fenster „Schnittstellen“ mit aus JSON-Schema erzeugtem Formular, verschlüsselten
  Schlüsseln, Verbindungstest und Ereignisprotokoll.
- Demo-Daten: 13 AAOs und ein aktiver Simulations-Empfänger.

### Sicherheit
- Reale Schnittstellen: nur im Echtbetrieb, nur mit `interfaces.activate_real` und
  Begründung aktivierbar; automatische Deaktivierung beim Wechsel in den Simulationsbetrieb;
  der Kern ruft reale Plugins im Simulationsbetrieb nie auf.

### Geändert
- Standardlayouts (Schema 5): neue Fenster in Verwaltung und Administrator-Arbeitsplatz.
- Ereignisprotokoll übersetzt nun auch Einsatz-, Notruf- und Alarmierungsaktionen.

### Behoben (während der Entwicklung gefunden)
- Polizei-Hinweise wurden bei einer Neuinstallation nicht gesetzt.
- Doppelte AAO lieferte HTTP 500 statt 409.

## 0.3.0 – 21.11.2026 – Phase 3: Einsatzbearbeitung

### Hinzugefügt
- Notrufannahme: Warteschlange nach Priorität und Wartezeit, Signalton (abschaltbar) und
  Notrufanzeige in der Kopfzeile, Annahme per Strg+Leertaste, Halten/Übernehmen, Beenden,
  Anruferdaten, Anruferstandort übernehmen, Zuständigkeitsprüfung, W-Fragen als dokumentierte
  Rückfragen, Gesprächsnotizen, Anruf manuell erfassen, laufende Telefonate.
- Einsätze: aus Notruf oder manuell, lückenlose Nummern je Leitstelle und Jahr, Stichwort,
  Einsatzart, Priorität, Statusmodell (Neu … Abgeschlossen) mit Abschlussregeln, Fahrzeuge
  zuordnen/freigeben/umsetzen (ein Fahrzeug nur in einem Einsatz), beteiligte Wachen,
  zugeordnete Notrufe, unveränderbarer Einsatzverlauf, Dokumentation.
- Stichwortkatalog mit 16 Standardstichworten (administrierbar).
- Simulierte Telefonie: zehn fiktive Notfallszenarien, Gesprächsprotokoll „auf Nachfrage“,
  nur im Simulationsbetrieb.

### Geändert
- Bearbeitungsschutz bei gleichzeitigen Änderungen jetzt einheitlich (auch Benutzer- und
  Leitstellenverwaltung).
- Standardlayouts (Schema 4) für Einsatzannahme und Disposition mit breiterer Einsatzliste.

### Behoben (während der Entwicklung gefunden)
- Eingaben konnten im Formular eines vorherigen Gesprächs landen; ein neues Gespräch hält jetzt
  automatisch das bisherige, und die Ansicht wechselt sofort.
- Eigene Notizen blockierten das Speichern des Notrufs (Versionskonflikt) – Notrufe nutzen
  stattdessen die Bearbeiter-Sperre.

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
