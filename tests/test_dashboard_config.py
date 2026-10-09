"""Validate the bundled Lovelace example dashboard."""

from pathlib import Path

import yaml


def test_dashboard_has_geofence_calibration_and_multiweek_learning_views():
    """The example dashboard parses and contains the promised diagnosis views."""
    dashboard_path = Path(__file__).parents[1] / "dashboards" / "dynamic_heating.yaml"
    dashboard = yaml.safe_load(dashboard_path.read_text(encoding="utf-8"))

    assert dashboard["title"] == "Dynamische Heizungssteuerung"
    views = {view["path"]: view for view in dashboard["views"]}
    assert "dynamic-heating" in views
    assert "learning-model" in views

    all_cards = [
        card
        for view in dashboard["views"]
        for card in view.get("cards", [])
    ]
    statistics = [
        card for card in all_cards if card.get("type") == "statistics-graph"
    ]
    assert any(card.get("days_to_show") == 30 for card in statistics)
    assert any(
        card.get("days_to_show") == 30
        and any(
            entity.get("entity") == "sensor.dynamische_heizungssteuerung_mittlerer_prognosefehler"
            for entity in card.get("entities", [])
        )
        for card in statistics
    )
    referenced_entities = {
        entity["entity"]
        for card in all_cards
        for entity in card.get("entities", [])
        if isinstance(entity, dict) and "entity" in entity
    }
    assert "sensor.dynamische_heizungssteuerung_geo_fencing_status" in referenced_entities
    assert (
        "sensor.dynamische_heizungssteuerung_mittleres_standortupdate_intervall"
        in referenced_entities
    )
