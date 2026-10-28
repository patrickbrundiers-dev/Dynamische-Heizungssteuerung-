"""0.15.0: ideas from velair (punctuality by weather, homecoming, preheat
breakdown, house timeline, airing, comfort in frost, temperature levels)."""

from datetime import date, datetime, timedelta

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events
from test_home_assistant_sandbox import _set_up_test_entities, _setup_integration
from test_runde7_094 import _setup_house

from custom_components.dynamic_heating.assist import answer_when_warm
from custom_components.dynamic_heating.logic import (
    absolute_humidity,
    airing_advice,
    decide_heating_target,
    dew_point,
    preheat_parts_text,
)
from custom_components.dynamic_heating.plan import PlanPoint, plan_segments
from custom_components.dynamic_heating.routine import (
    PUNCTUAL_GIVE_UP_MINUTES,
    Homecoming,
    MorningSample,
    Punctuality,
    homecomings_from_history,
)

# --- 1: punctuality by weather -----------------------------------------------


def _sample(day: int, outdoor: float, needed: float, late: int = 0, partial=False):
    return MorningSample(
        date(2026, 10, day).isoformat(), outdoor, 2.0, needed, partial, late
    )


def test_correction_waits_for_enough_mornings():
    punctuality = Punctuality(bias_minutes=12.0)
    punctuality.history = [_sample(day, 0.0, 30.0) for day in range(1, 5)]
    assert punctuality.bias_for(0.0, 2.0, date(2026, 10, 10)) == 12.0
    assert not punctuality.similar_ready()


def test_frosty_mornings_get_their_own_correction():
    punctuality = Punctuality(bias_minutes=15.0)
    punctuality.history = [_sample(day, -5.0, 30.0) for day in range(1, 6)] + [
        _sample(day, 10.0, 0.0) for day in range(6, 11)
    ]
    today = date(2026, 10, 12)
    assert punctuality.similar_ready()
    assert punctuality.bias_for(-4.0, 2.0, today) == 30.0
    assert punctuality.bias_for(11.0, 2.0, today) == 0.0


def test_often_late_plans_carefully():
    punctuality = Punctuality()
    needed = [0.0, 0.0, 0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 60.0]
    punctuality.history = [
        _sample(day + 1, 5.0, value, late=0) for day, value in enumerate(needed)
    ]
    relaxed = punctuality.bias_for(5.0, 2.0, date(2026, 10, 11))
    punctuality.history = [
        _sample(day + 1, 5.0, value, late=30 if day > 6 else 0)
        for day, value in enumerate(needed)
    ]
    careful = punctuality.bias_for(5.0, 2.0, date(2026, 10, 11))
    assert careful > relaxed


def test_a_morning_never_warm_in_time_is_a_lower_bound():
    punctuality = Punctuality()
    punctuality.history = [_sample(day, 5.0, 0.0) for day in range(1, 6)]
    punctuality.history.append(
        _sample(6, 5.0, 50.0, late=PUNCTUAL_GIVE_UP_MINUTES, partial=True)
    )
    assert punctuality.bias_for(5.0, 2.0, date(2026, 10, 8)) == 50.0
    # Long ago it no longer counts.
    assert punctuality.bias_for(5.0, 2.0, date(2026, 12, 20)) == 0.0


def test_morning_keeps_its_weather_and_survives_a_restart():
    punctuality = Punctuality(bias_minutes=10.0)
    start = datetime(2026, 10, 20, 5, 0, tzinfo=dt_util.UTC)
    for minute in range(0, 60, 10):
        punctuality.observe(
            start - timedelta(minutes=60 - minute),
            room=19.0 + minute / 60,
            mode="preheat",
            next_event=start,
            target=21.0,
            outdoor=-2.0,
            bias=10.0,
        )
    late = punctuality.observe(
        start + timedelta(minutes=25), room=21.0, mode="comfort",
        next_event=None, target=21.0,
    )
    assert late == 25
    sample = punctuality.history[-1]
    assert sample.outdoor == -2.0
    assert sample.gap == 2.0
    assert sample.needed == 35.0
    restored = Punctuality.from_dict(punctuality.as_dict())
    assert restored.history == punctuality.history
    assert restored.results == punctuality.results


# --- 2: homecoming -------------------------------------------------------------


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=dt_util.get_default_time_zone())


def test_homecoming_is_learned_per_weekday():
    learner = Homecoming(seen=True)
    # Mondays 5., 12., 19.10.: away from 7:30, home 17:10, 17:25, 16:55.
    for day, (hour, minute) in zip((5, 12, 19), ((17, 10), (17, 25), (16, 55)), strict=True):
        learner.observe(_local(day, 7, 30), False)
        assert learner.observe(_local(day, hour, minute), True)
    assert learner.usual(0, date(2026, 10, 20)) == 17 * 60 + 10
    assert learner.usual(1, date(2026, 10, 20)) is None
    assert learner.week(date(2026, 10, 20))["Montag"] == "17:10"
    # A short trip to the bakery is no homecoming.
    learner.observe(_local(26, 9, 0), False)
    assert not learner.observe(_local(26, 9, 40), True)
    restored = Homecoming.from_dict(learner.as_dict())
    assert restored.usual(0, date(2026, 10, 20)) == 17 * 60 + 10


def test_scattered_homecomings_are_no_habit():
    learner = Homecoming()
    for day, hour in ((5, 9), (12, 14), (19, 20)):
        learner.record(_local(day, hour))
    assert learner.usual(0, date(2026, 10, 20)) is None


def test_homecomings_from_the_people_history():
    changes = []
    for day in (6, 13, 20):
        changes += [
            (_local(day, 7, 0), "person.a", False),
            (_local(day, 8, 0), "person.b", False),
            (_local(day, 16, 40), "person.b", True),
            (_local(day, 18, 0), "person.a", True),
        ]
    learner = homecomings_from_history(changes, 2)
    # The first of the two to come home counts.
    assert learner.usual(1, date(2026, 10, 21)) == 16 * 60 + 40


async def _away_room(hass, freezer, *, homecoming: bool):
    await hass.config.async_set_time_zone("Europe/Berlin")
    # Tuesday 27.10.2026, 12:00 local; comfort runs all afternoon.
    freezer.move_to("2026-10-27T11:00:00+00:00")
    _set_up_test_entities(hass, room_temperature="17.0")
    hass.states.async_set("person.patrick", "not_home")
    hass.states.async_set(
        "schedule.living_room_comfort",
        "on",
        {"next_event": _local(27, 22, 0)},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = ["person.patrick"]
    coordinator.config["presence_entity"] = None
    coordinator.config["homecoming_preheat"] = homecoming
    coordinator.enabled = True
    for day in (6, 13, 20):
        coordinator.homecoming.record(_local(day, 17, 0))
    return coordinator


@pytest.mark.asyncio
async def test_room_is_warm_for_the_usual_homecoming(
    hass, enable_custom_integrations, freezer
):
    coordinator = await _away_room(hass, freezer, homecoming=True)
    await coordinator.async_refresh()
    assert coordinator.data["mode"] in ("away", "away_reduced")
    assert coordinator.data["homecoming_today"] == "17:00"
    # 16:00: an hour before the usual homecoming the room heats up.
    freezer.move_to("2026-10-27T15:00:00+00:00")
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "homecoming"
    assert coordinator.data["target_temperature"] == 21.0
    assert "üblichen Heimkehr (17:00 Uhr)" in coordinator.data["status"]
    # Nobody came: half an hour after the usual time it is away again.
    freezer.move_to("2026-10-27T16:31:00+00:00")
    await coordinator.async_refresh()
    assert coordinator.data["mode"] in ("away", "away_reduced")


@pytest.mark.asyncio
async def test_homecoming_preheat_is_off_by_default(
    hass, enable_custom_integrations, freezer
):
    coordinator = await _away_room(hass, freezer, homecoming=False)
    freezer.move_to("2026-10-27T15:00:00+00:00")
    await coordinator.async_refresh()
    assert coordinator.data["mode"] in ("away", "away_reduced")


@pytest.mark.asyncio
async def test_house_tells_the_usual_homecoming(
    hass, enable_custom_integrations, freezer
):
    coordinator = await _away_room(hass, freezer, homecoming=False)
    house = await _setup_house(hass, [])
    info = house.homecoming()
    assert info["today"] == "17:00"
    assert info["week"]["Dienstag"] == "17:00"
    assert info["room"] == coordinator.room_name


# --- 3: preheat breakdown and trigger -------------------------------------------


def test_preheat_parts_add_up():
    now = datetime(2026, 10, 27, 4, 0, tzinfo=dt_util.UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(minutes=60),
        room_temperature=19.0,
        outdoor_temperature=2.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=2.0,
        max_preheat_minutes=120,
        overshoot=0.3,
        lead_bias_minutes=12,
    )
    parts = decision.preheat_parts
    assert parts["source"] == "rate"
    assert parts["overshoot_minutes"] < 0
    assert parts["punctuality_minutes"] == 12
    assert (
        parts["base_minutes"] + parts["overshoot_minutes"] + parts["punctuality_minutes"]
        + parts["sun_minutes"]
        == parts["final_minutes"]
        == decision.preheat_minutes
    )
    text = preheat_parts_text(parts)
    assert text.startswith("Aufheizrate ")
    assert "Pünktlichkeit +12" in text
    assert "außen 2,0 °C" in text


def test_no_parts_without_a_comfort_start():
    now = datetime(2026, 10, 27, 4, 0, tzinfo=dt_util.UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=True,
        next_event=None,
        room_temperature=19.0,
        outdoor_temperature=2.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=2.0,
        max_preheat_minutes=120,
    )
    assert decision.preheat_parts is None


@pytest.mark.asyncio
async def test_preheat_sensor_and_trigger(hass, enable_custom_integrations, freezer):
    freezer.move_to("2026-10-27T04:00:00+00:00")
    _set_up_test_entities(hass, room_temperature="19.0")
    hass.states.async_set(
        "schedule.living_room_comfort",
        "off",
        {"next_event": (dt_util.now() + timedelta(hours=4)).isoformat()},
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.enabled = True
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "eco"
    events = async_capture_events(hass, "dynamic_heating_event")
    hass.states.async_set(
        "schedule.living_room_comfort",
        "off",
        {"next_event": (dt_util.now() + timedelta(minutes=30)).isoformat()},
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data["mode"] == "preheat"
    assert "preheat_started" in [event.data["type"] for event in events]
    state = next(
        hass.states.get(entity_id)
        for entity_id in hass.states.async_entity_ids("sensor")
        if entity_id.endswith("_geschatzte_vorheizzeit")
    )
    assert state.attributes["breakdown"].startswith(("Aufheizrate", "Raummodell"))
    assert "Wann" not in answer_when_warm(coordinator)


# --- 4: house timeline ----------------------------------------------------------


def test_plan_segments_join_the_steps():
    start = datetime(2026, 10, 27, 4, 0, tzinfo=dt_util.UTC)
    points = []
    for step in range(12):
        at = start + timedelta(minutes=15 * step)
        preheat = 4 <= step < 6
        target = 21.0 if step >= 4 else 18.0
        points.append(PlanPoint(at, target, 19.0, preheat, preheat, step < 2))
    segments = plan_segments(points, 18.0)
    assert [(item["kind"], item["supply_off"]) for item in segments] == [
        ("eco", True), ("eco", False), ("preheat", False), ("comfort", False),
    ]
    assert segments[0]["end"] == segments[1]["start"]
    assert segments[-1]["end"] == (start + timedelta(minutes=180)).isoformat()


def test_card_registers_the_timeline():
    from pathlib import Path

    source = (
        Path(__file__).parents[1]
        / "custom_components/dynamic_heating/frontend/dynamic-heating-card.js"
    ).read_text()
    assert 'customElements.define("dynamic-heating-timeline-card"' in source
    assert "attributes?.segments" in source
    # The schedule editor offers the levels.
    assert 'data-action="level"' in source


# --- 5: airing --------------------------------------------------------------------


def test_humidity_formulas():
    assert dew_point(20.0, 50.0) == pytest.approx(9.3, abs=0.1)
    assert absolute_humidity(20.0, 50.0) == pytest.approx(8.6, abs=0.1)


def test_airing_advice():
    common = {"humid_percent": 60.0, "min_difference": 1.0}
    assert airing_advice(21.0, 50.0, 3.0, 90.0, **common)["state"] == "not_needed"
    advice = airing_advice(22.0, 70.0, 3.0, 90.0, **common)
    assert advice["state"] == "helps"
    assert advice["minutes"] == 5
    assert advice["humidity_after_airing"] < 40
    assert airing_advice(22.0, 65.0, 21.0, 75.0, **common)["state"] == "useless"
    assert airing_advice(22.0, 70.0, None, None, **common)["state"] == "unknown"
    assert airing_advice(None, 70.0, 3.0, 90.0, **common) is None


@pytest.mark.asyncio
async def test_room_tells_whether_airing_helps(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="22.0")
    hass.states.async_set("sensor.bad_humidity", "72")
    hass.states.async_set("sensor.outdoor_humidity", "85")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["humidity_entity"] = "sensor.bad_humidity"
    coordinator.config["outdoor_humidity_entity"] = "sensor.outdoor_humidity"
    await coordinator.async_refresh()
    assert coordinator.data["airing"] == "Lüften hilft – 5 Minuten stoßlüften"
    assert coordinator.data["airing_details"]["dew_point"] > 16


# --- 6: comfort in frost -------------------------------------------------------------


@pytest.mark.asyncio
async def test_comfort_rises_a_little_in_frost(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    hass.states.async_set("schedule.living_room_comfort", "on", {})
    hass.states.async_set("sensor.outdoor_temperature", "-10.0")
    _, coordinator = await _setup_integration(hass)
    await coordinator.async_refresh()
    assert coordinator.data["comfort_temperature"] == 21.0
    coordinator.config["cold_comfort_boost"] = 0.6
    await coordinator.async_refresh()
    assert coordinator.data["comfort_temperature"] == pytest.approx(21.6)
    assert "+0,6 °C wegen Kälte" in coordinator.data["status"]
    hass.states.async_set("sensor.outdoor_temperature", "-2.5")
    await coordinator.async_refresh()
    assert coordinator.data["cold_comfort_raise"] == 0.3
    hass.states.async_set("sensor.outdoor_temperature", "8.0")
    await coordinator.async_refresh()
    assert coordinator.data["cold_comfort_raise"] == 0.0


# --- 7: temperature levels ----------------------------------------------------------


@pytest.mark.asyncio
async def test_schedule_block_follows_a_house_level(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    hass.states.async_set("schedule.living_room_comfort", "on", {"stufe": "Abend"})
    _, coordinator = await _setup_integration(hass)
    await coordinator.async_refresh()
    # Without a house the default of the level applies.
    assert coordinator.data["comfort_temperature"] == 21.5
    house = await _setup_house(hass, [])
    level = next(
        entity_id
        for entity_id in hass.states.async_entity_ids("number")
        if entity_id.endswith("_stufe_abend")
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": level, "value": 22.5}, blocking=True
    )
    await hass.async_block_till_done()
    assert house.level("abend") == 22.5
    await coordinator.async_refresh()
    assert coordinator.data["comfort_temperature"] == 22.5
    # A temperature of its own wins over the level.
    hass.states.async_set(
        "schedule.living_room_comfort", "on", {"stufe": "abend", "temperature": 20.5}
    )
    await coordinator.async_refresh()
    assert coordinator.data["comfort_temperature"] == 20.5
    assert {"key": "abend", "name": "Stufe Abend", "temperature": 22.5} in (
        coordinator.level_options()
    )


def test_plan_and_tuya_week_read_levels():
    from custom_components.dynamic_heating.plan import blocks_from_schedule
    from custom_components.dynamic_heating.routine import tuya_day_schedule

    now = datetime(2026, 10, 26, 0, 0, tzinfo=dt_util.get_default_time_zone())
    weekly = {
        "monday": [{"from": "18:00:00", "to": "22:00:00", "data": {"stufe": "abend"}}]
    }

    def level_of(data):
        return 22.0 if data.get("stufe") == "abend" else None

    blocks = blocks_from_schedule(weekly, now, lambda _value: None, level_of=level_of)
    assert blocks[0].temperature == 22.0
    text = tuya_day_schedule(
        weekly["monday"], 21.0, 18.0, 0.5, lambda _value: None, level_of
    )
    assert "18:00/22.0" in text
