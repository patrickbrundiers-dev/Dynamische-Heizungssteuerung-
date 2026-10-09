# Dynamische Heizungssteuerung für Home Assistant

Eine vorausschauende, lernfähige Heizungsregelung als eigene Home-Assistant-Integration. Die Integration wird schrittweise mit sicheren Standardwerten und automatisierten Tests erweitert.

## Aktueller Funktionsumfang

- Verknüpft ein Thermostat, einen Raumtemperatursensor und einen Home-Assistant-Zeitplan.
- Ein Schedule-Helfer kann mehrere Komfort-Zeitfenster pro Wochentag enthalten. Jeder Raum/Regler kann mit eigener Komfort- und Absenktemperatur eingerichtet werden.
- Nutzt den nächsten Zustandswechsel des Zeitplans, um bei Bedarf vor dem Komfortzeitraum vorzuheizen.
- Lernt während tatsächlicher Heizphasen die Aufheizrate und während stabiler Absenkphasen eine Abkühlrate. Beide Werte werden begrenzt, lokal gespeichert und über Neustarts erhalten.
- Berücksichtigt die gelernte Abkühlrate in der Prognose für den Beginn des nächsten Komfortzeitraums. Die Prognose fällt nicht unter die aktuelle Temperatur, wenn der Raum bereits kälter als die Absenktemperatur ist, und sonst nicht unter den konfigurierten Absenkwert.
- Berücksichtigt optional Fensterkontakt, Anwesenheit und Außentemperatur.
- Stellt Status, Raum-/Außentemperatur, Solltemperatur, prognostizierte Temperatur, Vorheizzeit sowie gelernte Aufheiz- und Abkühlraten als Sensoren bereit. Der Statussensor enthält Diagnoseattribute zur letzten Entscheidung.
- Unterstützt Home-Assistant-Diagnosedaten; konfigurierte Entity-IDs werden beim Export redigiert.
- Hat einen **separaten Aktivierungsschalter**. Nach der Installation bleibt die Regelung zunächst ausgeschaltet; solange sie ausgeschaltet ist, werden keine Thermostat-Sollwerte verändert.

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
5. Thermostat, Raumtemperatursensor und Schedule-Helfer auswählen. Fenster-, Anwesenheits- und Außentemperatursensor sind optional.
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
- **Prognostizierte Raumtemperatur** und **Gelernte Abkühlrate**.
- **Fenster-/Anwesenheitszustand**, falls diese optionalen Sensoren eingerichtet sind.

Wenn etwas nicht plausibel aussieht, bitte nicht sofort den Regler aktivieren. Die Diagnoseattribute zeigen zuerst, warum die Integration Komfort-, Absenk- oder Vorheizbetrieb gewählt hat.

## Tests in einer isolierten Home-Assistant-Instanz

Das Repository enthält Integrationstests mit pytest-homeassistant-custom-component. Die Tests starten eine isolierte Home-Assistant-Testinstanz, legen simulierte Entitäten an und prüfen das echte Setup der Integration, die Vorheizentscheidung, Fenster-/Anwesenheitslogik, Sensorfehler, Thermostatgrenzen und ob Sollwerte nur nach Aktivierung gesetzt werden. Dafür wird weder Zugriff auf die echte Heizung noch ein Token aus deiner produktiven Installation benötigt.

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

## Weitere geplante Ausbaustufen

1. Wetterprognose und Sonneneinstrahlung zur weiteren Verbesserung der Vorheizprognose.
2. Dashboard-Ansicht mit Historie und Vergleich zur bisherigen Referenzregelung.

Lizenz: MIT.
