"""0.9.9: the boiler's night pause, preheating that waits for it, mornings
without heat, real night cooling, Tuya valves and a morning push."""

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.model import CoolingCorrection, ModelView
from custom_components.dynamic_heating.plan import Block, simulate
from custom_components.dynamic_heating.plan import summary as plan_summary
from custom_components.dynamic_heating.radiator import (
    COLD,
    IDLE,
    SUPPLY_COLD,
    SUPPLY_PARTLY,
    SUPPLY_WARM,
    WAITING,
    WARM,
    RoomResponse,
    combined_supply,
)
from custom_components.dynamic_heating.routine import (
    Punctuality,
    tuya_day_schedule,
    tuya_week_schedule,
)

BERLIN = ZoneInfo("Europe/Berlin")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


# 1 – the room tells whether heat arrives


def _feed(response: RoomResponse, readings, demand=70, target=21.0):
    verdict = None
    for minute, room in readings:
        verdict = response.observe(
            _at(13, 2, 30).timestamp() + minute * 60, demand, room, target
        )
    return verdict


def test_room_cooling_with_open_valves_means_no_heat():
    # Wohnzimmer in the night of 12./13.10.: preheating from 02:30, no heat.
    readings = [(0, 19.22), (20, 19.2), (36, 19.18), (50, 19.16), (60, 19.15)]
    assert _feed(RoomResponse(), readings) == COLD


def test_room_warming_means_heat_and_a_short_stretch_is_not_judged():
    assert _feed(RoomResponse(), [(0, 18.97), (15, 19.53), (60, 19.6)]) == WARM
    assert _feed(RoomResponse(), [(0, 19.0), (30, 19.0)]) == WAITING
    # Holding its temperature may be the radiators' limit: not judged as cold.
    assert _feed(RoomResponse(), [(0, 20.3), (30, 20.3), (60, 20.3)]) == WAITING


def test_no_heat_asked_for_is_not_judged():
    assert _feed(RoomResponse(), [(0, 19.2), (60, 19.0)], demand=20) == IDLE
    assert _feed(RoomResponse(), [(0, 20.8), (60, 20.6)], target=21.0) == IDLE


def test_cooling_room_overrides_a_warm_looking_radiator():
    assert combined_supply(SUPPLY_WARM, COLD) == SUPPLY_COLD
    assert combined_supply(SUPPLY_PARTLY, COLD) == SUPPLY_COLD
    assert combined_supply(SUPPLY_WARM, WAITING) == SUPPLY_WARM
    # Rooms without radiator readings (Tuya valves) are judged by the room.
    assert combined_supply(None, WARM) == SUPPLY_WARM
    assert combined_supply(None, IDLE) is None


# 2 – preheating waits for the central heating


def _view() -> ModelView:
    return ModelView(1.0, 0.02, 0.0, 0.0, 7.0)


def test_plan_waits_for_the_boiler_and_says_so():
    now = _at(13, 1, 0)
    blocks = [Block(_at(13, 5, 30), _at(13, 22, 30))]
    points = simulate(
        _view(),
        now=now,
        room=19.5,
        comfort=21.0,
        eco=18.0,
        blocks=blocks,
        outdoor_at=lambda at: 7.0,
        supply_off=lambda at: 23 <= at.hour or at.hour < 5,
        max_preheat_minutes=180,
    )
    assert not any(p.preheat for p in points if p.at.hour < 5)
    assert all(p.target == 18.0 for p in points if p.at < _at(13, 5))
    info = plan_summary(points, blocks, now)
    assert info["preheat_start"].startswith("2026-10-13T05:00")
    assert "Zentralheizung liefert erst ab 05:00 Uhr" in info["text"]


@pytest.mark.asyncio
async def test_preheating_waits_while_the_boiler_usually_pauses(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    assert coordinator.data["mode"] == "preheat"
    hour = dt_util.now().hour
    coordinator.supply.slots[hour] = 0.0
    coordinator.supply.slots[(hour + 1) % 24] = 1.0
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "eco"
    assert coordinator.data["status"].startswith(
        "Vorheizen wartet auf die Zentralheizung"
    )
    assert f"ab {(hour + 1) % 24}:00 Uhr" in coordinator.data["status"]
    assert coordinator._preheat_event is None


@pytest.mark.asyncio
async def test_comfort_can_be_held_until_the_boiler_pauses(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    hour = dt_util.now().hour
    coordinator.supply.slots[hour] = 1.0
    coordinator.supply.slots[(hour + 1) % 24] = 0.0
    coordinator._comfort_ended_at = dt_util.utcnow() - timedelta(minutes=10)
    decision = coordinator._supply_wait(
        coordinator_decision("eco", 18.0),
        comfort_temperature=21.0,
        eco_temperature=18.0,
        schedule_active=False,
    )
    assert decision.mode == "eco"
    coordinator.config["hold_before_supply_pause"] = True
    decision = coordinator._supply_wait(
        coordinator_decision("eco", 18.0),
        comfort_temperature=21.0,
        eco_temperature=18.0,
        schedule_active=False,
    )
    assert decision.mode == "comfort"
    assert decision.target_temperature == 21.0


def coordinator_decision(mode: str, target: float):
    from custom_components.dynamic_heating.logic import HeatingDecision

    return HeatingDecision("Energiesparbetrieb", mode, target, 0)


# 3 – mornings without heat teach nothing


def test_late_morning_without_heat_is_not_learned():
    punctuality = Punctuality()
    start = _at(13, 5, 30)
    for minute in range(0, 180, 15):
        punctuality.observe(
            _at(13, 2, 30) + timedelta(minutes=minute),
            room=19.2,
            mode="preheat",
            next_event=start,
            target=21.0,
            supply_cold=True,
        )
    assert punctuality.observe(
        start, room=19.0, mode="comfort", next_event=None, target=21.0
    ) is None
    assert punctuality.morning is not None
    assert punctuality.morning.room == 19.0
    assert punctuality.morning.supply_missing is True
    late = punctuality.observe(
        start + timedelta(hours=3), room=20.0, mode="comfort", next_event=None,
        target=21.0,
    )
    assert late is None
    assert punctuality.results == []
    assert punctuality.bias_minutes == 0.0


def test_results_of_the_old_rule_are_dropped():
    assert Punctuality.from_dict(
        {"bias_minutes": 60, "results": [["2026-10-13", 180]]}
    ).results == []
    stored = Punctuality(bias_minutes=5.0, results=[("2026-10-14", 10)]).as_dict()
    assert Punctuality.from_dict(stored).bias_minutes == 5.0


@pytest.mark.asyncio
async def test_morning_push_when_the_room_was_cold(hass, enable_custom_integrations):
    sent = []

    async def capture(call):
        sent.append(call.data)

    hass.services.async_register("notify", "phone", capture)
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    coordinator.config["notify_service"] = "notify.phone"
    punctuality = coordinator.punctuality
    start = dt_util.now().replace(hour=5, minute=30, second=0, microsecond=0)
    from custom_components.dynamic_heating.routine import Morning

    punctuality.morning = Morning(start.date().isoformat(), start, 19.0, 21.0, True)
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.now",
        return_value=start.replace(hour=6),
    ):
        await coordinator._morning_report({"room_temperature": 19.6})
    assert sent == []
    with patch(
        "custom_components.dynamic_heating.coordinator.dt_util.now",
        return_value=start.replace(hour=7, minute=1),
    ):
        await coordinator._morning_report({"room_temperature": 19.6})
        await coordinator._morning_report({"room_temperature": 19.6})
    assert len(sent) == 1
    assert sent[0]["message"].startswith("Um 05:30 Uhr erst 19,0 statt 21,0 °C")
    assert "Zentralheizung lieferte beim Vorheizen noch keine Wärme" in sent[0]["message"]
    assert sent[0]["message"].endswith("Jetzt 19,6 °C.")


# 4 – real night cooling


def test_cooling_correction_learns_faster_night_cooling():
    view = ModelView(1.0, 0.0065, 0.0, 0.0, 8.0)
    expected = 21.0 - view.temperature_after(21.0, 2.0, 0.0)
    correction = CoolingCorrection()
    base = _at(13, 0).timestamp()
    actual_drop = expected * 2
    for step in range(0, 9):
        correction.observe(
            base + step * 900, 21.0 - actual_drop * step / 8, 8.0, True, view
        )
    assert correction.samples == 1
    assert correction.factor == pytest.approx(2.0, abs=0.05)
    assert correction.active_factor == 1.0
    for step in range(9, 17):
        correction.observe(
            base + step * 900, 21.0 - actual_drop * step / 8, 8.0, True, view
        )
    assert correction.samples == 2
    assert correction.active_factor == pytest.approx(2.0, abs=0.1)
    restored = CoolingCorrection.from_dict(correction.as_dict())
    assert restored.active_factor == correction.active_factor


def test_cooling_factor_only_changes_predictions_without_heat():
    plain = ModelView(1.0, 0.02, 0.0, 0.0, 8.0)
    faster = ModelView(1.0, 0.02, 0.0, 0.0, 8.0, cooling_factor=2.0)
    assert faster.temperature_after(21.0, 3.0, 0.0) < plain.temperature_after(
        21.0, 3.0, 0.0
    )
    assert faster.temperature_after(19.0, 1.0, 1.0) == plain.temperature_after(
        19.0, 1.0, 1.0
    )
    assert faster.with_weather(outdoor=5.0).cooling_factor == 2.0


@pytest.mark.asyncio
async def test_forecast_is_corrected_by_its_error_now(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
    coordinator._forecast_items = [
        {"datetime": (now + timedelta(hours=hour)).isoformat(), "temperature": 10.9}
        for hour in range(0, 24)
    ]
    assert coordinator._forecast_correction(8.4, now, now) == pytest.approx(-2.5)
    assert coordinator._forecast_correction(
        8.4, now + timedelta(hours=6), now
    ) == pytest.approx(-1.25)
    assert coordinator._forecast_correction(8.4, now + timedelta(hours=13), now) == 0


# 5 / 6 – Tuya valves


def test_tuya_day_has_six_points():
    items = [
        {"from": "06:00:00", "to": "08:00:00"},
        {"from": "13:30:00", "to": "20:00:00", "data": {"temperature": 21}},
    ]
    assert tuya_day_schedule(items, 20.0, 18.0, 1.0, lambda value: float(value)) == (
        "00:00/18.0 06:00/20.0 08:00/18.0 13:30/21.0 20:00/18.0 23:59/18.0"
    )
    assert tuya_day_schedule([], 20.0, 18.0) == (
        "00:00/18.0 23:55/18.0 23:56/18.0 23:57/18.0 23:58/18.0 23:59/18.0"
    )
    # Inside Home Assistant the service answers with time objects.
    native = [
        {"from": time(5, 30), "to": time(6, 50)},
        {"from": time(14, 30), "to": time(23, 59, 59)},
    ]
    assert tuya_day_schedule(native, 20.0, 18.0) == (
        "00:00/18.0 05:30/20.0 06:50/18.0 14:30/20.0 23:58/20.0 23:59/20.0"
    )
    week = tuya_week_schedule({"monday": items}, 20.0, 18.0)
    assert set(week) == {
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
    }


def _tuya_valve(hass):
    registry = er.async_get(hass)
    valve_entry = MockConfigEntry(domain="mqtt")
    valve_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=valve_entry.entry_id, identifiers={("mqtt", "tuya")}
    )
    objects = [("climate", "living_room"), ("number", "living_room_local_temperature_calibration")]
    objects += [
        ("text", f"living_room_schedule_{day}")
        for day in (
            "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        )
    ]
    for domain, object_id in objects:
        registry.async_get_or_create(
            domain, "mqtt", object_id, suggested_object_id=object_id,
            device_id=device.id, config_entry=valve_entry,
        )


@pytest.mark.asyncio
async def test_tuya_valve_runs_its_week_program_on_shutdown(
    hass, enable_custom_integrations
):
    _tuya_valve(hass)
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    _set_up_test_entities(hass)
    state = hass.states.get("climate.living_room")
    hass.states.async_set(
        "climate.living_room",
        "heat",
        {**state.attributes, "hvac_modes": ["auto", "heat", "off"]},
    )
    _entry, coordinator = await _setup_integration(hass)
    hass.services.async_register("climate", "set_hvac_mode", record)
    coordinator.enabled = True
    coordinator.config["valve_fallback"] = True
    await coordinator.async_arm_valve_fallback()
    assert (
        "climate", "set_hvac_mode",
        {"entity_id": "climate.living_room", "hvac_mode": "auto"},
    ) in calls
    assert coordinator._fallback_auto == ["climate.living_room"]
    calls.clear()
    hass.states.async_set(
        "climate.living_room", "auto", hass.states.get("climate.living_room").attributes
    )
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert (
        "climate", "set_hvac_mode",
        {"entity_id": "climate.living_room", "hvac_mode": "heat"},
    ) in calls
    assert coordinator._fallback_auto == []


@pytest.mark.asyncio
async def test_valve_sensor_is_calibrated_to_the_room(hass, enable_custom_integrations):
    _tuya_valve(hass)
    calls = []

    async def record(call):
        calls.append(dict(call.data))

    _set_up_test_entities(hass, room_temperature="18.2")
    hass.states.async_set(
        "number.living_room_local_temperature_calibration",
        "0",
        {"min": -9, "max": 9, "step": 1},
    )
    state = hass.states.get("climate.living_room")
    hass.states.async_set(
        "climate.living_room", "heat", {**state.attributes, "current_temperature": 16}
    )
    _entry, coordinator = await _setup_integration(hass)
    hass.services.async_register("number", "set_value", record)
    coordinator.enabled = True
    coordinator.config["valve_sensor_calibration"] = True
    start = dt_util.utcnow()
    for minute in range(0, 70, 10):
        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=start + timedelta(minutes=minute),
        ):
            await coordinator._calibrate_valve_sensors({"room_temperature": 18.2})
    assert calls == [
        {
            "entity_id": "number.living_room_local_temperature_calibration",
            "value": 2.0,
        }
    ]
    # The valve does not follow its calibration: put back, then left alone.
    hass.states.async_set("number.living_room_local_temperature_calibration", "2")
    calls.clear()
    later = start + timedelta(hours=4)
    for minute in range(0, 70, 10):
        with patch(
            "custom_components.dynamic_heating.coordinator.dt_util.utcnow",
            return_value=later + timedelta(minutes=minute),
        ):
            await coordinator._calibrate_valve_sensors({"room_temperature": 18.2})
    assert calls == [
        {
            "entity_id": "number.living_room_local_temperature_calibration",
            "value": 0.0,
        }
    ]
    assert "climate.living_room" in coordinator._valve_cal_off


# 8 – small fixes


@pytest.mark.asyncio
async def test_weather_does_not_stand_in_right_after_a_start(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    hass.states.async_set("sensor.outdoor_temperature", "unavailable")
    hass.states.async_set("weather.home", "sunny", {"temperature": 10.2})
    _, coordinator = await _setup_integration(hass)
    coordinator.config["weather_entity"] = "weather.home"
    assert coordinator._outdoor_temperature() is None
    coordinator._started_at -= timedelta(minutes=11)
    assert coordinator._outdoor_temperature() == 10.2
