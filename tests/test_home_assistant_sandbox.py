"""Integration tests using an isolated Home Assistant test instance."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_heating.const import (
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WINDOW_ENTITY,
    DOMAIN,
)


def _set_up_test_entities(hass, *, window_state="off", room_temperature="18"):
    """Create mock states; no physical devices or production HA connection."""
    next_event = (dt_util.now() + timedelta(minutes=30)).isoformat()
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {"temperature": 18.0, "hvac_action": "idle", "min_temp": 7, "max_temp": 28},
    )
    hass.states.async_set("sensor.living_room_temperature", room_temperature)
    hass.states.async_set("sensor.outdoor_temperature", "3.0")
    hass.states.async_set("schedule.living_room_comfort", "off", {"next_event": next_event})
    hass.states.async_set("binary_sensor.living_room_window", window_state)
    hass.states.async_set("binary_sensor.someone_home", "on")


def _config_data():
    return {
        CONF_CLIMATE_ENTITY: "climate.living_room",
        CONF_ROOM_TEMPERATURE_ENTITY: "sensor.living_room_temperature",
        CONF_SCHEDULE_ENTITY: "schedule.living_room_comfort",
        CONF_WINDOW_ENTITY: "binary_sensor.living_room_window",
        CONF_PRESENCE_ENTITY: "binary_sensor.someone_home",
        CONF_OUTDOOR_TEMPERATURE_ENTITY: "sensor.outdoor_temperature",
        CONF_COMFORT_TEMPERATURE: 21.0,
        CONF_ECO_TEMPERATURE: 18.0,
        CONF_MAX_PREHEAT_MINUTES: 120,
    }


async def _setup_integration(hass):
    """Load the custom integration into the test Home Assistant instance."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Wohnzimmer",
        unique_id="climate.living_room",
        data=_config_data(),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


@pytest.mark.asyncio
async def test_controller_calculates_preheat_but_does_not_control_by_default(
    hass, enable_custom_integrations
):
    """The sandbox should calculate a recommendation but never write when disabled."""
    _set_up_test_entities(hass)
    entry, coordinator = await _setup_integration(hass)

    assert coordinator.data["mode"] == "preheat"
    assert coordinator.data["target_temperature"] == 21.0
    assert coordinator.data["enabled"] is False

    service_call = AsyncMock()
    coordinator.enabled = False
    from unittest.mock import patch

    with patch.object(hass.services, "async_call", service_call):
        await coordinator.async_refresh()

    service_call.assert_not_awaited()
    assert entry.state.value == "loaded"


@pytest.mark.asyncio
async def test_controller_applies_target_only_after_explicit_activation(
    hass, enable_custom_integrations
):
    """The coordinator issues a real HA service call only when enabled."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)

    service_call = AsyncMock()
    from unittest.mock import patch

    with patch.object(hass.services, "async_call", service_call):
        coordinator.enabled = True
        await coordinator.async_refresh()

    service_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 21.0},
        blocking=True,
    )


@pytest.mark.asyncio
async def test_open_window_overrides_schedule_preheat(
    hass, enable_custom_integrations
):
    """An open window must force the eco target even shortly before comfort time."""
    _set_up_test_entities(hass, window_state="on")
    _, coordinator = await _setup_integration(hass)

    assert coordinator.data["mode"] == "window"
    assert coordinator.data["target_temperature"] == 18.0

    service_call = AsyncMock()
    from unittest.mock import patch

    with patch.object(hass.services, "async_call", service_call):
        coordinator.enabled = True
        await coordinator.async_refresh()

    service_call.assert_awaited_once_with(
        "climate",
        "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 18.0},
        blocking=True,
    )
