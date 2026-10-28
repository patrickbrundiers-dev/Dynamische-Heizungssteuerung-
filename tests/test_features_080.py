"""Integration tests for the 0.8.0 features (ideas from AHC, BT and CGH)."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
from test_home_assistant_sandbox import (
    _capture_all_calls,
    _config_data,
    _set_trv,
    _set_up_test_entities,
    _setup_house,
    _setup_integration,
)

from custom_components.dynamic_heating.const import DOMAIN

_UTCNOW = "custom_components.dynamic_heating.coordinator.dt_util.utcnow"


def _comfort_now(hass) -> None:
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=3)).isoformat()},
    )


def _set_setpoint(hass, entity_id: str, value: float) -> None:
    state = hass.states.get(entity_id)
    hass.states.async_set(
        entity_id, state.state, {**state.attributes, "temperature": value}
    )


@pytest.mark.asyncio
async def test_heating_limit_uses_the_two_day_average(hass, enable_custom_integrations):
    """A warm moment does not reach the limit when the last two days were cold."""
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    hass.states.async_set("sensor.outdoor_temperature", "16.0")
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["heating_limit_temperature"] = 15.0
    start = dt_util.utcnow() - timedelta(hours=8)
    coordinator._outdoor_history = [
        (start + timedelta(minutes=10 * index), 8.0) for index in range(48)
    ]
    await coordinator.async_refresh()
    assert coordinator.data["heating_limit_source"] == "history"
    assert coordinator.data["heating_limit_reached"] is False
    assert coordinator.data["mode"] == "comfort"

    # Without averaging the current 16 °C reach the limit.
    coordinator.config["heating_limit_average"] = False
    await coordinator.async_refresh()
    assert coordinator.data["heating_limit_source"] == "current"
    assert coordinator.data["heating_limit_reached"] is True
    assert coordinator.data["mode"] == "heating_limit"


@pytest.mark.asyncio
async def test_heating_limit_fallback_without_outdoor_temperature(
    hass, enable_custom_integrations
):
    """Without any outdoor value the room heats, unless told otherwise."""
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    hass.states.async_set("sensor.outdoor_temperature", "unavailable")
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["heating_limit_temperature"] = 15.0
    await coordinator.async_refresh()
    assert coordinator.data["heating_limit_reached"] is False
    coordinator.config["heating_limit_fallback_off"] = True
    await coordinator.async_refresh()
    assert coordinator.data["heating_limit_reached"] is True
    assert coordinator.data["heating_limit_source"] == "fallback"


@pytest.mark.asyncio
async def test_implausible_room_temperature_is_ignored_and_reported(
    hass, enable_custom_integrations
):
    """A reading of -40 °C is dropped and shows up under Repairs."""
    _set_up_test_entities(hass)
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    # Long after the start: the valves' readings may stand in for the room.
    coordinator._started_at -= timedelta(minutes=15)
    issue_id = f"implausible_room_temperature_{entry.entry_id}"
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {**hass.states.get("climate.living_room").attributes, "current_temperature": 19.5},
    )
    hass.states.async_set("sensor.living_room_temperature", "-40")
    await coordinator.async_refresh()
    assert coordinator.data["room_temperature"] == 19.5
    assert coordinator.data["room_temperature_source"] == "thermostats"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    hass.states.async_set("sensor.living_room_temperature", "20.1")
    await coordinator.async_refresh()
    assert coordinator.data["room_temperature"] == 20.1
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


async def _open_window_and_turn_valve(hass, coordinator):
    """Control on, window open, then the valve is turned to 23 °C."""
    coordinator.config["window_open_delay"] = 0
    coordinator.config["window_close_delay"] = 0
    with _capture_all_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        _set_setpoint(hass, "climate.living_room", coordinator.data["target_temperature"])
        await coordinator.async_refresh()
        hass.states.async_set("binary_sensor.living_room_window", "on")
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "window"
        _set_setpoint(hass, "climate.living_room", coordinator.data["target_temperature"])
        await coordinator.async_refresh()
        _set_setpoint(hass, "climate.living_room", 23.0)
        await coordinator.async_refresh()


@pytest.mark.asyncio
async def test_valve_turned_while_airing_applies_after_closing(
    hass, enable_custom_integrations
):
    """The value is kept, the open window still wins, closing applies it."""
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    await _open_window_and_turn_valve(hass, coordinator)
    assert coordinator.data["mode"] == "window"
    assert coordinator.data["window_change"] == "kept"
    assert "gemerkt" in coordinator.data["status"]
    assert coordinator.quick_mode == "manual"
    assert coordinator.quick_temperature == 23.0

    hass.states.async_set("binary_sensor.living_room_window", "off")
    with _capture_all_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "quick_manual"
    assert coordinator.data["target_temperature"] == 23.0


@pytest.mark.asyncio
async def test_valve_turned_while_airing_can_be_discarded(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["window_change"] = "discard"
    await _open_window_and_turn_valve(hass, coordinator)
    assert coordinator.data["window_change"] == "discarded"
    assert coordinator.quick_mode == "auto"


@pytest.mark.asyncio
async def test_doors_have_their_own_delay(hass, enable_custom_integrations):
    """A door opened briefly does not lower the room; a long-open one does."""
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    hass.states.async_set("binary_sensor.living_room_door", "on")
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["door_entities"] = ["binary_sensor.living_room_door"]
    await coordinator.async_refresh()
    assert coordinator.data["window_open"] is False
    assert coordinator.data["window_contact_open"] is True

    later = dt_util.utcnow() + timedelta(minutes=11)
    with patch(_UTCNOW, return_value=later):
        await coordinator.async_refresh()
    assert coordinator.data["window_open"] is True
    assert coordinator.data["mode"] == "window"


@pytest.mark.asyncio
async def test_skipped_valve_is_closed_and_left_alone(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    _set_trv(hass, "climate.living_room_2")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Wohnzimmer",
        unique_id="climate.living_room",
        data={**_config_data(), "additional_climate_entities": ["climate.living_room_2"]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    skip_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_skip_climate.living_room_2"
    )
    assert skip_id is not None

    with _capture_all_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_set_valve_skipped("climate.living_room_2", True)
    writes = {
        call[2]["entity_id"]: call[2]["temperature"]
        for call in calls
        if call[1] == "set_temperature"
    }
    assert writes["climate.living_room_2"] == 5.0
    assert writes["climate.living_room"] == 21.0
    assert coordinator.data["skipped_valves"] == ["climate.living_room_2"]
    assert "climate.living_room_2" not in coordinator.data["thermostat_setpoints"]

    # Taking it back sends the room's target again.
    with _capture_all_calls(hass) as calls:
        await coordinator.async_set_valve_skipped("climate.living_room_2", False)
    assert ("climate", "set_temperature", {
        "entity_id": "climate.living_room_2", "temperature": 21.0,
    }) in calls


@pytest.mark.asyncio
async def test_valve_that_does_not_take_the_setpoint_is_reported(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    with _capture_all_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        # The valve keeps reporting 18 °C instead of the 21 °C written.
        start = dt_util.utcnow()
        for minutes in (6, 12, 18):
            with patch(_UTCNOW, return_value=start + timedelta(minutes=minutes)):
                await coordinator.async_refresh()
    warnings = coordinator.data["thermostat_warnings"]["climate.living_room"]
    assert any("übernimmt den Sollwert nicht" in item for item in warnings)
    assert coordinator.data["valve_divergence"] == {
        "climate.living_room": "18,0 statt 21,0 °C"
    }


@pytest.mark.asyncio
async def test_entity_forces_comfort_with_the_temperature_in_its_name(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="20.0")
    hass.states.async_set(
        "schedule.living_room_comfort",
        "off",
        {"next_event": (dt_util.now() + timedelta(hours=8)).isoformat()},
    )
    hass.states.async_set("input_boolean.party", "on", {"friendly_name": "Party 23"})
    hass.states.async_set("input_boolean.sparen", "on", {"friendly_name": "Sparen"})
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["force_eco_entities"] = ["input_boolean.sparen"]
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "force_eco"
    coordinator.config["force_comfort_entities"] = ["input_boolean.party"]
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "force_comfort"
    assert coordinator.data["target_temperature"] == 23.0
    assert coordinator.data["status"] == "Komfort erzwungen – Party 23"
    # An open window still wins.
    hass.states.async_set("binary_sensor.living_room_window", "on")
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "window"


@pytest.mark.asyncio
async def test_schedule_block_pauses_window_and_presence(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, window_state="on", room_temperature="20.0")
    hass.states.async_set("binary_sensor.someone_home", "off")
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {
            "next_event": (dt_util.now() + timedelta(hours=3)).isoformat(),
            "fenster": "aus",
            "anwesenheit": "aus",
        },
    )
    entry, coordinator = await _setup_integration(hass)
    assert coordinator.data["mode"] == "comfort"
    assert coordinator.data["paused_features"] == ["presence", "window"]
    assert coordinator.data["window_open"] is False


@pytest.mark.asyncio
async def test_house_calendar_picks_schedules_and_comfort(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="20.0")
    hass.states.async_set(
        "schedule.living_room_comfort",
        "off",
        {"next_event": (dt_util.now() + timedelta(hours=8)).isoformat()},
    )
    hass.states.async_set(
        "schedule.ferien",
        "on",
        {
            "friendly_name": "Ferien",
            "next_event": (dt_util.now() + timedelta(hours=2)).isoformat(),
        },
    )
    end = (dt_util.now() + timedelta(days=3)).replace(tzinfo=None)
    hass.states.async_set(
        "calendar.haus",
        "on",
        {"message": "Ferien", "description": "", "end_time": end.isoformat(sep=" ")},
    )
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["additional_schedule_entities"] = ["schedule.ferien"]
    house_entry, house = await _setup_house(hass)
    hass.config_entries.async_update_entry(
        house_entry, options={"house_calendar": "calendar.haus"}
    )
    await coordinator.async_refresh()
    assert coordinator.active_schedule == "schedule.ferien"
    assert coordinator.data["house_calendar"] == "Ferien"
    assert coordinator.data["mode"] == "comfort"

    # An event naming no schedule of the room leaves it alone ...
    hass.states.async_set(
        "calendar.haus",
        "on",
        {"message": "Gäste", "description": "", "end_time": end.isoformat(sep=" ")},
    )
    await coordinator.async_refresh()
    assert coordinator.active_schedule == "schedule.living_room_comfort"
    assert coordinator.data["mode"] != "comfort"
    # ... unless it asks for comfort time.
    hass.states.async_set(
        "calendar.haus",
        "on",
        {
            "message": "Gäste",
            "description": "komfort: an\ntemperature: 22",
            "end_time": end.isoformat(sep=" "),
        },
    )
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"
    assert coordinator.data["target_temperature"] == 22.0
    # A room can opt out.
    coordinator.config["follow_house_calendar"] = False
    await coordinator.async_refresh()
    assert coordinator.data["mode"] != "comfort"


@pytest.mark.asyncio
async def test_valve_maintenance_on_demand_wakes_switched_off_valves(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    _set_trv(hass, "climate.living_room_2", state="off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test Wohnzimmer",
        unique_id="climate.living_room",
        data={**_config_data(), "additional_climate_entities": ["climate.living_room_2"]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    button_id = er.async_get(hass).async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_valve_maintenance_button"
    )
    assert button_id is not None
    coordinator.config["maintenance_duration"] = 60

    with _capture_all_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_start_valve_maintenance()
    assert coordinator.data["valve_maintenance"] == "open"
    assert ("climate", "set_hvac_mode", {
        "entity_id": "climate.living_room_2", "hvac_mode": "heat",
    }) in calls
    assert ("climate", "set_temperature", {
        "entity_id": "climate.living_room", "temperature": 28.0,
    }) in calls

    later = dt_util.utcnow() + timedelta(minutes=3)
    with _capture_all_calls(hass) as calls, patch(_UTCNOW, return_value=later):
        await coordinator.async_refresh()
    assert coordinator.data["valve_maintenance"] is None
    assert ("climate", "set_hvac_mode", {
        "entity_id": "climate.living_room_2", "hvac_mode": "off",
    }) in calls


@pytest.mark.asyncio
async def test_device_triggers_and_change_source(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    from custom_components.dynamic_heating.device_trigger import async_get_triggers

    triggers = await async_get_triggers(hass, device.id)
    assert {trigger["type"] for trigger in triggers} == {
        "heating_started", "heating_stopped", "target_reached",
        "window_opened", "window_closed", "humidity_high",
        "preheat_started",
    }
    events = async_capture_events(hass, "dynamic_heating_event")
    hass.states.async_set("binary_sensor.living_room_window", "on")
    await coordinator.async_refresh()
    assert [event.data["type"] for event in events] == ["window_opened"]
    assert events[0].data["device_id"] == device.id

    hass.states.async_set("binary_sensor.living_room_window", "off")
    await coordinator.async_refresh()
    await coordinator.async_set_quick_mode("eco", source="Taste")
    assert coordinator.data["last_change_source"] == "Taste"


@pytest.mark.asyncio
async def test_overshoot_is_learned_after_heating_stops(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    coordinator.data["target_temperature"] = 21.0
    start = dt_util.utcnow()
    track = coordinator._track_overshoot
    await track(20.5, True, window_open=False, now=start)
    await track(21.0, False, window_open=False, now=start + timedelta(minutes=5))
    await track(21.4, False, window_open=False, now=start + timedelta(minutes=20))
    await track(21.6, False, window_open=False, now=start + timedelta(minutes=35))
    assert coordinator._overshoot_samples == 0
    await track(21.45, False, window_open=False, now=start + timedelta(minutes=50))
    assert coordinator._overshoot_samples == 1
    assert coordinator.overshoot == 0.6


@pytest.mark.asyncio
async def test_command_delay_spaces_out_valve_commands(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["command_delay"] = 0.5
    type(coordinator)._last_command = None
    with patch(
        "custom_components.dynamic_heating.coordinator.asyncio.sleep"
    ) as sleep:
        await coordinator._pace()
        await coordinator._pace()
    assert sleep.await_count == 1
    assert 0 < sleep.await_args.args[0] <= 0.5


@pytest.mark.asyncio
async def test_target_reached_fires_when_the_room_warms_up(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="19.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    events = async_capture_events(hass, "dynamic_heating_event")
    await coordinator.async_refresh()
    hass.states.async_set("sensor.living_room_temperature", "20.9")
    await coordinator.async_refresh()
    assert [event.data["type"] for event in events] == ["target_reached"]
    # A lower target (window open) is no "reached".
    hass.states.async_set("sensor.living_room_temperature", "19.0")
    await coordinator.async_refresh()
    hass.states.async_set("binary_sensor.living_room_window", "on")
    await coordinator.async_refresh()
    assert [event.data["type"] for event in events] == [
        "target_reached", "window_opened"
    ]


def test_valve_entity_names_follow_the_valve_once_it_has_a_state() -> None:
    """After a restart the valve may have no state yet; the name must catch up."""
    from unittest.mock import MagicMock

    from custom_components.dynamic_heating.number import ValveOffset
    from custom_components.dynamic_heating.switch import SkipValveSwitch

    names = {}
    coordinator = MagicMock()
    coordinator._friendly_name.side_effect = lambda entity_id: names.get(
        entity_id, entity_id
    )
    entry = MagicMock(entry_id="room")
    offset = ValveOffset(coordinator, entry, "climate.sofa")
    skip = SkipValveSwitch(coordinator, entry, "climate.sofa")
    assert offset.name == "Versatz climate.sofa"

    names["climate.sofa"] = "Hinter Sofa"
    assert offset.name == "Versatz Hinter Sofa"
    assert skip.name == "Auslassen Hinter Sofa"
