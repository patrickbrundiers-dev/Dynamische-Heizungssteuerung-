"""A week of the real living room replayed through the controller.

The room temperatures are the raw readings of the Wohnzimmer sensor from
5 to 12 October 2026, the outdoor temperature and sun their hourly means.
Presence is not part of the recording: the room counts as used during the
comfort blocks. The replay is open loop (the room does not react to the
valves); it checks what the controller does with real, noisy readings: how
often it talks to the valves, that the night setback happens and that comfort
starts on time.
"""

import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_home_assistant_sandbox import (
    _capture_all_calls,
    _set_up_aqara_trv,
    _set_up_test_entities,
)

from custom_components.dynamic_heating.const import DOMAIN

FIXTURE = Path(__file__).parent / "fixtures" / "wohnzimmer_woche.json"
STEP = timedelta(minutes=5)
DAYS = 7
COMFORT = 22.0
ECO = 18.0


def _load():
    data = json.loads(FIXTURE.read_text())
    start = datetime.fromisoformat(data["start"])
    room = [(start + timedelta(seconds=s), v) for s, v in data["room"]]
    return start, room, data["outdoor_hourly"], data["schedule_local"]


def _blocks(day: datetime, schedule: dict[str, list[str]]) -> tuple[datetime, datetime]:
    """Comfort block of the local day ``day``."""
    begin, end = schedule[str(day.weekday())]
    def at(text: str) -> datetime:
        hour, minute = (int(part) for part in text.split(":"))
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return at(begin), at(end)


def _schedule_state(now: datetime, schedule) -> tuple[str, datetime]:
    """On/off and next switch of the recorded weekly schedule at ``now``."""
    local = dt_util.as_local(now)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    begin, end = _blocks(today, schedule)
    if local < begin:
        return "off", begin
    if local < end:
        return "on", end
    return "off", _blocks(today + timedelta(days=1), schedule)[0]


async def _replay(hass, freezer):
    start, room, outdoor, schedule = _load()
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(start)
    _set_up_test_entities(hass, room_temperature=str(room[0][1]))
    _set_up_aqara_trv(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Wohnzimmer Replay",
        unique_id="climate.living_room_aqara",
        data={
            "climate_entity": "climate.living_room_aqara",
            "room_temperature_entity": "sensor.living_room_temperature",
            "schedule_entity": "schedule.living_room_comfort",
            "window_entity": "binary_sensor.living_room_window",
            "presence_entity": "binary_sensor.someone_home",
            "outdoor_temperature_entity": "sensor.outdoor_temperature",
            "comfort_temperature": COMFORT,
            "eco_temperature": ECO,
            "max_preheat_minutes": 120,
            "external_temperature": True,
            "calibration": True,
            "hysteresis": 0.5,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.enabled = True

    targets: list[tuple[datetime, str, float | None]] = []
    index = seen = 0
    with _capture_all_calls(hass) as calls:
        now = start
        while now < start + timedelta(days=DAYS):
            freezer.move_to(now)
            while index + 1 < len(room) and room[index + 1][0] <= now:
                index += 1
            hour = min(int((now - start).total_seconds() // 3600), len(outdoor) - 1)
            state, next_event = _schedule_state(now, schedule)
            hass.states.async_set("sensor.living_room_temperature", str(room[index][1]))
            hass.states.async_set("sensor.outdoor_temperature", str(outdoor[hour]))
            hass.states.async_set(
                "schedule.living_room_comfort",
                state,
                {"next_event": next_event.isoformat()},
            )
            hass.states.async_set(
                "binary_sensor.someone_home", "on" if state == "on" else "off"
            )
            # The valve shows what it got: the last setpoint and room value.
            valve = hass.states.get("climate.living_room_aqara")
            attributes = dict(valve.attributes)
            for domain, service, data in calls[seen:]:
                if domain == "climate" and service == "set_temperature":
                    attributes["temperature"] = data["temperature"]
                if domain == "number":
                    attributes["current_temperature"] = data["value"]
            seen = len(calls)
            hass.states.async_set("climate.living_room_aqara", valve.state, attributes)
            await coordinator.async_refresh()
            targets.append((now, state, coordinator.data.get("target_temperature")))
            now += STEP
    assert await hass.config_entries.async_unload(entry.entry_id)
    return calls, targets


@pytest.mark.asyncio
async def test_real_week_keeps_the_valves_calm(hass, enable_custom_integrations, freezer):
    """Real sensor noise must not turn into a stream of valve commands."""
    calls, targets = await _replay(hass, freezer)

    setpoints = [c for c in calls if c[0] == "climate"]
    sends = [c for c in calls if c[0] == "number"]
    # Until 0.9.1 this week sent the room temperature 417 times (60 a day):
    # every wobble of 0.05 °C and a refresh every half hour. Now only real
    # changes and a refresh every two hours go out (186, 27 a day).
    assert len(sends) / DAYS <= 30, len(sends)
    # Setpoint changes: comfort, setback, preheat and little else.
    assert len(setpoints) / DAYS <= 4, len(setpoints)

    # Night setback happens every night, comfort is there when the block runs.
    by_hour = Counter()
    for at, state, target in targets:
        local = dt_util.as_local(at)
        if 1 <= local.hour < 4:
            assert target is not None and target <= ECO + 0.5, (local, target)
            by_hour["night"] += 1
        if state == "on" and target is not None and target >= COMFORT:
            by_hour["comfort"] += 1
    assert by_hour["night"] == DAYS * 3 * 12
    # During comfort blocks (about 16 h a day) the target is comfort.
    assert by_hour["comfort"] >= DAYS * 15 * 12


@pytest.mark.asyncio
async def test_value_waits_for_the_switch_and_is_resent_if_not_taken(
    hass, enable_custom_integrations, freezer
):
    """After a restart the value goes out once the valve confirms the switch.

    Zigbee2MQTT reports the new sensor mode a few seconds after the command; a
    value sent before that is lost and the valve regulates on its own sensor.
    """
    _set_up_test_entities(hass)
    _set_up_aqara_trv(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="climate.living_room_aqara",
        data={
            "climate_entity": "climate.living_room_aqara",
            "room_temperature_entity": "sensor.living_room_temperature",
            "schedule_entity": "schedule.living_room_comfort",
            "outdoor_temperature_entity": "sensor.outdoor_temperature",
            "comfort_temperature": 21.0,
            "eco_temperature": 18.0,
            "external_temperature": True,
            "calibration": True,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]

    calls = []

    async def fake_call(domain, service, data):
        # The select command is accepted, its state follows later.
        calls.append((domain, data.get("option", data.get("value"))))
        return True

    coordinator._call = fake_call
    coordinator.enabled = True
    await coordinator._sync_external_temperature()
    assert calls == [("select", "external")]
    # No offset from the valve's own 23 °C while it is switching.
    state = hass.states.get("climate.living_room_aqara")
    assert coordinator._calibrated(
        "climate.living_room_aqara", state, 21.0, 18.0, dt_util.utcnow()
    ) == 21.0

    calls.clear()
    hass.states.async_set(
        "select.living_room_aqara_sensor", "external", {"options": ["internal", "external"]}
    )
    await coordinator._sync_external_temperature()
    assert calls == [("number", 18.0)]

    # The valve still shows 23 °C two minutes later: send once more, and not
    # again before the retry interval is over.
    calls.clear()
    freezer.tick(timedelta(seconds=130))
    await coordinator._sync_external_temperature()
    assert calls == [("number", 18.0)]
    calls.clear()
    freezer.tick(timedelta(seconds=130))
    await coordinator._sync_external_temperature()
    assert calls == []

    # Taken: nothing more to send.
    hass.states.async_set(
        "climate.living_room_aqara", "heat",
        {**state.attributes, "current_temperature": 18.0},
    )
    freezer.tick(timedelta(seconds=400))
    await coordinator._sync_external_temperature()
    assert calls == []

    # A valve that never shows what it gets is tried three times, not forever.
    hass.states.async_set(
        "climate.living_room_aqara", "heat",
        {**state.attributes, "current_temperature": 23.0},
    )
    for _ in range(10):
        freezer.tick(timedelta(seconds=400))
        await coordinator._sync_external_temperature()
    assert len(calls) <= 3
