"""0.21.0: ideas from Raumklima (Goldi5)."""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util
from test_features_080 import _comfort_now
from test_home_assistant_sandbox import (
    _capture_all_calls,
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_runde7_094 import _setup_house

from custom_components.dynamic_heating.const import (
    DOMAIN,
    VALVE_FIXED_PRESETS,
    VALVE_MANUAL_PRESETS,
    VALVE_OFFSET_PRESETS,
    VALVE_OPEN_PRESETS,
    VALVE_PROGRAM_PRESETS,
)
from custom_components.dynamic_heating.logic import (
    evaluate_cold_snap,
    frost_night_eco,
    min_forecast_temperature,
    sun_on_facade,
    valve_own_state,
)
from custom_components.dynamic_heating.model import sun_azimuth
from custom_components.dynamic_heating.room_why import decision_area, why_checks
from custom_components.dynamic_heating.routine import Bedtime, bedtime_night

TZ = dt_util.get_default_time_zone()
_UTCNOW = "homeassistant.util.dt.utcnow"


def _own(state, modes, preset=None, presets=None):
    return valve_own_state(
        state, modes, preset, presets,
        open_presets=VALVE_OPEN_PRESETS,
        program_presets=VALVE_PROGRAM_PRESETS,
        fixed_presets=VALVE_FIXED_PRESETS,
        offset_presets=VALVE_OFFSET_PRESETS,
        manual_presets=VALVE_MANUAL_PRESETS,
    )


# --- 2: valve in a state of its own ---------------------------------------------


def test_valve_states_that_ignore_the_room_are_found():
    # Tuya in its own week program.
    assert _own("auto", ["auto", "heat", "off"]) == (
        "set_hvac_mode", "heat", "eigenes Programm (auto)"
    )
    # Aqara with its own schedule / away preset goes back to manual.
    aqara = ["none", "manual", "away", "auto"]
    assert _own("heat", ["off", "heat"], "auto", aqara)[:2] == ("set_preset_mode", "manual")
    assert _own("heat", ["off", "heat"], "away", aqara)[2] == "fester Zustand (Preset away)"
    assert _own("heat", ["heat"], "on", ["manual", "on"])[2].startswith("dauerhaft offen")
    # Normal states, and a preset without a way back, are left alone.
    assert _own("heat", ["off", "heat"], "manual", aqara) is None
    assert _own("heat", ["auto", "heat", "off"]) is None
    assert _own("heat", ["heat"], "eco", ["eco", "comfort"]) is None
    # Our own room climate entity is never a valve of the room.
    assert _own("heat", ["heat", "off"], "none", ["none", "comfort"]) is None


@pytest.mark.asyncio
async def test_valve_in_own_program_is_set_back_to_heat(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    _, coordinator = await _setup_integration(hass)
    state = hass.states.get("climate.living_room")
    hass.states.async_set(
        "climate.living_room", "auto", {**state.attributes, "hvac_modes": ["auto", "heat", "off"]}
    )
    with _capture_all_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    fixes = [call for call in calls if call[1] == "set_hvac_mode"]
    # Once, not every cycle.
    assert fixes == [("climate", "set_hvac_mode", {"entity_id": "climate.living_room", "hvac_mode": "heat"})]
    assert coordinator.data["valve_own_state"] == {}
    # Still in auto after two fixes half an hour apart: reported.
    start = dt_util.utcnow()
    with _capture_all_calls(hass):
        for minutes in (31, 62):
            with patch(_UTCNOW, return_value=start + timedelta(minutes=minutes)):
                await coordinator.async_refresh()
    assert coordinator.data["valve_own_state"] == {
        "climate.living_room": "eigenes Programm (auto)"
    }
    warnings = coordinator.data["thermostat_warnings"]["climate.living_room"]
    assert any("lässt sich nicht zurückstellen" in item for item in warnings)


# --- 6: window contacts -----------------------------------------------------------


@pytest.mark.asyncio
async def test_flapping_contact_is_ignored_and_reported(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    _, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        for index in range(22):
            hass.states.async_set(
                "binary_sensor.living_room_window", "on" if index % 2 == 0 else "off"
            )
            await coordinator.async_refresh()
        hass.states.async_set("binary_sensor.living_room_window", "on")
        await coordinator.async_refresh()
    problems = coordinator.data["contact_problems"]
    assert len(problems) == 1
    assert "Wechsel in 24 Stunden – wird ignoriert" in next(iter(problems.values()))
    # Ignored: the room heats although the contact says open.
    assert coordinator.data["window_open"] is False
    assert coordinator.data["mode"] == "comfort"


@pytest.mark.asyncio
async def test_contact_gone_for_hours_counts_as_closed(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    _, coordinator = await _setup_integration(hass)
    hass.states.async_set("binary_sensor.living_room_window", "unavailable")
    start = dt_util.utcnow()
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "waiting"
        with patch(_UTCNOW, return_value=start + timedelta(hours=2, minutes=1)):
            await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"
    assert "nicht erreichbar – gilt als zu" in next(
        iter(coordinator.data["contact_problems"].values())
    )


# --- 3: Heute heizen and cold snap ---------------------------------------------------


def test_cold_snap_needs_a_cold_measured_past_and_releases_with_hysteresis():
    now = datetime(2026, 11, 15, 12, 0, tzinfo=TZ)
    cold = [(now - timedelta(minutes=10 * i), 10.0) for i in range(36)][::-1]
    kwargs = {"hours": 6, "below": 5.0, "release": 3.0, "min_span_seconds": 4 * 3600}
    assert evaluate_cold_snap(cold, now, 17.0, False, **kwargs) == (True, 10.0)
    assert evaluate_cold_snap(cold, now, 14.0, False, **kwargs)[0] is False
    milder = [(t, 13.5) for t, _ in cold]
    # 13.5 is not 5 below 17, but still more than 3 below once active.
    assert evaluate_cold_snap(milder, now, 17.0, False, **kwargs)[0] is False
    assert evaluate_cold_snap(milder, now, 17.0, True, **kwargs)[0] is True
    # Too short a history says nothing.
    assert evaluate_cold_snap(cold[-6:], now, 17.0, False, **kwargs) == (False, None)
    assert evaluate_cold_snap(cold, now, None, False, **kwargs) == (False, None)


@pytest.mark.asyncio
async def test_heat_today_lifts_the_heating_limit(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    hass.states.async_set("sensor.outdoor_temperature", "19.0")
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, [])
    coordinator.config["heating_limit_temperature"] = 15.0
    coordinator.config["heating_limit_average"] = False
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "heating_limit"
    await house.async_set_heat_today(True)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"
    assert coordinator.data["heating_limit_lifted"] == "heat_today"
    assert "Heizgrenze aufgehoben: Heute heizen bis" in coordinator.data["status"]
    state = hass.states.get("switch.dynamische_heizung_haus_heute_heizen")
    assert state is not None
    await house.async_set_heat_today(False)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "heating_limit"


# --- 4: frost nights -----------------------------------------------------------------


def test_frost_night_helpers():
    now = datetime(2026, 1, 10, 20, 0, tzinfo=TZ)
    forecast = [
        {"datetime": (now + timedelta(hours=h)).isoformat(), "temperature": -2 - h}
        for h in range(16)
    ]
    assert min_forecast_temperature(forecast, now, 12) == -14
    assert min_forecast_temperature([], now, 12) is None
    assert frost_night_eco(18.0, 21.0) == 19.5
    assert frost_night_eco(17.0, 21.5) == 19.5
    assert frost_night_eco(20.0, 20.0) == 20.0


@pytest.mark.asyncio
async def test_frost_night_sets_back_only_half(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="19.0")
    _, coordinator = await _setup_integration(hass)
    now = dt_util.now()
    items = [
        {"datetime": (now + timedelta(hours=h)).isoformat(), "temperature": -7.0}
        for h in range(12)
    ]

    async def forecast():
        return items

    coordinator._async_get_forecast_items = forecast
    # Comfort starts in 10 hours: eco now.
    hass.states.async_set(
        "schedule.living_room_comfort", "off",
        {"next_event": (dt_util.now() + timedelta(hours=10)).isoformat()},
    )
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "eco"
    assert coordinator.data["target_temperature"] == 18.0
    coordinator.config["frost_night_setback"] = True
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["target_temperature"] == 19.5
    assert coordinator.data["frost_night"] == -7.0
    assert "Frostnacht (−7 °C): halb abgesenkt" in coordinator.data["status"]


# --- 5: facade ----------------------------------------------------------------------


def test_sun_azimuth_and_facade():
    # Mid-November at 51.7 °N 8.4 °E: south-east in the morning, south-west
    # in the afternoon.
    morning = datetime(2026, 11, 15, 9, 0, tzinfo=dt_util.UTC).timestamp()
    afternoon = datetime(2026, 11, 15, 14, 0, tzinfo=dt_util.UTC).timestamp()
    assert 130 < sun_azimuth(morning, 51.67, 8.35) < 160
    assert 200 < sun_azimuth(afternoon, 51.67, 8.35) < 230
    assert sun_on_facade(140, 15, 90, 80, 5)  # east wall in the morning
    assert not sun_on_facade(220, 15, 90, 80, 5)  # east wall in the afternoon
    assert sun_on_facade(220, 15, 270, 80, 5)
    assert not sun_on_facade(220, 3, 270, 80, 5)  # too low
    assert not sun_on_facade(180, 30, 0, 80, 5)  # north wall


@pytest.mark.asyncio
async def test_facade_gates_the_sun(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    hass.config.latitude, hass.config.longitude = 51.67, 8.35
    afternoon = datetime(2026, 11, 15, 13, 30, tzinfo=dt_util.UTC)
    assert coordinator._facade_sun(afternoon) is None
    coordinator.config["facade"] = "O"
    assert coordinator._facade_sun(afternoon) is False
    coordinator.config["facade"] = "SW"
    assert coordinator._facade_sun(afternoon) is True


# --- 8: bedtime ----------------------------------------------------------------------


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    # The test instance sets its own time zone after import.
    tz = dt_util.get_default_time_zone()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def test_bedtime_is_learned_per_night_across_midnight():
    learner = Bedtime()
    monday = date(2026, 11, 2)
    assert bedtime_night(_local(monday, 14)) is None
    assert bedtime_night(_local(monday, 0, 30)) == (monday - timedelta(days=1), 24 * 60 + 30)
    for offset, (hour, minute) in enumerate(((23, 30), (23, 10), (0, 5))):
        evening = monday + timedelta(days=offset)
        moment = _local(evening + timedelta(days=1), hour, minute) if hour < 12 else _local(evening, hour, minute)
        assert learner.record(moment)
        # A second one the same night does not count.
        assert not learner.record(moment + timedelta(minutes=30))
    today = monday + timedelta(days=7)
    # Pooled over Mon-Fri; 00:05 counts as 24:05, not as early evening.
    assert learner.usual(3, today) == 23 * 60 + 30
    assert learner.week(today)["Donnerstag"] == "23:30"
    restored = Bedtime.from_dict(learner.as_dict())
    assert restored.nights == learner.nights


@pytest.mark.asyncio
async def test_bed_sensor_teaches_bedtime_and_auto_good_night_runs(
    hass, enable_custom_integrations
):
    sent: list = []
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, sent)
    hass.config_entries.async_update_entry(
        house.entry, options={**house.entry.options, "bed_sensors": ["binary_sensor.bed"]}
    )
    await hass.async_block_till_done()
    house = hass.data[DOMAIN]["house"]
    evening = date(2026, 11, 9)

    class Bed:
        state = "on"
        last_changed = None

    original_get = hass.states.get
    bed = Bed()
    with patch.object(
        type(hass.states), "get",
        lambda self, entity_id: bed if entity_id == "binary_sensor.bed" else original_get(entity_id),
    ):
        for offset in range(3):
            day = evening + timedelta(days=offset)
            bed.last_changed = dt_util.as_utc(_local(day, 22, 30))
            # Only 10 minutes in bed: not yet.
            with patch(_UTCNOW, return_value=bed.last_changed + timedelta(minutes=10)):
                await house._async_bedtime_tick()
            with patch(_UTCNOW, return_value=bed.last_changed + timedelta(minutes=25)):
                await house._async_bedtime_tick()
    assert house.bedtime.count() == 3
    assert house.bedtime.usual(3, evening + timedelta(days=4)) == 22 * 60 + 30
    # Gute Nacht automatisch: at the usual time with somebody home.
    await house.async_set_auto_good_night(True)
    thursday = evening + timedelta(days=3)
    called = []

    async def good_night(automatic=False):
        called.append(automatic)
        return ["Wohnzimmer"]

    house.async_good_night = good_night
    coordinator._household_present = True
    coordinator.enabled = True
    with patch(_UTCNOW, return_value=dt_util.as_utc(_local(thursday, 22, 40))):
        await house._async_bedtime_tick()
    assert called == [True]
    assert any("Übliche Schlafenszeit 22:30" in item.get("message", "") for item in sent)


# --- 1 and 7: why and decisions ------------------------------------------------------


def test_why_names_what_stops_heating():
    data = {
        "room_temperature": 19.0, "target_temperature": 18.0, "mode": "window",
        "schedule_active": True, "comfort_temperature": 21.0, "window_open": True,
        "present": True, "quick_mode": "auto", "heating_limit_reached": False,
        "outdoor_temperature": 4.0, "status": "Fenster offen",
    }
    answer = why_checks(data, True)
    assert answer["heating"] is False
    assert answer["verdict"] == "Heizt nicht: Fenster – offen – Heizung pausiert"
    data.update(window_open=False, target_temperature=21.0, mode="comfort", status="Komfort")
    answer = why_checks(data, True)
    assert answer["heating"] is True
    assert answer["verdict"].startswith("Heizt: Soll 21,0 °C, im Raum 19,0 °C")
    data.update(heating_limit_reached=True, heating_limit_basis=16.2)
    assert "Heizgrenze – erreicht (Ø 16,2 °C)" in why_checks(data, True)["verdict"]
    assert why_checks(data, False)["checks"][0] == {
        "name": "Regelung", "ok": False,
        "detail": "ausgeschaltet – Ventile werden nicht gestellt",
    }
    assert decision_area("quick_manual") == "Bedienung"
    assert decision_area("supply_wait") == "Therme"


@pytest.mark.asyncio
async def test_why_and_decisions_services(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _comfort_now(hass)
    _, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        hass.states.async_set("binary_sensor.living_room_window", "on")
        start = dt_util.utcnow()
        with patch(_UTCNOW, return_value=start + timedelta(minutes=10)):
            await coordinator.async_refresh()
    entity_id = next(
        state.entity_id for state in hass.states.async_all("select")
        if state.entity_id.endswith("betriebsart")
    )
    why = await hass.services.async_call(
        DOMAIN, "why", {"entity_id": entity_id}, blocking=True, return_response=True
    )
    assert why["verdict"].startswith("Heizt nicht: Fenster")
    answer = await hass.services.async_call(
        DOMAIN, "decisions", {"entity_id": entity_id, "days": 1},
        blocking=True, return_response=True,
    )
    modes = [item["mode"] for item in answer["decisions"] if item["mode"]]
    assert modes[:2] == ["window", "comfort"]
    window = await hass.services.async_call(
        DOMAIN, "decisions", {"entity_id": entity_id, "area": "Fenster"},
        blocking=True, return_response=True,
    )
    assert window["count"] >= 1
    assert all(item["area"] == "Fenster" for item in window["decisions"])
