"""0.12.1: review of 13.–17.10. – the boiler's night pause was learned as
delivery (an idle valve still read warm), false alarms at 4 o'clock, a
flickering setback status and the thermostat problem around restarts."""

from datetime import timedelta

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.radiator import (
    IDLE,
    SUPPLY_COLD,
    SUPPLY_IDLE,
    SUPPLY_WARM,
    WAITING,
    WARM,
    COLD,
    RadiatorTracker,
    SupplyProfile,
    house_supply,
    judged_supply,
)

# 1 – the night pause


def test_stale_warm_reading_at_heating_start_is_not_warm():
    # Wohnzimmer 16.10.: the valve still read 24 °C from the evening when
    # preheating began at 02:58, with no new reading until 05:24.
    tracker = RadiatorTracker()
    assert tracker.observe(0, 0, 24.0, 20.0) == WARM  # idle: shown as warm
    assert tracker.observe(60, 80, 24.0, 20.0) == WAITING
    assert tracker.observe(1800, 80, 24.0, 19.9) == WAITING
    assert tracker.observe(3700, 80, 24.0, 19.8) == COLD
    # A fresh reading from the radiator counts again.
    assert tracker.observe(3800, 80, 24.2, 19.8) == WARM


def test_fresh_warm_reading_still_counts():
    tracker = RadiatorTracker()
    assert tracker.observe(0, 80, 20.0, 19.5) == WAITING
    assert tracker.observe(600, 80, 23.5, 19.5) == WARM


def test_only_rooms_asking_for_heat_judge_the_boiler():
    assert judged_supply(SUPPLY_WARM, False) == SUPPLY_IDLE
    assert judged_supply(SUPPLY_WARM, True) == SUPPLY_WARM
    assert judged_supply(None, False) is None
    # One idle room with a warm valve no longer outvotes a cold one.
    assert house_supply([judged_supply(SUPPLY_WARM, False), SUPPLY_COLD]) == (
        SUPPLY_COLD
    )


def test_night_without_demand_is_not_learned_as_delivery():
    profile = SupplyProfile()
    for minute in range(0, 61, 5):
        profile.observe(1 if minute < 60 else 2, judged_supply(SUPPLY_WARM, False), 300)
    assert profile.slots[1] is None
    assert not profile.usually_off(1)


@pytest.mark.asyncio
async def test_watchdog_stays_quiet_while_the_boiler_pauses(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    coordinator.data["house_supply"] = SUPPLY_COLD
    coordinator.data["radiator_supply"] = SUPPLY_COLD
    coordinator._shortfall_since = dt_util.utcnow() - timedelta(hours=3)
    coordinator._shortfall_temperature = 18.0
    coordinator._update_heating_watchdog(21.0, 18.0, watch=True)
    assert coordinator.heating_problem is False
    coordinator.data["house_supply"] = SUPPLY_WARM
    coordinator.data["radiator_supply"] = None
    coordinator.data["supply_usually_off"] = False
    coordinator._shortfall_since = dt_util.utcnow() - timedelta(hours=3)
    coordinator._shortfall_temperature = 18.0
    coordinator._update_heating_watchdog(21.0, 18.0, watch=True)
    assert coordinator.heating_problem is True


@pytest.mark.asyncio
async def test_idle_room_does_not_tell_the_house_about_the_boiler(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert "supply_judged" in coordinator.data
    if coordinator.data.get("radiator_supply") in (None, SUPPLY_IDLE):
        assert coordinator.data["supply_judged"] in (None, SUPPLY_IDLE)


# 2 – the setback floor does not flicker


@pytest.mark.asyncio
async def test_setback_floor_changes_only_in_steps(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    coordinator._setback_floor = 19.2
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    floor = coordinator.data.get("setback_floor")
    if floor is not None:
        assert floor == 19.2 or abs(floor - 19.2) >= 0.2 - 1e-9


# 7 – no thermostat problem for a valve that is gone only for a moment


@pytest.mark.asyncio
async def test_unreachable_thermostat_needs_a_grace_time(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    climate_id = coordinator._thermostat_ids()[0]
    hass.states.async_set(climate_id, "unavailable")
    assert climate_id not in coordinator._thermostat_warnings()
    coordinator._unreachable_since[climate_id] = dt_util.utcnow() - timedelta(
        minutes=4
    )
    assert "nicht erreichbar" in coordinator._thermostat_warnings()[climate_id]


def test_idle_constant_is_reexported():
    # The coordinator imports IDLE from radiator for the asking check.
    assert IDLE == "idle"
