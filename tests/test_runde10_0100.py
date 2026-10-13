"""0.10.0: a short handover at home, automations that set the valves, a cap
for hand changes, Gute Nacht, school-free days, showers and geo-fencing once."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.core import Context, ServiceResponse, SupportsResponse
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _config_data,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.const import DOMAIN, QUICK_SLEEP
from custom_components.dynamic_heating.plan import Block, blocks_switched_at
from custom_components.dynamic_heating.routine import (
    Habits,
    ShowerWatch,
    schedule_covers,
    showers_from_history,
)

BERLIN = ZoneInfo("Europe/Berlin")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


def _comfort_now(hass, entity_id="schedule.living_room_comfort"):
    hass.states.async_set(
        entity_id,
        "on",
        {"next_event": (dt_util.now() + timedelta(hours=2)).isoformat()},
    )


# 1 – a short handover is not "nobody home"


@pytest.mark.asyncio
async def test_handover_within_the_leaving_delay_keeps_the_house_home(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _comfort_now(hass)
    hass.states.async_set("person.jenny", "home")
    hass.states.async_set("person.patrick", "Arbeit Patrick")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = ["person.jenny", "person.patrick"]
    coordinator.config["leaving_home_duration"] = 600
    await coordinator.async_refresh()
    assert coordinator._household_present is True

    # 13.10. 16:07 Jenny leaves (straight into a zone), 16:14 Patrick is back.
    hass.states.async_set("person.jenny", "Engel Oma")
    await coordinator.async_refresh()
    assert coordinator._household_present is True
    assert coordinator.data["absence"] != "house_empty"

    # Long gone: nobody home.
    coordinator._seen_home["person.jenny"] = dt_util.utcnow() - timedelta(minutes=11)
    await coordinator.async_refresh()
    assert coordinator._household_present is False


@pytest.mark.asyncio
async def test_preheating_keeps_a_just_gone_household_longer(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    hass.states.async_set("person.jenny", "home")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["person_entities"] = ["person.jenny"]
    coordinator.config["leaving_home_duration"] = 300
    await coordinator.async_refresh()
    assert coordinator.data["mode"] == "preheat"
    hass.states.async_set("person.jenny", "not_home")
    coordinator._seen_home["person.jenny"] = dt_util.utcnow() - timedelta(minutes=10)
    await coordinator.async_refresh()
    assert coordinator._household_present is True
    coordinator._seen_home["person.jenny"] = dt_util.utcnow() - timedelta(minutes=16)
    await coordinator.async_refresh()
    assert coordinator._household_present is False


@pytest.mark.asyncio
async def test_update_moves_the_old_leaving_delay_and_turns_off_room_geofencing(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    data = _config_data()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer",
        unique_id="climate.living_room",
        data=data,
        options={**data, "leaving_home_duration": 2},
        version=1,
        minor_version=1,
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_proximity_status", config_entry=entry
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 2
    assert entry.options["leaving_home_duration"] == 600
    assert registry.async_get(old.entity_id).disabled_by is (
        er.RegistryEntryDisabler.INTEGRATION
    )


@pytest.mark.asyncio
async def test_a_set_leaving_delay_is_kept(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    data = {**_config_data(), "leaving_home_duration": 180}
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="climate.living_room", data=data, minor_version=1
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.options.get("leaving_home_duration", 180) == 180


# 2 – automations that set the valves


@pytest.mark.asyncio
async def test_automation_setting_the_valve_is_reported(
    hass, enable_custom_integrations
):
    sent = []

    async def capture(call):
        sent.append(call.data)

    hass.services.async_register("notify", "phone", capture)
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["notify_service"] = "notify.phone"
    run = Context()
    hass.states.async_set(
        "automation.leonie", "on", {"friendly_name": "Leonie"}, context=run
    )
    if not hass.services.has_service("climate", "set_temperature"):

        async def ignore(call):
            return None

        hass.services.async_register("climate", "set_temperature", ignore)
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 20},
        blocking=True,
        context=run,
    )
    await hass.async_block_till_done()
    assert "automation.leonie" in coordinator.foreign_control
    issue_id = f"foreign_control_{coordinator.entry_id}_automation_leonie"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert len(sent) == 1
    assert "Automation „Leonie“" in sent[0]["message"]
    assert "auf 20 °C gestellt" in sent[0]["message"]

    # A call without an automation behind it (the app, a person) is not.
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": "climate.living_room", "temperature": 21},
        blocking=True,
    )
    await hass.async_block_till_done()
    assert list(coordinator.foreign_control) == ["automation.leonie"]

    # Turned off: the repair entry goes.
    hass.states.async_set("automation.leonie", "off", {"friendly_name": "Leonie"})
    await coordinator.async_refresh()
    assert coordinator.foreign_control == {}
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


# 3 – a cap for hand changes


@pytest.mark.asyncio
async def test_hand_changes_are_capped_when_set(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    await coordinator.async_set_manual_temperature(27.5)
    assert coordinator.quick_temperature == 27.5

    coordinator.config["manual_max_temperature"] = 23.0
    coordinator.config["manual_max_duration"] = 7200
    coordinator.quick_duration = "forever"
    await coordinator.async_set_manual_temperature(27.5)
    assert coordinator.quick_temperature == 23.0
    assert coordinator.quick_until is not None
    assert coordinator.quick_until <= dt_util.utcnow() + timedelta(hours=2)
    await coordinator.async_set_manual_temperature(21.0)
    assert coordinator.quick_temperature == 21.0


# 5 – Gute Nacht


@pytest.mark.asyncio
async def test_good_night_lowers_rooms_in_comfort_only(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _comfort_now(hass)
    _, coordinator = await _setup_integration(hass)
    house_entry = MockConfigEntry(
        domain=DOMAIN, title="Haus", unique_id="house", data={"entry_type": "house"}
    )
    house_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(house_entry.entry_id)
    await hass.async_block_till_done()
    house = hass.data[DOMAIN]["house"]
    coordinator.enabled = True
    await coordinator.async_refresh()
    assert coordinator.data["schedule_active"] is True

    with _capture_climate_calls(hass):
        lowered = await house.async_good_night()
    assert lowered == [coordinator.room_name]
    assert coordinator.quick_mode == QUICK_SLEEP
    assert coordinator.quick_until == coordinator._next_event
    assert coordinator.data["target_temperature"] == 18.0

    # Outside comfort time nothing changes (morning preheating stays).
    coordinator.quick_mode = "auto"
    coordinator.quick_until = None
    hass.states.async_set(
        "schedule.living_room_comfort",
        "off",
        {"next_event": (dt_util.now() + timedelta(hours=8)).isoformat()},
    )
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
        assert await house.async_good_night() == []
    assert coordinator.quick_mode == "auto"


# 6 – school-free days


def test_tomorrow_switches_schedule_at_midnight():
    midnight = _at(14, 0)
    today = [Block(_at(13, 17), _at(13, 20)), Block(_at(14, 6), _at(14, 8))]
    free = [Block(_at(13, 8), _at(13, 20)), Block(_at(14, 8), _at(14, 20))]
    blocks = blocks_switched_at(today, free, midnight)
    assert blocks == [Block(_at(13, 17), _at(13, 20)), Block(_at(14, 8), _at(14, 20))]


@pytest.mark.asyncio
async def test_school_free_picks_its_schedule_and_knows_tomorrow(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    hass.states.async_set(
        "schedule.school_free", "off", {"friendly_name": "Kinderzimmer Schulfrei"}
    )
    hass.states.async_set("binary_sensor.schulfrei", "off")
    hass.states.async_set("binary_sensor.workday_sensor", "on")
    asked = []

    async def check_date(call) -> ServiceResponse:
        asked.append(call.data["check_date"])
        return {"binary_sensor.workday_sensor": {"workday": False}}

    hass.services.async_register(
        "workday", "check_date", check_date, supports_response=SupportsResponse.ONLY
    )

    async def get_events(call) -> ServiceResponse:
        return {call.data["entity_id"]: {"events": []}}

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config.update(
        {
            "school_free_entity": "binary_sensor.schulfrei",
            "school_free_schedule": "schedule.school_free",
            "workday_entity": "binary_sensor.workday_sensor",
            "school_holiday_calendar": "calendar.ferien",
        }
    )
    assert ("schedule.school_free", "Kinderzimmer Schulfrei") in (
        coordinator.schedule_options()
    )
    await coordinator.async_refresh()
    assert coordinator.active_schedule == "schedule.living_room_comfort"
    hass.states.async_set("binary_sensor.schulfrei", "on")
    await coordinator.async_refresh()
    assert coordinator.active_schedule == "schedule.school_free"
    # Picked by hand: holds until the next change.
    await coordinator.async_set_schedule("schedule.living_room_comfort")
    await coordinator.async_refresh()
    assert coordinator.active_schedule == "schedule.living_room_comfort"
    hass.states.async_set("binary_sensor.schulfrei", "off")
    await coordinator.async_refresh()
    assert coordinator.active_schedule == "schedule.living_room_comfort"

    # Tomorrow is no workday: school-free, asked once per day.
    assert await coordinator._tomorrow_schedule(dt_util.utcnow()) == (
        "schedule.school_free"
    )
    await coordinator._tomorrow_schedule(dt_util.utcnow())
    assert len(asked) == 1


@pytest.mark.asyncio
async def test_holiday_calendar_makes_tomorrow_free(hass, enable_custom_integrations):
    _set_up_test_entities(hass)

    async def get_events(call) -> ServiceResponse:
        return {"calendar.nrw": {"events": [{"summary": "Herbstferien Nordrhein-Westfalen"}]}}

    hass.services.async_register(
        "calendar", "get_events", get_events, supports_response=SupportsResponse.ONLY
    )
    _, coordinator = await _setup_integration(hass)
    coordinator.config.update(
        {
            "school_free_entity": "binary_sensor.schulfrei",
            "school_free_schedule": "schedule.school_free",
            "school_holiday_calendar": "calendar.nrw",
        }
    )
    assert await coordinator._free_tomorrow(dt_util.utcnow()) is True


# 7 – showers from the humidity


def _readings(day: int, values) -> list[tuple[float, float]]:
    return [(_at(day, hour, minute).timestamp(), value) for hour, minute, value in values]


def test_showers_are_found_in_the_real_bathroom_humidity():
    # Großes Bad 12./13.10.2026 (recorder): evening shower 19:18-19:34, the
    # slow rise in the morning of the 12th is no shower.
    readings = _readings(
        12,
        [
            (7, 9, 60.71), (7, 34, 64.29), (8, 2, 68.99), (8, 25, 71.81),
            (9, 7, 74.46), (9, 46, 78.59), (18, 45, 57.7), (19, 1, 60.04),
            (19, 18, 62.74), (19, 27, 69.03), (19, 30, 75.32), (19, 34, 81.36),
            (19, 47, 68.25), (19, 59, 50.95), (20, 10, 57.06), (23, 42, 57.66),
        ],
    ) + _readings(
        13,
        [
            (0, 29, 58.07), (2, 24, 58.87), (4, 10, 59.09), (4, 57, 59.14),
            (5, 3, 59.19), (5, 33, 65.38), (6, 2, 63.86),
        ],
    )
    watch = ShowerWatch(6.0, 20 * 60, 2 * 3600)
    found = showers_from_history(watch, readings, _at(13, 7).timestamp())
    clocks = [datetime.fromtimestamp(at, BERLIN).strftime("%d. %H:%M") for at in found]
    assert clocks == ["12. 19:27", "13. 05:33"]


def test_shower_suggestion_skips_times_the_schedule_already_warms():
    weekly = {
        day: [{"from": "05:00:00", "to": "07:00:00"}]
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday")
    }
    assert schedule_covers(weekly, False, 5 * 60 + 45)
    assert not schedule_covers(weekly, False, 19 * 60)
    assert not schedule_covers(weekly, True, 5 * 60 + 45)
    weekly["saturday"] = [{"from": time(18, 0), "to": time.max}]
    weekly["sunday"] = [{"from": "18:00:00", "to": "24:00:00"}]
    assert schedule_covers(weekly, True, 23 * 60 + 50)

    showers = Habits()
    for day in (12, 13, 14):
        showers.record(_at(day, 19, 30), "shower", "Duschen")
    texts = [
        item["text"]
        for item in showers.suggestions(
            _at(15, 8),
            lambda when, clock, _label, days: f"{when} {clock} {days}",
        )
    ]
    assert texts == ["Montag bis Freitag 19:30 3"]


@pytest.mark.asyncio
async def test_a_shower_is_seen_and_kept_out_of_the_room_model(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    hass.states.async_set("sensor.bad_humidity", "58.0")
    _, coordinator = await _setup_integration(hass)
    coordinator.config["humidity_entity"] = "sensor.bad_humidity"
    coordinator.config["shower_learning"] = True
    await coordinator.async_refresh()
    assert coordinator.data["shower_until"] is None
    hass.states.async_set("sensor.bad_humidity", "75.0")
    await coordinator.async_refresh()
    assert coordinator.data["shower_until"] is not None
    assert len(coordinator.showers.events) == 1
    assert await coordinator._observe_model(dict(coordinator.data)) is False


# 8 – geo-fencing counts per person


@pytest.mark.asyncio
async def test_stale_events_are_counted_per_person(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    start = coordinator._proximity_stale_events
    for _ in range(5):
        coordinator._record_proximity_category("stale", "sensor.jenny_distance")
        coordinator._record_proximity_category("out_of_range", "sensor.patrick_distance")
    assert coordinator._proximity_stale_events == start + 1
    assert coordinator._proximity_out_of_range_events >= 1
