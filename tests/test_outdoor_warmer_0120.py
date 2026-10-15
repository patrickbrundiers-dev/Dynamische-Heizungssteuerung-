"""0.12.0: 15.10. – 20 °C outside, rooms at 19–21 °C and still heating,
because the heating limit judged the two-day forecast average (13 °C)."""

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.logic import (
    decide_heating_target,
    evaluate_outdoor_warmer,
)


def _decide(**overrides):
    values = dict(
        now=datetime.now(UTC),
        schedule_active=True,
        next_event=None,
        room_temperature=19.6,
        outdoor_temperature=20.0,
        comfort_temperature=20.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        off_temperature=5.0,
        outdoor_warmer=True,
    )
    values.update(overrides)
    return decide_heating_target(**values)


def test_warmer_outside_than_inside_reached_and_released_with_hysteresis() -> None:
    assert evaluate_outdoor_warmer(20.0, 19.6, False)
    assert evaluate_outdoor_warmer(19.6, 19.6, False)
    assert not evaluate_outdoor_warmer(19.5, 19.6, False)
    # Once reached, heating resumes only 0.5 °C below the room.
    assert evaluate_outdoor_warmer(19.2, 19.6, True)
    assert not evaluate_outdoor_warmer(19.1, 19.6, True)
    # With a margin the outdoor value may be that much below the room.
    assert evaluate_outdoor_warmer(20.0, 20.9, False, margin=1.0)
    assert not evaluate_outdoor_warmer(20.0, 20.9, False)
    assert not evaluate_outdoor_warmer(None, 19.6, True)
    assert not evaluate_outdoor_warmer(20.0, None, True)


def test_warmer_outside_beats_comfort_with_frost_floor() -> None:
    decision = _decide()
    assert decision.mode == "outdoor_warm"
    assert decision.status == "Außen wärmer als innen – nicht geheizt"
    assert decision.target_temperature == 5.0
    floored = _decide(frost_protection_temperature=12.0)
    assert floored.target_temperature == 12.0


def test_hand_picked_heating_and_windows_still_win() -> None:
    assert _decide(boost_temperature=24.0).mode == "boost"
    assert _decide(quick_mode=("quick_comfort", "Komfort", 21.0)).mode == "quick_comfort"
    for mode in ("quick_sleep", "quick_home", "quick_activity", "learn_run"):
        assert _decide(quick_mode=(mode, "von Hand", 21.0)).mode == mode
    assert _decide(window_open=True, window_temperature=15.0).mode == "window"
    assert _decide(heating_season=False).mode == "season_off"
    assert _decide(maintenance_temperature=30.0).mode == "maintenance"
    # Automatic house modes (return preheat) do not heat the warm room.
    assert _decide(quick_mode=("house_return", "Rückkehr", 21.0)).mode == "outdoor_warm"
    assert _decide(outdoor_warmer=False).mode == "comfort"


@pytest.mark.asyncio
async def test_warm_afternoon_stops_comfort_and_cooler_evening_resumes(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set("sensor.living_room_temperature", "19.6")
    hass.states.async_set("sensor.outdoor_temperature", "20.0")
    hass.states.async_set("binary_sensor.winter_mode", "on")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["heating_season_entity"] = "binary_sensor.winter_mode"
    min_temp = hass.states.get("climate.living_room").attributes.get("min_temp", 7)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "outdoor_warm"
        assert coordinator.data["outdoor_warmer"] is True
        assert coordinator.data["target_temperature"] == float(min_temp)

        # Slightly cooler outside: still within the hysteresis.
        hass.states.async_set("sensor.outdoor_temperature", "19.3")
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "outdoor_warm"

        hass.states.async_set("sensor.outdoor_temperature", "18.5")
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "comfort"
        assert coordinator.data["outdoor_warmer"] is False

    assert [call[2]["temperature"] for call in calls][0] == float(min_temp)


@pytest.mark.asyncio
async def test_rule_off_or_without_winter_mode_keeps_previous_behaviour(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )
    hass.states.async_set("sensor.living_room_temperature", "19.6")
    hass.states.async_set("sensor.outdoor_temperature", "20.0")
    hass.states.async_set("binary_sensor.winter_mode", "off")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["heating_season_entity"] = "binary_sensor.winter_mode"

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "season_off"
        assert coordinator.data["outdoor_warmer"] is False

        hass.states.async_set("binary_sensor.winter_mode", "on")
        coordinator.config["outdoor_warmer_stop"] = False
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "comfort"

        coordinator.config["outdoor_warmer_stop"] = True
        coordinator.config["outdoor_warmer_margin"] = 1.0
        hass.states.async_set("sensor.living_room_temperature", "20.9")
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "outdoor_warm"
