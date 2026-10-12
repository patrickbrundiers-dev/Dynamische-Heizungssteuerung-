"""Tests for the smart control of 0.9.0: room model, setback limit, presence,
reachable temperature, early stop and the sun."""

import math
import random
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.logic import decide_heating_target
from custom_components.dynamic_heating.model import (
    RoomModel,
    SampleCollector,
    UsageProfile,
    seed_room_model,
)

_UTCNOW = "custom_components.dynamic_heating.coordinator.dt_util.utcnow"


def _trained_model(heat_output=0.35, loss=0.02, solar=0.0, hours=96, seed=1) -> RoomModel:
    """A model fed with a simulated room that follows the room equation."""
    rng = random.Random(seed)
    model = RoomModel()
    room = 19.0
    for hour in range(hours):
        outdoor = 10 + 4 * math.sin(hour / 24 * 2 * math.pi)
        sun = max(0.0, math.sin((hour % 24 - 6) / 12 * math.pi)) * 0.3 * rng.random()
        demand = rng.choice([0.0, 0.3, 1.0]) if 6 <= hour % 24 < 22 else 0.0
        rate = heat_output * demand - loss * (room - outdoor) + solar * sun
        model.add(rate + rng.gauss(0, 0.05), demand, room + rate / 2, outdoor, sun, 0.0)
        room += rate
    return model


def test_room_model_learns_heat_output_and_loss():
    model = _trained_model(solar=1.0, hours=168)
    heat_output, loss, solar, wind = model.parameters()
    assert model.ready
    assert heat_output == pytest.approx(0.35, abs=0.08)
    assert loss == pytest.approx(0.02, abs=0.005)
    assert solar == pytest.approx(1.0, abs=0.35)
    assert wind == pytest.approx(0.0, abs=0.002)


def test_room_model_is_not_ready_without_heating_and_idle_hours():
    model = RoomModel()
    for _ in range(30):
        model.add(-0.2, 0.0, 20.0, 10.0)
    assert not model.ready
    assert model.idle_samples == 30


def test_room_model_rejects_implausible_samples_and_survives_storage():
    model = _trained_model()
    assert model.add(9.0, 1.0, 20.0, 10.0) is False
    assert model.add(0.1, 1.5, 20.0, 10.0) is False
    assert model.add(float("nan"), 1.0, 20.0, 10.0) is False
    restored = RoomModel.from_dict(model.as_dict())
    assert restored.parameters() == pytest.approx(model.parameters())
    assert restored.ready
    assert RoomModel.from_dict({"matrix": "x"}).samples == 0
    assert RoomModel.from_dict(None).samples == 0


def test_model_predicts_reach_heating_time_and_setback_floor():
    view = _trained_model().view(9.0)
    settle = view.equilibrium(1.0)
    # Weak radiators: 0.35 °C/h at full heat against 0.02 per hour and Kelvin.
    assert settle == pytest.approx(9 + 0.35 / 0.02, abs=4)
    hours = view.hours_to_reach(18.0, 20.0)
    assert hours is not None and hours > 4
    assert view.hours_to_reach(20.0, 19.0) == 0.0
    assert view.hours_to_reach(18.0, settle + 1) is None
    floor = view.lowest_start(20.0, 2.0)
    assert 19.0 < floor < 20.0
    # From the floor, two hours of full heating reach the target again.
    assert view.temperature_after(floor, 2.0, 1.0) == pytest.approx(20.0, abs=0.01)
    assert view.lowest_start(settle + 1, 2.0) == settle + 1


def test_sample_collector_averages_one_hour():
    collector = SampleCollector()
    assert collector.observe(0, 20.0, 1.0, 10.0, 0.0, 0.0) is None
    for at in (900, 1800, 2700):
        assert collector.observe(at, 20.2, 0.0, 12.0, 0.2, 2.0) is None
    sample = collector.observe(3600, 20.3, 0.0, 12.0, 0.2, 2.0)
    assert sample is not None
    rate, demand, room, outdoor, solar, wind = sample
    assert rate == pytest.approx(0.3)
    assert demand == pytest.approx(0.25)
    assert room == pytest.approx(20.15)
    assert outdoor == pytest.approx(11.5)
    assert solar == pytest.approx(0.15)
    assert wind == pytest.approx(1.5)
    # A gap in the readings starts over.
    assert collector.observe(3600 + 2000, 20.3, 0.0, 12.0, 0.0, 0.0) is None
    assert collector.started_at == 3600 + 2000


def test_usage_profile_learns_hours_the_room_is_used():
    profile = UsageProfile()
    for minute in range(0, 60, 5):
        profile.observe(0, 18, minute < 45, 300)
    assert profile.observe(0, 19, False, 300) is True
    assert profile.usage(0, 18) == pytest.approx(0.75)
    assert profile.usually_used(0, 18)
    assert not profile.usually_used(0, 19)
    restored = UsageProfile.from_list(profile.as_list())
    assert restored.usage(0, 18) == pytest.approx(0.75)
    assert UsageProfile.from_list("x").usage(0, 18) is None


def test_seed_room_model_from_recorded_history():
    start = 0.0
    room = 19.0
    room_states, outdoor_states, demand_states, window_states = [], [], [], []
    for step in range(0, 72 * 12):
        at = start + step * 300
        hour = step // 12
        demand = 100.0 if 6 <= hour % 24 < 20 else 0.0
        rate = 0.35 * demand / 100 - 0.02 * (room - 10.0)
        room += rate / 12
        room_states.append((at, f"{room:.2f}"))
        demand_states.append((at, str(demand)))
        if step == 0:
            outdoor_states.append((at, "10.0"))
    window_states.append((start, "off"))
    model = RoomModel()
    added = seed_room_model(
        model,
        {
            "sensor.room": room_states,
            "sensor.outdoor": outdoor_states,
            "sensor.demand": demand_states,
            "binary_sensor.window": window_states,
        },
        room_id="sensor.room",
        outdoor_id="sensor.outdoor",
        demand_id="sensor.demand",
        window_ids=["binary_sensor.window"],
        solar_id=None,
        wind_id=None,
        units={},
        start=start,
        end=start + 72 * 3600,
    )
    assert added >= 60
    assert model.ready
    heat_output, loss, _solar, _wind = model.parameters()
    assert heat_output == pytest.approx(0.35, abs=0.1)
    assert loss == pytest.approx(0.02, abs=0.008)


def _decide(**overrides):
    values = {
        "now": datetime(2026, 10, 12, 4, 0),
        "schedule_active": False,
        "next_event": datetime(2026, 10, 12, 6, 0),
        "room_temperature": 18.0,
        "outdoor_temperature": 9.0,
        "comfort_temperature": 20.0,
        "eco_temperature": 18.0,
        "heating_rate_c_per_hour": 1.0,
        "max_preheat_minutes": 120,
    }
    values.update(overrides)
    return decide_heating_target(**values)


def test_model_times_preheating_instead_of_the_fixed_rate():
    view = _trained_model().view(9.0)
    # The old rate of 1 °C/h would wait until 2 h before; the model knows
    # the room needs longer and starts at the maximum preheat time.
    now = datetime(2026, 10, 12, 4, 30)
    decision = _decide(now=now, room_temperature=19.0, room_model=view)
    assert decision.mode == "preheat"
    assert decision.preheat_minutes == 120
    assert _decide(now=now, room_temperature=19.0).mode == "eco"


def test_setback_floor_limits_the_setback():
    decision = _decide(now=datetime(2026, 10, 12, 0, 0), setback_floor=19.4)
    assert decision.mode == "eco"
    assert decision.target_temperature == 19.4
    assert "nur bis 19,4 °C" in decision.status
    # Never above comfort, and no effect below eco.
    assert _decide(
        now=datetime(2026, 10, 12, 0, 0), setback_floor=25.0
    ).target_temperature == 20.0
    assert _decide(
        now=datetime(2026, 10, 12, 0, 0), setback_floor=17.0
    ).status == "Energiesparbetrieb"


def test_empty_room_is_preheated_while_somebody_is_home():
    now = datetime(2026, 10, 12, 5, 30)
    assert _decide(now=now, present=False).mode == "away"
    decision = _decide(now=now, present=False, household_present=True)
    assert decision.mode == "preheat"
    # During comfort time an empty room still drops as before.
    assert (
        _decide(
            now=now, present=False, household_present=True, schedule_active=True
        ).mode
        == "away"
    )


def _comfort_until(hass, minutes: int) -> None:
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": (dt_util.now() + timedelta(minutes=minutes)).isoformat()},
    )


@pytest.mark.asyncio
async def test_status_and_watchdog_know_what_the_room_can_reach(
    hass, enable_custom_integrations
):
    """A comfort target out of reach is named, and is not a heating problem."""
    _set_up_test_entities(hass, room_temperature="21.8")
    hass.states.async_set("sensor.outdoor_temperature", "9.0")
    _comfort_until(hass, 600)
    _, coordinator = await _setup_integration(hass)
    coordinator.room_model = _trained_model(heat_output=0.25, loss=0.02)
    coordinator.config["comfort_temperature"] = 25.0
    start = dt_util.utcnow()

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        for minutes in (0, 130, 260):
            at = start + timedelta(minutes=minutes)
            hass.states.async_set(
                "sensor.living_room_temperature",
                "21.8",
                force_update=True,
                timestamp=at.timestamp(),
            )
            with patch(_UTCNOW, return_value=at):
                await coordinator.async_refresh()

    data = coordinator.data
    reachable = data["reachable_temperature"]
    assert reachable is not None and reachable < 25.0
    assert "heute erreichbar ca." in data["status"]
    assert data["model_status"] == "Aktiv"
    assert data["heat_output"] is not None
    # The room sits close to what it can reach: no heating problem, even
    # though it stays 3 °C below the comfort target for hours.
    assert reachable - 0.3 - 21.8 < 1.0
    assert data["heating_problem"] is False


@pytest.mark.asyncio
async def test_heating_ends_early_before_comfort_ends(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="21.0")
    _comfort_until(hass, 20)
    _, coordinator = await _setup_integration(hass)
    coordinator.room_model = _trained_model()

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()

    assert coordinator.data["mode"] == "early_stop"
    assert coordinator.data["target_temperature"] == 18.0
    assert "Heizung schon aus" in coordinator.data["status"]

    # Without the option it stays in comfort.
    coordinator.config["early_stop"] = 0
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"


@pytest.mark.asyncio
async def test_no_early_stop_while_the_room_is_still_cold(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="19.0")
    _comfort_until(hass, 20)
    _, coordinator = await _setup_integration(hass)
    coordinator.room_model = _trained_model()
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"


@pytest.mark.asyncio
async def test_empty_room_keeps_comfort_at_block_start(
    hass, enable_custom_integrations
):
    """Somebody is home, nobody in the room yet: comfort holds for a while."""
    _set_up_test_entities(hass, room_temperature="19.0")
    hass.states.async_set("person.patrick", "home")
    hass.states.async_set("binary_sensor.someone_home", "off")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = ["person.patrick"]
    coordinator.config["away_offset"] = 3.0
    start = dt_util.utcnow()

    with _capture_climate_calls(hass):
        coordinator.enabled = True
        with patch(_UTCNOW, return_value=start):
            await coordinator.async_refresh()
        _comfort_until(hass, 600)
        with patch(_UTCNOW, return_value=start + timedelta(minutes=1)):
            await coordinator.async_refresh()
        assert coordinator.data["mode"] == "comfort"
        assert "Komfortbeginn" in coordinator.data["presence_status"]
        with patch(_UTCNOW, return_value=start + timedelta(minutes=40)):
            await coordinator.async_refresh()
        assert coordinator.data["mode"] == "away_reduced"


@pytest.mark.asyncio
async def test_learned_room_use_keeps_comfort(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="19.0")
    hass.states.async_set("person.patrick", "home")
    hass.states.async_set("binary_sensor.someone_home", "off")
    _comfort_until(hass, 600)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = ["person.patrick"]
    coordinator.config["away_offset"] = 3.0
    local = dt_util.now()
    coordinator.usage.slots[local.weekday()][local.hour] = 0.8
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"
    assert "meist genutzt" in coordinator.data["presence_status"]


@pytest.mark.asyncio
async def test_sun_pauses_heating_when_it_keeps_the_room_warm(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="20.9")
    hass.states.async_set("sensor.outdoor_temperature", "12.0")
    hass.states.async_set(
        "sensor.solar_radiation", "600", {"unit_of_measurement": "W/m²"}
    )
    _comfort_until(hass, 600)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["solar_radiation_entity"] = "sensor.solar_radiation"
    coordinator.config["early_stop"] = 0
    coordinator.room_model = _trained_model(solar=1.0, hours=168)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "solar"
    assert coordinator.data["solar_pause"] is True

    hass.states.async_set(
        "sensor.solar_radiation", "0", {"unit_of_measurement": "W/m²"}
    )
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"


@pytest.mark.asyncio
async def test_room_model_learns_from_control_cycles(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="19.0")
    _comfort_until(hass, 600)
    _, coordinator = await _setup_integration(hass)
    start = dt_util.utcnow()
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        for minutes in range(0, 125, 5):
            at = start + timedelta(minutes=minutes)
            hass.states.async_set(
                "sensor.living_room_temperature",
                f"{19.0 + minutes / 600:.2f}",
                force_update=True,
                timestamp=at.timestamp(),
            )
            with patch(_UTCNOW, return_value=at):
                await coordinator.async_refresh()
    assert coordinator.room_model.samples == 2
    assert coordinator.room_model.heating_samples == 2
    assert coordinator.data["model_status"].startswith("Lernt noch")


def test_reachable_stays_within_a_few_hours_of_heating():
    view = _trained_model().view(18.0)
    # Settling far above anything real, but six hours ahead stays modest.
    assert view.equilibrium(1.0) > 30
    assert view.reachable(20.0) < 22.5
    assert view.reachable(20.0) >= 20.0


@pytest.mark.asyncio
async def test_a_young_model_only_times_preheating(hass, enable_custom_integrations):
    """Ready but not proven: no setback limit, no reachability, no sun pause."""
    _set_up_test_entities(hass, room_temperature="19.0")
    _, coordinator = await _setup_integration(hass)
    coordinator.room_model = _trained_model(hours=30)
    assert coordinator.room_model.ready
    assert not coordinator.room_model.trusted
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    data = coordinator.data
    assert data["setback_floor"] is None
    assert data["reachable_temperature"] is None
    assert data["model_status"].startswith("Aktiv fürs Vorheizen")
