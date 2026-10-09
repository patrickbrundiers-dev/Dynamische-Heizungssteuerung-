"""Integration tests using an isolated Home Assistant test instance."""

from contextlib import contextmanager
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    assert "Proximity-Entität nicht verfügbar" in coordinator.data["status"]

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
            "presence_schedule_entity": "schedule.presence_active",
        },
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    config = diagnostics["config"]

    assert config["person_entities"] != ["person.patrick", "person.jenny"]
    assert config["guest_entity"] != "input_boolean.guest_mode"
    assert config["proximity_entity"] != "proximity.home"
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
        return_value=start + timedelta(seconds=300),
    ):
        await coordinator._learn(
            20.6, climate, window_open=False, present=True,
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
        return_value=start + timedelta(hours=1),
    ):
        await coordinator._learn(
            18.5, climate, window_open=False, present=True,
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


