"""0.9.7: entity names, calibration run, warm on time, push buttons,
schedule suggestions, long-term figures and the valves' fallback schedule."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.const import DOMAIN
from custom_components.dynamic_heating.logic import decide_heating_target
from custom_components.dynamic_heating.model import RoomModel, SampleCollector
from custom_components.dynamic_heating.radiator import SupplyProfile
from custom_components.dynamic_heating.routine import (
    BIAS_MAX,
    Habits,
    HeatStats,
    Punctuality,
    fallback_schedule,
)

BERLIN = ZoneInfo("Europe/Berlin")


def _at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=BERLIN)


# 1 – entity ids follow the device name


@pytest.mark.asyncio
async def test_default_entity_ids_follow_the_named_device(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    entry, _coordinator = await _setup_integration(hass)
    registry = er.async_get(hass)
    assert registry.async_get("sensor.dynamische_heizungssteuerung_status") is not None
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    dr.async_get(hass).async_update_device(device.id, name_by_user="Schlafzimmer Heizung")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get("sensor.dynamische_heizungssteuerung_status") is None
    assert registry.async_get("sensor.schlafzimmer_heizung_status") is not None
    assert registry.async_get("button.schlafzimmer_heizung_boost") is not None
    assert hass.states.get("sensor.schlafzimmer_heizung_status") is not None
    leftovers = [
        entity.entity_id
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if "dynamische_heizungssteuerung" in entity.entity_id
    ]
    assert leftovers == []


# 2 – calibration run


@pytest.mark.asyncio
async def test_calibration_run_heats_fully_for_two_hours(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="19.0")
    _entry, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_start_learn_run()
        assert coordinator.data["mode"] == "learn_run"
        assert coordinator.data["target_temperature"] == pytest.approx(23.0)
        left = coordinator.learn_run_until - dt_util.utcnow()
        assert timedelta(minutes=119) < left <= timedelta(hours=2)
        coordinator.learn_run_until = dt_util.utcnow() - timedelta(seconds=1)
        await coordinator.async_refresh()
        assert coordinator.data["mode"] != "learn_run"
        assert coordinator.learn_run_until is None


@pytest.mark.asyncio
async def test_calibration_run_can_be_planned(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="19.0")
    _entry, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        later = dt_util.utcnow() + timedelta(hours=3)
        await coordinator.async_start_learn_run(later)
        assert coordinator.learn_run_at == later
        assert coordinator.data["mode"] != "learn_run"
        coordinator.learn_run_at = dt_util.utcnow() - timedelta(seconds=1)
        await coordinator.async_refresh()
        assert coordinator.data["mode"] == "learn_run"
        assert coordinator.learn_run_at is None


def test_warm_radiators_count_lower_demand_as_heating_hours():
    model = RoomModel()
    model.add(0.3, 0.3, 19.0, 8.0)
    assert model.heating_samples == 0
    model.add(0.3, 0.3, 19.0, 8.0, warm=True)
    assert model.heating_samples == 1


def test_collector_remembers_warm_radiators_of_the_hour():
    collector = SampleCollector()
    for minute in range(0, 65, 5):
        sample = collector.observe(
            minute * 60.0, 19.0 + minute / 600, 0.3, 8.0, 0.0, 0.0,
            warm=minute == 20,
        )
    assert sample is not None
    assert collector.last_warm is True


# 3 – warm on time


def test_late_morning_raises_the_preheat_correction():
    punctuality = Punctuality()
    start = _at(13, 5, 30)
    assert punctuality.observe(
        _at(13, 3, 30), room=20.0, mode="preheat", next_event=start, target=21.0
    ) is None
    punctuality.observe(_at(13, 5, 0), room=20.4, mode="preheat", next_event=start, target=21.0)
    assert punctuality.observe(
        _at(13, 5, 31), room=20.5, mode="comfort", next_event=None, target=21.0
    ) is None
    late = punctuality.observe(
        _at(13, 6, 30), room=20.8, mode="comfort", next_event=None, target=21.0
    )
    assert late == 60
    assert punctuality.bias_minutes == pytest.approx(30)
    assert punctuality.summary() == "0 von 1 Tagen pünktlich, wenn zu spät im Schnitt 60 Minuten"


def test_early_morning_lowers_the_correction_and_on_time_keeps_it():
    punctuality = Punctuality(bias_minutes=20)
    start = _at(14, 5, 30)
    punctuality.observe(_at(14, 4, 0), room=20.0, mode="preheat", next_event=start, target=21.0)
    punctuality.observe(_at(14, 4, 50), room=20.9, mode="preheat", next_event=start, target=21.0)
    late = punctuality.observe(_at(14, 5, 30), room=21.0, mode="comfort", next_event=None, target=21.0)
    assert late == -40
    assert punctuality.bias_minutes == pytest.approx(5)
    start = _at(15, 5, 30)
    punctuality.observe(_at(15, 4, 0), room=20.0, mode="preheat", next_event=start, target=21.0)
    assert punctuality.observe(
        _at(15, 5, 35), room=20.85, mode="comfort", next_event=None, target=21.0
    ) == 5
    assert punctuality.bias_minutes == pytest.approx(5)


def test_morning_without_preheat_or_with_window_is_not_judged():
    punctuality = Punctuality()
    assert punctuality.observe(
        _at(13, 5, 31), room=19.0, mode="comfort", next_event=None, target=21.0
    ) is None
    start = _at(13, 5, 30)
    punctuality.observe(_at(13, 4, 0), room=20.0, mode="preheat", next_event=start, target=21.0)
    punctuality.observe(_at(13, 4, 30), room=19.0, mode="window", next_event=start, target=15.0)
    assert punctuality.watch_start is None
    assert punctuality.results == []


def test_correction_is_bounded_and_survives_storage():
    punctuality = Punctuality()
    for day in range(1, 9):
        start = _at(day, 5, 30)
        punctuality.observe(_at(day, 4, 0), room=19.0, mode="preheat", next_event=start, target=21.0)
        punctuality.observe(_at(day, 8, 31), room=19.5, mode="comfort", next_event=None, target=21.0)
    assert punctuality.bias_minutes == BIAS_MAX
    assert len(punctuality.results) == 7
    restored = Punctuality.from_dict(punctuality.as_dict())
    assert restored.bias_minutes == BIAS_MAX
    assert restored.results == punctuality.results


def test_lead_bias_starts_preheating_earlier():
    now = _at(13, 4, 0)
    common = dict(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(minutes=90),
        room_temperature=20.0,
        outdoor_temperature=8.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=180,
    )
    assert decide_heating_target(**common).mode == "eco"
    decision = decide_heating_target(**common, lead_bias_minutes=30)
    assert decision.mode == "preheat"
    assert decision.preheat_minutes == 102


@pytest.mark.asyncio
async def test_preheat_may_run_longer_unless_the_boiler_is_off(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    event = dt_util.as_utc(
        dt_util.now().replace(hour=5, minute=30, second=0, microsecond=0)
        + timedelta(days=1)
    )
    assert coordinator._preheat_limit(120, event) == 180
    profile = SupplyProfile()
    profile.slots[2] = 0.0
    coordinator.supply = profile
    assert coordinator._preheat_limit(120, event) == 120
    coordinator.config["punctuality"] = False
    profile.slots[2] = None
    assert coordinator._preheat_limit(120, event) == 120


# 4 – push buttons


@pytest.mark.asyncio
async def test_push_buttons_mute_ignore_window_and_come_home(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    _entry, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        actions = coordinator._notify_actions("heating")
        assert [item["title"] for item in actions] == [
            "Boost 1 Stunde", "Heute nicht mehr melden",
        ]
        assert actions[0]["action"].endswith(coordinator.entry_id)

        await coordinator.async_handle_notify_action("mute")
        assert coordinator._heating_muted_until > dt_util.utcnow()
        coordinator.heating_problem = True
        assert "heating" not in coordinator._alert_conditions(coordinator.data)

        hass.states.async_set("binary_sensor.living_room_window", "on")
        await coordinator.async_handle_notify_action("ignore_window")
        await coordinator.async_refresh()
        assert coordinator.data["mode"] != "window"
        hass.states.async_set("binary_sensor.living_room_window", "off")
        await coordinator.async_refresh()
        assert coordinator._window_ignored is False

        hass.bus.async_fire(
            "mobile_app_notification_action",
            {"action": f"DYNHEAT_home_{coordinator.entry_id}"},
        )
        await hass.async_block_till_done()
        assert coordinator.quick_mode == "home"


@pytest.mark.asyncio
async def test_away_push_comes_from_one_room_with_a_button(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    coordinator.config["notify_service"] = "notify.mobile_app_phone"
    coordinator._absence = "house_empty"
    conditions = coordinator._alert_conditions(coordinator.data or {})
    assert "away" in conditions
    assert coordinator._notify_actions("away")[0]["title"] == "Stimmt nicht, ich bin da"
    coordinator.config["notify_away"] = False
    assert "away" not in coordinator._alert_conditions(coordinator.data or {})


# 5 – schedule suggestions


def test_repeated_hand_picks_become_a_suggestion():
    habits = Habits()
    habits.record(_at(5, 21, 5), "sleep", "Schlafen")
    habits.record(_at(6, 20, 50), "sleep", "Schlafen")
    assert habits.suggestions(_at(7, 12)) == []
    habits.record(_at(7, 21, 20), "sleep", "Schlafen")
    habits.record(_at(7, 9, 0), "comfort", "Komfort")
    suggestions = habits.suggestions(_at(8, 12))
    assert len(suggestions) == 1
    assert suggestions[0]["text"] == (
        "Montag bis Freitag gegen 21:00 Uhr „Schlafen“ (3× von Hand in 3 Wochen) – "
        "in den Zeitplan übernehmen?"
    )
    restored = Habits.from_dict(habits.as_dict())
    assert restored.suggestions(_at(8, 12))[0]["key"] == suggestions[0]["key"]


def test_same_weekday_is_named_and_old_picks_expire():
    habits = Habits()
    for week in range(3):
        habits.record(_at(3 + 7 * week, 10, 0), "comfort", "Komfort")
    assert habits.suggestions(_at(18, 12))[0]["text"].startswith("Samstags gegen 10:00 Uhr")
    assert habits.suggestions(_at(31, 12)) == []


@pytest.mark.asyncio
async def test_hand_picked_mode_is_remembered(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_set_quick_mode("sleep")
        await coordinator.async_set_manual_temperature(21.5)
        await coordinator.async_set_quick_mode("auto")
    assert [(mode, label) for _, mode, label in coordinator.habits.events] == [
        ("sleep", "Schlafen"), ("manual:21.5", "21,5 °C"),
    ]
    assert coordinator.data["schedule_suggestion"] == "Keine Vorschläge"


# 7 – long-term figures


def test_heating_hours_and_degree_days_add_up():
    stats = HeatStats()
    at = _at(12, 0, 0)
    for _ in range(24 * 12 + 1):
        stats.observe(at, 50.0, 5.0)
        at += timedelta(minutes=5)
    assert stats.heating_hours == pytest.approx(12.0, abs=0.01)
    assert stats.degree_days == pytest.approx(15.0, abs=0.01)
    assert stats.hours_per_degree_day(_at(13, 12).date()) == pytest.approx(0.8, abs=0.01)
    stats.observe(at + timedelta(hours=2), 100.0, 0.0)
    assert stats.heating_hours == pytest.approx(12.0, abs=0.01)
    restored = HeatStats.from_dict(stats.as_dict())
    assert restored.heating_hours == stats.heating_hours
    assert restored.days == stats.days


def test_warm_days_add_no_degree_days():
    stats = HeatStats()
    stats.observe(_at(12, 12), 0.0, 16.0)
    stats.observe(_at(12, 12, 10), 0.0, 16.0)
    assert stats.degree_days == 0.0


@pytest.mark.asyncio
async def test_figures_are_sensors(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _entry, coordinator = await _setup_integration(hass)
    await coordinator.async_refresh()
    state = hass.states.get("sensor.dynamische_heizungssteuerung_heizstunden")
    assert state is not None
    assert state.attributes["state_class"] == "total_increasing"
    assert hass.states.get("sensor.dynamische_heizungssteuerung_punktlichkeit").state == (
        "Noch kein Morgen mit Vorheizen ausgewertet"
    )
    assert hass.states.get("button.dynamische_heizungssteuerung_raummodell_kalibrieren")
    assert hass.states.get("datetime.dynamische_heizungssteuerung_kalibrierlauf_um")


# 8 – fallback schedule in the valves


def test_fallback_schedule_has_four_points_per_day():
    blocks = [
        (_at(13, 5, 30), _at(13, 8, 0), 21.0),
        (_at(13, 16, 0), _at(13, 22, 30), 21.3),
    ]
    assert fallback_schedule(blocks, 18.0) == (
        "mon,tue,wed,thu,fri,sat,sun|5:30,21.0|8:00,18.0|16:00,21.5|22:30,18.0"
    )
    assert fallback_schedule(blocks[:1], 18.0) == (
        "mon,tue,wed,thu,fri,sat,sun|0:00,18.0|5:30,21.0|8:00,18.0|23:59,18.0"
    )
    assert fallback_schedule([], 17.0) == (
        "mon,tue,wed,thu,fri,sat,sun|0:00,17.0|6:00,17.0|12:00,17.0|23:59,17.0"
    )


@pytest.mark.asyncio
async def test_shutdown_switches_valves_to_their_own_schedule(hass, enable_custom_integrations):
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    valve_entry = MockConfigEntry(domain="mqtt")
    valve_entry.add_to_hass(hass)
    device = devices.async_get_or_create(
        config_entry_id=valve_entry.entry_id, identifiers={("mqtt", "valve")}
    )
    for domain, object_id in (
        ("climate", "living_room"),
        ("switch", "living_room_schedule"),
        ("text", "living_room_schedule_settings"),
    ):
        registry.async_get_or_create(
            domain, "mqtt", object_id, suggested_object_id=object_id,
            device_id=device.id, config_entry=valve_entry,
        )
    calls = []

    async def record(call):
        calls.append((call.domain, call.service, dict(call.data)))

    _set_up_test_entities(hass)
    hass.states.async_set("switch.living_room_schedule", "off")
    _entry, coordinator = await _setup_integration(hass)
    hass.services.async_register("switch", "turn_on", record)
    hass.services.async_register("switch", "turn_off", record)
    hass.services.async_register("text", "set_value", record)
    coordinator.enabled = True
    coordinator.config["valve_fallback"] = True
    await coordinator.async_arm_valve_fallback()
    assert ("switch", "turn_on", {"entity_id": "switch.living_room_schedule"}) in calls
    assert any(
        domain == "text" and data["value"].startswith("mon,tue,wed,thu,fri,sat,sun|")
        for domain, _service, data in calls
    )
    assert coordinator._fallback_armed == ["switch.living_room_schedule"]
    calls.clear()
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    assert ("switch", "turn_off", {"entity_id": "switch.living_room_schedule"}) in calls
    assert coordinator._fallback_armed == []
