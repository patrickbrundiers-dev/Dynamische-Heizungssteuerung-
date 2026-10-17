"""0.13.0 (Runde 11): heat meter, Spar-Rechner and questions via Assist."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.assist import (
    SENTENCES,
    answer_house_energy,
    answer_room_energy,
    answer_why_cold,
    find_room,
)
from custom_components.dynamic_heating.const import DOMAIN
from custom_components.dynamic_heating.model import ModelView, RoomModel
from custom_components.dynamic_heating.plan import (
    Block,
    blocks_from_schedule,
    compare_plans,
    full_load_hours,
    savings_text,
    shifted_blocks,
    simulate,
    warm_delays,
)
from custom_components.dynamic_heating.radiator import SUPPLY_COLD
from custom_components.dynamic_heating.routine import HeatStats

BERLIN = ZoneInfo("Europe/Berlin")


def _view(outdoor=5.0):
    return ModelView(2.0, 0.08, 0.0, 0.0, outdoor)


def _week_blocks(now: datetime) -> list[Block]:
    weekly = {
        day: [{"from": "06:00:00", "to": "08:00:00"}, {"from": "17:00:00", "to": "22:00:00"}]
        for day in (
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        )
    }
    return blocks_from_schedule(weekly, now, lambda _value: None, hours=7 * 24)


def _plan(now, blocks, *, eco=18.0, comfort=21.0, room=19.0):
    return simulate(
        _view(),
        now=now,
        room=room,
        comfort=comfort,
        eco=eco,
        blocks=blocks,
        outdoor_at=lambda _at: 5.0,
        supply_off=lambda _at: False,
        max_preheat_minutes=120,
        hours=7 * 24,
    )


# 3 – heat meter


def test_heat_meter_counts_demand_times_radiator_power():
    stats = HeatStats()
    start = datetime(2026, 10, 17, 10, 0, tzinfo=BERLIN)
    stats.observe(start, 50, 5.0, power_kw=2.0)
    stats.observe(start + timedelta(minutes=10), 50, 5.0, power_kw=2.0)
    # 10 minutes at half of 2 kW
    assert stats.energy_kwh == pytest.approx(1 / 6, abs=0.001)
    # Cold radiators (boiler pause) give no heat although the valves are open.
    stats.observe(start + timedelta(minutes=20), 100, 5.0, power_kw=2.0, supplied=False)
    assert stats.energy_kwh == pytest.approx(1 / 3, abs=0.001)
    stats.observe(start + timedelta(minutes=30), 100, 5.0, power_kw=2.0)
    assert stats.energy_kwh == pytest.approx(1 / 3, abs=0.001)
    stats.observe(start + timedelta(minutes=40), 0, 5.0, power_kw=2.0)
    assert stats.energy_kwh == pytest.approx(2 / 3, abs=0.001)
    assert stats.energy_between(start.date(), start.date()) == pytest.approx(
        2 / 3, abs=0.01
    )


def test_heat_meter_keeps_old_days_without_kwh():
    restored = HeatStats.from_dict(
        {
            "heating_hours": 3.0,
            "degree_days": 1.0,
            "energy_kwh": 4.5,
            "days": {"2026-10-16": [3.0, 1.0], "2026-10-17": [1.0, 0.5, 2.0]},
        }
    )
    assert restored.energy_kwh == 4.5
    assert restored.days["2026-10-16"] == [3.0, 1.0, 0.0]
    assert restored.energy_between(date(2026, 10, 16), date(2026, 10, 17)) == 2.0
    assert HeatStats.from_dict(restored.as_dict()).days == restored.days


@pytest.mark.asyncio
async def test_room_and_house_show_the_heat_meter(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="19.0")
    _, coordinator = await _setup_integration(hass)
    # One thermostat without a configured output: 1000 W.
    assert coordinator.radiator_power_w == 1000
    coordinator.config["radiator_power"] = 1600
    assert coordinator.radiator_power_w == 1600
    now = dt_util.now()
    coordinator.heat_stats.observe(now - timedelta(minutes=10), 100, 5.0, power_kw=1.6)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    data = coordinator.data
    assert data["heat_energy_total"] == pytest.approx(0.27, abs=0.02)
    assert data["heat_energy_today"] + data["heat_energy_yesterday"] == pytest.approx(
        0.27, abs=0.02
    )
    assert data["radiator_power_w"] == 1600
    sensor = next(
        entity_id
        for entity_id in hass.states.async_entity_ids("sensor")
        if entity_id.endswith("_warmemenge")
    )
    await hass.async_block_till_done()
    state = hass.states.get(sensor)
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["state_class"] == "total_increasing"
    assert state.attributes["estimated"] is True


def test_house_meter_never_drops_while_a_room_restarts():
    from custom_components.dynamic_heating.sensor import HouseEnergySensor

    room = SimpleNamespace(
        room_name="Bad", entry_id="bad", data={"heat_energy_total": 5.0}
    )
    house = SimpleNamespace(rooms=lambda: [room])
    entry = SimpleNamespace(entry_id="house")
    sensor = HouseEnergySensor(house, entry, "heat_energy")
    assert sensor.native_value == 5.0
    room.data = None  # reloading
    assert sensor.native_value == 5.0
    room.data = {"heat_energy_total": 5.5}
    assert sensor.native_value == 5.5


# 4 – Spar-Rechner


def test_plan_steps_carry_the_heat_they_take():
    now = datetime(2026, 10, 17, 12, 0, tzinfo=BERLIN)
    points = _plan(now, _week_blocks(now))
    assert any(point.demand == 1.0 for point in points)
    # Holding a temperature takes part of the output, never more than all.
    holding = [point for point in points if 0 < point.demand < 1]
    assert holding
    assert all(0 <= point.demand <= 1 for point in points)
    assert full_load_hours(points) > 0


def test_lower_eco_saves_heat_and_later_start_too():
    now = datetime(2026, 10, 17, 12, 0, tzinfo=BERLIN)
    blocks = _week_blocks(now)
    assert len(blocks) == 14
    base = _plan(now, blocks)
    lower = _plan(now, blocks, eco=16.0)
    result = compare_plans(base, blocks, lower, blocks, now)
    assert result["saving"] > 0.02
    later = shifted_blocks(blocks, 30)
    assert later[0].start == blocks[0].start + timedelta(minutes=30)
    shifted = compare_plans(base, blocks, _plan(now, later), later, now)
    assert shifted["saving"] > 0
    # More comfort costs heat.
    warmer = compare_plans(base, blocks, _plan(now, blocks, comfort=22.0), blocks, now)
    assert warmer["saving"] < 0


def test_warm_delays_per_comfort_block():
    now = datetime(2026, 10, 17, 12, 0, tzinfo=BERLIN)
    blocks = [Block(now + timedelta(hours=1), now + timedelta(hours=3))]
    # A weak radiator: the room does not get warm in time.
    points = simulate(
        ModelView(0.4, 0.03, 0.0, 0.0, 5.0),
        now=now, room=17.0, comfort=21.0, eco=17.0, blocks=blocks,
        outdoor_at=lambda _at: 5.0, supply_off=lambda _at: False,
        max_preheat_minutes=30, hours=6,
    )
    assert warm_delays(points, blocks, now) == [None]
    points = simulate(
        _view(), now=now, room=20.0, comfort=21.0, eco=18.0, blocks=blocks,
        outdoor_at=lambda _at: 5.0, supply_off=lambda _at: False,
        max_preheat_minutes=120, hours=6,
    )
    # On time within one step of the plan.
    assert warm_delays(points, blocks, now)[0] <= 15


def _answer(**changes):
    answer = {
        "eco": 18.0,
        "comfort": 21.0,
        "new_eco": 18.0,
        "new_comfort": 21.0,
        "shift_minutes": 0,
        "days": 7,
        "saving": 0.06,
        "base_kwh": 50.0,
        "kwh": 47.0,
        "base_punctuality": {"blocks": 14, "missed": 0, "average_delay_minutes": 0, "late": 0},
        "punctuality": {"blocks": 14, "missed": 0, "average_delay_minutes": 0, "late": 0},
    }
    answer.update(changes)
    return answer


def test_savings_text_in_plain_german():
    assert savings_text(_answer(new_eco=17.0)) == (
        "Eco 17,0 statt 18,0 °C: ca. 6 % weniger Wärme (etwa 3,0 kWh weniger "
        "in 7 Tagen). Trotzdem pünktlich warm."
    )
    late = savings_text(
        _answer(
            shift_minutes=30,
            punctuality={
                "blocks": 14, "missed": 0, "average_delay_minutes": 25, "late": 7
            },
        )
    )
    assert late.startswith("Komfort 30 Minuten später: ca. 6 % weniger Wärme")
    assert "im Schnitt 25 Minuten nach Komfortbeginn (bisher 0)" in late
    missed = savings_text(
        _answer(
            new_comfort=23.0,
            saving=-0.1,
            kwh=55.0,
            punctuality={
                "blocks": 14, "missed": 3, "average_delay_minutes": 0, "late": 0
            },
        )
    )
    assert "ca. 10 % mehr Wärme (etwa 5,0 kWh mehr in 7 Tagen)" in missed
    assert "An 3 von 14 Komfortzeiten wird es nicht ganz warm (bisher 0)." in missed
    assert savings_text(_answer()).startswith("So wie jetzt eingestellt")


@pytest.mark.asyncio
async def test_savings_service_answers_without_changing_anything(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="19.0")
    entry, coordinator = await _setup_integration(hass)
    model = RoomModel()
    for hour in range(40):
        model.add(0.5 if hour % 2 else -0.3, 1.0 if hour % 2 else 0.0, 19.0, 5.0)
    coordinator.room_model = model
    now = dt_util.now()
    blocks = [
        Block(now + timedelta(hours=offset), now + timedelta(hours=offset + 3))
        for offset in (2, 14)
    ]
    select = next(
        entity_id
        for entity_id in hass.states.async_entity_ids("select")
        if entity_id.endswith("_betriebsart")
    )
    with (
        _capture_climate_calls(hass),
        patch.object(coordinator, "_schedule_blocks", return_value=blocks),
    ):
        await coordinator.async_refresh()
        response = await hass.services.async_call(
            DOMAIN,
            "estimate_savings",
            {"entity_id": select, "eco_temperature": 16.0},
            blocking=True,
            return_response=True,
        )
    assert response["days"] == 1
    assert response["new_eco"] == 16.0
    assert response["saving"] >= 0
    assert response["base_kwh"] > 0
    assert response["text"].startswith("Eco 16,0 statt 18,0 °C: ")
    assert coordinator.config["eco_temperature"] == 18.0
    assert entry.options.get("eco_temperature") is None


# 6 – Assist


def _room(name, **data):
    return SimpleNamespace(
        room_name=name,
        data=data,
        enabled=True,
        plan_points=[],
        plan_info={},
        heating_problem=False,
        heating_problem_detail=None,
        supply_profile=SimpleNamespace(next_on_hour=lambda _hour: 5),
    )


def test_rooms_are_found_by_what_is_said():
    rooms = [
        _room("Wohnzimmer"), _room("Großes Bad"), _room("Leonie"), _room("Schlafzimmer")
    ]
    assert find_room(rooms, "Bad").room_name == "Großes Bad"
    assert find_room(rooms, "im großen Bad so").room_name == "Großes Bad"
    assert find_room(rooms, "wohnzimmer").room_name == "Wohnzimmer"
    assert find_room(rooms, "Leonies Zimmer").room_name == "Leonie"
    assert find_room(rooms, "Schlafzimmer heute").room_name == "Schlafzimmer"
    assert find_room(rooms, "Garage") is None


def test_why_cold_names_the_reason():
    room = _room(
        "Großes Bad",
        room_temperature=19.5,
        target_temperature=22.0,
        radiator_supply=SUPPLY_COLD,
        supply_usually_off=True,
    )
    assert answer_why_cold(room) == (
        "Großes Bad: 19,5 °C, Ziel 22,0 °C. Die Zentralheizung liefert gerade "
        "keine Wärme, meist wieder ab 5:00 Uhr."
    )
    room.data = {"room_temperature": 19.5, "target_temperature": 22.0, "window_open": True}
    assert "Das Fenster ist offen" in answer_why_cold(room)
    room.data = {
        "room_temperature": 21.9,
        "target_temperature": 22.0,
        "status": "Komfort laut Zeitplan",
    }
    assert "Das Ziel ist erreicht. Gerade gilt: Komfort laut Zeitplan." in (
        answer_why_cold(room)
    )


def test_energy_answers():
    bad = _room("Bad", heat_energy_today=2.4, heat_energy_7_days=18.0)
    wohnzimmer = _room("Wohnzimmer", heat_energy_today=5.0, heat_energy_7_days=30.0)
    assert answer_room_energy(bad) == (
        "Bad hat heute etwa 2,4 kWh Wärme gebraucht, in den letzten 7 Tagen etwa "
        "18 kWh. Das ist geschätzt."
    )
    assert answer_house_energy([bad, wohnzimmer]) == (
        "Heute bisher etwa 7,4 kWh Wärme im ganzen Haus, am meisten Wohnzimmer mit "
        "5,0 kWh. Das ist geschätzt."
    )


@pytest.mark.asyncio
async def test_assist_answers_a_question(hass, enable_custom_integrations):
    from homeassistant.components import conversation
    from homeassistant.core import Context
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    _set_up_test_entities(hass, room_temperature="19.0")
    _, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    result = await conversation.async_converse(
        hass,
        f"Warum ist es im {coordinator.room_name} so kalt",
        None,
        Context(),
        language="de",
    )
    speech = result.response.speech["plain"]["speech"]
    assert speech.startswith(f"{coordinator.room_name}: 19,0 °C")
    assert all(SENTENCES.values())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sentence", "start"),
    [
        ("Wann ist es im {room} warm?", "{room}"),
        ("Wie viel Wärme hat das {room} heute verbraucht", "{room} hat heute etwa"),
        ("Wie viel hat die Heizung heute verbraucht", "Heute bisher etwa"),
        ("Wie läuft die Heizung", "Kein Raum heizt gerade"),
        ("Warum ist es in der Garage kalt", "Den Raum „Garage“ kenne ich nicht"),
    ],
)
async def test_assist_sentences(hass, enable_custom_integrations, sentence, start):
    from homeassistant.components import conversation
    from homeassistant.core import Context
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(hass, "conversation", {})
    _set_up_test_entities(hass, room_temperature="19.0")
    _, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    room = coordinator.room_name
    result = await conversation.async_converse(
        hass, sentence.format(room=room), None, Context(), language="de"
    )
    speech = result.response.speech["plain"]["speech"]
    assert speech.startswith(start.format(room=room)), speech
