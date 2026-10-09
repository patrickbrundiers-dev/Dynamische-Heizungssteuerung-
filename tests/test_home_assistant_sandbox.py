"""Integration tests using an isolated Home Assistant test instance."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.helpers import entity_registry as er
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


def _set_up_test_entities(
    hass, *, window_state="off", room_temperature="18", climate_setpoint=18.0
):
    """Create mock states; no physical devices or production HA connection."""
    next_event = (dt_util.now() + timedelta(minutes=30)).isoformat()
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {
            "temperature": climate_setpoint,
            "hvac_action": "idle",
            "min_temp": 7,
            "max_temp": 28,
        },
    )
    hass.states.async_set("sensor.living_room_temperature", room_temperature)
    hass.states.async_set("sensor.outdoor_temperature", "3.0")
    hass.states.async_set(
        "schedule.living_room_comfort", "off", {"next_event": next_event}
    )
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


@contextmanager
def _capture_climate_calls(hass):
    """Capture thermostat writes while delegating all other HA service calls."""
    calls = []
    service_registry_type = type(hass.services)
    original_call = service_registry_type.async_call

    async def record_calls(
        service_registry, domain, service, service_data=None, *args, **kwargs
    ):
        if domain == "climate" and service == "set_temperature":
            calls.append((domain, service, service_data))
            return None
        return await original_call(
            service_registry, domain, service, service_data, *args, **kwargs
        )

    with patch.object(service_registry_type, "async_call", record_calls):
        yield calls


@pytest.mark.asyncio
async def test_controller_calculates_preheat_but_does_not_control_by_default(
    hass, enable_custom_integrations
):
    """The sandbox calculates a recommendation but does not write when disabled."""
    _set_up_test_entities(hass)
    entry, coordinator = await _setup_integration(hass)

    assert coordinator.data["mode"] == "preheat"
    assert coordinator.data["target_temperature"] == 21.0
    assert coordinator.data["current_setpoint"] == 18.0
    assert coordinator.data["solar_adjustment_minutes"] == 0
    assert coordinator.data["enabled"] is False

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = False
        await coordinator.async_refresh()

    assert calls == []
    assert entry.state.value == "loaded"


@pytest.mark.asyncio
async def test_controller_switch_enables_real_ha_service_call(
    hass, enable_custom_integrations
):
    """Calling the exposed HA switch enables target writes."""
    _set_up_test_entities(hass)
    entry, coordinator = await _setup_integration(hass)
    registry = er.async_get(hass)
    switch_entity_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_enabled"
    )
    assert switch_entity_id is not None

    with _capture_climate_calls(hass) as calls:
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": switch_entity_id},
            blocking=True,
        )
        await hass.async_block_till_done()

    assert coordinator.enabled is True
    assert calls == [
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.living_room", "temperature": 21.0},
        )
    ]


@pytest.mark.asyncio
async def test_open_window_overrides_schedule_preheat(
    hass, enable_custom_integrations
):
    """An open window must force the eco target before comfort time."""
    _set_up_test_entities(hass, window_state="on", climate_setpoint=21.0)
    _, coordinator = await _setup_integration(hass)

    assert coordinator.data["mode"] == "window"
    assert coordinator.data["target_temperature"] == 18.0

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert calls == [
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.living_room", "temperature": 18.0},
        )
    ]


@pytest.mark.asyncio
async def test_unavailable_room_sensor_prevents_control(
    hass, enable_custom_integrations
):
    """Bad sensor readings must never result in a temperature service call."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    hass.states.async_set("sensor.living_room_temperature", "unavailable")

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert calls == []
    assert coordinator.data["target_temperature"] is None
    assert coordinator.data["mode"] == "waiting"


@pytest.mark.asyncio
async def test_unavailable_presence_sensor_prevents_control(
    hass, enable_custom_integrations
):
    """An unavailable configured presence sensor must not be mistaken for absence."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    hass.states.async_set("binary_sensor.someone_home", "unavailable")

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert calls == []
    assert coordinator.data["target_temperature"] is None
    assert coordinator.data["mode"] == "waiting"


@pytest.mark.asyncio
async def test_target_is_clamped_to_thermostat_maximum(
    hass, enable_custom_integrations
):
    """Never request a temperature beyond limits advertised by the climate entity."""
    _set_up_test_entities(hass, climate_setpoint=18.0)
    climate_state = hass.states.get("climate.living_room")
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {**climate_state.attributes, "temperature": 18.0, "max_temp": 20.5},
    )
    _, coordinator = await _setup_integration(hass)

    assert coordinator.data["target_temperature"] == 20.5

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert calls == [
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.living_room", "temperature": 20.5},
        )
    ]


@pytest.mark.asyncio
async def test_unavailable_thermostat_prevents_control(
    hass, enable_custom_integrations
):
    """An unavailable climate entity must stop control and expose a clear status."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    hass.states.async_set("climate.living_room", "unavailable")

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert calls == []
    assert coordinator.data["target_temperature"] is None
    assert coordinator.data["mode"] == "waiting"
    assert "Thermostat nicht verfügbar" in coordinator.data["status"]


@pytest.mark.asyncio
async def test_cooling_rate_is_learned_from_a_stable_setback_period(
    hass, enable_custom_integrations
):
    """Bounded cooling learning updates the persisted estimate when the room cools."""
    _set_up_test_entities(
        hass, room_temperature="19.0", climate_setpoint=17.0
    )
    _, coordinator = await _setup_integration(hass)
    climate_state = hass.states.get("climate.living_room")

    # Replace the first setup sample to use deterministic test timestamps.
    coordinator._cooling_sample_temperature = None
    coordinator._cooling_sample_time = None
    start = dt_util.utcnow()

    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start,
    ):
        await coordinator._learn(
            19.0,
            climate_state,
            window_open=False,
            present=True,
            schedule_active=False,
            eco_temperature=18.0,
        )

    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(minutes=30),
    ):
        await coordinator._learn(
            18.7,
            climate_state,
            window_open=False,
            present=True,
            schedule_active=False,
            eco_temperature=18.0,
        )

    assert coordinator.cooling_rate == pytest.approx(0.36)
