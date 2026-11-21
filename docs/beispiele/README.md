# Beispieldateien für den Datenimport

Fiktive Daten zur Demo-Leitstelle (`ils-admin seed-demo`). Reihenfolge beim Ausprobieren:

1. **`wachen-beispiel.csv`** – drei Wachen (CSV mit Semikolon, deutsche Dezimalkommas).
   Datenimport → „Wachen“ → Datei wählen → Zuordnung prüfen → übernehmen.
2. **`fahrzeuge-beispiel.xlsx`** – zehn Fahrzeuge, die auf diese Wachen, auf
   Funkrufgruppen und RICs der Demo-Daten verweisen.

Die Spaltennamen dürfen abweichen; der Assistent schlägt eine Zuordnung vor
(z. B. „Rufname“ → Funkrufname, „Standort“ → Wache). Pflichtfelder:
Fahrzeuge = Funkrufname, Fahrzeugtyp, Wache; Wachen = Name, Organisation.
