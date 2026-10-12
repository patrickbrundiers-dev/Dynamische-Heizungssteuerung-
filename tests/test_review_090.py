"""Integration tests for the 0.9.0 review of the control logic."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_trv,
    _set_up_test_entities,
    _setup_integration,
)

_UTCNOW = "custom_components.dynamic_heating.coordinator.dt_util.utcnow"


def _comfort_now(hass) -> None:
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=12)).isoformat()},
    )


@pytest.mark.asyncio
async def test_valve_turned_in_several_steps_keeps_the_last_value(
    hass, enable_custom_integrations
):
    """Each click of a knob arrives on its own; the room follows to the end."""
    _set_up_test_entities(hass)
    _set_trv(hass, "climate.living_room_2")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["additional_climate_entities"] = ["climate.living_room_2"]

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        target = coordinator.data["target_temperature"]
        _set_trv(hass, "climate.living_room", temperature=target)
        _set_trv(hass, "climate.living_room_2", temperature=target)
        await coordinator.async_refresh()
        # The knob is still turning when the first value is taken over.
        _set_trv(hass, "climate.living_room_2", temperature=22.0)
        await coordinator.async_refresh()
        assert coordinator.quick_temperature == 22.0
        _set_trv(hass, "climate.living_room", temperature=22.0)
        _set_trv(hass, "climate.living_room_2", temperature=23.5)
        await coordinator.async_refresh()

    assert coordinator.quick_temperature == 23.5
    assert coordinator.data["target_temperature"] == 23.5
    # The turned valve is never set back to the intermediate value.
    assert not any(
        call[2] == {"entity_id": "climate.living_room_2", "temperature": 22.0}
        for call in calls
    )
    assert calls[-1][2] == {"entity_id": "climate.living_room", "temperature": 23.5}


@pytest.mark.asyncio
async def test_heating_watchdog_sees_a_room_that_only_creeps_up(
    hass, enable_custom_integrations
):
    """Creeping up 0.1 °C an hour while 2 °C short is still a heating problem."""
    _set_up_test_entities(hass, room_temperature="19.0")
    _comfort_now(hass)
    _, coordinator = await _setup_integration(hass)
    start = dt_util.utcnow()

    async def refresh_at(minutes: int, temperature: str) -> bool:
        at = start + timedelta(minutes=minutes)
        hass.states.async_set(
            "sensor.living_room_temperature",
            temperature,
            force_update=True,
            timestamp=at.timestamp(),
        )
        with patch(_UTCNOW, return_value=at):
            await coordinator.async_refresh()
        return coordinator.data["heating_problem"]

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        assert await refresh_at(0, "19.0") is False
        assert await refresh_at(60, "19.1") is False
        assert await refresh_at(100, "19.3") is False
        # 0.3 °C in two hours: far too slow for a 2 °C gap.
        assert await refresh_at(121, "19.3") is True
        assert "19,3" in coordinator.data["heating_problem_detail"]
        # Really warming up now: the problem clears.
        assert await refresh_at(150, "19.9") is False


@pytest.mark.asyncio
async def test_heating_watchdog_survives_a_restart(hass, enable_custom_integrations):
    """A restart does not start the two hours again."""
    _set_up_test_entities(hass, room_temperature="19.0")
    _comfort_now(hass)
    entry, coordinator = await _setup_integration(hass)
    start = dt_util.utcnow()

    def set_room(at, temperature):
        hass.states.async_set(
            "sensor.living_room_temperature",
            temperature,
            force_update=True,
            timestamp=at.timestamp(),
        )

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        set_room(start, "19.0")
        with patch(_UTCNOW, return_value=start):
            await coordinator.async_refresh()
        assert coordinator._runtime_state()["shortfall"] is not None
        saved = coordinator._runtime_state()

        restarted = type(coordinator)(hass, dict(coordinator.config), entry.entry_id)
        later = start + timedelta(minutes=125)
        with patch.object(
            restarted._state_store, "async_load", return_value=saved
        ):
            await restarted.async_load_state()
        restarted.enabled = True
        set_room(later, "19.1")
        with patch(_UTCNOW, return_value=later):
            await restarted.async_refresh()

    assert restarted.data["heating_problem"] is True


@pytest.mark.asyncio
async def test_learning_uses_the_room_target_not_a_shifted_valve_setpoint(
    hass, enable_custom_integrations
):
    """A valve offset must not hide a heating phase from the learning model."""
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {"temperature": 20.0, "min_temp": 7, "max_temp": 28},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config["comfort_temperature"] = 21.0
    coordinator.valve_offsets["climate.living_room"] = -1.0

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        await coordinator.async_refresh()

    # The valve holds 20 °C (21 - 1), the room is 1 °C below its target.
    assert coordinator.data["learning_status"] != (
        "Warte auf aktive Heizphase unter Solltemperatur"
    )
    assert coordinator._heating_sample.started_at is not None


@pytest.mark.asyncio
async def test_slow_heating_is_learned_instead_of_rejected(
    hass, enable_custom_integrations
):
    """A room that heats slower than the model's floor teaches the floor."""
    _set_up_test_entities(hass, room_temperature="19.0")
    _comfort_now(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["comfort_temperature"] = 22.0
    start = dt_util.utcnow()

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        for minutes, temperature in ((0, "19.0"), (10, "19.1"), (130, "19.3")):
            at = start + timedelta(minutes=minutes)
            hass.states.async_set(
                "sensor.living_room_temperature",
                temperature,
                force_update=True,
                timestamp=at.timestamp(),
            )
            hass.states.async_set(
                "climate.living_room",
                "heat",
                {"temperature": 22.0, "min_temp": 7, "max_temp": 28},
            )
            with patch(_UTCNOW, return_value=at):
                await coordinator.async_refresh()

    assert coordinator.data["heating_samples"] == 1
    assert coordinator.data["rejected_samples"] == 0
    # 0.2 °C in two hours = 0.1 °C/h, counted as the 0.2 °C/h floor.
    assert coordinator.heating_rate == pytest.approx(0.8 * 1.0 + 0.2 * 0.2)


@pytest.mark.asyncio
async def test_valve_already_at_target_is_not_set_back_when_turned(
    hass, enable_custom_integrations
):
    """After a restart the valves often hold the target already; a turn counts."""
    _set_up_test_entities(hass)
    _comfort_now(hass)
    _set_trv(hass, "climate.living_room", temperature=21.0)
    _, coordinator = await _setup_integration(hass)

    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert calls == []
        _set_trv(hass, "climate.living_room", temperature=23.0)
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "quick_manual"
    assert coordinator.data["target_temperature"] == 23.0
    assert not any(call[2]["temperature"] == 21.0 for call in calls)
