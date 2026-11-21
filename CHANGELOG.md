# Änderungsprotokoll

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
