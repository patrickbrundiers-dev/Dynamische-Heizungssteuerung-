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

Eine neu eingerichtete Regelung startet ausgeschaltet und muss bewusst eingeschaltet werden. Ab Version 0.4.1 behält der Schalter danach seinen Zustand über Neustarts und Änderungen im Raum-Editor hinweg.

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

### Heizgrenze (Außentemperatur)

Optional lässt sich im Editor auf der Seite **Fenster, Außentemperatur und Wetter** eine Heizgrenze setzen, z. B. 16 °C. Ist es draußen mindestens so warm, bleibt der Raum auf der Absenktemperatur, auch während Komfortzeiten, und es wird nicht vorgeheizt. Wieder normal geheizt wird erst, wenn die Außentemperatur 1 °C unter die Grenze fällt; so pendelt der Sollwert nicht, wenn die Temperatur um die Grenze schwankt. Fenster offen und Abwesenheit haben weiterhin Vorrang. Leer gelassen ist die Heizgrenze aus.

Als Außentemperatur dient der Außensensor. Ist keiner gesetzt oder liefert er keinen Wert, wird die aktuelle Temperatur der Wetter-Entität verwendet; das gilt auch für die Vorheizschätzung. Ohne beide Werte wird normal geheizt. Der Statussensor zeigt im Attribut `heating_limit_reached`, ob die Grenze gerade greift.


### Personen, Präsenz und Geo-Fencing (Version 0.3.3)

- **Personen / Geräte-Tracker:** Komfortbetrieb gilt, wenn mindestens eine konfigurierte Person bzw. ein Tracker zu Hause ist. Ankunfts- und Abwesenheitswartezeit schützen vor kurzen Statuswechseln.
- **Gastmodus:** Eine eingeschaltete Gast-Entität zählt als Anwesenheit.
- **Abwesenheitstemperatur (optional):** Ist niemand zu Hause, gilt dieser eigene Sollwert statt der Absenktemperatur, z. B. 16 °C. Leer gelassen bleibt es beim bisherigen Verhalten (Absenktemperatur). Der Wert muss unter der Komforttemperatur liegen und lässt sich auf der Seite **Personen und Anwesenheit** im Raum-Editor ändern. Ein offenes Fenster heizt während der Abwesenheit nie über diesen Wert. Kommt jemand zurück, gilt sofort wieder Komfort- bzw. Absenkbetrieb laut Zeitplan; mit Geo-Fencing beginnt das schon bei der bestätigten Anfahrt.
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
- **Messfenster an Sensorsprüngen:** Eine Messung beginnt erst, wenn sich der Temperaturwert ändert, und wird erst ausgewertet, wenn er sich um mindestens 0,2 °C bewegt hat. So verfälschen grobe 0,1-°C-Schritte die Rate nicht mehr (vorher wurde ein langsamer Raum mit 0,5 °C/h als etwa 1,2 °C/h gelernt).
- **Vorheizen bis zum Komfortbeginn:** Hat das Vorheizen für einen Komfortzeitraum begonnen, bleibt der Komfortsollwert bis zu dessen Beginn bestehen, statt kurz vorher wieder abzusenken.
- **Thermostat-Schrittweite:** Sollwerte werden auf die vom Thermostat gemeldete Schrittweite (`target_temp_step`) gerundet, und ein erfolgreich geschriebener Sollwert wird höchstens alle 5 Minuten erneut gesendet.
- **Manuelle Übersteuerung:** Wird der Sollwert direkt am Thermostat oder in Home Assistant geändert, nachdem das Thermostat den zuletzt geschriebenen Wert bestätigt hat, pausiert die Regelung. Sie übernimmt wieder, sobald sich die Entscheidung ändert (z. B. Wechsel zwischen Komfort, Vorheizen, Absenkung, Fenster offen oder Abwesenheit). Der Statussensor zeigt dann „Manuell übersteuert“ und das Attribut `manual_override`.
- **Ausgeschaltetes Thermostat:** Steht das Thermostat auf „Aus“, wird kein Sollwert geschrieben.
- **Thermostate ohne `hvac_action`:** Meldet ein Thermostat nicht, ob es heizt, gilt für das Lernen eine Heizphase, wenn es im Heizmodus ist und der Sollwert mindestens 0,5 °C über der Raumtemperatur liegt.
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

## Version 0.3.6: Fenster-Reaktionszeiten, Fenstertemperatur und Frostschutz

Übernommen aus Advanced Heating Control; alle Werte sind optional und ändern ohne Eingabe nichts am bisherigen Verhalten.

- **Reaktionszeit beim Öffnen:** Das Fenster gilt erst als offen, wenn der Kontakt so lange offen ist (z. B. 5 Minuten). Kurzes Öffnen oder Durchzug ändert den Sollwert nicht.
- **Wartezeit nach dem Schließen:** Nach dem Schließen bleibt die Fensterabsenkung so lange bestehen (z. B. 10 Minuten), damit sich die Raumluft beruhigt.
- **Temperatur bei offenem Fenster:** Eigener Sollwert bei offenem Fenster, z. B. 15 °C. Leer bleibt es bei Absenk- bzw. Abwesenheitstemperatur.
- **Frostschutztemperatur:** Kein Sollwert geht unter diesen Wert, auch nicht bei offenem Fenster oder Abwesenheit, z. B. 12 °C. Der Status zeigt dann den Zusatz „(Frostschutz)“.

Die Fensterwerte stehen im Raum-Editor auf der Seite **Fenster, Außentemperatur und Wetter**, der Frostschutz auf der Seite **Raum und Heizverhalten**. Der Statussensor zeigt mit `window_contact_open` den Rohzustand des Kontakts und mit `window_open` den entprellten Zustand, nach dem geregelt wird.

## Version 0.3.7: Heizperiode / Wintermodus

- **Heizperiode (optional):** Ein Schalter oder Sensor (z. B. `binary_sensor.wintermodus` oder ein `input_boolean`) legt fest, ob überhaupt geheizt wird. Ist er AUS, geht der Sollwert auf die Frostschutztemperatur oder, ohne sie, auf das Minimum des Thermostats; Status „Heizperiode aus – nicht geheizt“. Ist die Entität nicht verfügbar, wird normal weitergeheizt.
- Die Heizperiode ergänzt die Heizgrenze: die Heizgrenze reagiert auf die aktuelle Außentemperatur, die Heizperiode schaltet saisonal ganz ab.
- **Editor:** Optionale Entitäten wie Fensterkontakt, Außensensor, Wetter oder Gastmodus lassen sich jetzt im Raum-Editor wieder entfernen. Vorher wurde ein geleertes Feld beim Speichern mit dem alten Wert neu befüllt.

## Version 0.3.8: Mehrere Thermostate pro Raum

- **Weitere Thermostate im Raum (optional):** Auf der Seite **Raum und Heizverhalten** lassen sich zusätzliche Heizkörperthermostate desselben Raums auswählen. Alle erhalten denselben Sollwert wie das Hauptthermostat, so wie eine Climate-Gruppe im Sync-Modus „lock“. Damit kann die Integration die Thermostatköpfe direkt ansteuern statt über eine Gruppe.
- Ist ein weiteres Thermostat nicht verfügbar, wird es übersprungen; der Status nennt die Anzahl, das Attribut `unavailable_thermostats` die Entitäten. Ist das Hauptthermostat nicht verfügbar, wird wie bisher gar nichts geschrieben.
- Ein ausgeschaltetes Thermostat wird nicht beschrieben. Eine manuelle Sollwertänderung an irgendeinem Thermostat des Raums pausiert die Regelung bis zum nächsten Moduswechsel.

## Version 0.3.9: Kalibrierung mit dem Raumfühler

- **Sollwert mit Raumfühler kalibrieren (optional):** Heizkörperthermostate messen direkt am Heizkörper und schließen deshalb zu früh. Ist die Option auf der Seite **Raum und Heizverhalten** aktiv, wird der Sollwert jedes Thermostats um die Differenz zwischen seiner eigenen Temperatur (`current_temperature`) und dem Raumfühler verschoben, wie die zieltemperaturbasierte Kalibrierung von Better Thermostat. Beispiel: Raum 18 °C, Ventil 21 °C, Ziel 21 °C → das Ventil bekommt 24 °C.
- Die Abweichung wird pro Thermostat höchstens alle 10 Minuten neu berechnet und auf ±10 °C sowie die Grenzen und Schrittweite des Thermostats begrenzt. Meldet ein Thermostat keine eigene Temperatur, erhält es den unkalibrierten Sollwert. Außerhalb der Heizperiode wird nicht kalibriert.
- Der Statussensor zeigt im Attribut `thermostat_setpoints` den tatsächlich an jedes Thermostat gesendeten Sollwert.
- **Wichtig:** Nicht einschalten, wenn das gewählte Thermostat bereits ein Better-Thermostat ist; sonst wird doppelt kalibriert.

## Version 0.4.0: Ventilwartung

- **Wöchentliche Ventilwartung (optional):** Gegen Verkalkung öffnet die Integration die Ventile einmal pro Woche gegen 11 Uhr für 5 Minuten ganz (Maximaltemperatur des Thermostats) und schließt sie danach 5 Minuten ganz (Minimaltemperatur), wie Better Thermostat. Danach gilt wieder der normale Sollwert.
- Bei offenem Fenster oder manueller Übersteuerung wird die Wartung auf die nächste passende Stunde verschoben. Sie läuft nur bei eingeschalteter Regelung. Der Zeitpunkt der letzten Wartung wird gespeichert und übersteht Neustarts.
- Der Statussensor zeigt während der Wartung „Ventilwartung – Ventile öffnen/schließen“ und das Attribut `valve_maintenance`.
- Mit den Versionen 0.3.6 bis 0.4.0 kann die Integration die Aufgaben von Advanced Heating Control, Climate Group Helper und Better Thermostat übernehmen: Thermostatköpfe direkt als Haupt- und weitere Thermostate wählen, Kalibrierung und Ventilwartung einschalten. Vorher die alte Steuerung für diesen Raum abschalten, damit nicht zwei Regler dieselben Ventile stellen.

## Version 0.4.1: Schalter „Regelung aktiv“ bleibt erhalten

- Der Schalter **Regelung aktiv** behält seinen letzten Zustand über Home-Assistant-Neustarts, Updates und Änderungen im Raum-Editor. Vorher war er danach immer aus. Steuert die Integration die Ventile allein, wären sie sonst nach jedem Neustart auf dem zuletzt geschriebenen Sollwert stehen geblieben.
- Neu eingerichtete Räume starten weiterhin ausgeschaltet.

## Version 0.4.2: Hysterese und Ersatzwert bei Fühlerausfall

- **Hysterese der Kalibrierung:** Eine neu berechnete Kalibrierung wird nur übernommen, wenn sie sich um mindestens 0,5 °C geändert hat (einstellbar auf der Seite **Raum und Heizverhalten**, 0 schaltet ab). Die Thermostate werden so nicht bei jeder kleinen Temperaturschwankung nachgestellt; das schont Batterie und Ventilmotor.
- **Ersatzwert bei Ausfall des Raumfühlers:** Ist der Raumfühler nicht verfügbar, regelt die Integration mit dem Mittelwert der Thermostat-Temperaturen weiter, wie der „degraded mode“ von Better Thermostat. Der Status nennt den Ersatzwert, das Attribut `room_temperature_source` ist dann `thermostats`. In dieser Zeit wird weder gelernt noch die Kalibrierung neu berechnet. Melden auch die Thermostate keine Temperatur, wird wie bisher nichts geschrieben.

## Version 0.4.3: Thermostat-Warnungen

- **Neuer Sensor „Thermostat-Problem“:** Er ist an, sobald ein Thermostat des Raums nicht erreichbar ist, seine Batterie bei 20 % oder darunter liegt oder ein Problem-Sensor desselben Geräts (z. B. der Ventilalarm der Aqara-Köpfe) meldet. Das Attribut `warnings` listet die Meldungen je Thermostat, der Statussensor zeigt sie im Attribut `thermostat_warnings`. Für eine Benachrichtigung reicht eine Automation auf diesen Sensor.
- Gelesen werden die Batterie- und Problem-Entitäten, die zum selben Gerät wie das Thermostat gehören; es muss nichts zusätzlich eingestellt werden.
