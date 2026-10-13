"""0.9.12: what went wrong on 13.10. – valves left on their own program after
a restart, valve readings as room temperature right after a start."""

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_runde9_099 import _tuya_valve


@pytest.mark.asyncio
async def test_valve_reporting_unknown_after_start_still_goes_back_to_heat(
    hass, enable_custom_integrations
):
    # 13.10. 07:15: the valves said "unknown" for a minute after the restart,
    # were taken as done and kept running their own week program all day.
    _tuya_valve(hass)
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    _set_up_test_entities(hass)
    attributes = {
        **hass.states.get("climate.living_room").attributes,
        "hvac_modes": ["auto", "heat", "off"],
    }
    hass.states.async_set("climate.living_room", "heat", attributes)
    _entry, coordinator = await _setup_integration(hass)
    hass.services.async_register("climate", "set_hvac_mode", record)
    coordinator.enabled = True
    coordinator.config["valve_fallback"] = True
    await coordinator.async_arm_valve_fallback()
    assert coordinator._fallback_auto == ["climate.living_room"]
    calls.clear()

    hass.states.async_set("climate.living_room", "unknown", attributes)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator._fallback_auto == ["climate.living_room"]
    assert not [call for call in calls if call[1] == "set_hvac_mode"]

    hass.states.async_set("climate.living_room", "auto", attributes)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert (
        "climate", "set_hvac_mode",
        {"entity_id": "climate.living_room", "hvac_mode": "heat"},
    ) in calls
    assert coordinator._fallback_auto == []


@pytest.mark.asyncio
async def test_valve_readings_do_not_stand_in_for_the_room_right_after_a_start(
    hass, enable_custom_integrations
):
    # 13.10.: after each restart the room temperature showed 21–23 °C (the
    # valves next to the radiator) until the room sensor came back.
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {"temperature": 18.0, "current_temperature": 23.0, "min_temp": 7,
         "max_temp": 28},
    )
    hass.states.async_set("sensor.living_room_temperature", "unavailable")
    _, coordinator = await _setup_integration(hass)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["room_temperature"] is None
    assert calls == []

    # Later on, a sensor that stays away is replaced by the valves.
    coordinator._started_at -= timedelta(minutes=15)
    await coordinator.async_refresh()
    assert coordinator.data["room_temperature"] == 23.0
    assert coordinator.data["room_temperature_source"] == "thermostats"
