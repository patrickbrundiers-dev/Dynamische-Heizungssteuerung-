"""0.18.0: ideas from other integrations and studies (Runde 16)."""

from datetime import date, datetime, timedelta

import pytest
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_runde7_094 import _setup_house
from test_smart_090 import _comfort_until, _trained_model

from custom_components.dynamic_heating.anomaly import HEAT, LOSS, HeatLossWatch
from custom_components.dynamic_heating.house_insights import (
    CycleWatch,
    FlowStats,
    RoomRate,
    balance_point,
    week_ahead,
    week_ahead_text,
)
from custom_components.dynamic_heating.model import (
    ROBUST_LIMIT,
    ModelView,
    RoomModel,
    expected_solar_kw,
    sun_elevation,
)
from custom_components.dynamic_heating.routine import HeatStats, Homecoming

TZ = dt_util.get_default_time_zone()


def _local(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ)


# --- 1: departures --------------------------------------------------------------


def test_departures_are_learned_like_homecomings_and_pooled_on_workdays():
    learner = Homecoming(seen=True)
    monday = date(2026, 10, 26)
    for offset in range(3):
        day = monday + timedelta(days=offset)
        learner.observe(_local(day, 6, 0), True)
        learner.observe(_local(day, 7, 30 + offset * 5), False)
        # Still away two hours later: the absence counts as a departure.
        assert learner.observe(_local(day, 9, 45), False)
        learner.observe(_local(day, 17, 0), True)
    # A short trip to the bakery is no departure.
    learner.observe(_local(monday + timedelta(days=3), 8, 0), False)
    learner.observe(_local(monday + timedelta(days=3), 8, 30), True)
    today = monday + timedelta(days=7)
    # Pooled over Mon-Fri: Thursday has its own nothing but gets the habit.
    assert learner.usual_departure(3, today) == 7 * 60 + 35
    assert learner.usual(3, today) == 17 * 60
    assert learner.departure_count() == 3
    restored = Homecoming.from_dict(learner.as_dict())
    assert restored.departures == learner.departures
    assert restored.arrivals == learner.arrivals
    # Stored data from before 0.18.0 has no departures.
    assert Homecoming.from_dict({"0": [["2026-10-26", 1020]]}).departures == {}


def test_history_seed_finds_departures():
    from custom_components.dynamic_heating.routine import homecomings_from_history

    monday = date(2026, 10, 26)
    changes = []
    for offset in range(3):
        day = monday + timedelta(days=offset)
        changes += [
            (_local(day, 7, 40), "person.a", False),
            (_local(day, 16, 50), "person.a", True),
        ]
    seeded = homecomings_from_history(changes, 1)
    assert seeded.departure_count() == 3
    assert seeded.usual_departure(0, monday + timedelta(days=7)) == 7 * 60 + 40


@pytest.mark.asyncio
async def test_heating_stops_before_the_usual_departure(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="21.0")
    _comfort_until(hass, 600)
    hass.states.async_set("person.a", "home")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = ["person.a"]
    coordinator.config["departure_stop"] = True
    coordinator.room_model = _trained_model()
    assert coordinator.room_model.trusted
    leave = dt_util.now() + timedelta(minutes=40)
    for weeks in range(1, 4):
        coordinator.homecoming.record_departure(leave - timedelta(days=7 * weeks))
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "departure_stop"
    assert "Meist geht ihr um" in coordinator.data["status"]
    assert coordinator.data["target_temperature"] == 18.0
    # Off by default: comfort as before.
    coordinator.config["departure_stop"] = False
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"


# --- 3: unusual heat loss ---------------------------------------------------------


def _view() -> ModelView:
    return ModelView(heat_output=0.6, loss=0.02, solar_gain=0.0, wind_loss=0.0, outdoor=5.0)


def test_unusual_loss_is_found_and_a_normal_room_is_not():
    watch = HeatLossWatch()
    view = _view()
    assert watch.observe(0, 21.0, 0.0, True, view) is None
    # Normal cooling: about 0.6 °C in two hours.
    assert watch.observe(7200, 20.4, 0.0, True, view) is None
    # Next stretch: 1.6 °C in two hours with all contacts closed.
    finding = watch.observe(14400, 18.8, 0.0, True, view)
    assert finding is not None and finding.kind == LOSS
    assert finding.observed == 1.6
    assert watch.first_today(LOSS, "2026-11-01")
    assert not watch.first_today(LOSS, "2026-11-01")
    # An open window breaks the stretch.
    assert watch.observe(15000, 18.0, 0.0, False, view) is None
    assert watch.started_at is None


def test_a_radiator_that_stays_cold_is_found():
    watch = HeatLossWatch()
    view = ModelView(heat_output=1.0, loss=0.02, solar_gain=0.0, wind_loss=0.0, outdoor=5.0)
    watch.observe(0, 18.0, 1.0, True, view)
    finding = watch.observe(7200, 18.1, 1.0, True, view)
    assert finding is not None and finding.kind == HEAT
    assert finding.expected > 0.8


# --- 6: robust learning -------------------------------------------------------------


def test_one_party_hour_bends_the_trusted_model_much_less():
    plain = _trained_model(hours=200)
    assert plain.trusted
    robust = RoomModel.from_dict(plain.as_dict())
    before = robust.parameters()
    # A party: +2 °C in an hour without heat.
    robust.add(2.0, 0.0, 21.0, 8.0)
    assert robust.last_weight == pytest.approx(ROBUST_LIMIT / robust.last_error, abs=0.01)
    after = robust.parameters()
    # The plain fit (weight 1) moves the loss much further.
    unweighted = RoomModel.from_dict(plain.as_dict())
    unweighted.matrix = [list(row) for row in plain.matrix]
    unweighted.vector = list(plain.vector)
    features = (0.0, -13.0, 0.0, 0.0)
    for row in range(4):
        unweighted.vector[row] = 0.995 * unweighted.vector[row] + features[row] * 2.0
        for column in range(4):
            unweighted.matrix[row][column] = (
                0.995 * unweighted.matrix[row][column] + features[row] * features[column]
            )
    assert abs(after[1] - before[1]) < abs(unweighted.parameters()[1] - before[1]) / 2


@pytest.mark.asyncio
async def test_learning_pauses_today_and_with_guests(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    await coordinator.async_pause_learning_today()
    await hass.async_block_till_done()
    assert coordinator.learning_paused_until is not None
    assert coordinator.learning_paused()
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["learning_paused"] == "Heute nicht lernen"
    coordinator.learning_paused_until = dt_util.utcnow() - timedelta(seconds=1)
    hass.states.async_set("input_boolean.gaeste", "on")
    coordinator.config["guest_entity"] = "input_boolean.gaeste"
    assert coordinator.learning_paused()
    assert coordinator.learning_paused_until is None
    hass.states.async_set("input_boolean.gaeste", "off")
    assert not coordinator.learning_paused()


# --- 7: sun forecast -------------------------------------------------------------


def test_sun_elevation_and_radiation_are_plausible():
    # Lippstadt, 21 June at 13:30 local (11:30 UTC): about 61°.
    noon = datetime(2026, 6, 21, 11, 30, tzinfo=dt_util.UTC).timestamp()
    assert sun_elevation(noon, 51.67, 8.35) == pytest.approx(61.5, abs=1.5)
    winter = datetime(2026, 12, 21, 11, 30, tzinfo=dt_util.UTC).timestamp()
    assert sun_elevation(winter, 51.67, 8.35) == pytest.approx(15.0, abs=1.5)
    night = datetime(2026, 12, 21, 23, 0, tzinfo=dt_util.UTC).timestamp()
    assert sun_elevation(night, 51.67, 8.35) < 0
    assert expected_solar_kw(-3, 0) == 0
    clear = expected_solar_kw(30, 0)
    assert 0.45 < clear < 0.6
    assert expected_solar_kw(30, 100) == pytest.approx(clear * 0.25, rel=0.01)


@pytest.mark.asyncio
async def test_forecast_sun_takes_the_last_half_degree(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.8")
    _comfort_until(hass, 600)
    hass.states.async_set("sensor.solar", "0", {"unit_of_measurement": "W/m²"})
    _, coordinator = await _setup_integration(hass)
    coordinator.config["solar_radiation_entity"] = "sensor.solar"
    coordinator.room_model = _trained_model(solar=2.0, hours=200)
    assert coordinator.room_model.trusted
    coordinator.config["comfort_temperature"] = 21.0
    # Clear sky in the forecast and the sun high in the sky.
    hass.config.latitude, hass.config.longitude = 51.67, 8.35
    coordinator._expected_sun = lambda hours: 0.6
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "solar_ahead"
    assert coordinator.data["target_temperature"] == 20.5
    # Without sun in the forecast: comfort as before.
    coordinator._expected_sun = lambda hours: 0.0
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"


# --- 2, 4, 5, 8: house -------------------------------------------------------------


def test_flow_stats_find_a_too_hot_heating_curve():
    stats = FlowStats()
    today = date(2026, 11, 1)
    for _ in range(30):
        stats.observe("Wohnzimmer", today, 1.0, outdoor=2.0, mode="comfort",
                      room_temperature=21.1, target=21.0, demand=15)
        stats.observe("Wohnzimmer", today, 0.25, outdoor=2.0, mode="comfort",
                      room_temperature=21.8, target=21.0, demand=0)
    verdict = stats.verdict()
    assert verdict["state"] == "zu_warm"
    assert "eine Stufe flacher" in verdict["text"]
    # A room that stays cold at full demand vetoes a flatter curve.
    for _ in range(10):
        stats.observe("Leonie", today, 1.0, outdoor=2.0, mode="comfort",
                      room_temperature=19.0, target=20.0, demand=100)
    verdict = stats.verdict()
    assert verdict["state"] == "zu_kalt"
    assert verdict["short_rooms"] == ["Leonie"]
    restored = FlowStats.from_dict(stats.as_dict())
    assert restored.verdict() == verdict
    # A new day lets old hours fade.
    stats.observe("Leonie", today + timedelta(days=1), 0.0, outdoor=None, mode=None,
                  room_temperature=None, target=None, demand=None)
    assert stats.rooms["Leonie"][1][0] == pytest.approx(10 * 0.97)


def test_flow_stats_need_cold_days():
    assert FlowStats().verdict()["state"] == "zu_wenig_daten"


def test_balance_point_from_heating_days():
    days = [(outdoor, max(0.0, 2.0 * (15.0 - outdoor))) for outdoor in
            (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13)]
    fit = balance_point(days)
    assert fit is not None
    assert fit["balance_point"] == 15.0
    assert fit["days"] == 12
    assert balance_point(days[:5]) is None
    # Too little spread: no fit.
    assert balance_point([(5.0 + i * 0.1, 10.0) for i in range(12)]) is None


def test_week_ahead_respects_degree_days_and_heating_limit():
    rooms = [RoomRate("Bad", 0.5, 1.0, None), RoomRate("Wohnzimmer", 1.0, 2.0, 12.0)]
    forecast = [(date(2026, 11, 2), 5.0), (date(2026, 11, 3), 13.0), (date(2026, 11, 4), 16.0)]
    result = week_ahead(forecast, rooms, 12.0)
    first, second, third = result["days"]
    # 15 degree days: Bad 7.5 h × 1 kW, Wohnzimmer 15 h × 2 kW.
    assert first["kwh"] == 37.5
    # Above the Wohnzimmer's heating limit only the Bad heats.
    assert second["kwh"] == 3.5
    assert third["kwh"] == 0.0
    assert result["kwh"] == 41.0
    assert result["kwh_low"] < 41.0 < result["kwh_high"]
    assert result["euro"] == pytest.approx(4.92)
    text = week_ahead_text(result)
    assert "41 kWh" in text and "5 €" in text and "02.11." in text


def test_cycle_watch_counts_phases():
    watch = CycleWatch()
    day = date(2026, 10, 31)
    for _ in range(20):
        watch.observe(day, True, 1.0)
        for _minute in range(9):
            watch.observe(day, True, 1.0)
        for _minute in range(20):
            watch.observe(day, False, 1.0)
    verdict = watch.verdict(day + timedelta(days=1))
    assert verdict["phases"] == 20
    assert verdict["mean_minutes"] == 10
    assert verdict["cycling"]
    assert "Heizen bündeln" in verdict["text"]
    assert CycleWatch.from_dict(watch.as_dict()).days == watch.days


def test_heat_stats_keep_the_daily_outdoor_mean():
    stats = HeatStats()
    start = _local(date(2026, 10, 30), 0)
    for step in range(0, 24 * 6):
        stats.observe(start + timedelta(minutes=10 * step), 50, 6.0, power_kw=1.0)
    [(day, hours, mean, covered)] = [
        item for item in stats.daily(date(2026, 10, 31)) if item[0] == "2026-10-30"
    ]
    assert mean == pytest.approx(6.0, abs=0.01)
    assert covered == pytest.approx(23.83, abs=0.01)
    assert hours == pytest.approx(11.92, abs=0.01)


@pytest.mark.asyncio
async def test_bundled_holding_joins_and_waits(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="21.0")
    _comfort_until(hass, 600)
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, [])
    coordinator.config["comfort_temperature"] = 21.0
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
    assert coordinator.data["mode"] == "comfort"
    assert coordinator.data["target_temperature"] == 21.0
    await house.async_set_bundle_holding(True)
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    # Nobody else heats: wait a little.
    assert coordinator.data["bundle"] == "wait"
    assert coordinator.data["target_temperature"] == 20.7

    class Other:
        enabled = True
        entry_id = "other"
        room_name = "Andere"
        data = {"heat_demand": 80, "bundle": None}

    rooms = house.rooms
    house.rooms = lambda: [*rooms(), Other()]
    try:
        with _capture_climate_calls(hass):
            await coordinator.async_refresh()
    finally:
        house.rooms = rooms
    assert coordinator.data["bundle"] == "join"
    assert coordinator.data["target_temperature"] == 21.3
    assert "heizt mit den anderen Räumen mit" in coordinator.data["status"]


@pytest.mark.asyncio
async def test_house_sensors_and_report_lines(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, [])
    assert house.heating_curve()["state"] == "zu_wenig_daten"
    balance = house.balance()
    assert balance["balance_point"] is None and "Noch nicht genug" in balance["text"]
    phases = house.heating_phases()
    assert phases["today"] >= 0 and not phases["cycling"]
    # Heating days of the room with outdoor means from the recorder.
    today = dt_util.now().date()
    house.outdoor_means = {}
    for offset in range(1, 13):
        day = (today - timedelta(days=offset)).isoformat()
        outdoor = 2.0 + offset
        coordinator.heat_stats.days[day] = [2.0 * (15 - outdoor), 0, 0, 0, 0]
        house.outdoor_means[day] = outdoor
    coordinator.config["heating_limit_temperature"] = 17.0
    balance = house.balance()
    assert balance["balance_point"] == 15.0
    assert balance["suggest"]
    assert "eingestellt sind 17,0 °C" in balance["text"]
    assert "Heizgrenze:" in house.report_text()
    for entity_id in (
        "sensor.dynamische_heizung_haus_heizkurve",
        "sensor.dynamische_heizung_haus_gelernte_heizgrenze",
        "sensor.dynamische_heizung_haus_heizbedarf_nachste_tage",
        "sensor.dynamische_heizung_haus_heizphasen_heute",
        "sensor.dynamische_heizung_haus_ubliches_weggehen",
        "switch.dynamische_heizung_haus_heizen_bundeln",
        "number.dynamische_heizung_haus_warmepreis",
        "button.dynamische_heizung_haus_heizgrenze_ubernehmen",
    ):
        assert hass.states.get(entity_id) is not None, entity_id
    assert hass.states.get("number.dynamische_heizung_haus_warmepreis").state == "12.0"
