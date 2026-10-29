"""0.16.0: boiler night pause learned again, data quality, backup of what
was learned, radiator test."""

import json
from datetime import timedelta

import pytest
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_runde7_094 import _setup_house

from custom_components.dynamic_heating.learning_backup import (
    async_export_learning,
    async_restore_learning,
    backup_dir,
    match_room,
)
from custom_components.dynamic_heating.logic import (
    QUALITY_MISSING,
    QUALITY_OK,
    QUALITY_STALE,
    data_quality,
    source_quality,
)
from custom_components.dynamic_heating.radiator import (
    RADIATOR_TEST_SECONDS,
    SUPPLY_COLD,
    SUPPLY_IDLE,
    SUPPLY_WAITING,
    SUPPLY_WARM,
    TEST_COLD,
    TEST_NO_SUPPLY,
    TEST_WARM,
    TEST_WARM_ROOM_COLD,
    SupplyProfile,
    radiator_test_verdict,
)

# --- 1: boiler night pause ----------------------------------------------------


def _night(profile: SupplyProfile, start_hour: int, start_minute: int, cold_until: int):
    """A night preheat: waiting for an hour, then cold until ``cold_until``,
    then warm for an hour. Steps of 5 minutes."""
    minute = start_hour * 60 + start_minute
    end = (cold_until + 1) * 60
    while minute < end:
        hour = minute // 60
        if minute < start_hour * 60 + start_minute + 60:
            supply = SUPPLY_WAITING
        elif hour < cold_until:
            supply = SUPPLY_COLD
        else:
            supply = SUPPLY_WARM
        profile.observe(hour, supply, 300)
        minute += 5
    # The room stops asking; the day goes on.
    for hour in range(cold_until + 1, cold_until + 3):
        profile.observe(hour, SUPPLY_IDLE, 300)


def test_the_hour_a_night_preheat_starts_learns_the_pause():
    profile = SupplyProfile()
    _night(profile, 2, 15, cold_until=4)
    # Before 0.16.0 hour 2 stayed unknown: it was only "waiting".
    assert profile.slots[2] == 0.0
    assert profile.slots[3] == 0.0
    assert profile.usually_off(2)
    assert profile.slots[4] == 1.0


def test_a_misread_night_does_not_stick():
    # Hour 2 was once seen "warm" (a valve near a warm wall).
    profile = SupplyProfile.from_list([None, None, 1.0] + [None] * 21)
    nights = 0
    while not profile.usually_off(2):
        _night(profile, 2, 15, cold_until=4)
        nights += 1
    assert nights == 3
    restored = SupplyProfile.from_list(profile.as_list(), profile.count_list())
    assert restored.counts[2] == profile.counts[2] == 4


def test_warm_up_after_waiting_counts_as_delivery_only_for_half_an_hour():
    profile = SupplyProfile()
    # 50 minutes waiting from 6:00, then warm.
    for _step in range(10):
        profile.observe(6, SUPPLY_WAITING, 300)
    for _step in range(2):
        profile.observe(6, SUPPLY_WARM, 300)
    profile.observe(7, SUPPLY_IDLE, 300)
    # 20 of 60 minutes were before the radiators could have been warm.
    assert profile.slots[6] == pytest.approx(40 / 60, abs=0.01)


def test_a_wait_the_room_gives_up_teaches_nothing():
    profile = SupplyProfile()
    for _step in range(10):
        profile.observe(1, SUPPLY_WAITING, 300)
    for _step in range(12):
        profile.observe(2, SUPPLY_IDLE, 300)
    profile.observe(3, SUPPLY_IDLE, 300)
    assert profile.slots[1] is None
    assert profile.slots[2] is None


# --- 6: data quality ---------------------------------------------------------


def test_data_quality_states():
    assert source_quality(False, None, 60) == QUALITY_MISSING
    assert source_quality(True, 120, 60) == QUALITY_STALE
    assert source_quality(True, 120, None) == QUALITY_OK
    assert data_quality([])["state"] is None
    assert data_quality([("Raumfühler", QUALITY_OK, 10)])["state"] == "Vollständig"
    partly = data_quality(
        [("Raumfühler", QUALITY_OK, 10), ("Außentemperatur", QUALITY_STALE, 7 * 3600)]
    )
    assert partly["state"] == "Teilweise"
    assert partly["problems"] == ["Außentemperatur meldet seit 7 h nichts"]
    stale = data_quality([("Raumfühler", QUALITY_MISSING, None)])
    assert stale["state"] == "Veraltet"
    assert stale["problems"] == ["Raumfühler fehlt"]


@pytest.mark.asyncio
async def test_room_reports_its_data_quality(hass, enable_custom_integrations, freezer):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    await coordinator.async_refresh()
    assert coordinator.data["data_quality"] == "Vollständig"
    freezer.tick(timedelta(hours=7))
    hass.states.async_set("sensor.living_room_temperature", "18.5")
    hass.states.async_set("climate.living_room", "unavailable")
    await coordinator.async_refresh()
    assert coordinator.data["data_quality"] == "Teilweise"
    problems = coordinator.data["data_quality_problems"]
    assert any(item.startswith("Außentemperatur meldet seit 7 h") for item in problems)
    assert any(item.endswith("fehlt") for item in problems)
    coordinator.enabled = True
    checks = {check["name"]: check for check in coordinator._selftest_checks(coordinator.data)}
    assert checks["Datenqualität"]["ok"] is False


# --- 7: backup of what was learned -------------------------------------------


def test_room_is_found_again_by_its_name():
    rooms = {"old": {"room": "Leonie", "learning": {"a": 1}}}
    assert match_room(rooms, "old", "x")["learning"] == {"a": 1}
    assert match_room(rooms, "new", "leonie ")["learning"] == {"a": 1}
    assert match_room(rooms, "new", "Lisa") is None


@pytest.mark.asyncio
async def test_export_and_restore_learning(hass, enable_custom_integrations, tmp_path):
    hass.config.config_dir = str(tmp_path)
    _set_up_test_entities(hass)
    entry, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, [])
    coordinator.heating_rate = 1.7
    house.levels["abend"] = 22.5
    answer = await async_export_learning(hass)
    assert answer["rooms"] == [coordinator.room_name]
    assert answer["house"] is True
    path = backup_dir(hass) / answer["file"]
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["rooms"][entry.entry_id]["learning"]["heating_rate"] == 1.7

    # Learning lost: rates back to default, a level changed.
    coordinator.heating_rate = 0.5
    await coordinator._save_learning()
    house.levels["abend"] = 20.0
    await house._async_save()
    answer = await async_restore_learning(hass)
    await hass.async_block_till_done()
    assert answer["restored"] == [coordinator.room_name]
    assert answer["house"] is True
    restored = hass.data["dynamic_heating"][entry.entry_id]
    assert restored is not coordinator
    assert restored.heating_rate == 1.7
    assert hass.data["dynamic_heating"]["house"].levels["abend"] == 22.5


@pytest.mark.asyncio
async def test_restore_without_backup_says_so(hass, enable_custom_integrations, tmp_path):
    from homeassistant.exceptions import ServiceValidationError

    hass.config.config_dir = str(tmp_path)
    _set_up_test_entities(hass)
    await _setup_integration(hass)
    with pytest.raises(ServiceValidationError):
        await async_restore_learning(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "dynamic_heating", "restore_learning", {"file": "../secrets.yaml"},
            blocking=True, return_response=True,
        )


# --- 8: radiator test --------------------------------------------------------


def test_radiator_test_verdicts():
    assert radiator_test_verdict({"Ventil": 6.0}, 0.3, True)[0] == TEST_WARM
    code, text = radiator_test_verdict({"Ventil": 6.0}, 0.02, True)
    assert code == TEST_WARM_ROOM_COLD
    assert "verliert viel Wärme" in text
    code, text = radiator_test_verdict({"Ventil": 0.4}, 0.0, True)
    assert code == TEST_COLD
    assert "entlüften" in text
    assert radiator_test_verdict({"Ventil": 0.4}, 0.0, False)[0] == TEST_NO_SUPPLY
    code, text = radiator_test_verdict({"A": 5.0, "B": 0.2}, 0.2, True)
    assert code == TEST_COLD
    assert "B +0,2 K" in text
    assert radiator_test_verdict({}, 0.3, None)[0] == TEST_WARM
    assert radiator_test_verdict({"Ventil": None}, None, None)[0] == "no_data"


@pytest.mark.asyncio
async def test_radiator_test_opens_the_valves_and_reports(
    hass, enable_custom_integrations, freezer
):
    _set_up_test_entities(hass, room_temperature="19.0")
    hass.states.async_set(
        "climate.living_room", "heat",
        {"temperature": 18.0, "current_temperature": 19.5, "min_temp": 7, "max_temp": 28},
    )
    _, coordinator = await _setup_integration(hass)
    sent = []

    async def capture(message):
        sent.append(message)

    coordinator._push_room = capture
    with _capture_climate_calls(hass) as calls:
        coordinator.enabled = True
        await coordinator.async_start_radiator_test()
        assert coordinator.data["status"].startswith("Heizkörpertest")
        assert calls[-1][2]["temperature"] == 28
        freezer.tick(timedelta(seconds=RADIATOR_TEST_SECONDS + 10))
        hass.states.async_set(
            "climate.living_room", "heat",
            {"temperature": 28, "current_temperature": 26.0, "min_temp": 7, "max_temp": 28},
        )
        hass.states.async_set("sensor.living_room_temperature", "19.4")
        await coordinator.async_refresh()
    assert coordinator.radiator_test_result["code"] == TEST_WARM
    assert coordinator.data["radiator_test"].startswith("Heizkörper wird warm")
    assert sent and sent[0].startswith("Heizkörpertest")
    assert coordinator._radiator_test is None


@pytest.mark.asyncio
async def test_open_window_stops_the_radiator_test(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_start_radiator_test()
        assert coordinator._radiator_test is not None
        hass.states.async_set("binary_sensor.living_room_window", "on")
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert coordinator._radiator_test is None
    assert coordinator.radiator_test_result["code"] == "aborted"
