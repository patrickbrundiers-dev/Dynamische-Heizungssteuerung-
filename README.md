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

Die Abkühlrate wird nur gelernt, wenn das Fenster geschlossen ist, der Schedule-Helfer inaktiv ist und das Thermostat auf einer Absenktemperatur steht. Das Lernen ignoriert kleine/unplausible Temperaturänderungen und begrenzt die resultierende Rate. Anfangs wird ein konservativer Startwert verwendet; der Wert wird erst durch reale stabile Beobachtungen angepasst. Außentemperaturkorrektur und Abkühlrate sind Schätzungen, keine Wetter- oder Gebäudesimulation.

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

## Version 0.4.4: Raumtemperatur an die Thermostate senden

- **Externer Sensor im Thermostat (optional):** Manche Thermostatköpfe, z. B. Aqara E1 über Zigbee2MQTT, können statt ihres eigenen Fühlers eine externe Temperatur verwenden. Ist **Raumtemperatur an die Thermostate senden** auf der Seite **Raum und Heizverhalten** aktiv, schaltet die Integration sie auf den externen Sensor und schickt ihnen die Temperatur des Raumfühlers, wie Better Thermostat. Das Ventil regelt dann selbst nach der Raumtemperatur; genauer als das Verschieben des Sollwerts und ohne Nachstellen alle 10 Minuten.
- Erkannt werden Thermostate, deren Gerät eine Auswahl mit den Optionen `internal`/`external` und eine Zahl `…external_temperature…` hat. Andere Thermostate desselben Raums werden wie bisher (gegebenenfalls kalibriert) angesteuert.
- Gesendet wird, wenn sich die Raumtemperatur um mindestens 0,1 °C ändert, sonst spätestens alle 30 Minuten. Ist die Regelung aus, der Raumfühler nicht verfügbar oder wird die Integration entladen bzw. die Option abgeschaltet, werden die Thermostate wieder auf ihren eigenen Sensor geschaltet.
- Das Attribut `external_temperature_thermostats` am Statussensor nennt die Thermostate, die gerade die Raumtemperatur erhalten.

## Version 0.4.5: Komfort je Zeitfenster und Boost

- **Komforttemperatur je Zeitfenster:** Ein Block im Zeitplan-Helfer kann unter „Zusätzliche Daten“ eine eigene Temperatur tragen, z. B. `temperature: 22`. Solange dieser Block aktiv ist, gilt sie statt der Komforttemperatur des Raums; Blöcke ohne Angabe nutzen weiter die normale Komforttemperatur. Das Vorheizen zielt auf die normale Komforttemperatur, weil der Zeitplan die Daten des nächsten Blocks erst zeigt, wenn er beginnt. Die Attribute `comfort_temperature` und `schedule_comfort_temperature` zeigen den gerade gültigen Wert.
- **Boost:** Der neue Schalter **Boost** heizt für die eingestellte Dauer (Standard 60 Minuten) auf die Boost-Temperatur (Standard 24 °C) und schaltet sich danach selbst aus. Boost hat Vorrang vor Zeitplan, Anwesenheit und Heizgrenze, nicht aber vor einem offenen Fenster oder ausgeschalteter Heizperiode. Temperatur und Dauer stehen auf der Seite **Raum und Heizverhalten**.

### Selbstüberwachung (Version 0.4.7)

- **Thermostat-Problem** meldet schwache Batterien, nicht erreichbare Thermostate und Gerätefehler. Den `valve_alarm` der Aqara E1 ignoriert er, weil die Ventilerkennung ihn auch bei einwandfrei arbeitenden Ventilen tagelang setzt.
- **Heizproblem** schaltet ein, wenn der Raum mindestens 1 °C unter dem Ziel liegt und sich in zwei Stunden um weniger als 0,5 °C erwärmt (Ventil hängt, Heizung aus, Vorlauftemperatur zu niedrig). Geprüft wird in festen Zwei-Stunden-Abschnitten, damit auch ein Raum auffällt, der nur in kleinen Schritten hochkriecht; ein Neustart setzt die Zeit nicht zurück. Das Attribut `detail` sagt, was der Raum stattdessen erreicht. Bei offenem Fenster und manueller Übersteuerung wird nicht überwacht.
- Kommt ein Thermostat nach einem Funk- oder Neustart-Ausfall mit einem anderen Sollwert zurück, wird das Ziel erneut gesendet und nicht als manuelle Änderung gewertet.
- Meldet der Raumfühler sechs Stunden lang keinen Wert, gilt er als ausgefallen: Die Regelung nutzt dann die Thermostat-Messwerte, und Thermostate mit externem Fühler werden auf ihren eigenen Sensor zurückgestellt.
- Abwesenheit pausiert das Lernen nicht mehr; nur ein offenes Fenster tut das. So wird nachts im Absenkbetrieb die Abkühlrate gelernt.

### Schnellauswahl und Benachrichtigungen (Version 0.4.8)

- **Betriebsart** (Auswahl-Entität) mit *Automatik*, *Komfort*, *Eco*, *Boost* und *Aus*. Komfort, Eco und Aus gelten bis zum nächsten Wechsel des Komfort-Zeitplans, danach regelt der Raum wieder automatisch. Boost läuft wie der Boost-Schalter für die eingestellte Dauer. Aus hält die Frostschutztemperatur (ohne sie das Thermostat-Minimum). Ein offenes Fenster und das Ende der Heizperiode haben weiter Vorrang. Das Beispiel-Dashboard zeigt die Auswahl als Tastenreihe.
- **Push-Benachrichtigung** (Editor, Seite 4): ein Notify-Dienst wie `notify.mobile_app_patrick`. Bei aktiver Regelung meldet er Thermostat-Probleme, einen ausgefallenen Raumfühler oder eine wartende Regelung nach 30 Minuten, ein Heizproblem und Frostgefahr sofort, und ein Fenster, das in der Heizperiode über eine Stunde offen ist. Jede Meldung kommt einmal; endet das Problem, folgt eine „Wieder in Ordnung“-Meldung.

## Version 0.5.0: Proximity-Zone, Neustartfestigkeit und Dauer der Betriebsart

- **Proximity-Zone** (Editor, Seite 3): Es reicht, die Zone der Proximity-Integration (z. B. *Home*) auszuwählen. Die Entfernungs- und Richtungssensoren der Personen dieses Raums werden automatisch gefunden; andere Personen der Zone zählen nicht. Ohne eingetragene Personen gilt die Person, die der Zone am nächsten ist. Die Zone ist nur aktiv, solange keine dieser Personen zuhause ist. Ist mindestens eine zuhause, **schlummert** sie. Sind alle weg und die Standortdaten zu alt, bleibt der Raum abgesenkt, statt die Regelung anzuhalten. Die früheren Felder für Entfernungs- und Richtungssensor entfallen; bestehende Einstellungen gelten weiter, bis die Seite gespeichert wird.
- **Neustartfest**: Betriebsart mit Endzeit, Boost, bereits gesendete Meldungen und die Entscheidung des Anwesenheitssensors bleiben über einen Neustart von Home Assistant erhalten.
- **Betriebsart-Dauer** (Auswahl-Entität): *Bis Zeitplanwechsel*, *1 Stunde*, *3 Stunden*, *Bis morgen früh* (6 Uhr) oder *Dauerhaft*. Gilt für Komfort, Eco und Aus; eine laufende Betriebsart wird neu getaktet.

## Version 0.5.1: Haus, Räume, Wetter, Wochenbericht und Raumkarte

- **Haus-Einstellungen** (Integration hinzufügen → *Haus-Einstellungen*): **Hausmodus** *Zuhause*, *Abwesend* oder *Urlaub* für alle Räume. *Abwesend* senkt jeden Raum auf seine Abwesenheitstemperatur (sonst Eco). *Urlaub* hält den Frostschutz und heizt bis **Urlaub bis** rechtzeitig auf Komfort vor; danach steht der Hausmodus wieder auf Zuhause. Beim Wechsel auf Abwesend oder Urlaub werden von Hand gewählte Betriebsarten der Räume zurückgesetzt. Ein offenes Fenster hat weiter Vorrang.
- **Raum kopieren** (Integration hinzufügen → *Raum mit den Einstellungen eines anderen Raums anlegen*): Nur Thermostate, Raumfühler, Zeitplan, Fensterkontakt und Anwesenheitssensor des neuen Raums werden abgefragt, alles andere kommt aus dem Vorlage-Raum.
- **Übersicht**: Der Sensor *Räume heizen* des Hauses zählt die Räume, die gerade heizen, und listet jeden Raum mit Ist, Soll, Status und Problemen in seinen Attributen.
- **Vorheizen mit Wettervorhersage**: Mit einer Wetter-Entität wird die Vorheizzeit mit der vorhergesagten Außentemperatur zum Komfortbeginn berechnet, also an kalten Morgen früher und an milden später. Sensor *Vorhergesagte Außentemperatur zum Komfortbeginn*.
- **Fenster ohne Kontakt erkennen** (Editor, Seite 4): Fällt die Raumtemperatur innerhalb von 10 Minuten um 1 °C, wird der Raum 15 Minuten wie bei offenem Fenster abgesenkt.
- **Wärmebedarf**: Sensor je Raum (0–100 %, aus den Ventilöffnungen oder aus dem Abstand zum Soll geschätzt) und *Wärmebedarf* des Hauses (höchster Raum, Durchschnitt und alle Räume als Attribute), z. B. für eine Therme.
- **Wochenbericht**: Sonntags um 18 Uhr eine Meldung an den Benachrichtigungsdienst des Hauses (sonst den des ersten Raums) mit Heizstunden, Durchschnittstemperatur, offenen Fenstern beim Heizen und Meldungen je Raum. Taste *Wochenbericht senden* schickt ihn sofort.
- **Raumkarte**: Die Integration bringt die Karte *Dynamische Heizung* mit. Im Dashboard *Karte hinzufügen* → *Dynamische Heizung*; es reicht die Betriebsart-Entität des Raums:

  ```yaml
  type: custom:dynamic-heating-card
  entity: select.dynamische_heizungssteuerung_betriebsart
  ```

## Version 0.5.2: Tasten zur manuellen Übersteuerung wie bei Better Thermostat

- **Neue Betriebsarten** wie die Presets von Better Thermostat: *Zuhause*, *Aktivität*, *Schlafen* und *Abwesend*, zusätzlich zu *Automatik*, *Komfort*, *Eco*, *Boost* und *Aus*. Sie gelten wie Komfort und Eco für die gewählte **Betriebsart-Dauer**; ein offenes Fenster und das Ende der Heizperiode haben weiter Vorrang.
- **Temperaturen** (Editor, Seite **Raum und Heizverhalten**): *Zuhause* 20 °C, *Aktivität* 22 °C, *Schlafen* 18 °C als Standard. *Abwesend* nutzt die Abwesenheitstemperatur, ohne sie die Eco-Temperatur.
- **Tasten je Raum**: Für jede Betriebsart gibt es eine Taste-Entität (z. B. `button.<raum>_schlafen`), die den Raum sofort umschaltet, auch für Automationen, Sprachassistenten oder NFC-Tags. Das Attribut `active` zeigt, ob diese Betriebsart gerade läuft.
- **Raumkarte**: zeigt alle Betriebsarten als Tasten mit Symbol. Mit `modes:` lässt sich die Auswahl eingrenzen, z. B. `modes: [Automatik, Komfort, Schlafen, Abwesend, Boost]`.

## Version 0.5.3: Raum-Thermostat wie bei Better Thermostat

- **Thermostat-Entität je Raum** (`climate.<raum>_heizung` o. ä.): zeigt Raumtemperatur und das Ziel, das die Steuerung gerade gewählt hat. Damit funktionieren die normale Thermostat-Karte, Mushroom-, Tile- und Better-Thermostat-Karten sowie Sprachassistenten wie bisher mit dem BT-Thermostat.
- **Temperatur einstellen**: hält den Wert für die gewählte **Betriebsart-Dauer** (z. B. bis zum nächsten Zeitplanwechsel), danach regelt der Raum wieder automatisch. Die Betriebsart zeigt dann *Manuell*, der Status z. B. „21,5 °C von Hand bis 22:30 Uhr“. Der Wert übersteht Neustarts.
- **Presets** sind die Betriebsarten (*Komfort*, *Zuhause*, *Aktivität*, *Eco*, *Schlafen*, *Abwesend*, *Boost*); *Kein Preset* ist Automatik.
- **Aus** setzt die Betriebsart *Aus* (Frostschutz), **Heizen** geht zurück auf Automatik.
- Ein offenes Fenster und das Ende der Heizperiode haben weiter Vorrang.

## Version 0.6.0: Ideen aus Advanced Heating Control

- **Drehen am Ventil gilt für den Raum**: Wird an einem Thermostat gedreht, bekommen alle Thermostate des Raums diesen Wert. Er gilt als Betriebsart *Manuell* für die eingestellte Betriebsart-Dauer (Option *Drehen am Ventil gilt für den Raum*, standardmäßig an). Ausgeschaltet pausiert die Regelung wie bisher bis zum nächsten Moduswechsel.
- **Abgestufte Abwesenheit**: Mit *Absenkung bei leerem Raum* heizt ein Raum, in dem gerade niemand ist, während jemand zuhause ist, zur Komfortzeit auf Komfort minus diesen Wert (nicht unter Eco) statt abzusenken. Optional gilt das auch, wenn niemand zuhause ist.
- **Frostschutz nach Abwesenheit**: Ist so lange niemand zuhause wie unter *Frostschutz nach Abwesenheit* eingestellt, hält der Raum den Frostschutz. Der Beginn der Abwesenheit übersteht einen Neustart.
- **Mehrere Zeitpläne**: Unter *Weitere Zeitpläne* lassen sich zusätzliche Komfort-Zeitpläne angeben (z. B. Ferien, Homeoffice). Die Auswahl-Entität **Zeitplan** des Raums legt fest, welcher gilt; Automationen können sie umschalten.
- **Eco-Zeitplan**: Ein Zeitplan-Helfer, dessen Blöcke in den Zusatzdaten `temperature: 17` tragen, ersetzt während des Blocks die Absenktemperatur, z. B. nachts kühler als tagsüber.
- **Betriebsart Wartung**: Öffnet alle Ventile voll (Thermostat-Maximum), auch bei offenem Fenster und außerhalb der Heizperiode, z. B. für Thermenwartung oder Schornsteinfeger. Gilt für die Betriebsart-Dauer.
- **Ereignis `dynamic_heating_mode_changed`**: Bei jedem Wechsel von Modus oder Sollwert, mit `room`, `mode`, `previous_mode`, `target_temperature`, `status`, `present`, `window_open`, `active_schedule` und `quick_mode`.
- **Aggressiv-Modus**: Liegt der Raum weiter als der eingestellte Bereich unter oder über dem Soll, wird Soll plus bzw. minus Versatz an die Ventile gesendet. Angezeigt wird weiter der eigentliche Sollwert. Standardmäßig aus.
- **Fenstererkennung der Thermostate abschalten**: Bei aktiver Regelung und vorhandenem Fensterkontakt schaltet die Integration die eigenen Fenstererkennungs-Schalter der Thermostate (`…_window_detection`, z. B. Aqara E1) aus.

## Version 0.7.0: Ideen aus Better Thermostat und Climate Group Helper

- **Mehrere Fenster- und Türkontakte**: Unter *Weitere Fenster- und Türkontakte* zählt jeder offene Kontakt, mit denselben Verzögerungen. Ein ausgefallener zusätzlicher Kontakt gilt als geschlossen.
- **Kalender als Zeitplan**: Statt eines Zeitplan-Helfers kann auch eine Kalender-Entität dienen, als Haupt-, weiterer oder Eco-Zeitplan. Ein laufender Termin ist Komfortzeit; `temperature: 22` in der Beschreibung setzt die Temperatur.
- **Temperatur-Regler**: Komfort-, Eco-, Zuhause-, Aktivität-, Schlafen- und Boost-Temperatur gibt es als Regler-Entitäten fürs Dashboard (wie die Preset-Temperaturen von Better Thermostat). Sie werden in den Raum-Optionen gespeichert, ohne den Raum neu zu laden.
- **Raum-Versatz**: verschiebt alle Sollwerte des Raums um bis zu ±3 °C (nicht bei offenem Fenster, Frostschutz, Aus, Wartung). Eine direkt am Raum-Thermostat eingestellte Temperatur setzt ihn auf 0.
- **Versatz je Ventil**: Bei mehreren Thermostaten pro Raum bekommt jedes einen eigenen Versatz-Regler, z. B. für ein Ventil in einer kalten Ecke.
- **Ventile sperren**: Wird an einem Thermostat gedreht, stellt die Regelung den Sollwert des Raums sofort wieder her. Hat Vorrang vor „Drehen am Ventil gilt für den Raum“.
- **Kindersicherung**: Ein Schalter je Raum sperrt die Tasten aller Thermostate, wenn sie einen Kindersicherungs-Schalter haben (z. B. Aqara E1).
- **Luftfeuchte**: Ein optionaler Luftfeuchtesensor wird am Raum-Thermostat angezeigt.
- **Temperaturtrend**: Sensor mit der Änderung der Raumtemperatur in °C pro Stunde über die letzte halbe Stunde.

## Version 0.8.0: Weitere Ideen aus AHC, Better Thermostat und Climate Group Helper

- **Heizgrenze nach dem Durchschnitt** (Editor, Seite 4, standardmäßig an): Entscheidend ist der Durchschnitt der Wettervorhersage für die nächsten zwei Tage, ohne Vorhersage der Durchschnitt des Außenfühlers der letzten zwei Tage (nach sechs Stunden Messwerten), sonst die aktuelle Temperatur. Ein warmer Nachmittag stellt die Komfortheizung so nicht mehr ab. Der Sensor *Außentemperatur für die Heizgrenze* zeigt den Wert, das Attribut `heating_limit_source` seine Herkunft. Mit *Ohne Außentemperatur nicht heizen* gilt die Heizgrenze als erreicht, wenn es gar keinen Außenwert gibt.
- **Raumtemperatur klüger an die Ventile senden**: Eine Änderung ab 0,11 °C geht sofort raus, eine kleinere ab 0,05 °C erst, wenn sie zwei Minuten stabil ist. Ein Fühler, der zwischen zwei Werten springt, weckt die Ventile nicht mehr bei jedem Zyklus; spätestens alle 30 Minuten wird trotzdem gesendet.
- **Änderungen bei offenem Fenster** (Seite 4): Wird bei offenem Fenster am Ventil gedreht, wird nicht geheizt. Der Wert wird gemerkt und gilt als *Manuell*, sobald das Fenster zu ist, oder er wird verworfen (dann lehnt auch das Raum-Thermostat eine Änderung beim Lüften ab).
- **Unplausible Raumtemperatur**: Werte unter −5 °C oder über 45 °C werden ignoriert, der Raum regelt mit den Thermostat-Messwerten weiter, und unter *Einstellungen → Reparaturen* erscheint eine Meldung, bis wieder plausible Werte kommen.
- **Haus-Kalender** (Haus-Einstellungen): Ein Kalender oder Zeitplan fürs ganze Haus. Ein laufender Termin wählt in jedem Raum den Zeitplan, den sein Titel oder `zeitplan: Ferien` nennt; Räume ohne passenden Zeitplan bleiben unverändert. Mit `komfort: an` oder `temperature: 21` in der Beschreibung ist der Termin in allen Räumen Komfortzeit. Ein Raum kann das mit *Haus-Kalender folgen* abschalten.
- **Türen und Kontakte für mehrere Räume** (Seite 4): Türkontakte mit eigener Verzögerung (Standard 10 Minuten) und Kontakte wie die Terrassentür mit eigener Verzögerung (Standard 5 Minuten).
- **Pause zwischen Ventilbefehlen** (Seite 1): Abstand zwischen zwei Befehlen an Ventile, auch über Räume hinweg, damit Zigbee bei vielen gleichzeitigen Befehlen keinen verschluckt. Standard 0.
- **Einstellungen übertragen** (Haus → Konfigurieren → *Einstellungen auf Räume übertragen*): Schreibt gewählte Gruppen (Temperaturen, Fenster, Anwesenheit, Ventile, Außentemperatur) eines Raums in andere Räume. Geräte werden nie übertragen.
- **Abweichende Ventile**: Meldet ein Ventil 15 Minuten lang einen anderen Sollwert als geschrieben, steht das im Attribut `valve_divergence` und im *Thermostat-Problem*.
- **Komfort oder Eco erzwingen** (Seite 2): Schalter, Sensoren oder Timer halten den Raum auf Komfort bzw. Eco, solange sie an sind. Endet der Name auf eine Zahl („Party 23“), gilt diese Temperatur. Ein offenes Fenster hat Vorrang.
- **Zeitplan-Blöcke, die Funktionen pausieren**: `fenster: aus` in den Zusatzdaten eines Blocks (oder in der Beschreibung eines Kalendertermins) ignoriert die Fensterkontakte, `anwesenheit: aus` die Anwesenheit.
- **Ventil auslassen**: Bei mehreren Thermostaten gibt es je Ventil einen Schalter *Auslassen …*. Das Ventil wird einmal geschlossen und dann in Ruhe gelassen, zählt nicht für den Wärmebedarf und wird von „Ventile sperren“ nicht zurückgedreht. Mindestens ein Ventil bleibt immer aktiv.
- **Logbuch, Gerätetrigger und letzte Änderung**: Jeder Moduswechsel steht mit Grund im Logbuch des Statussensors. Im Automationseditor gibt es für den Raum die Auslöser *Heizen beginnt/endet*, *Zieltemperatur erreicht*, *Fenster geöffnet/geschlossen* und *Luftfeuchte hoch*. Die Attribute `last_change_source` und `last_change_at` zeigen, was den Sollwert zuletzt geändert hat (Automatik, Taste, Betriebsart, Raum-Thermostat, Ventil, Hausmodus, Boost).
- **Ventilwartung einstellbar** (Seite 1): Wochentag, Stunde und Dauer je Phase. Die Taste *Ventilwartung starten* startet sie sofort. Ausgeschaltete Ventile werden dafür eingeschaltet und danach wieder ausgeschaltet.
- **Überschwingen lernen**: Nach dem Heizen wird gemessen, wie weit die Raumtemperatur noch steigt (Sensor *Gelerntes Überschwingen*). Das Vorheizen endet um so viel früher.

## Version 0.9.0: Intelligente Regelung

Neue Editor-Seite 5 *Intelligente Regelung*. Alles ist standardmäßig an, wirkt aber erst, wenn das Raummodell genug Daten hat.

- **Raummodell**: Statt einer festen Aufheizrate lernt der Raum aus jeder Stunde Regelbetrieb eine Gleichung aus Heizleistung, Wärmeverlust nach außen, Sonne und Wind. Beim ersten Start lernt es aus den letzten 7 Tagen im Recorder (Raum-, Außentemperatur und Sensor *Wärmebedarf*). Bereit ist es nach mindestens 12 Stunden, davon 3 mit und 3 ohne Heizen. Sensoren: *Raummodell* (Status, Attribute mit Stundenzahl und Fehler), *Erreichbare Temperatur*, *Heizleistung*, *Wärmeverlust je 10 °C Unterschied*, *Sonnengewinn je kW/m²*. Das Vorheizen wird damit physikalisch berechnet.
- **Absenkung nach Rückkehrzeit**: Außerhalb der Komfortzeit wird nur so tief abgesenkt, dass der Raum innerhalb der maximalen Vorheizzeit wieder Komfort erreicht; ist Komfort heute gar nicht erreichbar, zählt das Erreichbare. Ist der Raum leer, obwohl jemand zuhause ist, muss er innerhalb von *Raum leer: in dieser Zeit wieder warm* (Standard 60 Minuten) zurück sein. Ist niemand zuhause, gilt die normale Absenkung.
- **Vorheizen, wenn jemand zuhause ist**: Auch ein leerer Raum wird vor einem Komfortblock vorgeheizt, solange jemand im Haus ist. Zu Beginn eines Komfortblocks bleibt Komfort *Komfortbeginn: so lange auf jemanden im Raum warten* (Standard 30 Minuten) erhalten.
- **Raumnutzung lernen**: Aus dem Präsenzmelder lernt der Raum je Wochentag und Stunde, wann er meist genutzt wird. Dann bleibt Komfort auch ohne Bewegung (Attribut `usage_today` am Sensor *Raummodell*).
- **Erreichbare Temperatur**: Liegt das Ziel über dem, was die Heizkörper heute schaffen, steht das im Status („heute erreichbar ca. 20,4 °C“). *Heizproblem* meldet nur noch, wenn der Raum deutlich unter dem Erreichbaren bleibt.
- **Früher abschalten**: Bis zu *Vor Komfortende früher abschalten* (Standard 30 Minuten) vor dem Ende eines Komfortblocks geht die Heizung auf Eco, wenn der Raum am Ziel ist und bis zum Ende höchstens 0,5 °C verliert.
- **Sonne und Wind**: Mit einem Sensor für Sonneneinstrahlung (W/m² oder lx) lernt das Modell den Sonnengewinn; hält die Sonne allein den Raum warm, pausiert die Heizung („Sonne wärmt den Raum“). Ein Windsensor (m/s, km/h, mph, kn) erhöht den gelernten Wärmeverlust bei Wind.

## Version 0.9.1: Raummodell erst bewähren lassen

Ein frisch gelerntes Raummodell steuert nur das Vorheizen. Absenkungsgrenzen, „heute erreichbar“, die Heizproblem-Bewertung und die Sonnenpause greifen erst ab 48 Stunden Daten und einem mittleren Vorhersagefehler unter 0,12 °C/h (Attribut `model_trusted` am Sensor *Raummodell*). „Erreichbar“ heißt jetzt: in sechs Stunden voller Heizung, nicht der rechnerische Endwert, der bei mildem Wetter weit über allem lag, was der Raum je geschafft hat.

## Version 0.9.2: Ruhigere Ventile, ein Lernsystem, Testlauf mit echten Daten

- **Raumtemperatur seltener an die Ventile**: Gesendet wird auf 0,1 °C gerundet und erst ab 0,2 °C Änderung, eine kleinere Änderung von 0,1 °C erst, wenn sie 10 Minuten hält. Ohne Änderung wird alle 2 Stunden erneut gesendet. Mit einer echten Woche aus dem Wohnzimmer sinkt das von 60 auf 27 Sendungen am Tag; jede Sendung lässt das Ventil neu rechnen und oft den Motor laufen.
- **Nach Neustart sicher**: Nach dem Umschalten eines Ventils auf den externen Fühler wird der Wert erst gesendet, wenn das Ventil den Wechsel meldet. Zeigt ein Ventil 2 Minuten nach dem Senden noch eine andere Temperatur (mehr als 0,3 °C daneben), wird der Wert erneut gesendet, höchstens alle 5 Minuten. Bisher regelte ein Ventil nach einem Neustart oder Neuladen bis zu 30 Minuten auf seinen eigenen Fühler.
- **Keine Kalibrierung, während ein Ventil umschaltet**: Ventile mit externem Fühler bekommen nie einen Kalibrier-Versatz, auch nicht in den Sekunden nach einem Neustart. Bisher wurde dann kurz ein Sollwert mit Versatz geschrieben und gleich wieder zurückgenommen.
- **Ein Lernsystem**: Sobald das Raummodell bereit ist, kommen Aufheiz- und Abkühlrate aus dem Modell (Sensoren *Aufheizrate* und *Abkühlrate*, vorher *Gelernte …*), und die alten Einzelmessungen ruhen. Ohne Raummodell lernt der alte Weg wie bisher. Die 11 Sensoren des alten Lernwegs und der Prognoseprüfung (*Akzeptierte/Verworfene Messungen*, *Lernmodell Status*, *Letzte beobachtete …*, *Prognosefehler* usw.) werden entfernt; ihre Werte stehen weiter in den Attributen des Statussensors.
- **Aufgeräumt**: Raten, Modellwerte, Wetterprognose, Heizgrenzen-Basis und Geo-Fencing-Alter sind Diagnose-Sensoren. Die sieben Geo-Fencing-Zähler sind bei neuen Räumen ausgeschaltet. Der Status zählt bei veralteten Standortdaten nicht mehr jede Minute hoch.
- **Testlauf mit echten Daten**: `tests/test_replay_week.py` spielt eine Woche des Wohnzimmers (Raumtemperatur roh, Außentemperatur und Sonne stündlich, keine Anwesenheitsdaten) durch die Regelung und prüft, wie oft sie Ventile anspricht, dass jede Nacht abgesenkt wird und Komfort pünktlich anliegt.

## Version 0.9.3: Heizkörper-Check und Zeiten der Zentralheizung

- **Heizkörper-Check**: Ventile, die ihre eigene Gehäusetemperatur melden (z. B. Aqara E1, Sensor `*_device_temperature`), zeigen, ob heißes Wasser ankommt. Ein Heizkörper gilt als warm, wenn das Gehäuse 3,5 °C über dem Raum liegt oder seit Heizbeginn um 2 °C gestiegen ist. Verlangt der Raum eine Stunde lang volle Wärme (Wärmebedarf ab 50 %) und kein Heizkörper wird warm, steht beim neuen Sensor *Heizkörper* „Kalt – die Zentralheizung liefert keine Wärme“, und der Status endet mit „Heizkörper bleiben kalt“. Bleibt nur einer kalt, nennt der Sensor ihn (entlüften oder Ventil prüfen) und es kommt nach 30 Minuten eine Meldung.
- **Zeiten der Zentralheizung**: Der Raum lernt je Stunde des Tages, ob die Zentralheizung liefert (Attribute `supply_off_hours` und `supply_today` am Sensor *Heizkörper*). Bleiben die Heizkörper zu einer Zeit kalt, in der das üblich ist (z. B. Nachtabsenkung im Mietshaus), sagt der Sensor, ab wann sie meist wieder liefert, und die Heizproblem-Meldung bleibt aus. Sonst nennt die Meldung die Zentralheizung als Ursache statt allgemein Ventile und Vorlauf.
- **Raummodell lernt nur aus Stunden mit Wärme**: Stunden, in denen geheizt werden sollte, die Heizkörper aber kalt blieben, zählen nicht mehr. Bisher lernte das Modell daraus eine viel zu kleine Heizleistung und plante beim Vorheizen immer die volle Zeit. Ein mit 0.9.2 oder älter gelerntes Modell wird einmal verworfen und neu aus dem Recorder angelernt (dann mit den Gehäusetemperaturen).
- **Wochenbericht**: nennt zusätzlich die geschätzte Ersparnis gegenüber Dauer-Komfort (aus der Temperaturdifferenz zu draußen, nach der sich der Wärmeverlust richtet), die Stunden mit kalten Heizkörpern trotz Heizbedarf und wie gut das Raummodell liegt.

## Version 0.13.0: Wärmezähler, Spar-Rechner und Fragen über Assist

- **Wärmezähler**: Jeder Raum hat den Sensor *Wärmemenge* (kWh, steigt nur), das Haus die Summe aller Räume. Gerechnet wird Wärmebedarf (Ventilöffnung) mal Heizkörperleistung mal Zeit; Zeiten, in denen die Heizkörper kalt bleiben (Nachtpause der Therme), zählen nicht. Die Leistung stellst du je Raum in den Einstellungen unter *Ventile im Detail → Heizkörperleistung für den Wärmezähler* ein, ohne Angabe gelten 1000 W je Thermostat. Es ist eine Schätzung, kein geeichter Zähler. Attribute: `today_kwh`, `yesterday_kwh`, `last_7_days_kwh`. Die Haus-Summe lässt sich im Energie-Dashboard als Gasverbrauch (kWh) eintragen; sie fällt nie, auch nicht während ein Raum neu startet. Der Wochenbericht nennt die Wärme der Woche.
- **Spar-Rechner**: Die Taste *Sparen?* in der Raumkarte rechnet die nächsten 7 Tage mit dem gelernten Raummodell zweimal durch, einmal wie eingestellt und einmal mit anderer Eco- oder Komforttemperatur oder späterem Komfortbeginn, z. B. „Eco 17,0 statt 18,0 °C: ca. 6 % weniger Wärme (etwa 3,0 kWh weniger in 7 Tagen). Trotzdem pünktlich warm.“ Erst *Übernehmen* ändert Eco und Komfort; Zeiten änderst du im Zeitplan. Dahinter steht die Aktion `dynamic_heating.estimate_savings` (mit Antwort) für eigene Automationen. Anwesenheit, Fenster und Sonne rechnet sie nicht mit.
- **Fragen über Assist** (Home-Assistant-App, Sprachassistent mit dem eingebauten Agenten): „Warum ist es im Bad kalt?“, „Wann ist das Wohnzimmer warm?“, „Wie viel Wärme hat Leonie heute verbraucht?“, „Wie viel hat die Heizung heute verbraucht?“, „Wie läuft die Heizung?“. Die Antwort nennt den Grund (Fenster offen, Zentralheizung liefert nicht, Ziel erreicht, Heizproblem) und aus dem Tagesplan, wann es warm ist. Alexa über Nabu Casa kann nur schalten, nicht fragen.

## Version 0.11.0: Zeitplan als Graph bearbeiten

- **Zeitplan-Editor in der Raumkarte**: Die Taste *Zeitplan* in der Karte *Dynamische Heizung* klappt den Zeitplan des Raums als Graph auf. Gibt es mehrere Zeitpläne (z. B. *Kinderzimmer Schulfrei*), stehen sie oben zur Wahl, der gerade aktive hat einen grünen Punkt. Die Integration bleibt der einzige Regler: Bearbeitet wird der Zeitplan-Helfer selbst, wie unter *Einstellungen → Helfer*.
- **Bedienung**: Tippen auf eine freie Stelle legt einen Block von 2 Stunden an. Block seitlich ziehen verschiebt ihn, nach oben oder unten ändert die Temperatur (in 0,5 °C), die Ränder ändern Anfang und Ende (in 15 Minuten). Ein angetippter Block lässt sich auch über Von/Bis, −/+ und *Löschen* einstellen; *Komforttemperatur* nimmt die eigene Temperatur wieder heraus. Ein Tag lässt sich auf Mo–Fr, Sa–So oder alle Tage kopieren. Erst *Speichern* schreibt den Zeitplan.
- **Was der Graph zeigt**: Orange die Komfortblöcke mit ihrer Temperatur (aus den Zusatzdaten `temperature`, sonst die Komforttemperatur des Raums, markiert mit „K“), grau gestrichelt Eco dazwischen und blau die Raumtemperatur des gewählten Tages (heute oder der letzte gleiche Wochentag). Andere Zusatzdaten eines Blocks (z. B. Pausen) bleiben erhalten.
- **Eigene Karte** *Dynamische Heizung – Zeitplan* für eine breite Ansicht, z. B. auf dem Tablet:

  ```yaml
  type: custom:dynamic-heating-schedule-card
  entity: select.leonie_heizung_betriebsart
  ```

  Speichern dürfen nur Administratoren (wie im Helfer-Editor). Zeitpläne aus der YAML-Konfiguration werden nur angezeigt. Mit `schedule_editor: false` blendet die Raumkarte die Taste aus.
- **Status-Sensor**: neue Attribute `schedules`, `active_schedule` und `eco_temperature`.
- **0.11.1**: Von/Bis zeigen Zeiten außerhalb des 15-Minuten-Rasters (z. B. 05:10 aus dem Helfer-Editor) richtig an, statt auf 00:00 zu springen.

## Version 0.10.0: Übergabe zuhause, fremde Automationen, Gute Nacht, Schulfrei, Duschzeiten

- **Kurze Übergabe ist nicht „alle weg“**: Die Wartezeit nach dem Verlassen ist jetzt 10 Minuten. Bisher stand sie auf 2 – gemeint waren Minuten, gelesen wurden Sekunden; Räume mit diesem alten Wert bekommen beim Update die 10 Minuten. Die Wartezeit gilt auch, wenn eine Person direkt in eine andere Zone wechselt (z. B. „Arbeit“). Während des Vorheizens zählt eine gerade gegangene Person 15 Minuten lang noch als zuhause, damit die schon eingesetzte Wärme nicht verloren geht.
- **Wächter für fremde Automationen**: Stellt eine Automation oder ein Skript die Ventile eines Raums, gibt es einen Eintrag unter *Einstellungen → Reparaturen*, eine Logbuch-Zeile und höchstens einmal am Tag eine Meldung mit dem Namen der Automation. Der Eintrag verschwindet, sobald die Automation aus ist (ein Skript nach einem Tag). Attribut `foreign_control` am Status-Sensor.
- **Obergrenze für Handänderungen** (unter *Betriebsarten*, aus): *Höchstwert für Handänderungen* begrenzt, was am Ventil, in der App oder am Raum-Thermostat eingestellt wird (Status z. B. „27,5 °C gedreht – auf 23 °C begrenzt“); *Längste Dauer einer Handänderung* lässt den Raum danach zum Zeitplan zurückkehren.
- **Gute Nacht**: Haus-Taste *Gute Nacht* (auch für Alexa). Alle Räume, die gerade Komfortzeit haben, gehen sofort auf die Temperatur „Schlafen“, bis ihr Komfortblock endet. Räume außerhalb der Komfortzeit bleiben, wie sie sind, das Vorheizen am Morgen läuft normal.
- **Schulfrei in der Integration** (unter *Betriebsarten*): *Schulfrei heute* und *Zeitplan an schulfreien Tagen* wählen den Zeitplan selbst, wie bisher eine Automation. Mit *Arbeitstag-Sensor* (Workday) und *Ferienkalender* weiß der Tagesplan schon am Abend, ob morgen schulfrei ist, und plant ab Mitternacht mit dem richtigen Zeitplan („… (morgen schulfrei)“).
- **Duschzeiten lernen** (unter *Intelligente Regelung*, aus): Steigt die Luftfeuchte im Bad in 20 Minuten um mindestens 6 Punkte, gilt das als Duschen. Beim ersten Start werden die letzten 10 Tage aus dem Verlauf gelesen. Wird an mindestens drei Tagen zur ähnlichen Zeit geduscht und hat der Zeitplan 30 Minuten vorher keine Komfortzeit, zeigt *Zeitplan-Vorschlag* z. B. „Montag bis Freitag gegen 06:15 Uhr wird geduscht – Komfort im Bad ab 05:45 Uhr in den Zeitplan?“. In der Stunde nach dem Duschen lernt das Raummodell nicht (das warme Wasser heizt mit).
- **Geo-Fencing einmal fürs Haus**: Neuer Haus-Sensor *Geo-Fencing* mit Entfernung, Alter und Zählern. Die gleichen Sensoren in den Räumen sind beim Update deaktiviert (nicht gelöscht) und bei neuen Räumen standardmäßig aus. Die Zähler zählen je Person: Bisher zählte „veraltete Standortereignisse“ bei zwei Personen in jedem Durchlauf hoch.

## Version 0.9.9: Nachtpause der Therme, echte Nachtauskühlung, Tuya-Ventile

- **Nachtpause der Therme erkennen**: Ob die Zentralheizung liefert, sagt jetzt auch der Raum selbst. Verlangt er eine Stunde lang Wärme (Wärmebedarf ab 50 %, mindestens 0,5 °C unter dem Ziel) und kühlt dabei weiter ab, kommt keine Wärme an, auch wenn ein Ventilgehäuse warm aussieht. Räume ohne Gehäusetemperatur (z. B. Tuya-Ventile) werden so überhaupt erst beurteilt. Die bisher gelernten Lieferzeiten werden einmal verworfen, weil sie die Nachtpause als „liefert“ gelernt hatten. Während die Zentralheizung nicht liefert, gibt es keine „entlüften“-Meldung und der Heizkörper-Abgleich lernt nichts. Die Haus-Meldung „Zentralheizung liefert keine Wärme“ kommt nicht zwischen 22 und 7 Uhr.
- **Vorheizen wartet auf die Therme**: In Stunden, in denen die Zentralheizung üblicherweise nichts liefert, bleibt der Raum auf Eco („Vorheizen wartet auf die Zentralheizung (liefert meist ab 5:00 Uhr)“), statt die Ventile umsonst zu öffnen. Der Tagesplan rechnet genauso und sagt es, z. B. „um 05:30 Uhr ca. 19,5 °C (Ziel 21,0 °C), Zentralheizung liefert erst ab 05:00 Uhr“. Neue Option *Abends bis zur Pause der Zentralheizung warm halten* (aus): Endet der Komfort kurz vor der Nachtpause, bleibt er bis zu deren Beginn.
- **Pünktlichkeit lernt nicht aus Morgen ohne Wärme**: War die Zentralheizung beim Vorheizen aus, zählt eine Verspätung nicht für die Vorheiz-Korrektur. Die bisher gelernten Morgen werden einmal verworfen.
- **Echte Nachtauskühlung**: Je zwei Stunden ohne Wärme vergleicht der Raum, wie stark er wirklich abgekühlt ist, mit dem Raummodell und lernt daraus einen Faktor (Attribut `cooling_factor`, ab zwei Vergleichen). Tagesplan, Vorheizen und Absenkung rechnen damit. Die stündliche Wettervorhersage wird um ihren aktuellen Fehler gegenüber dem eigenen Außenfühler korrigiert (über 12 Stunden auslaufend).
- **Ventilfühler kalibrieren** (Option unter *Ventile im Detail*, aus): Für Ventile ohne Eingang für die Raumtemperatur stellt die Integration `local_temperature_calibration` so ein, dass das Ventil ungefähr die Raumtemperatur misst (Median der letzten 3 Stunden, höchstens alle 3 Stunden). Folgt die Anzeige des Ventils der Kalibrierung nicht, wird sie zurückgesetzt und das Ventil in Ruhe gelassen.
- **Notprogramm auch für Tuya-Ventile**: Mit *Notprogramm im Ventil* bekommen Ventile mit eigenem Wochenprogramm (`text.*_schedule_monday` …) laufend den Wochenplan des aktiven Zeitplans (sechs Schaltpunkte je Tag). Beim Herunterfahren schalten sie auf `auto`, nach dem Start wieder auf `heat`.
- **Morgenmeldung** (Option unter *Intelligente Regelung*, an): Lag der Raum zum Komfortbeginn mindestens 0,5 °C unter dem Ziel, kommt um 7 Uhr (oder zum späteren Komfortbeginn) eine Meldung mit dem Grund.
- **Kleinigkeiten**: Nach einem Start springt die Außentemperatur nicht mehr kurz auf den Wert der Wettervorhersage, solange der eigene Fühler noch fehlt (10 Minuten Wartezeit). „Heute erreichbar“ fehlt, solange der Raum deutlich schneller warm wird, als das Raummodell erlaubt (z. B. ein neu übernommener Raum).

## Version 0.9.7: Pünktlich warm, Kalibrierlauf, Push mit Knöpfen

- **Entitäten heißen wie der Raum**: Entitäten, die angelegt wurden, als das Gerät noch „Dynamische Heizungssteuerung“ hieß (`*.dynamische_heizungssteuerung_*`), bekommen beim Start die IDs des Gerätenamens, z. B. `*.schlafzimmer_heizung_*`. Eine schon vergebene ID bleibt unangetastet. Neue Räume heißen gleich „<Bereich> Heizung“, wenn das Ventil einem Bereich zugeordnet ist.
- **Kalibrierlauf**: Taste *Raummodell kalibrieren* (jetzt) oder *Kalibrierlauf um* (geplant, z. B. wenn niemand im Raum ist). Der Raum heizt zwei Stunden voll (Ventile auf Raumtemperatur + 4 °C), danach regelt er wieder normal. So lernt das Raummodell die Heizleistung in einem Rutsch. Stunden mit warmen Heizkörpern zählen schon ab 25 % Wärmebedarf als Heizstunden. Ein Raummodell, das noch nicht bereit ist, wird einmal neu aus dem Recorder angelernt.
- **Pünktlich warm**: Jeden Morgen mit Vorheizen wird geprüft, ob der Raum zum Komfortbeginn warm war (Sensor *Pünktlichkeit*, z. B. „5 von 7 Tagen pünktlich“). Aus Verspätungen und zu frühem Warmsein lernt die Regelung eine Korrektur (−30 bis +60 Minuten, Attribut `preheat_correction_minutes`). Reicht die maximale Vorheizzeit nicht, darf das Vorheizen bis zu 60 Minuten länger dauern (einstellbar), aber nur, wenn die Zentralheizung dann nicht üblicherweise aus ist. Beides unter *Intelligente Regelung*.
- **Push-Meldungen mit Knöpfen** (Home-Assistant-App): Heizproblem mit „Boost 1 Stunde“ und „Heute nicht mehr melden“, Fenster offen mit „In 15 Minuten erinnern“ und „Heizung trotzdem an“ (gilt, bis das Fenster zu ist). Neu ist die Meldung „Niemand zuhause erkannt“ nach 15 Minuten mit „Stimmt nicht, ich bin da“ (alle Räume auf *Zuhause*); sie kommt von einem Raum fürs ganze Haus und lässt sich unter *Fenster und Wetter* abschalten.
- **Zeitplan-Vorschläge**: Betriebsarten und Temperaturen, die von Hand gewählt werden, merkt sich der Raum drei Wochen lang. Wird dasselbe an mindestens drei Tagen zur ähnlichen Zeit gewählt, zeigt Sensor *Zeitplan-Vorschlag* z. B. „Montag bis Freitag gegen 21:00 Uhr „Schlafen“ – in den Zeitplan übernehmen?“, und es kommt einmal eine Meldung. Der Zeitplan selbst wird nie geändert.
- **Heiz-Statistik**: Sensoren *Heizstunden* (Volllast-Stunden aus dem Wärmebedarf) und *Heizgradtage* (VDI 3807, 20/15 °C) zählen fortlaufend und eignen sich für Statistik-Karten über Monate. *Heizstunden je Gradtag* (letzte 7 Tage) ist der wetterbereinigte Verbrauch: sinkt er, heizt die Regelung sparsamer.
- **Notprogramm im Ventil** (Option unter *Ventile im Detail*, aus): Beim Herunterfahren von Home Assistant bekommen Ventile mit eigenem Zeitplan (Aqara E1: `schedule` und `schedule_settings`) die Komfort- und Eco-Zeiten des Tages, schalten ihn ein und regeln auf ihren eigenen Fühler. Nach dem Start schaltet die Integration das wieder aus. Bei Stromausfall oder Absturz greift es nicht, dann behalten die Ventile wie bisher den letzten Sollwert.

## Version 0.9.6: Tagesplan sobald die Temperaturen da sind

- Der Tagesplan wird auch sofort neu gerechnet, sobald Raum- und Außentemperatur nach einem Neustart ankommen. Bisher stand er danach bis zu 15 Minuten auf „Raum- oder Außentemperatur fehlt“.

## Version 0.9.5: Tagesplan nach dem Neustart

- Der Tagesplan wird sofort neu gerechnet, wenn die Regelung eingeschaltet wird, das Raummodell fertig wird oder der Zeitplan wechselt. Bisher blieb er nach einem Neustart bis zu 15 Minuten bei „Regelung aus – kein Tagesplan“, weil die Regelung erst kurz nach dem ersten Durchlauf einschaltet.

## Version 0.9.4: Neue Räume, eine Therme, Tagesplan, Selbsttest

- **Neuer Raum lernt sofort**: Fehlt der Verlauf des Sensors *Wärmebedarf* (ein gerade angelegter Raum), schätzt das Raummodell den Wärmebedarf der letzten 7 Tage aus den Sollwerten der Ventile und dem Raumfühler, wie die Live-Schätzung. Ein Raum, der bisher nichts aus dem Verlauf lernen konnte, versucht es nach dem Update einmal neu.
- **Eine Therme für das Haus**: Mit Haus-Eintrag gilt die Zentralheizung als liefernd, sobald in einem Raum Heizkörper warm werden. Das Haus lernt daraus die Lieferzeiten für alle Räume (anfangs aus dem, was die Räume einzeln gelernt haben) und meldet einmal für alle Räume, wenn eine Stunde lang kein Heizkörper warm wird, außer zu den üblichen Aus-Zeiten. Neuer Haus-Sensor *Zentralheizung*. Bleibt ein Raum kalt, während andere warm werden, nennen Sensor *Heizkörper* und Meldung den Raum (Ventil klemmt, Heizkörper entlüften).
- **Tagesplan**: Sensor *Tagesplan* zeigt, was der Raum in den nächsten 24 Stunden vorhat, z. B. „Morgen Vorheizen ab 05:40 Uhr, um 06:30 Uhr ca. 21,8 °C (Ziel 22,0 °C)“. Gerechnet wird mit Raummodell, Wettervorhersage, Lieferzeiten der Zentralheizung und den Blöcken des Zeitplans (Schedule-Helfer oder Kalender); Anwesenheit, Fenster und Betriebsarten sind nicht vorhersehbar und bleiben außen vor. Das Attribut `forecast` enthält die Kurve (alle 30 Minuten) für ApexCharts. Jede Stunde wird festgehalten, was der Plan für drei Stunden später erwartet, und mit dem Raum verglichen (Attribut `plan_error`).
- **Selbsttest**: Zehn Minuten nach jedem Start prüft jeder Raum Raumfühler, Zeitplan, Ventile, ob die Raumtemperatur an den Ventilen ankommt, Fensterkontakte, Außentemperatur sowie Batterie- und Funkmeldungen. Bei Problemen gibt es einen Eintrag unter *Einstellungen → Reparaturen* und eine Meldung; der Test wiederholt sich dann stündlich, bis alles passt. Sensor *Selbsttest*, Taste *Selbsttest starten*.
- **Heizkörper-Abgleich**: Für jeden Heizkörper wird je Heizphase (45 Minuten bis 3 Stunden, nur wenn die Zentralheizung liefert) festgehalten, wie schnell und wie stark sein Ventilgehäuse warm wird. Ab drei Heizphasen je Heizkörper vergleicht Sensor *Heizkörper-Abgleich* die Heizkörper eines Raums und nennt einen, der weniger als 60 % so warm wird wie der beste.
- **Kurz wärmer**: Taste je Raum, die das aktuelle Ziel für eine Stunde um 1 °C anhebt (einstellbar), danach Automatik. Nochmals drücken legt einen weiteren Schritt drauf (höchstens drei). Für Alexa: Taste freigeben und „Alexa, Wohnzimmer Heizung kurz wärmer einschalten“ sagen oder in einer Alexa-Routine verwenden.
- **Einstellungen als Menü**: Der Raum-Editor ist kein Durchklicken von fünf Seiten mehr, sondern ein Menü: *Grundlagen* (Ventile, Fühler, Zeitplan, Temperaturen), *Ventile im Detail*, *Betriebsarten*, *Personen und Anwesenheit*, *Geo-Fencing*, *Fenster und Wetter*, *Intelligente Regelung*, *Speichern*. Beim Speichern fallen Einträge weg, die keine Version mehr liest.
