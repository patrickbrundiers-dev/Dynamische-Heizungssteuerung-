"""0.17.0: room model trust over three hours, homecoming pooled over workdays,
comfort by motion (bathroom)."""

from datetime import date, datetime, timedelta

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_runde7_094 import _setup_house
from test_smart_090 import _trained_model

from custom_components.dynamic_heating.model import (
    HORIZON_MIN,
    HORIZON_WINDOW,
    TRUSTED_HORIZON_ERROR,
    RoomModel,
)
from custom_components.dynamic_heating.routine import Homecoming

# --- 2: room model ------------------------------------------------------------


def _feed(model: RoomModel, hours: int, noise, start: float = 0.0, step: float = 3600):
    """Hourly samples of a room following the equation, plus ``noise(hour)``."""
    room = 19.0
    for hour in range(hours):
        outdoor = 8.0
        demand = (0.0, 0.5, 1.0)[hour % 3]
        rate = 0.6 * demand - 0.02 * (room - outdoor)
        model.add(
            rate + noise(hour), demand, room, outdoor, at=start + (hour + 1) * step
        )
        room += rate


def test_hourly_noise_that_cancels_out_still_earns_trust():
    # Doors and showers: ±0.2 °C/h every hour, alternating. The hourly error
    # stays far above 0.12, but over three hours the room is well predicted.
    model = RoomModel()
    _feed(model, 120, lambda hour: 0.2 if hour % 2 else -0.2)
    assert model.mean_error is not None and model.mean_error > 0.12
    assert model.horizon_error is not None
    assert model.horizon_error < TRUSTED_HORIZON_ERROR
    assert model.trusted


def test_errors_that_add_up_over_hours_cost_trust():
    model = RoomModel()
    # A steady drift the equation does not know: 0.25 °C/h too warm.
    _feed(model, 120, lambda hour: 0.25 if (hour // 12) % 2 else -0.25)
    assert model.horizon_error is not None
    assert model.horizon_error > TRUSTED_HORIZON_ERROR
    assert not model.trusted


def test_gaps_break_the_three_hour_chain_and_old_rule_applies_until_enough():
    model = RoomModel()
    # Samples five hours apart never chain.
    _feed(model, 60, lambda hour: 0.0, step=5 * 3600)
    assert model.horizon_errors == []
    assert model.horizon_error is None
    # Without three-hour errors the hourly rule decides, as before.
    assert model.trusted == (model.mean_error <= 0.12)


def test_three_hour_errors_survive_a_restart_and_stay_bounded():
    model = RoomModel()
    _feed(model, 200, lambda hour: 0.05)
    assert len(model.horizon_errors) == HORIZON_WINDOW
    restored = RoomModel.from_dict(model.as_dict())
    assert restored.horizon_errors == model.horizon_errors
    assert restored.chain == model.chain
    assert restored.last_at == model.last_at
    assert restored.trusted == model.trusted
    # Old saved models without the new fields load as before.
    data = model.as_dict()
    for key in ("chain", "last_at", "horizon_errors"):
        data.pop(key)
    old = RoomModel.from_dict(data)
    assert old.horizon_errors == [] and old.horizon_error is None
    assert len(model.horizon_errors) >= HORIZON_MIN


@pytest.mark.asyncio
async def test_heat_load_marks_rooms_whose_model_is_not_proven(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, [])
    # Ready, but only 30 hours: not trusted yet. Weak radiators on paper.
    coordinator.room_model = _trained_model(heat_output=0.35, loss=0.02, hours=30)
    assert coordinator.room_model.ready and not coordinator.room_model.trusted
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    load = house.heat_load(-12)
    [room] = load["rooms"]
    assert room["verdict"] == "noch ungenau"
    assert "(noch ungenau)" in load["text"]
    # No verdict from a model that has not proven itself.
    assert "Zu schwach" not in load["text"]


@pytest.mark.asyncio
async def test_heat_load_does_not_report_absurd_outdoor_limits(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    # A room that barely loses heat (warmed by its neighbours).
    coordinator.room_model = _trained_model(heat_output=1.6, loss=0.003, hours=96)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    load = coordinator.heat_load(-10)
    assert load is not None
    assert load["holds_comfort_down_to"] == -30.0


# --- 4: homecoming -------------------------------------------------------------


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=dt_util.get_default_time_zone())


def test_homecoming_pools_workdays_until_a_day_has_its_own_habit():
    learner = Homecoming()
    # Mon 19., Tue 20., Wed 21.10. around 17:00; Sat 24.10. once.
    for day, minute in ((19, 0), (20, 15), (21, 5)):
        learner.record(_local(day, 17, minute))
    learner.record(_local(24, 12))
    today = date(2026, 10, 26)
    # Every workday gets the pooled habit, the weekend has too little.
    assert learner.usual(3, today) == 17 * 60 + 5
    assert learner.usual(4, today) == 17 * 60 + 5
    assert learner.usual(5, today) is None
    # Three Thursdays of their own win over the pool.
    for day in (1, 8, 15):
        learner.record(datetime(2026, 10, day, 19, 30, tzinfo=dt_util.get_default_time_zone()))
    assert learner.usual(3, today) == 19 * 60 + 30
    assert learner.usual(0, today) is not None


# --- 6: comfort by motion -------------------------------------------------------

MOTION = "binary_sensor.bath_motion"


async def _bath(hass, freezer):
    # The last motion was last night.
    freezer.move_to("2026-10-28 23:00:00+00:00")
    hass.states.async_set(MOTION, "off")
    freezer.move_to("2026-10-29 05:00:00+00:00")
    _set_up_test_entities(hass, room_temperature="21.0")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["occupancy_entity"] = MOTION
    coordinator.config["away_offset"] = 2
    return coordinator


def _schedule(hass, on: bool, minutes: int) -> None:
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on" if on else "off",
        {"next_event": (dt_util.now() + timedelta(minutes=minutes)).isoformat()},
    )


async def _refresh(hass, coordinator) -> dict:
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    return coordinator.data


@pytest.mark.asyncio
async def test_comfort_stays_while_the_bath_is_still_in_use(
    hass, enable_custom_integrations, freezer
):
    coordinator = await _bath(hass, freezer)
    _schedule(hass, True, 30)
    await _refresh(hass, coordinator)
    freezer.tick(timedelta(minutes=10))
    hass.states.async_set(MOTION, "on")
    await _refresh(hass, coordinator)
    freezer.tick(timedelta(minutes=20))
    hass.states.async_set(MOTION, "off")
    # The block ends while somebody is still in the bath.
    _schedule(hass, False, 600)
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 21.0
    assert data["presence_status"] == "Raum wird noch genutzt – Komfort gehalten"
    # More motion keeps it warm ...
    freezer.tick(timedelta(minutes=8))
    hass.states.async_set(MOTION, "on")
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 21.0
    hass.states.async_set(MOTION, "off")
    # ... until ten minutes pass without any.
    freezer.tick(timedelta(minutes=11))
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 18.0


@pytest.mark.asyncio
async def test_comfort_extension_ends_after_an_hour_at_most(
    hass, enable_custom_integrations, freezer
):
    coordinator = await _bath(hass, freezer)
    _schedule(hass, True, 30)
    await _refresh(hass, coordinator)
    freezer.tick(timedelta(minutes=30))
    hass.states.async_set(MOTION, "on")
    _schedule(hass, False, 600)
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 21.0
    freezer.tick(timedelta(minutes=61))
    hass.states.async_set(MOTION, "on")
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 18.0


@pytest.mark.asyncio
async def test_unused_bath_is_reduced_until_the_first_motion(
    hass, enable_custom_integrations, freezer
):
    coordinator = await _bath(hass, freezer)
    _schedule(hass, True, 90)
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 21.0
    # Nobody comes in the first half hour.
    freezer.tick(timedelta(minutes=31))
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 19.0
    assert data["presence_status"].startswith("Seit Komfortbeginn keine Bewegung")
    # A short pulse brings comfort back for the rest of the block.
    hass.states.async_set(MOTION, "on")
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 21.0
    freezer.tick(timedelta(minutes=1))
    hass.states.async_set(MOTION, "off")
    freezer.tick(timedelta(minutes=40))
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 21.0


@pytest.mark.asyncio
async def test_without_motion_sensor_nothing_changes(
    hass, enable_custom_integrations, freezer
):
    coordinator = await _bath(hass, freezer)
    coordinator.config["occupancy_entity"] = None
    _schedule(hass, True, 90)
    await _refresh(hass, coordinator)
    freezer.tick(timedelta(minutes=31))
    data = await _refresh(hass, coordinator)
    assert data["target_temperature"] == 21.0
