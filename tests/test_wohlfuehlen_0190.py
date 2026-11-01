"""0.19.0: Betriebsart "Wohlfühlen" with its own temperature and duration."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import _set_up_test_entities, _setup_integration

from custom_components.dynamic_heating.const import DOMAIN


@pytest.mark.asyncio
async def test_wohlfuehlen_heats_to_its_own_temperature_for_its_own_duration(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="20.0")
    entry, coordinator = await _setup_integration(hass)
    registry = er.async_get(hass)
    select_id = registry.async_get_entity_id(
        "select", DOMAIN, f"{entry.entry_id}_quick_mode"
    )
    assert "Wohlfühlen" in hass.states.get(select_id).attributes["options"]
    climate_id = registry.async_get_entity_id(
        "climate", DOMAIN, f"{entry.entry_id}_room_climate"
    )
    assert "cozy" in hass.states.get(climate_id).attributes["preset_modes"]

    await hass.services.async_call(
        "select", "select_option", {"entity_id": select_id, "option": "Wohlfühlen"},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert coordinator.data["mode"] == "quick_cozy"
    assert coordinator.data["target_temperature"] == 23.0
    assert "Wohlfühlen" in coordinator.data["status"]
    # Its own duration (3 h), not the Betriebsart-Dauer (until the schedule).
    remaining = coordinator.quick_until - dt_util.utcnow()
    assert timedelta(hours=2, minutes=59) < remaining <= timedelta(hours=3)
    assert hass.states.get(climate_id).attributes["preset_mode"] == "cozy"
    # Not learned as a habit, so never suggested in a push.
    assert not any(event[1] == "cozy" for event in coordinator.habits.events)

    # The temperature can be changed per room.
    coordinator.config["cozy_temperature"] = 22.5
    await coordinator.async_refresh()
    assert coordinator.data["target_temperature"] == 22.5

    later = dt_util.utcnow() + timedelta(hours=3, minutes=1)
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=later,
    ):
        await coordinator.async_refresh()
    assert coordinator.data["quick_mode"] == "auto"


@pytest.mark.asyncio
async def test_wohlfuehlen_duration_setting_and_button(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["cozy_duration"] = 3600
    registry = er.async_get(hass)
    button_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_quick_button_cozy"
    )
    assert button_id is not None
    await hass.services.async_call(
        "button", "press", {"entity_id": button_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert coordinator.data["mode"] == "quick_cozy"
    remaining = coordinator.quick_until - dt_util.utcnow()
    assert timedelta(minutes=59) < remaining <= timedelta(hours=1)
    # Changing the Betriebsart-Dauer does not cut it short.
    until = coordinator.quick_until
    await coordinator.async_set_quick_duration("1h")
    assert coordinator.quick_until == until
