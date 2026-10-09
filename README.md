# Dynamische Heizungssteuerung für Home Assistant

Eine vorausschauende, lernfähige Heizungsregelung als eigene Home-Assistant-Integration. Das Projekt startet mit einer sicheren Basisversion und wird über automatisierte Tests erweitert.

## Aktueller Funktionsumfang

- Verknüpft ein Thermostat, einen Raumtemperatursensor und einen Home-Assistant-Zeitplan.
- Nutzt den nächsten Zustandswechsel des Zeitplans, um bei Bedarf vor dem Komfortzeitraum vorzuheizen.
- Lernt während tatsächlicher Heizphasen schrittweise die Aufheizrate des Raums und speichert den Wert über Neustarts.
- Berücksichtigt optional Fensterkontakt, Anwesenheit und Außentemperatur.
- Stellt Status, Solltemperatur, Vorheizzeit und gelernte Aufheizrate als Sensoren bereit.
- Hat einen **separaten Aktivierungsschalter**. Nach der Installation bleibt die Regelung zunächst ausgeschaltet; solange sie ausgeschaltet ist, werden keine Thermostat-Sollwerte verändert.

> **Wichtig:** Advanced Heating Control (AHC) und diese Integration dürfen nicht gleichzeitig dasselbe Thermostat steuern. Teste zunächst mit ausgeschalteter Regelung. Vor dem Aktivieren muss AHC für das betreffende Thermostat deaktiviert sein.

## Installation über HACS

Derzeit ist das Repository für die manuelle Installation als **benutzerdefiniertes HACS-Repository** vorgesehen; es ist nicht automatisch Teil der offiziellen HACS-Standardliste.

1. In Home Assistant **HACS → Integrationen** öffnen.
2. Über das Drei-Punkte-Menü **Benutzerdefinierte Repositories** wählen.
3. `https://github.com/patrickbrundiers-dev/Dynamische-Heizungssteuerung-` als Repository eintragen und als Kategorie **Integration** auswählen.
4. Hinzufügen, **Dynamische Heizungssteuerung** suchen und installieren.
5. Home Assistant neu starten und anschließend unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** einrichten.

Alternativ manuell:

1. Home Assistant sichern.
2. Den Ordner `custom_components/dynamic_heating` nach `<config>/custom_components/dynamic_heating/` kopieren.
3. Home Assistant neu starten.
4. Unter **Einstellungen → Geräte & Dienste → Integration hinzufügen** nach **Dynamische Heizungssteuerung** suchen.
5. Thermostat, Raumtemperatursensor und Schedule-Helfer auswählen. Fenster-, Anwesenheits- und Außentemperatursensor sind optional.
6. Prüfen, dass der Schedule-Helfer die Komfortzeiten korrekt abbildet. Wenn der Zeitplan ausgeschaltet ist, dient sein Attribut `next_event` als Grundlage für das vorausschauende Vorheizen.
7. Zuerst die angezeigten Status- und Prognosesensoren beobachten. Den Schalter **Regelung aktiv** erst einschalten, wenn die Vorhersage plausibel ist und AHC das Thermostat nicht mehr steuert.

Die Regelung wird nach einem Home-Assistant-Neustart aus Sicherheitsgründen wieder deaktiviert und muss bewusst erneut eingeschaltet werden. Das ist beabsichtigt, damit ein Update oder Neustart nicht unbemerkt eine Regelung aktiviert.

### Temperaturwerte

Die Komfort- und Absenktemperatur sowie die maximale Vorheizzeit werden beim Einrichten konfiguriert. Fenster offen oder keine Anwesenheit führt zur Absenkung. Ist ein notwendiger Messwert nicht verfügbar, wird kein neuer Sollwert gesetzt.

## Tests in einer isolierten Home-Assistant-Instanz

Das Repository enthält Integrationstests mit `pytest-homeassistant-custom-component`. Die Tests starten eine isolierte Home-Assistant-Testinstanz, legen simulierte Entitäten an und prüfen das echte Setup der Integration, die Vorheizentscheidung, Fenster-/Anwesenheitslogik und ob Sollwerte nur nach Aktivierung gesetzt werden. Dafür wird weder Zugriff auf die echte Heizung noch ein Token aus deiner produktiven Installation benötigt.

Automatische Tests laufen bei Push, Pull Request und manuellem Start in GitHub Actions. Lokal:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
python -m pip install -r requirements_test.txt
pytest -q
ruff check .
```

## Sicherheits- und Entwicklungsprinzipien

- Standardmäßig keine Steuerung bis zur bewussten Aktivierung.
- Nur konfigurierte Entitäten ansprechen und Sollwerte nur bei relevanter Abweichung ändern.
- Keine Abhängigkeit von der echten Hardware im Test.
- Lernwerte bleiben lokal in Home Assistant; keine Cloud-Übertragung.
- Änderungen an der Heizungslogik müssen von Tests begleitet werden.

## Geplante Ausbaustufen

1. Mehrere Tages-Zeitfenster und komfortable Raumprofile.
2. Robusteres Lernmodell mit Abkühlkurve und Außentemperatur-Historie.
3. Wetterprognose und Sonneneinstrahlung für vorausschauende Anpassungen.
4. Dashboard, Diagnoseinformationen und Vergleich mit einer Referenzregelung.

Lizenz: MIT.
