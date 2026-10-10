"""Integration tests using an isolated Home Assistant test instance."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.core import State
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
)

from custom_components.dynamic_heating.diagnostics import (
    async_get_config_entry_diagnostics,
)
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
        # Keep legacy integration scenarios independent of debounce timing.
        "enter_home_duration": 0,
        "leaving_home_duration": 0,
        "presence_on_duration": 0,
        "presence_off_duration": 0,
        "proximity_duration": 0,
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
async def test_controller_switch_survives_options_reload(
    hass, enable_custom_integrations
):
    """Reloading the entry (e.g. after the room editor) keeps control on."""
    _set_up_test_entities(hass)
    entry, _ = await _setup_integration(hass)
    switch_entity_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_enabled"
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch_entity_id}, blocking=True
    )

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.data[DOMAIN][entry.entry_id].enabled is True
    assert hass.states.get(switch_entity_id).state == "on"


@pytest.mark.asyncio
async def test_controller_switch_restores_on_after_restart(
    hass, enable_custom_integrations
):
    """A switch that was on before a restart is on again and writes."""
    _set_up_test_entities(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Wohnzimmer",
        unique_id="climate.living_room",
        data=_config_data(),
    )
    entry.add_to_hass(hass)
    switch_entity_id = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_enabled", config_entry=entry
    ).entity_id
    mock_restore_cache(hass, [State(switch_entity_id, "on")])

    with _capture_climate_calls(hass) as calls:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert hass.data[DOMAIN][entry.entry_id].enabled is True
    assert hass.states.get(switch_entity_id).state == "on"
    assert calls == [
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.living_room", "temperature": 21.0},
        )
    ]


@pytest.mark.asyncio
async def test_controller_switch_restores_off_after_restart(
    hass, enable_custom_integrations
):
    """A switch that was off before a restart stays off."""
    _set_up_test_entities(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Wohnzimmer",
        unique_id="climate.living_room",
        data=_config_data(),
    )
    entry.add_to_hass(hass)
    switch_entity_id = er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_enabled", config_entry=entry
    ).entity_id
    mock_restore_cache(hass, [State(switch_entity_id, "off")])

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.data[DOMAIN][entry.entry_id].enabled is False


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
    coordinator._cooling_sample.reset()
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

    # The window starts at the first change of the sensor reading.
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=10),
    ):
        await coordinator._learn(
            18.9,
            climate_state,
            window_open=False,
            present=True,
            schedule_active=False,
            eco_temperature=18.0,
        )

    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=10, minutes=30),
    ):
        await coordinator._learn(
            18.6,
            climate_state,
            window_open=False,
            present=True,
            schedule_active=False,
            eco_temperature=18.0,
        )

    assert coordinator.cooling_rate == pytest.approx(0.36)


@pytest.mark.asyncio
async def test_failed_temperature_write_is_reported_and_retried(
    hass, enable_custom_integrations
):
    """A climate service failure is visible but does not break the coordinator."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.enabled = True

    service_registry_type = type(hass.services)
    original_call = service_registry_type.async_call
    climate_calls = []

    async def fail_once_then_accept(
        service_registry, domain, service, service_data=None, *args, **kwargs
    ):
        if domain == "climate" and service == "set_temperature":
            climate_calls.append(service_data)
            if len(climate_calls) == 1:
                raise HomeAssistantError("simulated thermostat service failure")
            return None
        return await original_call(
            service_registry, domain, service, service_data, *args, **kwargs
        )

    with patch.object(service_registry_type, "async_call", fail_once_then_accept):
        await coordinator.async_refresh()

        assert coordinator.data["control_error"] is True
        assert coordinator.data["decision_status"] == "Vorausschauendes Vorheizen"
        assert "erneuter Versuch" in coordinator.data["status"]

        await coordinator.async_refresh()

    assert len(climate_calls) == 2
    assert climate_calls[0]["entity_id"] == "climate.living_room"
    assert climate_calls[1]["temperature"] == 21.0
    assert coordinator.data["control_error"] is False
    assert coordinator.data["status"] == "Vorausschauendes Vorheizen"




@pytest.mark.asyncio
async def test_person_presence_requires_someone_home_or_guest_mode(
    hass, enable_custom_integrations
):
    """A household person at home or an active guest enables presence."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = ["person.patrick", "person.jenny"]
    coordinator.config["enter_home_duration"] = 0
    coordinator.config["leaving_home_duration"] = 0
    coordinator.config["presence_entity"] = None
    hass.states.async_set("person.patrick", "not_home")
    hass.states.async_set("person.jenny", "not_home")

    await coordinator.async_refresh()
    assert coordinator.data["present"] is False
    assert coordinator.data["mode"] == "away"

    hass.states.async_set("person.patrick", "home")
    await coordinator.async_refresh()
    assert coordinator.data["present"] is True

    hass.states.async_set("person.patrick", "not_home")
    coordinator.config["guest_entity"] = "input_boolean.guest_mode"
    hass.states.async_set("input_boolean.guest_mode", "on")
    await coordinator.async_refresh()
    assert coordinator.data["present"] is True


@pytest.mark.asyncio
async def test_proximity_can_trigger_presence_when_approaching_within_distance(
    hass, enable_custom_integrations
):
    """Proximity only counts when the configured zone reports approaching nearby."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "proximity.home"
    coordinator.config["proximity_distance"] = 500
    coordinator.config["proximity_duration"] = 0
    hass.states.async_set("proximity.home", "300", {"dir_of_travel": "towards"})

    await coordinator.async_refresh()
    assert coordinator.data["present"] is True
    assert coordinator.data["presence_status"] == "Anwesenheit erkannt"

    hass.states.async_set("proximity.home", "800", {"dir_of_travel": "towards"})
    await coordinator.async_refresh()
    assert coordinator.data["present"] is False


@pytest.mark.asyncio
async def test_unavailable_proximity_prevents_thermostat_control(
    hass, enable_custom_integrations
):
    """A configured but unavailable proximity source must fail safe."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "proximity.home"
    hass.states.async_set("proximity.home", "unavailable")

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert calls == []
    assert coordinator.data["mode"] == "waiting"
    assert "Proximity-Entfernung nicht verfügbar" in coordinator.data["status"]

@pytest.mark.asyncio
async def test_proximity_debounce_survives_changing_distance_states(
    hass, enable_custom_integrations
):
    """Distance updates keep the timer; an unavailable gap restarts it."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "proximity.home"
    coordinator.config["proximity_distance"] = 500
    coordinator.config["proximity_duration"] = 120
    start = dt_util.utcnow()

    hass.states.async_set("proximity.home", "450", {"dir_of_travel": "towards"})
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start,
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("proximity.home", "380", {"dir_of_travel": "towards"})
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=60),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("proximity.home", "unavailable")
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=90),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "waiting"

    hass.states.async_set("proximity.home", "320", {"dir_of_travel": "towards"})
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=180),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("proximity.home", "290", {"dir_of_travel": "towards"})
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=240),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("proximity.home", "250", {"dir_of_travel": "towards"})
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=300),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is True

    hass.states.async_set("proximity.home", "250", {"dir_of_travel": "away_from"})
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=310),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

@pytest.mark.asyncio
async def test_presence_sensor_works_standalone_and_schedule_can_disable_it(
    hass, enable_custom_integrations
):
    """A presence sensor can be the sole source; its schedule can suppress motion."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = []
    coordinator.config["guest_entity"] = None
    coordinator.config["proximity_entity"] = None
    coordinator.config["presence_on_duration"] = 0
    coordinator.config["presence_off_duration"] = 1200
    coordinator.config["presence_schedule_entity"] = "schedule.presence_active"
    hass.states.async_set("schedule.presence_active", "off")
    hass.states.async_set("binary_sensor.someone_home", "on")

    await coordinator.async_refresh()
    assert coordinator.data["present"] is False
    assert coordinator.data["mode"] == "away"

    hass.states.async_set("schedule.presence_active", "on")
    await coordinator.async_refresh()
    assert coordinator.data["present"] is True

    hass.states.async_set("binary_sensor.someone_home", "off")
    await coordinator.async_refresh()
    assert coordinator.data["present"] is True

@pytest.mark.asyncio
async def test_diagnostics_redact_new_presence_and_location_entities(
    hass, enable_custom_integrations
):
    """Person, guest, Proximity and presence schedule IDs are sensitive diagnostics."""
    entry, _ = await _setup_integration(hass)
    hass.config_entries.async_update_entry(
        entry,
        options={
            "person_entities": ["person.patrick", "person.jenny"],
            "guest_entity": "input_boolean.guest_mode",
            "proximity_entity": "proximity.home",
            "proximity_direction_entity": "sensor.home_direction",
            "presence_schedule_entity": "schedule.presence_active",
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    config = diagnostics["config"]

    assert config["person_entities"] != ["person.patrick", "person.jenny"]
    assert config["guest_entity"] != "input_boolean.guest_mode"
    assert config["proximity_entity"] != "proximity.home"
    assert config["proximity_direction_entity"] != "sensor.home_direction"
    assert config["presence_schedule_entity"] != "schedule.presence_active"

@pytest.mark.asyncio
async def test_modern_proximity_sensors_normalize_distance_to_meters(
    hass, enable_custom_integrations
):
    """Modern Proximity exposes separate distance/direction sensors and known units."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "sensor.home_distance"
    coordinator.config["proximity_direction_entity"] = "sensor.home_direction"
    coordinator.config["proximity_distance"] = 500
    coordinator.config["proximity_duration"] = 0
    coordinator.config["proximity_max_age"] = 900
    hass.states.async_set(
        "sensor.home_distance", "0.3", {"unit_of_measurement": "km"}
    )
    hass.states.async_set("sensor.home_direction", "towards")

    await coordinator.async_refresh()

    assert coordinator.data["present"] is True
    assert coordinator.data["proximity_distance_m"] == pytest.approx(300.0)
    assert coordinator.data["proximity_direction"] == "towards"
    assert coordinator.data["proximity_status"] == "Anfahrt bestätigt"


@pytest.mark.asyncio
async def test_stale_proximity_data_prevents_a_new_heating_decision(
    hass, enable_custom_integrations
):
    """Old GPS-derived distance readings fail closed when no local presence is known."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "sensor.home_distance"
    coordinator.config["proximity_direction_entity"] = "sensor.home_direction"
    coordinator.config["proximity_max_age"] = 900
    hass.states.async_set(
        "sensor.home_distance", "250", {"unit_of_measurement": "m"}
    )
    hass.states.async_set("sensor.home_direction", "towards")
    future = dt_util.utcnow() + timedelta(minutes=20)

    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=future,
    ):
        with _capture_climate_calls(hass) as calls:
            coordinator.enabled = True
            await coordinator.async_refresh()

    assert calls == []
    assert coordinator.data["mode"] == "waiting"
    assert "Standortdaten veraltet" in coordinator.data["status"]


@pytest.mark.asyncio
async def test_home_person_tracker_overrides_stale_geofence_data(
    hass, enable_custom_integrations
):
    """Fresh person state at home remains usable if GPS-derived distance went stale."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["person_entities"] = ["person.patrick"]
    coordinator.config["enter_home_duration"] = 0
    coordinator.config["proximity_entity"] = "sensor.home_distance"
    coordinator.config["proximity_direction_entity"] = "sensor.home_direction"
    coordinator.config["proximity_max_age"] = 900
    hass.states.async_set("person.patrick", "home")
    hass.states.async_set(
        "sensor.home_distance", "0", {"unit_of_measurement": "m"}
    )
    hass.states.async_set("sensor.home_direction", "arrived")
    future = dt_util.utcnow() + timedelta(minutes=20)

    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=future,
    ):
        await coordinator.async_refresh()

    assert coordinator.data["present"] is True
    assert coordinator.data["mode"] != "waiting"
    assert "bekannte Anwesenheit hat Vorrang" in coordinator.data["proximity_status"]


@pytest.mark.asyncio
async def test_proximity_direction_change_cancels_approach_timer(
    hass, enable_custom_integrations
):
    """A direction change resets approach debounce even as distance stays in range."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "sensor.home_distance"
    coordinator.config["proximity_direction_entity"] = "sensor.home_direction"
    coordinator.config["proximity_distance"] = 500
    coordinator.config["proximity_duration"] = 120
    coordinator.config["proximity_max_age"] = 900
    start = dt_util.utcnow()
    hass.states.async_set(
        "sensor.home_distance", "450", {"unit_of_measurement": "m"}
    )
    hass.states.async_set("sensor.home_direction", "towards")
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start,
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set(
        "sensor.home_distance", "400", {"unit_of_measurement": "m"}
    )
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=60),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("sensor.home_direction", "away_from")
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=90),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("sensor.home_direction", "towards")
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=120),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set(
        "sensor.home_distance", "350", {"unit_of_measurement": "m"}
    )
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=240),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is True


@pytest.mark.asyncio
async def test_implausible_heating_sample_is_rejected_not_clamped(
    hass, enable_custom_integrations
):
    """Large rate outliers increase the rejected count without poisoning the model."""
    _set_up_test_entities(hass, room_temperature="18.0", climate_setpoint=18.0)
    _, coordinator = await _setup_integration(hass)
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {
            "temperature": 21.0,
            "hvac_action": "heating",
            "min_temp": 7,
            "max_temp": 28,
        },
    )
    climate = hass.states.get("climate.living_room")
    start = dt_util.utcnow()

    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start,
    ):
        await coordinator._learn(
            18.0, climate, window_open=False, present=True,
            schedule_active=False, eco_temperature=18.0
        )
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=10),
    ):
        await coordinator._learn(
            18.1, climate, window_open=False, present=True,
            schedule_active=False, eco_temperature=18.0
        )
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=310),
    ):
        await coordinator._learn(
            20.7, climate, window_open=False, present=True,
            schedule_active=False, eco_temperature=18.0
        )

    assert coordinator.heating_rate == pytest.approx(1.0)
    assert coordinator._heating_samples == 0
    assert coordinator._rejected_samples == 1
    assert "unplausibel" in coordinator._last_learning_status


@pytest.mark.asyncio
async def test_plausible_heating_sample_updates_model_and_quality_counters(
    hass, enable_custom_integrations
):
    """Accepted heating observations are bounded, counted and inspectable."""
    _set_up_test_entities(hass, room_temperature="18.0", climate_setpoint=18.0)
    _, coordinator = await _setup_integration(hass)
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {
            "temperature": 21.0,
            "hvac_action": "heating",
            "min_temp": 7,
            "max_temp": 28,
        },
    )
    climate = hass.states.get("climate.living_room")
    start = dt_util.utcnow()

    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start,
    ):
        await coordinator._learn(
            18.0, climate, window_open=False, present=True,
            schedule_active=False, eco_temperature=18.0
        )
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=10),
    ):
        await coordinator._learn(
            18.1, climate, window_open=False, present=True,
            schedule_active=False, eco_temperature=18.0
        )
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(hours=1, seconds=10),
    ):
        await coordinator._learn(
            18.6, climate, window_open=False, present=True,
            schedule_active=False, eco_temperature=18.0
        )

    assert coordinator.heating_rate == pytest.approx(0.9)
    assert coordinator._heating_samples == 1
    assert coordinator._rejected_samples == 0
    assert coordinator._last_observed_heating_rate == pytest.approx(0.5)
    assert coordinator._last_learning_status == "Aufheizrate aktualisiert"


@pytest.mark.asyncio
async def test_schedule_forecast_error_and_running_mae_are_recorded(
    hass, enable_custom_integrations
):
    """The model compares projected and actual room temperature at comfort start."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    start = dt_util.utcnow()
    event = start + timedelta(minutes=30)
    coordinator._pending_forecast_event = event
    coordinator._pending_forecast_temperature = 19.0

    await coordinator._evaluate_pending_forecast(
        now=event + timedelta(seconds=10),
        room_temperature=19.5,
        schedule_active=True,
        present=True,
        window_open=False,
    )

    assert coordinator._forecast_evaluations == 1
    assert coordinator._last_forecast_error_c == pytest.approx(0.5)
    assert coordinator._forecast_mae_c == pytest.approx(0.5)
    assert coordinator._last_forecast_predicted_temperature == pytest.approx(19.0)
    assert coordinator._last_forecast_actual_temperature == pytest.approx(19.5)
    assert coordinator._pending_forecast_event is None

    coordinator._pending_forecast_event = event + timedelta(days=1)
    coordinator._pending_forecast_temperature = 20.0
    await coordinator._evaluate_pending_forecast(
        now=event + timedelta(days=1, seconds=10),
        room_temperature=19.0,
        schedule_active=True,
        present=True,
        window_open=False,
    )
    assert coordinator._forecast_evaluations == 2
    assert coordinator._last_forecast_error_c == pytest.approx(-1.0)
    assert coordinator._forecast_mae_c == pytest.approx(0.75)

@pytest.mark.asyncio
async def test_proximity_calibration_counts_actual_sensor_updates_and_stale_periods(
    hass, enable_custom_integrations
):
    """Only sensor-state changes count as updates; stale periods count once."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "sensor.home_distance"
    coordinator.config["proximity_direction_entity"] = "sensor.home_direction"
    coordinator.config["proximity_distance"] = 500
    coordinator.config["proximity_duration"] = 0
    coordinator.config["proximity_max_age"] = 900

    hass.states.async_set(
        "sensor.home_distance", "450", {"unit_of_measurement": "m"}
    )
    hass.states.async_set("sensor.home_direction", "towards")
    await coordinator.async_refresh()
    assert coordinator.data["proximity_updates_seen"] == 1
    assert coordinator.data["proximity_approach_attempts"] == 1
    assert coordinator.data["proximity_confirmed_approaches"] == 1

    hass.states.async_set(
        "sensor.home_distance", "420", {"unit_of_measurement": "m"}
    )
    await coordinator.async_refresh()
    assert coordinator.data["proximity_updates_seen"] == 2
    assert coordinator.data["proximity_average_update_interval_s"] is not None

    future = dt_util.utcnow() + timedelta(minutes=20)
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=future,
    ):
        await coordinator.async_refresh()
        assert coordinator.data["proximity_stale_events"] == 1
        await coordinator.async_refresh()
        assert coordinator.data["proximity_stale_events"] == 1

    stored = await coordinator._store.async_load()
    assert stored["proximity_updates_seen"] == 2
    assert stored["proximity_stale_events"] == 1


@pytest.mark.asyncio
async def test_geofence_stationary_direction_resets_approach_timer(
    hass, enable_custom_integrations
):
    """A stationary state cancels an unfinished arrival debounce."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["presence_entity"] = None
    coordinator.config["proximity_entity"] = "sensor.home_distance"
    coordinator.config["proximity_direction_entity"] = "sensor.home_direction"
    coordinator.config["proximity_distance"] = 500
    coordinator.config["proximity_duration"] = 120
    coordinator.config["proximity_max_age"] = 900
    start = dt_util.utcnow()

    hass.states.async_set(
        "sensor.home_distance", "450", {"unit_of_measurement": "m"}
    )
    hass.states.async_set("sensor.home_direction", "towards")
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start,
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("sensor.home_direction", "stationary")
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=60),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False

    hass.states.async_set("sensor.home_direction", "towards")
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
        return_value=start + timedelta(seconds=120),
    ):
        await coordinator.async_refresh()
    assert coordinator.data["present"] is False
    assert coordinator.data["proximity_approach_attempts"] == 2


@pytest.mark.asyncio
async def test_setpoint_is_rounded_to_thermostat_step_and_not_resent(
    hass, enable_custom_integrations
):
    """A 0.5 °C thermostat gets a value it can store, and only once."""
    _set_up_test_entities(hass)
    climate_state = hass.states.get("climate.living_room")
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {**climate_state.attributes, "target_temp_step": 0.5},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config[CONF_COMFORT_TEMPERATURE] = 21.2

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        # The thermostat has not reported the new setpoint yet.
        await coordinator.async_refresh()

    assert coordinator.data["target_temperature"] == 21.0
    assert calls == [
        (
            "climate",
            "set_temperature",
            {"entity_id": "climate.living_room", "temperature": 21.0},
        )
    ]


@pytest.mark.asyncio
async def test_started_preheat_continues_when_room_warms_up(
    hass, enable_custom_integrations
):
    """Preheating keeps the comfort target until the schedule starts."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    assert coordinator.data["mode"] == "preheat"

    hass.states.async_set("sensor.living_room_temperature", "20.9")
    await coordinator.async_refresh()

    assert coordinator.data["mode"] == "preheat"
    assert coordinator.data["target_temperature"] == 21.0


def _set_climate(hass, state="heat", **attributes):
    current = hass.states.get("climate.living_room")
    hass.states.async_set(
        "climate.living_room", state, {**current.attributes, **attributes}
    )


@pytest.mark.asyncio
async def test_manual_setpoint_change_pauses_control_until_mode_changes(
    hass, enable_custom_integrations
):
    """A setpoint changed at the thermostat is kept until the decision changes."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert [call[2]["temperature"] for call in calls] == [21.0]

        # The thermostat confirms the written value, then someone turns it down.
        _set_climate(hass, temperature=21.0)
        await coordinator.async_refresh()
        _set_climate(hass, temperature=19.5)
        await coordinator.async_refresh()

        assert coordinator.data["manual_override"] is True
        assert "Manuell übersteuert" in coordinator.data["status"]
        assert len(calls) == 1

        # Opening the window changes the decision and control resumes.
        hass.states.async_set("binary_sensor.living_room_window", "on")
        await coordinator.async_refresh()

    assert coordinator.data["manual_override"] is False
    assert [call[2]["temperature"] for call in calls] == [21.0, 18.0]


@pytest.mark.asyncio
async def test_unconfirmed_setpoint_is_not_taken_as_manual_change(
    hass, enable_custom_integrations
):
    """A thermostat still reporting the old value right after a write is no override."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    assert coordinator.data["manual_override"] is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_switched_off_thermostat_is_not_written(
    hass, enable_custom_integrations
):
    """A thermostat turned off by the user keeps its state."""
    _set_up_test_entities(hass)
    _set_climate(hass, state="off")
    _, coordinator = await _setup_integration(hass)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert calls == []
    assert "ausgeschaltet" in coordinator.data["status"]


@pytest.mark.asyncio
async def test_heating_is_inferred_without_hvac_action(
    hass, enable_custom_integrations
):
    """Thermostats without hvac_action still provide heating samples."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    hass.states.async_set(
        "climate.living_room", "heat", {"temperature": 21.0, "min_temp": 7}
    )
    climate = hass.states.get("climate.living_room")

    assert coordinator._is_heating(climate, 18.0, 21.0) is True
    assert coordinator._is_heating(climate, 20.8, 21.0) is False
    _set_climate(hass, hvac_action="idle")
    assert coordinator._is_heating(
        hass.states.get("climate.living_room"), 18.0, 21.0
    ) is False
    hass.states.async_set("climate.living_room", "off", {"temperature": 21.0})
    assert coordinator._is_heating(
        hass.states.get("climate.living_room"), 18.0, 21.0
    ) is False


@pytest.mark.asyncio
async def test_away_temperature_is_written_when_everyone_leaves(
    hass, enable_custom_integrations
):
    """Leaving lowers to the away setpoint; returning heats to comfort."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config["away_temperature"] = 16.0

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        _set_climate(hass, temperature=21.0)

        hass.states.async_set("binary_sensor.someone_home", "off")
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "away"
        assert coordinator.data["target_temperature"] == 16.0
        _set_climate(hass, temperature=16.0)

        hass.states.async_set("binary_sensor.someone_home", "on")
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "comfort"
    assert [call[2]["temperature"] for call in calls] == [21.0, 16.0, 21.0]


@pytest.mark.asyncio
async def test_heating_limit_holds_eco_until_it_cools_down(
    hass, enable_custom_integrations
):
    """Warm outdoor air pauses comfort heating; it resumes 1 °C below the limit."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set("sensor.outdoor_temperature", "17.0")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["heating_limit_temperature"] = 16.0

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "heating_limit"
        assert coordinator.data["heating_limit_reached"] is True

        # Just below the limit the hysteresis keeps the setback.
        hass.states.async_set("sensor.outdoor_temperature", "15.5")
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "heating_limit"

        hass.states.async_set("sensor.outdoor_temperature", "14.9")
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "comfort"
    assert coordinator.data["heating_limit_reached"] is False
    assert [call[2]["temperature"] for call in calls] == [21.0]


@pytest.mark.asyncio
async def test_weather_entity_temperature_is_used_without_outdoor_sensor(
    hass, enable_custom_integrations
):
    """Without an outdoor sensor the weather entity temperature is used."""
    _set_up_test_entities(hass)
    hass.states.async_set("sensor.outdoor_temperature", "unavailable")
    hass.states.async_set("weather.home", "sunny", {"temperature": 19.5})
    _, coordinator = await _setup_integration(hass)
    coordinator.config["weather_entity"] = "weather.home"
    coordinator.config["heating_limit_temperature"] = 18.0

    await coordinator.async_refresh()

    assert coordinator.data["outdoor_temperature"] == 19.5
    assert coordinator.data["mode"] == "heating_limit"


@pytest.mark.asyncio
async def test_window_delays_and_window_temperature(
    hass, enable_custom_integrations
):
    """Short airing is ignored; after closing the setback is held for a while."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config["window_open_delay"] = 300
    coordinator.config["window_close_delay"] = 600
    coordinator.config["window_temperature"] = 15.0
    start = dt_util.utcnow()

    async def refresh_at(seconds: int) -> None:
        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=start + timedelta(seconds=seconds),
        ):
            await coordinator.async_refresh()

    hass.states.async_set("binary_sensor.living_room_window", "on")
    await refresh_at(60)
    assert coordinator.data["window_contact_open"] is True
    assert coordinator.data["window_open"] is False
    assert coordinator.data["mode"] == "comfort"

    await refresh_at(400)
    assert coordinator.data["window_open"] is True
    assert coordinator.data["mode"] == "window"
    assert coordinator.data["target_temperature"] == 15.0

    hass.states.async_set("binary_sensor.living_room_window", "off")
    closed_at = (dt_util.utcnow() - start).total_seconds()
    await refresh_at(int(closed_at) + 300)
    assert coordinator.data["mode"] == "window"

    await refresh_at(int(closed_at) + 700)
    assert coordinator.data["window_open"] is False
    assert coordinator.data["mode"] == "comfort"


@pytest.mark.asyncio
async def test_frost_protection_floor_is_written(hass, enable_custom_integrations):
    """An away temperature below frost protection is raised to the floor."""
    _set_up_test_entities(hass, window_state="on")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["window_temperature"] = 7.0
    coordinator.config["frost_protection_temperature"] = 12.0

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "window"
    assert coordinator.data["target_temperature"] == 12.0
    assert [call[2]["temperature"] for call in calls] == [12.0]


@pytest.mark.asyncio
async def test_heating_season_off_stops_heating_and_unknown_keeps_it(
    hass, enable_custom_integrations
):
    """Winter mode off writes the thermostat minimum; unavailable keeps heating."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set("binary_sensor.winter_mode", "off")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["heating_season_entity"] = "binary_sensor.winter_mode"
    min_temp = hass.states.get("climate.living_room").attributes.get("min_temp", 7)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "season_off"
        assert coordinator.data["heating_season"] is False

        hass.states.async_set("binary_sensor.winter_mode", "unavailable")
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "comfort"
    assert coordinator.data["heating_season"] is True
    assert [call[2]["temperature"] for call in calls] == [float(min_temp), 21.0]


def _set_trv(hass, entity_id: str, state: str = "heat", temperature: float = 18.0):
    hass.states.async_set(
        entity_id,
        state,
        {"temperature": temperature, "min_temp": 5, "max_temp": 30,
         "target_temp_step": 0.5},
    )


@pytest.mark.asyncio
async def test_additional_thermostats_get_the_same_target(
    hass, enable_custom_integrations
):
    """Every thermostat of the room is written; unavailable ones are skipped."""
    _set_up_test_entities(hass)
    _set_trv(hass, "climate.living_room_2")
    _set_trv(hass, "climate.living_room_3")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = [
        "climate.living_room_2",
        "climate.living_room_3",
    ]

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert sorted(
            (call[2]["entity_id"], call[2]["temperature"]) for call in calls
        ) == [
            ("climate.living_room", 21.0),
            ("climate.living_room_2", 21.0),
            ("climate.living_room_3", 21.0),
        ]

        # Thermostats confirm 21 °C; then one drops out and the window opens.
        _set_climate(hass, temperature=21.0)
        _set_trv(hass, "climate.living_room_2", temperature=21.0)
        hass.states.async_set("climate.living_room_3", "unavailable")
        hass.states.async_set("binary_sensor.living_room_window", "on")
        await coordinator.async_refresh()

    assert coordinator.data["unavailable_thermostats"] == ["climate.living_room_3"]
    assert "nicht verfügbar" in coordinator.data["status"]
    assert sorted(
        call[2]["entity_id"] for call in calls if call[2]["temperature"] == 18.0
    ) == ["climate.living_room", "climate.living_room_2"]


@pytest.mark.asyncio
async def test_manual_change_on_additional_thermostat_pauses_room(
    hass, enable_custom_integrations
):
    """A manual change on any thermostat of the room pauses control."""
    _set_up_test_entities(hass)
    _set_trv(hass, "climate.living_room_2")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_2"]

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        _set_climate(hass, temperature=21.0)
        _set_trv(hass, "climate.living_room_2", temperature=21.0)
        await coordinator.async_refresh()
        _set_trv(hass, "climate.living_room_2", temperature=23.0)
        await coordinator.async_refresh()

    assert coordinator.data["manual_override"] is True
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_calibration_shifts_each_valve_by_its_measurement_error(
    hass, enable_custom_integrations
):
    """A valve reading warmer than the room gets a higher setpoint."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set(
        "climate.living_room_2",
        "heat",
        {"temperature": 18.0, "current_temperature": 21.0, "min_temp": 5,
         "max_temp": 30, "target_temp_step": 0.5},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_2"]
    coordinator.config["calibration"] = True
    start = dt_util.utcnow()

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=start,
        ):
            await coordinator.async_refresh()
        # Room 18 °C, valve 21 °C: comfort 21 becomes 24 at that valve. The
        # primary reports no own temperature and keeps the plain target.
        assert coordinator.data["thermostat_setpoints"] == {
            "climate.living_room": 21.0,
            "climate.living_room_2": 24.0,
        }

        # A new valve reading inside the interval does not move the setpoint.
        hass.states.async_set(
            "climate.living_room_2",
            "heat",
            {"temperature": 24.0, "current_temperature": 22.0, "min_temp": 5,
             "max_temp": 30, "target_temp_step": 0.5},
        )
        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=start + timedelta(minutes=5),
        ):
            await coordinator.async_refresh()
        assert coordinator.data["thermostat_setpoints"]["climate.living_room_2"] == 24.0

        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=start + timedelta(minutes=11),
        ):
            await coordinator.async_refresh()

    assert coordinator.data["thermostat_setpoints"]["climate.living_room_2"] == 25.0
    assert [
        call[2]["temperature"]
        for call in calls
        if call[2]["entity_id"] == "climate.living_room_2"
    ] == [24.0, 25.0]


@pytest.mark.asyncio
async def test_valve_maintenance_opens_closes_and_resumes(
    hass, enable_custom_integrations
):
    """Due maintenance drives the valve to max, then min, then back to target."""
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["valve_maintenance"] = True
    start = dt_util.as_utc(
        dt_util.now().replace(hour=11, minute=0, second=0, microsecond=0)
    )

    async def refresh_at(seconds: int) -> None:
        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=start + timedelta(seconds=seconds),
        ):
            await coordinator.async_refresh()

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await refresh_at(0)
        assert coordinator.data["valve_maintenance"] == "open"
        await refresh_at(320)
        assert coordinator.data["valve_maintenance"] == "close"
        await refresh_at(620)
        assert coordinator.data["valve_maintenance"] is None
        # It does not start again in the same week.
        await refresh_at(700)

    assert coordinator.data["valve_maintenance"] is None
    assert [call[2]["temperature"] for call in calls] == [
        28.0,
        7.0,
        coordinator.data["target_temperature"],
    ]


@pytest.mark.asyncio
async def test_calibration_hysteresis_ignores_small_offset_changes(
    hass, enable_custom_integrations
):
    """Offset changes below the hysteresis do not re-adjust the valve."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set(
        "climate.living_room_2",
        "heat",
        {"temperature": 18.0, "current_temperature": 21.0, "min_temp": 5,
         "max_temp": 30, "target_temp_step": 0.5},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_2"]
    coordinator.config["calibration"] = True
    coordinator.config["hysteresis"] = 0.5
    start = dt_util.utcnow()

    async def refresh_with_valve_at(
        valve: float, minutes: int, setpoint: float = 24.0
    ) -> None:
        hass.states.async_set(
            "climate.living_room_2",
            "heat",
            {"temperature": setpoint, "current_temperature": valve, "min_temp": 5,
             "max_temp": 30, "target_temp_step": 0.5},
        )
        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=start + timedelta(minutes=minutes),
        ):
            await coordinator.async_refresh()

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await refresh_with_valve_at(21.0, 0, setpoint=18.0)
        # +0.4 °C after the interval: inside the hysteresis, no new setpoint.
        await refresh_with_valve_at(21.4, 11)
        assert coordinator.data["thermostat_setpoints"]["climate.living_room_2"] == 24.0
        # +0.8 °C against the adopted offset: re-adjusted.
        await refresh_with_valve_at(21.8, 22)

    assert [
        call[2]["temperature"]
        for call in calls
        if call[2]["entity_id"] == "climate.living_room_2"
    ] == [24.0, 25.0]


@pytest.mark.asyncio
async def test_unavailable_room_sensor_falls_back_to_thermostat_readings(
    hass, enable_custom_integrations
):
    """Without the room sensor, the valves' own mean temperature is used."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {"temperature": 18.0, "current_temperature": 19.0, "min_temp": 7,
         "max_temp": 28},
    )
    hass.states.async_set(
        "climate.living_room_2",
        "heat",
        {"temperature": 18.0, "current_temperature": 20.0, "min_temp": 5,
         "max_temp": 30},
    )
    hass.states.async_set("sensor.living_room_temperature", "unavailable")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_2"]

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "comfort"
    assert coordinator.data["room_temperature"] == 19.5
    assert coordinator.data["room_temperature_source"] == "thermostats"
    assert "Ersatzwert" in coordinator.data["status"]
    assert sorted(call[2]["entity_id"] for call in calls) == [
        "climate.living_room",
        "climate.living_room_2",
    ]


@pytest.mark.asyncio
async def test_no_room_sensor_and_no_thermostat_reading_waits(
    hass, enable_custom_integrations
):
    """Without any temperature at all, nothing is written."""
    _set_up_test_entities(hass)
    hass.states.async_set("sensor.living_room_temperature", "unavailable")
    _, coordinator = await _setup_integration(hass)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "waiting"
    assert calls == []


@pytest.mark.asyncio
async def test_thermostat_problems_are_reported(hass, enable_custom_integrations):
    """Low battery, a device fault and an unreachable valve raise the problem sensor."""
    _set_up_test_entities(hass)
    trv_entry = MockConfigEntry(domain="mqtt")
    trv_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=trv_entry.entry_id, identifiers={("mqtt", "trv_1")}
    )
    registry = er.async_get(hass)
    for domain, unique_id, object_id in (
        ("climate", "trv_1_climate", "living_room_trv"),
        ("sensor", "trv_1_battery", "living_room_battery"),
        ("binary_sensor", "trv_1_alarm", "living_room_valve_alarm"),
    ):
        registry.async_get_or_create(
            domain,
            "mqtt",
            unique_id,
            suggested_object_id=object_id,
            device_id=device.id,
            config_entry=trv_entry,
        )
    hass.states.async_set(
        "sensor.living_room_battery", "15", {"device_class": "battery"}
    )
    hass.states.async_set(
        "binary_sensor.living_room_valve_alarm",
        "on",
        {"device_class": "problem", "friendly_name": "Ventilalarm"},
    )
    _set_trv(hass, "climate.living_room_trv")
    hass.states.async_set("climate.living_room_3", "unavailable")
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = [
        "climate.living_room_trv",
        "climate.living_room_3",
    ]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.data["thermostat_warnings"] == {
        "climate.living_room_trv": [
            "Batterie schwach (15 %)",
            "meldet Problem (Ventilalarm)",
        ],
        "climate.living_room_3": ["nicht erreichbar"],
    }
    problem_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_thermostat_problem"
    )
    assert hass.states.get(problem_id).state == "on"

    hass.states.async_set(
        "sensor.living_room_battery", "80", {"device_class": "battery"}
    )
    hass.states.async_set(
        "binary_sensor.living_room_valve_alarm", "off", {"device_class": "problem"}
    )
    coordinator.config["additional_climate_entities"] = ["climate.living_room_trv"]
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert coordinator.data["thermostat_warnings"] == {}
    assert hass.states.get(problem_id).state == "off"


def _set_up_aqara_trv(hass):
    """Register a thermostat device with an external temperature input."""
    trv_entry = MockConfigEntry(domain="mqtt")
    trv_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=trv_entry.entry_id, identifiers={("mqtt", "aqara_1")}
    )
    registry = er.async_get(hass)
    for domain, unique_id, object_id in (
        ("climate", "aqara_1_climate", "living_room_aqara"),
        ("select", "aqara_1_sensor", "living_room_aqara_sensor"),
        ("number", "aqara_1_external_temperature_input", "living_room_aqara_external_temperature_input"),
    ):
        registry.async_get_or_create(
            domain,
            "mqtt",
            unique_id,
            suggested_object_id=object_id,
            device_id=device.id,
            config_entry=trv_entry,
        )
    hass.states.async_set(
        "climate.living_room_aqara",
        "heat",
        {"temperature": 18.0, "current_temperature": 23.0, "min_temp": 5,
         "max_temp": 30, "target_temp_step": 0.5},
    )
    hass.states.async_set(
        "select.living_room_aqara_sensor",
        "internal",
        {"options": ["internal", "external"]},
    )
    hass.states.async_set(
        "number.living_room_aqara_external_temperature_input", "0"
    )


@contextmanager
def _capture_all_calls(hass):
    """Record climate/select/number calls and apply select changes to states."""
    calls = []
    service_registry_type = type(hass.services)
    original_call = service_registry_type.async_call

    async def record_calls(
        service_registry, domain, service, service_data=None, *args, **kwargs
    ):
        if domain in ("climate", "select", "number"):
            calls.append((domain, service, dict(service_data)))
            if domain == "select":
                state = hass.states.get(service_data["entity_id"])
                hass.states.async_set(
                    service_data["entity_id"], service_data["option"], state.attributes
                )
            return None
        return await original_call(
            service_registry, domain, service, service_data, *args, **kwargs
        )

    with patch.object(service_registry_type, "async_call", record_calls):
        yield calls


@pytest.mark.asyncio
async def test_room_temperature_is_fed_to_external_sensor_thermostats(
    hass, enable_custom_integrations
):
    """Supported valves get the room temperature and no calibration offset."""
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    _set_up_aqara_trv(hass)
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_aqara"]
    coordinator.config["calibration"] = True
    coordinator.config["external_temperature"] = True

    with _capture_all_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        # Unchanged room temperature: nothing is sent again.
        await coordinator.async_refresh()

    assert ("number", "set_value", {
        "entity_id": "number.living_room_aqara_external_temperature_input",
        "value": 18.0,
    }) in calls
    assert ("select", "select_option", {
        "entity_id": "select.living_room_aqara_sensor", "option": "external",
    }) in calls
    assert [c for c in calls if c[0] == "number"] == [calls[0]]
    assert coordinator.data["external_temperature_thermostats"] == [
        "climate.living_room_aqara"
    ]
    # Fed with the room temperature, the valve gets the plain target, not
    # target + (23 - 18).
    assert coordinator.data["thermostat_setpoints"]["climate.living_room_aqara"] == 21.0

    with _capture_all_calls(hass) as calls:
        hass.states.async_set("sensor.living_room_temperature", "18.3")
        await coordinator.async_refresh()
    assert calls[0] == ("number", "set_value", {
        "entity_id": "number.living_room_aqara_external_temperature_input",
        "value": 18.3,
    })

    # Room sensor gone: the valve goes back to its own sensor.
    with _capture_all_calls(hass) as calls:
        hass.states.async_set("sensor.living_room_temperature", "unavailable")
        await coordinator.async_refresh()
    assert ("select", "select_option", {
        "entity_id": "select.living_room_aqara_sensor", "option": "internal",
    }) in calls
    assert coordinator.data["external_temperature_thermostats"] == []


@pytest.mark.asyncio
async def test_external_sensor_is_released_when_control_stops_or_unloads(
    hass, enable_custom_integrations
):
    """Switching control off or unloading hands the valve back to its sensor."""
    _set_up_test_entities(hass)
    _set_up_aqara_trv(hass)
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_aqara"]
    coordinator.config["external_temperature"] = True

    with _capture_all_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert hass.states.get("select.living_room_aqara_sensor").state == "external"
        coordinator.enabled = False
        await coordinator.async_refresh()
        assert hass.states.get("select.living_room_aqara_sensor").state == "internal"

        coordinator.enabled = True
        await coordinator.async_refresh()
        assert hass.states.get("select.living_room_aqara_sensor").state == "external"
        assert await hass.config_entries.async_unload(entry.entry_id)
        assert hass.states.get("select.living_room_aqara_sensor").state == "internal"


@pytest.mark.asyncio
async def test_external_temperature_option_off_touches_nothing(
    hass, enable_custom_integrations
):
    """Without the option, select and number entities are left alone."""
    _set_up_test_entities(hass)
    _set_up_aqara_trv(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_aqara"]

    with _capture_all_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert [c for c in calls if c[0] != "climate"] == []
