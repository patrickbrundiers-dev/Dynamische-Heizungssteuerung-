"""0.11.0: the room card edits the room's schedules as a graph."""

from pathlib import Path

import pytest
from test_home_assistant_sandbox import _set_up_test_entities, _setup_integration

CARD = (
    Path(__file__).parents[1]
    / "custom_components"
    / "dynamic_heating"
    / "frontend"
    / "dynamic-heating-card.js"
)


@pytest.mark.asyncio
async def test_status_lists_the_schedules_the_card_can_edit(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.school_free", "off", {"friendly_name": "Kinderzimmer Schulfrei"}
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config["school_free_schedule"] = "schedule.school_free"
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    attributes = hass.states.get("sensor.dynamische_heizungssteuerung_status").attributes
    assert [s["entity_id"] for s in attributes["schedules"]] == [
        "schedule.living_room_comfort",
        "schedule.school_free",
    ]
    assert attributes["schedules"][1]["name"] == "Kinderzimmer Schulfrei"
    assert attributes["active_schedule"] == "schedule.living_room_comfort"
    assert attributes["eco_temperature"] == coordinator.data["eco_temperature"]


def test_card_registers_the_schedule_editor():
    source = CARD.read_text(encoding="utf-8")
    assert 'customElements.define("dynamic-heating-schedule-card"' in source
    # Saving goes through Home Assistant's own schedule helper.
    assert '"schedule/update"' in source
