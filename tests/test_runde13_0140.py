"""0.14.0: clock changes, battery forecast and the heat load check."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_component import async_update_entity
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_runde7_094 import _setup_house
from test_smart_090 import _trained_model

from custom_components.dynamic_heating.battery import BatteryWatch, describe_days
from custom_components.dynamic_heating.const import DOMAIN
from custom_components.dynamic_heating.model import ModelView, heat_load
from custom_components.dynamic_heating.plan import Block, simulate, temperature_at
from custom_components.dynamic_heating.routine import Punctuality

BERLIN = ZoneInfo("Europe/Berlin")


async def _room_at(hass, freezer, utc: str, comfort_local: datetime):
    """A room at 20 °C at ``utc`` with comfort starting at ``comfort_local``.

    The schedule helper hands over a local datetime, as Home Assistant's own
    schedule does; an ISO text would hide the clock change.
    """
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(utc)
    _set_up_test_entities(hass, room_temperature="20.0")
    event = comfort_local.replace(tzinfo=dt_util.get_default_time_zone())
    hass.states.async_set("schedule.living_room_comfort", "off", {"next_event": event})
    _, coordinator = await _setup_integration(hass)
    return coordinator


@pytest.mark.asyncio
async def test_preheat_is_not_an_hour_early_when_the_clock_goes_back(
    hass, enable_custom_integrations, freezer
):
    # 25.10.2026: comfort at 04:00 CET is 150 real minutes after 02:30 CEST,
    # but only 90 on the wall clock.
    coordinator = await _room_at(
        hass, freezer, "2026-10-25T00:30:00+00:00", datetime(2026, 10, 25, 4, 0)
    )
    assert coordinator.data["preheat_minutes"] < 150
    assert coordinator.data["mode"] == "eco"
    # An hour later (02:30 CET, 90 minutes to go) it is time.
    freezer.move_to("2026-10-25T01:30:00+00:00")
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "preheat"


@pytest.mark.asyncio
async def test_preheat_is_not_an_hour_late_when_the_clock_goes_forward(
    hass, enable_custom_integrations, freezer
):
    # 28.03.2027: comfort at 03:30 CEST is 90 real minutes after 01:00 CET,
    # the wall clock says 150.
    coordinator = await _room_at(
        hass, freezer, "2027-03-28T00:00:00+00:00", datetime(2027, 3, 28, 3, 30)
    )
    assert coordinator.data["preheat_minutes"] > 90
    assert coordinator.data["mode"] == "preheat"


@pytest.mark.parametrize(
    "start", [datetime(2026, 10, 24, 20, 0), datetime(2027, 3, 27, 20, 0)]
)
def test_day_plan_steps_evenly_through_a_clock_change(start):
    now = start.replace(tzinfo=BERLIN)
    comfort = datetime(start.year, start.month, start.day + 1, 6, 0, tzinfo=BERLIN)
    points = simulate(
        ModelView(2.0, 0.03, 0.0, 0.0, 5.0),
        now=now,
        room=20.0,
        comfort=21.0,
        eco=18.0,
        blocks=[Block(comfort, comfort + timedelta(hours=2), None)],
        outdoor_at=lambda _at: 5.0,
        supply_off=lambda _at: False,
        max_preheat_minutes=180,
    )
    stamps = [point.at.timestamp() for point in points]
    assert all(later - earlier == 900 for earlier, later in zip(stamps, stamps[1:], strict=False))
    assert all(point.at.tzinfo is BERLIN for point in points)
    # Warm when comfort starts, not an hour off.
    assert temperature_at(points, comfort) == pytest.approx(21.0, abs=0.3)
    first = next(point for point in points if point.preheat)
    assert first.at.timestamp() < comfort.timestamp()


def test_temperature_at_tells_the_two_half_past_two_apart():
    first = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    points = simulate(
        ModelView(2.0, 0.03, 0.0, 0.0, 5.0),
        now=first.astimezone(BERLIN),
        room=20.0,
        comfort=21.0,
        eco=15.0,
        blocks=[],
        outdoor_at=lambda _at: 5.0,
        supply_off=lambda _at: False,
        max_preheat_minutes=0,
        hours=2,
    )
    # 02:30 CEST and 02:30 CET are an hour apart; the room cools in between.
    earlier = temperature_at(points, first)
    later = temperature_at(points, first + timedelta(hours=1))
    assert later < earlier


def test_punctuality_counts_real_minutes_across_the_clock_change():
    punctuality = Punctuality()
    start = datetime(2026, 10, 25, 6, 0, tzinfo=BERLIN)  # 05:00 UTC
    warm_at = datetime(2026, 10, 25, 0, 50, tzinfo=UTC)  # 02:50 CEST
    for minutes in range(-20, 1, 5):
        punctuality.observe(
            warm_at + timedelta(minutes=minutes),
            room=21.0 if minutes == 0 else 20.0,
            mode="preheat",
            next_event=start,
            target=21.0,
        )
    late = punctuality.observe(
        datetime(2026, 10, 25, 5, 0, tzinfo=UTC),
        room=21.0,
        mode="comfort",
        next_event=start,
        target=21.0,
    )
    # Warm 4 h 10 min before the start, not 3 h 10 min.
    assert late == -250


def _days(watch: BatteryWatch, entity_id: str, levels: list[float], first: date):
    for offset, level in enumerate(levels):
        watch.observe(entity_id, first + timedelta(days=offset), level)


def test_battery_forecast_follows_the_drain():
    watch = BatteryWatch()
    first = date(2026, 10, 1)
    _days(watch, "sensor.bad_battery", [80 - day for day in range(11)], first)
    today = first + timedelta(days=10)
    # 70 % today, 1 % a day: the warning at 20 % in about 50 days.
    assert watch.days_left("sensor.bad_battery", today, 20) == 50
    assert describe_days(50) == "in etwa 7 Wochen"
    assert describe_days(5) == "in etwa 5 Tagen"
    # A new battery starts the history over.
    watch.observe("sensor.bad_battery", today + timedelta(days=1), 100)
    assert watch.days_left("sensor.bad_battery", today + timedelta(days=1), 20) is None
    restored = BatteryWatch.from_dict(watch.as_dict())
    assert restored.days == watch.days


def test_battery_forecast_waits_for_enough_data():
    watch = BatteryWatch()
    first = date(2026, 10, 1)
    # Too short.
    _days(watch, "sensor.a", [90, 89, 88], first)
    assert watch.days_left("sensor.a", first + timedelta(days=2), 20) is None
    # Coarse steps (100 / 50) are no line to follow.
    _days(watch, "sensor.b", [100] * 10 + [50] * 5, first)
    assert watch.days_left("sensor.b", first + timedelta(days=14), 20) is None
    # Hardly draining: no forecast.
    _days(watch, "sensor.c", [90] * 20, first)
    assert watch.days_left("sensor.c", first + timedelta(days=19), 20) is None
    # The lowest reading of a day counts; an older day is not taken back.
    watch.observe("sensor.d", first, 80)
    watch.observe("sensor.d", first, 78)
    watch.observe("sensor.d", first, 79)
    assert watch.days["sensor.d"] == [(first.isoformat(), 78)]
    assert watch.observe("sensor.d", first - timedelta(days=1), 70) is False


def _add_valve_with_battery(hass, level: str) -> None:
    trv_entry = MockConfigEntry(domain="mqtt")
    trv_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=trv_entry.entry_id, identifiers={("mqtt", "trv_1")}
    )
    registry = er.async_get(hass)
    for domain, unique_id, object_id in (
        ("climate", "trv_1_climate", "living_room_trv"),
        ("sensor", "trv_1_battery", "living_room_trv_battery"),
    ):
        registry.async_get_or_create(
            domain,
            "mqtt",
            unique_id,
            suggested_object_id=object_id,
            device_id=device.id,
            config_entry=trv_entry,
            original_device_class="battery" if domain == "sensor" else None,
        )
    hass.states.async_set(
        "climate.living_room_trv",
        "heat",
        {"temperature": 18.0, "min_temp": 5, "max_temp": 30},
    )
    hass.states.async_set(
        "sensor.living_room_trv_battery", level, {"friendly_name": "Sofa Batterie"}
    )


@pytest.mark.asyncio
async def test_room_and_house_tell_when_batteries_are_due(
    hass, enable_custom_integrations
):
    sent: list = []
    _set_up_test_entities(hass)
    _add_valve_with_battery(hass, "30")
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, sent)
    coordinator.config["climate_entity"] = "climate.living_room_trv"
    today = dt_util.now().date()
    # Two weeks from 44 % down to 30 %: 1 % a day, 10 days to 20 %.
    _days(
        coordinator.batteries,
        "sensor.living_room_trv_battery",
        [44 - day for day in range(14)],
        today - timedelta(days=14),
    )
    coordinator.batteries.seeded.add("sensor.living_room_trv_battery")
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert coordinator.data["battery_days_left"] == 10
    [battery] = coordinator.data["batteries"]
    assert battery["name"] == "Sofa Batterie"
    assert battery["level"] == 30.0
    state = hass.states.get("sensor.dynamische_heizungssteuerung_batterie_fallig_in")
    assert state.state == "10"
    assert state.attributes["batteries"][0]["days_left"] == 10

    assert await house.async_battery_notice() is True
    assert sent[-1]["title"] == "Batterien bald leer"
    assert "Sofa Batterie in etwa 10 Tagen" in sent[-1]["message"]
    # Once a week, not every day.
    assert await house.async_battery_notice() is False
    assert "Batterien fällig:" in house.report_text()


@pytest.mark.asyncio
async def test_battery_history_comes_from_the_recorder(
    recorder_mock, hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _add_valve_with_battery(hass, "60")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["climate_entity"] = "climate.living_room_trv"
    await coordinator.async_seed_batteries()
    assert "sensor.living_room_trv_battery" in coordinator.batteries.seeded
    # Today's reading at least, and no second seeding.
    assert coordinator.batteries.days["sensor.living_room_trv_battery"]
    await coordinator.async_refresh()
    assert coordinator._battery_seed_at is not None


def test_heat_load_compares_the_cold_day_with_the_radiators():
    strong = heat_load(ModelView(1.5, 0.02, 0.0, 0.0, 5.0), 21.0, -10.0)
    assert strong.share == pytest.approx(0.02 * 31 / 1.5)
    assert strong.holds_down_to == pytest.approx(21.0 - 75.0)
    assert strong.verdict == "reicht, auch mit niedrigerer Vorlauftemperatur"
    tight = heat_load(ModelView(0.7, 0.02, 0.0, 0.0, 5.0), 21.0, -10.0)
    assert tight.verdict == "reicht, mit niedrigerer Vorlauftemperatur knapp"
    weak = heat_load(ModelView(0.35, 0.02, 0.0, 0.0, 5.0), 21.0, -10.0)
    assert weak.share > 1
    assert weak.holds_down_to == pytest.approx(3.5)
    assert weak.verdict == "reicht nicht"


@pytest.mark.asyncio
async def test_house_heat_load_service_and_sensor(hass, enable_custom_integrations):
    sent: list = []
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, sent)
    empty = await hass.services.async_call(
        DOMAIN, "heat_load", {}, blocking=True, return_response=True
    )
    assert empty["rooms"] == []
    assert empty["text"].startswith("Noch kein Raum")

    coordinator.room_model = _trained_model(heat_output=0.35, loss=0.02)
    coordinator.config["comfort_temperature"] = 21.0
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    result = await hass.services.async_call(
        DOMAIN,
        "heat_load",
        {"outdoor_temperature": -12},
        blocking=True,
        return_response=True,
    )
    [room] = result["rooms"]
    assert result["outdoor_temperature"] == -12
    assert room["radiator_kw"] == 1.0
    assert room["share_percent"] > 100
    assert room["verdict"] == "reicht nicht"
    assert result["total_kw"] == pytest.approx(room["load_kw"], abs=0.05)
    assert "Zu schwach:" in result["text"]
    assert "Bei −12,0 °C braucht das Haus etwa" in result["text"]
    assert house.heat_load()["outdoor_temperature"] == -10.0
    entity_id = next(
        state.entity_id
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_heizlast")
    )
    await async_update_entity(hass, entity_id)
    sensor = hass.states.get(entity_id)
    assert float(sensor.state) == pytest.approx(house.heat_load()["total_kw"])
    assert sensor.attributes["rooms"][0]["room"] == coordinator.room_name
