# Dynamische Heizungssteuerung für Home Assistant

Eine vorausschauende, lernfähige Heizungsregelung als eigene Home-Assistant-Integration. Die Integration wird schrittweise mit sicheren Standardwerten und automatisierten Tests erweitert.

## Aktueller Funktionsumfang

- Verknüpft ein Thermostat, einen Raumtemperatursensor und einen Home-Assistant-Zeitplan.
- Ein Schedule-Helfer kann mehrere Komfort-Zeitfenster pro Wochentag enthalten. Jeder Raum/Regler kann mit eigener Komfort- und Absenktemperatur eingerichtet werden.
- Nutzt den nächsten Zustandswechsel des Zeitplans, um bei Bedarf vor dem Komfortzeitraum vorzuheizen.
- Lernt während tatsächlicher Heizphasen die Aufheizrate und während stabiler Absenkphasen eine Abkühlrate. Beide Werte werden begrenzt, lokal gespeichert und über Neustarts erhalten.
- Berücksichtigt die gelernte Abkühlrate in der Prognose für den Beginn des nächsten Komfortzeitraums. Die Prognose fällt nicht unter die aktuelle Temperatur, wenn der Raum bereits kälter als die Absenktemperatur ist, und sonst nicht unter den konfigurierten Absenkwert.
- Berücksichtigt optional Fensterkontakt, Personen-/Geräte-Tracker, Gastmodus, Präsenzsensor samt Zeitplan und Reaktionszeiten, Proximity/Geo-Fencing, Außentemperatur und Wetter-Entität. Ankunfts-/Abwesenheitsverzögerungen und Entfernungsschwelle sind pro Raum konfigurierbar. Stündliche Wetterprognosen werden höchstens alle 30 Minuten abgerufen; bei sonnigen Tagesprognosen kann die Vorheizzeit um bis zu 15 Minuten sinken. Bei fehlender oder ungültiger Prognose bleibt die normale Berechnung erhalten.
- Stellt Status, Raum-/Außentemperatur, berechnete Solltemperatur, aktuellen Thermostat-Sollwert, prognostizierte Temperatur, Wetterbedingung, Sonnenkorrektur, Vorheizzeit sowie gelernte Aufheiz- und Abkühlraten als Sensoren bereit. Der Statussensor enthält Diagnoseattribute zur letzten Entscheidung.
- Unterstützt Home-Assistant-Diagnosedaten; konfigurierte Entity-IDs werden beim Export redigiert.
- Hat einen **separaten Aktivierungsschalter**. Nach der Installation bleibt die Regelung zunächst ausgeschaltet; solange sie ausgeschaltet ist, werden keine Thermostat-Sollwerte verändert.
- Fängt fehlgeschlagene Thermostat-Sollwertaufrufe ab, zeigt einen klaren Fehlerstatus samt ursprünglicher Heizentscheidung an und versucht es beim nächsten Update erneut.

> **Wichtig:** Advanced Heating Control (AHC) und diese Integration dürfen nicht gleichzeitig dasselbe Thermostat steuern. Teste zunächst mit ausgeschalteter Regelung. Vor dem Aktivieren muss AHC für das betreffende Thermostat deaktiviert sein.

## Installation über HACS

Das Repository ist für die manuelle Installation als **benutzerdefiniertes HACS-Repository** vorgesehen; es ist nicht automatisch Teil der offiziellen HACS-Standardliste.

1. In Home Assistant **HACS → Integrationen** öffnen.
2. Über das Drei-Punkte-Menü **Benutzerdefinierte Repositories** wählen.
3. https://github.com/patrickbrundiers-dev/Dynamische-Heizungssteuerung- als Repository eintragen und als Kategorie **Integration** auswählen.
4. Hinzufügen, **Dynamische Heizungssteuerung** suchen und installieren.
5. Home Assistant neu starten und anschließend unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** einrichten.

Alternativ manuell:

1. Home Assistant sichern.
2. Den Ordner custom_components/dynamic_heating nach <config>/custom_components/dynamic_heating/ kopieren.
3. Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Dynamische Heizungssteuerung** suchen.
5. Thermostat, Raumtemperatursensor und Schedule-Helfer auswählen. Fenster-, Anwesenheits-, Personen-/Geräte-Tracker-, Gastmodus-, Proximity-, Präsenzzeitplan-, Außen- und Wetter-Entitäten sind optional. Bei Geo-Fencing müssen die Entfernungsangaben zur Einheit der gewählten Proximity-Entität passen. Eine Wetter-Entität lässt sich auch später über Einstellungen → Geräte & Dienste → Dynamische Heizungssteuerung → Konfigurieren setzen.
6. Im Schedule-Helfer alle gewünschten Komfort-Zeitfenster pro Wochentag konfigurieren. Komfort- und Absenktemperatur werden pro Regler eingestellt.
7. Zuerst die Status-, Temperatur- und Prognosesensoren beobachten. Den Schalter **Regelung aktiv** erst einschalten, wenn die Prognose plausibel ist und AHC das Thermostat nicht mehr steuert.

Die Regelung wird nach einem Home-Assistant-Neustart aus Sicherheitsgründen wieder deaktiviert und muss bewusst erneut eingeschaltet werden. Das ist beabsichtigt, damit ein Update oder Neustart nicht unbemerkt eine Regelung aktiviert.

### Temperaturwerte und Lernmodell

Die Komfort- und Absenktemperatur sowie die maximale Vorheizzeit werden beim Einrichten konfiguriert. Fenster offen oder keine Anwesenheit führt zur Absenkung. Ist ein notwendiger Messwert nicht verfügbar, wird kein neuer Sollwert gesetzt. Ist das Thermostat selbst nicht verfügbar, stoppt die Regelung ebenfalls mit einem klaren Status.

Die Abkühlrate wird nur gelernt, wenn das Fenster geschlossen ist, Anwesenheit erkannt wird, der Schedule-Helfer inaktiv ist und das Thermostat auf einer Absenktemperatur steht. Das Lernen ignoriert kleine/unplausible Temperaturänderungen und begrenzt die resultierende Rate. Anfangs wird ein konservativer Startwert verwendet; der Wert wird erst durch reale stabile Beobachtungen angepasst. Außentemperaturkorrektur und Abkühlrate sind Schätzungen, keine Wetter- oder Gebäudesimulation.

### Diagnose bei der ersten Raumprobe

Für den ersten Raum sollten zunächst die folgenden Werte beobachtet werden:

- **Status** und dessen Attribute mode, enabled, schedule_active, next_event und preheat_minutes.
- **Berechnete Solltemperatur** im Vergleich zum aktuell am Thermostat gesetzten Sollwert.
- **Prognostizierte Raumtemperatur**, **Gelernte Abkühlrate**, **Wetterprognose** und **Sonnenkorrektur Vorheizzeit**.
- **Fenster-/Anwesenheitszustand**, falls diese optionalen Sensoren eingerichtet sind.

Wenn etwas nicht plausibel aussieht, bitte nicht sofort den Regler aktivieren. Die Diagnoseattribute zeigen zuerst, warum die Integration Komfort-, Absenk- oder Vorheizbetrieb gewählt hat.

## Tests in einer isolierten Home-Assistant-Instanz

Das Repository enthält Integrationstests mit pytest-homeassistant-custom-component. Die Tests starten eine isolierte Home-Assistant-Testinstanz, legen simulierte Entitäten an und prüfen das echte Setup der Integration, die Vorheizentscheidung, Fenster-/Anwesenheitslogik, Sensorfehler, Thermostatgrenzen, fehlgeschlagene Thermostat-Serviceaufrufe samt Wiederholungsversuch und ob Sollwerte nur nach Aktivierung gesetzt werden. Dafür wird weder Zugriff auf die echte Heizung noch ein Token aus deiner produktiven Installation benötigt.

Automatische Tests laufen bei Push, Pull Request und manuellem Start in GitHub Actions. Lokal:

~~~bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
python -m pip install -r requirements_test.txt
pytest -q
ruff check .
~~~

## Sicherheits- und Entwicklungsprinzipien

- Standardmäßig keine Steuerung bis zur bewussten Aktivierung.
- Nur konfigurierte Entitäten ansprechen und Sollwerte nur bei relevanter Abweichung ändern.
- Bei nicht verfügbaren Pflichtwerten keine neuen Sollwerte setzen.
- Lernwerte bleiben lokal in Home Assistant; keine Cloud-Übertragung.
- Änderungen an der Heizungslogik müssen von Tests begleitet werden.

## Nächste Ausbaustufen

1. Nach dem sicheren Praxistest in einem Raum das Lernmodell anhand realer Status- und Temperaturverläufe bewerten, bevor aggressivere Regelstrategien aktiviert werden.
2. Danach die Dashboard-Beispiele für mehrere Räume übersichtlicher strukturieren und die Inbetriebnahme-/Fehlerdiagnose weiter vereinfachen.

Lizenz: MIT.


## Dashboard mit Verlauf und Sollwertvergleich

Ein Lovelace-Beispiel liegt unter dashboards/dynamic_heating.yaml. Es enthält einen Statusbereich, einen 24-Stunden-Verlauf sowie einen 7-Tage-Verlauf der Lernraten. Ersetze vor der Nutzung die Beispiel-Entity-IDs mit den IDs aus Einstellungen → Geräte & Dienste → Entitäten. Die Kurve für den aktuellen Thermostat-Sollwert dient als Referenz, während die dynamische Regelung noch ausgeschaltet ist; so lässt sich die Empfehlung zunächst beobachten, ohne zwei Regler gleichzeitig auf dasselbe Thermostat wirken zu lassen.

### Wetterprognose und Sonneneinfluss

Nach der Erstellung eines Raums kannst du über **Einstellungen → Geräte & Dienste → Dynamische Heizungssteuerung → Konfigurieren** den vollständigen Editor öffnen und Thermostat, Temperaturfühler, Schedule, Komfort-/Absenktemperaturen, maximale Vorheizzeit sowie optionale Sensoren ändern. Die Wetter-Entität kann dort ebenfalls hinzugefügt oder entfernt werden. Es werden stündliche Vorhersagen höchstens alle 30 Minuten geladen, damit die Integration nicht jede Minute einen Wetterabruf auslöst. Nur ein zeitlich passender Forecast-Punkt mit den Bedingungen sunny oder partlycloudy zwischen 08:00 und vor 17:00 Uhr kann die geschätzte Vorheizzeit reduzieren. Der maximale Einfluss ist auf 15 Minuten begrenzt. Wolkige, nächtliche, fehlende oder veraltete Prognosen verändern die Vorheizzeit nicht.

Das ist bewusst eine konservative Heuristik und keine echte Strahlungs- oder Raumwärmesimulation. Bei Räumen mit wenig direkter Sonne kann sie den Einfluss überschätzen. Beobachte die Empfehlung erst bei ausgeschalteter Regelung und aktiviere sie nur, wenn sie zu deinem Raum passt.


### Personen, Präsenz und Geo-Fencing (Version 0.3.3)

- **Personen / Geräte-Tracker:** Komfortbetrieb gilt, wenn mindestens eine konfigurierte Person bzw. ein Tracker zu Hause ist. Ankunfts- und Abwesenheitswartezeit schützen vor kurzen Statuswechseln.
- **Gastmodus:** Eine eingeschaltete Gast-Entität zählt als Anwesenheit.
- **Präsenzsensor:** Optional mit eigenem Zeitplan sowie getrennten Reaktionszeiten für EIN und AUS. Ist der Präsenzzeitplan ausgeschaltet, wird der Präsenzsensor für die Entscheidung ignoriert.
- **Proximity / Geo-Fencing:** In aktuellen Home-Assistant-Versionen wählst du den Entfernungssensor und den zugehörigen Richtungssensor separat (z. B. Distanz zur Zone und Richtung der Bewegung). Ältere kombinierte Proximity-Entitäten werden weiter unterstützt. Die Grenzentfernung wird in Metern angegeben; bekannte Entfernungs-Einheiten werden normalisiert. Nur die Richtung `towards` innerhalb der Grenze startet die Anfahrtszeit. Richtungswechsel, ungültige Messwerte oder fehlende Entitäten setzen den Timer zurück. Standortdaten, die älter als die einstellbare Maximaldauer sind, lösen keine neue Heizentscheidung aus. Bestätigt ein Personen- oder Gast-Tracker bereits Zuhause, hat dieser lokale Status Vorrang vor veralteten Geodaten.
- **Sicherheit:** Ist eine konfigurierte erforderliche Entität nicht verfügbar, wird kein neuer Thermostat-Sollwert gesetzt. Alle neuen Entitätsfelder sind optional. Standardmäßig gelten 2 Sekunden für Ankunft und Verlassen, 2 Minuten für die Anfahrt sowie 5 Minuten EIN- und 20 Minuten AUS-Reaktionszeit am Präsenzsensor. Diese Sensor-Verzögerungen greifen nur, wenn ein entsprechender Präsenzsensor konfiguriert ist.


Die Zeitfelder verwenden im Raum-Editor den nativen Home-Assistant-Dauerauswähler mit Stunden, Minuten und Sekunden. Die Anfahrtszeit wird intern vom ersten stabilen Proximity-Messpunkt in Richtung Zuhause gemessen; spätere Änderungen der Entfernung setzen den Timer nicht zurück, solange Richtung und Distanzbedingung weiter erfüllt sind.


### Geo-Fencing: Datenqualität und Fehlerverhalten (Version 0.3.4)

- Wähle **zwei Sensoren** der aktuellen Proximity-Integration: den Entfernungssensor und den passenden Richtungssensor. Die aktuelle Core-Integration stellt Entfernung und Bewegungsrichtung getrennt bereit. Ältere kombinierte Entitäten mit dem Attribut `dir_of_travel` bleiben kompatibel.
- **Einheiten:** Entfernungen werden vor dem Vergleich in Meter umgerechnet (m, km, mi, ft und yd).
- **Aktualität:** Das Alter des Entfernungssensors wird gegen die konfigurierte Maximaldauer geprüft (Standard: 15 Minuten). Bei veralteten GPS-Werten oder fehlender Richtung gibt es keine neue Sollwertänderung aus der unklaren Proximity-Situation. Ist gleichzeitig ein Personen-/Gast-Tracker bekannt zu Hause, gilt der lokale Zuhause-Status statt eines veralteten Geofence-Signals.
- **Anfahrt:** Der Timer läuft nur, solange die Richtung `towards` meldet und die Entfernung innerhalb der Grenze liegt. Laufende Distanzänderungen starten ihn nicht neu; Richtungswechsel, überschrittene Entfernung und Verfügbarkeitspausen setzen ihn zurück.
- **Wichtig zur Einrichtung:** Bei Geo-Fencing nur dann die Regelung auf Basis dieser Funktion aktivieren, wenn Entfernungssensor und Richtungssensor denselben Proximity-Tracker/dieselbe Zone darstellen. Ist das Handy lange offline, wird eine veraltete Entität sichtbar als Problem gemeldet statt alte Daten als aktuelle Anfahrt zu behandeln.

### Qualität des adaptiven Lernmodells (Version 0.3.4)

- **Plausibilitätsfilter:** Aufheiz- und Abkühlmessungen mit zu langem Zeitfenster, unerwarteter Temperaturänderung oder einer beobachteten Rate außerhalb der definierten Grenzen werden verworfen statt an eine Maximalrate geklemmt. Das verhindert, dass einzelne Messausreißer die gelernte Rate in eine falsche Richtung ziehen.
- **Messzähler:** Die Integration speichert die Zahl akzeptierter Aufheiz- und Abkühlmessungen sowie verworfener Messungen. Der Statussensor enthält den letzten Lernstatus, die letzte beobachtete Rate und den Zeitstempel.
- **Prognoseprüfung:** Wenn ein inaktiver Zeitplan in den Komfortzeitraum wechselt, wird die zuvor für diesen Zeitpunkt gespeicherte projizierte Raumtemperatur mit der tatsächlichen Raumtemperatur verglichen. Die Integration aktualisiert den letzten signierten Prognosefehler, Anzahl der ausgewerteten Prognosen und den mittleren absoluten Fehler (MAE) in °C.
- **Persistenz und Datenschutz:** Raten, Zähler und zusammengefasste Fehlerkennzahlen werden lokal gespeichert. Es wird keine vollständige Temperatur-, Bewegungs- oder GPS-Historie gesammelt. Die einzelne noch offene Prognose für den nächsten Zeitplanwechsel liegt nur im Arbeitsspeicher und wird nach einem Neustart nicht nachträglich ausgewertet.
- **Interpretation:** Der MAE wird erst aussagekräftig, wenn mehrere Komfortbeginn-Prognosen ausgewertet wurden und Raum, Fenster, Präsenz sowie Zeitplan stabil konfiguriert sind. Er ist eine Beobachtungskennzahl, keine Garantie für einen bestimmten Komfortzeitpunkt.


## Version 0.3.5: Editor, Geo-Fencing-Kalibrierung und Modell-Dashboard

### Neuer geführter Raum-Editor

Der Dialog **Konfigurieren** ist in vier kurze Seiten gegliedert:

1. **Raum und Heizverhalten:** Thermostat, Raumtemperatur, Komfortzeitplan, Komfort- und Absenktemperatur, maximale Vorheizzeit.
2. **Personen und Anwesenheit:** Personen/Geräte-Tracker, Ankunftsbestätigung, Abwesenheits-Nachlauf, Gastmodus, Präsenzsensor und dessen Zeitplan sowie EIN-/AUS-Reaktionszeiten.
3. **Geo-Fencing und Standortqualität:** Entfernungssensor, zugehöriger Richtungssensor, maximaler Radius, Anfahrtsbestätigung und maximales Alter der Standortdaten.
4. **Fenster, Außentemperatur und Wetter:** optionale Sensoren mit Erklärung, wie sie die Regelung beeinflussen.

Jede Seite hat eine eigene Überschrift, eine kurze Einführung und ausführliche Feldbeschreibungen. Bereits gespeicherte Einstellungen bleiben beim Weiterklicken erhalten. Die endgültige Speicherung erfolgt erst auf der letzten Seite.

### Geo-Fencing über echte Updates kalibrieren

Das Dashboard unter `dashboards/dynamic_heating.yaml` enthält jetzt eine eigene Geo-Fencing-Ansicht für:
- aktueller Status, Entfernung in Metern und Alter der zuletzt empfangenen Entfernungsmessung
- Anzahl empfangener Standortupdates und durchschnittliches Update-Intervall
- Phasen mit veralteten oder ungültigen Standortdaten
- Ereignisse außerhalb des Radius sowie begonnene und bestätigte Anfahrten

Die Messung wird aus den Zeitstempeln tatsächlicher Zustandsänderungen berechnet; wiederholtes Abfragen des gleichen alten Wertes zählt nicht als neues Standortupdate. Aggregierte Kennzahlen werden gespeichert, eine Rohhistorie der GPS-Positionen wird nicht angelegt. Stimmen Update-Intervall und Grenzwert für das Datenalter nicht zusammen, passe den Grenzwert anhand realer Beobachtungen an.

### Lernmodell über mehrere Wochen bewerten

Die Statussensoren und die zweite Dashboard-Ansicht zeigen:
- gelernte und zuletzt gemessene Aufheiz-/Abkühlrate
- akzeptierte und verworfene Lernmessungen
- Anzahl ausgewerteter Komfortbeginn-Prognosen
- letzten signierten Temperaturfehler und den mittleren absoluten Prognosefehler (MAE)
- Verlauf der Raten und Prognosewerte über sieben Tage

Für eine brauchbare Aussage sollte der Raum mehrere Komfortwechsel mit verfügbaren Sensoren, geschlossenen Fenstern und stabiler Anwesenheit durchlaufen. Der MAE wird nur an einer auswertbaren Zeitplan-Umschaltung aktualisiert. Die Steuerung verändert ihre Lernstrategie nicht automatisch nur aufgrund eines einzelnen hohen Fehlers; zuerst sollten Sensorposition, Zeitplan und Thermostatverhalten geprüft werden.

### Sicherheit und Datenhaltung

Alle neuen Kalibrierungswerte sind aggregierte Kennzahlen. Die Integration speichert weder eine fortlaufende GPS-Koordinaten-Historie noch Rohverläufe sämtlicher Temperaturmessungen. Die Regelung bleibt standardmäßig ausgeschaltet.
