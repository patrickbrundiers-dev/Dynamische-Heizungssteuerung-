"""0.9.4: new rooms learn from history, one boiler for the house, day plan,
self-test, radiator balance and "Kurz wärmer"."""

from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_radiator_093 import _add_valve, _history_with_cold_central_heating

from custom_components.dynamic_heating.coordinator import SEED_VERSION
from custom_components.dynamic_heating.const import DOMAIN
from custom_components.dynamic_heating.model import (
    ModelView,
    RoomModel,
    estimate_demand,
    seed_room_model,
)
from custom_components.dynamic_heating.plan import (
    Block,
    blocks_from_schedule,
    simulate,
    summary,
    temperature_at,
)
from custom_components.dynamic_heating.radiator import (
    SUPPLY_COLD,
    SUPPLY_IDLE,
    SUPPLY_PARTLY,
    SUPPLY_WAITING,
    SUPPLY_WARM,
    HeatingPeriod,
    RadiatorStats,
    RadiatorTracker,
    SupplyProfile,
    balance_verdict,
    house_supply,
)

BERLIN = ZoneInfo("Europe/Berlin")


# 1 – a new room learns from the valves' history


def test_demand_is_estimated_from_valve_setpoints():
    assert estimate_demand([], 20.0, 2.0) is None
    assert estimate_demand([None, "unknown"], 20.0, 2.0) is None
    assert estimate_demand(["22", "off"], 20.0, 2.0) == pytest.approx(50.0)
    assert estimate_demand(["21"], 20.0, 2.0) == pytest.approx(50.0)
    assert estimate_demand(["18"], 20.0, 2.0) == pytest.approx(0.0)


def test_room_without_recorded_demand_learns_from_valve_setpoints():
    """Schlafzimmer: set up today, but the valve's setpoints go back a week."""
    states = _history_with_cold_central_heating()
    demand = states.pop("sensor.demand")
    states["setpoint:climate.valve"] = [
        (at, "28" if float(value) >= 50 else "off") for at, value in demand
    ]
    model = RoomModel()
    added = seed_room_model(
        model,
        states,
        room_id="sensor.room",
        outdoor_id="sensor.outdoor",
        demand_id="",
        window_ids=[],
        solar_id=None,
        wind_id=None,
        units={},
        start=0.0,
        end=3 * 24 * 3600.0,
        radiator_ids=["sensor.valve"],
        setpoint_ids=["setpoint:climate.valve"],
    )
    assert added >= 12
    assert model.ready
    assert model.parameters()[0] == pytest.approx(0.6, abs=0.15)


@pytest.mark.asyncio
async def test_room_learned_with_nothing_seeds_again(hass, enable_custom_integrations):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator._model_seeded = True
    coordinator._seed_version = 0
    await coordinator._save_learning()
    await coordinator.async_load_learning()
    assert coordinator._seed_version == 0
    hass.config.components.add("recorder")
    with patch(
        "homeassistant.components.recorder.get_instance",
    ) as instance:
        instance.return_value.async_add_executor_job = _executor(
            {"climate.living_room": []}
        )
        await coordinator.async_seed_model()
    assert coordinator._seed_version == SEED_VERSION
    stored = await coordinator._store.async_load()
    assert stored["seed_version"] == SEED_VERSION


def _executor(result):
    async def run(_function, *_args):
        return result

    return run


# 2 – one boiler for the house


def test_house_verdict_needs_only_one_warm_room():
    assert house_supply([]) is None
    assert house_supply([None, SUPPLY_COLD]) == SUPPLY_COLD
    assert house_supply([SUPPLY_COLD, SUPPLY_WARM]) == SUPPLY_WARM
    assert house_supply([SUPPLY_COLD, SUPPLY_PARTLY]) == SUPPLY_WARM
    assert house_supply([SUPPLY_IDLE, SUPPLY_WAITING]) == SUPPLY_WAITING
    assert house_supply([SUPPLY_IDLE]) == SUPPLY_IDLE


def test_house_profile_starts_from_what_a_room_learned():
    room = SupplyProfile()
    room.slots[3] = 0.0
    house = SupplyProfile()
    assert not house.known
    house.merge(room)
    assert house.known
    assert house.usually_off(3)
    house.slots[3] = 1.0
    house.merge(room)
    assert not house.usually_off(3)


async def _setup_house(hass, sent):
    async def capture(call):
        sent.append(call.data)

    hass.services.async_register("notify", "phone", capture)
    house_entry = MockConfigEntry(
        domain=DOMAIN, title="Haus", unique_id="house",
        data={"entry_type": "house"}, options={"notify_service": "notify.phone"},
    )
    house_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(house_entry.entry_id)
    await hass.async_block_till_done()
    return hass.data[DOMAIN]["house"]


@pytest.mark.asyncio
async def test_house_tells_once_when_the_boiler_delivers_nothing(
    hass, enable_custom_integrations
):
    sent: list = []
    _set_up_test_entities(hass, room_temperature="17.0")
    _add_valve(hass, 18)
    _, coordinator = await _setup_integration(hass)
    house = await _setup_house(hass, sent)
    coordinator.config["climate_entity"] = "climate.living_room_trv"
    coordinator.config["comfort_temperature"] = 21.0
    start = dt_util.utcnow()
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        coordinator.quick_mode = "comfort"
        await coordinator.async_refresh()
        coordinator._radiators["climate.living_room_trv"].heating_since -= 3700
        await coordinator.async_refresh()
    assert coordinator.data["radiator_supply"] == SUPPLY_COLD
    assert coordinator.data["house_supply"] == SUPPLY_COLD
    # The room leaves the boiler message to the house.
    result = dict(coordinator.data, heating_problem=True)
    assert "heating" not in coordinator._alert_conditions(result)

    for minutes in (0, 30, 61, 90):
        with patch(
            "custom_components.dynamic_heating.house.dt_util.utcnow",
            return_value=start + timedelta(minutes=minutes),
        ):
            await house._async_observe_supply()
    boiler = [item for item in sent if "Zentralheizung liefert keine" in item["message"]]
    assert len(boiler) == 1
    assert house.supply_text().startswith("Liefert keine Wärme")
    await hass.async_block_till_done()
    sensor = next(
        state for state in hass.states.async_all("sensor")
        if state.attributes.get("friendly_name", "").endswith("Zentralheizung")
    )
    assert sensor.attributes["delivers"] == SUPPLY_COLD

    # Back on: one all-clear.
    hass.states.async_set("sensor.living_room_trv_device_temperature", "25")
    with _capture_climate_calls(hass):
        await coordinator.async_refresh()
    with patch(
        "custom_components.dynamic_heating.house.dt_util.utcnow",
        return_value=start + timedelta(minutes=95),
    ):
        await house._async_observe_supply()
    assert sent[-1]["message"] == "Die Zentralheizung liefert wieder Wärme."


@pytest.mark.asyncio
async def test_cold_room_while_the_boiler_heats_elsewhere_names_the_room(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    result = {
        "heating_problem": True,
        "heating_problem_detail": None,
        "radiator_supply": SUPPLY_COLD,
        "house_supply": SUPPLY_WARM,
    }
    message = coordinator._alert_conditions(result)["heating"][1]
    assert "obwohl die Zentralheizung in anderen Räumen" in message
    text = coordinator._radiator_text({}, SUPPLY_COLD, 10, SUPPLY_WARM)
    assert text.startswith("Kalt, obwohl die Zentralheizung liefert")


# 3 – day plan


def _view(outdoor=8.0):
    return ModelView(2.0, 0.03, 0.0, 0.0, outdoor)


def test_blocks_are_read_from_the_schedule_week():
    now = datetime(2026, 10, 12, 20, 0, tzinfo=BERLIN)  # Monday
    weekly = {
        "monday": [{"from": "17:00:00", "to": "22:30:00"}],
        "tuesday": [
            {"from": "06:00:00", "to": "08:00:00", "data": {"temperature": 22}},
            {"from": "18:00:00", "to": "24:00:00"},
        ],
    }
    blocks = blocks_from_schedule(weekly, now, lambda value: float(value))
    assert [(b.start.hour, b.end.hour, b.temperature) for b in blocks] == [
        (17, 22, None),
        (6, 8, 22.0),
        (18, 0, None),
    ]
    assert blocks_from_schedule(None, now, float) == []


def test_plan_preheats_early_enough_and_names_the_times():
    now = datetime(2026, 10, 12, 23, 0, tzinfo=BERLIN)
    start = datetime(2026, 10, 13, 6, 30, tzinfo=BERLIN)
    blocks = [Block(start, start + timedelta(hours=2), None)]
    points = simulate(
        _view(),
        now=now,
        room=19.0,
        comfort=21.0,
        eco=18.0,
        blocks=blocks,
        outdoor_at=lambda _at: 8.0,
        supply_off=lambda _at: False,
        max_preheat_minutes=180,
    )
    first_preheat = next(point for point in points if point.preheat)
    assert first_preheat.at < start
    at_start = temperature_at(points, start)
    assert at_start == pytest.approx(21.0, abs=0.3)
    # The night cools the room from 19 towards the setback first.
    assert temperature_at(points, now + timedelta(hours=4)) < 19.0
    info = summary(points, blocks, now)
    assert info["text"].startswith("Morgen Vorheizen ab")
    assert "um 06:30 Uhr ca." in info["text"]
    assert info["comfort_start"] == start.isoformat()


def test_plan_knows_the_boiler_is_off_at_night():
    now = datetime(2026, 10, 13, 3, 0, tzinfo=BERLIN)
    start = datetime(2026, 10, 13, 6, 0, tzinfo=BERLIN)
    blocks = [Block(start, start + timedelta(hours=3), 21.0)]
    kwargs = dict(
        now=now, room=19.0, comfort=21.0, eco=18.0, blocks=blocks,
        outdoor_at=lambda _at: 8.0, max_preheat_minutes=180,
    )
    warm = simulate(_view(), supply_off=lambda _at: False, **kwargs)
    cold = simulate(_view(), supply_off=lambda at: at.hour < 6, **kwargs)
    assert temperature_at(cold, start) < temperature_at(warm, start) - 0.5


def test_plan_without_comfort_says_so():
    now = datetime(2026, 10, 12, 12, 0, tzinfo=BERLIN)
    points = simulate(
        _view(), now=now, room=20.0, comfort=21.0, eco=18.0, blocks=[],
        outdoor_at=lambda _at: 8.0, supply_off=lambda _at: False,
        max_preheat_minutes=120,
    )
    assert summary(points, [], now)["text"].startswith("Kein Komfort")


@pytest.mark.asyncio
async def test_room_publishes_its_day_plan_and_checks_it(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="19.0")
    _, coordinator = await _setup_integration(hass)
    await coordinator.async_refresh()
    assert coordinator.data["day_plan"] == "Regelung aus – kein Tagesplan"

    model = RoomModel()
    for hour in range(40):
        model.add(0.5 if hour % 2 else -0.3, 1.0 if hour % 2 else 0.0, 19.0, 5.0)
    coordinator.room_model = model
    now = dt_util.now()
    block = Block(now + timedelta(hours=2), now + timedelta(hours=4), None)
    with (
        _capture_climate_calls(hass),
        patch.object(coordinator, "_schedule_blocks", return_value=[block]),
    ):
        coordinator.enabled = True
        await coordinator.async_refresh()
    data = coordinator.data
    assert "Uhr" in data["day_plan"]
    attributes = coordinator.plan_attributes()
    assert attributes["forecast"]
    assert attributes["comfort_start"] == block.start.isoformat()

    # Three hours later the plan is compared with the room.
    checks = coordinator._plan_checks
    assert len(checks) == 1
    due = next(iter(checks))
    checks[due] = 20.5
    coordinator._check_plan(
        {"room_temperature": 19.0, "mode": "eco", "room_temperature_source": "sensor"},
        due + timedelta(minutes=5),
    )
    assert coordinator.plan_error == pytest.approx(1.5)
    assert coordinator.plan_checked == 1


@pytest.mark.asyncio
async def test_day_plan_follows_as_soon_as_the_temperatures_arrive(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="19.0")
    hass.states.async_set("sensor.outdoor_temperature", "unavailable")
    _, coordinator = await _setup_integration(hass)
    model = RoomModel()
    for hour in range(40):
        model.add(0.5 if hour % 2 else -0.3, 1.0 if hour % 2 else 0.0, 19.0, 5.0)
    coordinator.room_model = model
    now = dt_util.now()
    block = Block(now + timedelta(hours=2), now + timedelta(hours=4), None)
    with (
        _capture_climate_calls(hass),
        patch.object(coordinator, "_schedule_blocks", return_value=[block]),
    ):
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert coordinator.data["day_plan"] == (
            "Raum- oder Außentemperatur fehlt – kein Tagesplan"
        )
        hass.states.async_set("sensor.outdoor_temperature", "3.0")
        await coordinator.async_refresh()
    assert "Uhr" in coordinator.data["day_plan"]


# 4 – self-test


@pytest.mark.asyncio
async def test_self_test_reports_problems_under_repairs_and_clears_them(
    hass, enable_custom_integrations
):
    sent = []

    async def capture(call):
        sent.append(call.data)

    hass.services.async_register("notify", "phone", capture)
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["notify_service"] = "notify.phone"
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()
        assert coordinator.data["selftest"] == "Läuft 10 Minuten nach dem Start"

        hass.states.async_set("binary_sensor.living_room_window", "unavailable")
        hass.states.async_set("sensor.outdoor_temperature", "unavailable")
        await coordinator.async_run_selftest()
    names = {check["name"]: check["ok"] for check in coordinator.selftest["checks"]}
    assert names["Außentemperatur"] is False
    assert names["Raumfühler"] is True
    issue_id = f"selftest_{coordinator.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert any("Selbsttest nach dem Start" in item["message"] for item in sent)

    hass.states.async_set("binary_sensor.living_room_window", "off")
    hass.states.async_set("sensor.outdoor_temperature", "3.0")
    with _capture_climate_calls(hass):
        await coordinator.async_run_selftest()
    assert coordinator.data["selftest"] == "Alles in Ordnung"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert sent[-1]["message"] == "Selbsttest: wieder alles in Ordnung."


# 5 – radiator balance


def test_tracker_hands_out_a_heating_period_once():
    tracker = RadiatorTracker()
    tracker.observe(0, 100, 20.0, 19.0)
    tracker.observe(600, 100, 22.0, 19.0)
    tracker.observe(1200, 100, 24.0, 19.2)
    assert tracker.period is None
    tracker.observe(3000, 100, 25.0, 19.5)
    tracker.observe(3300, 0, 24.0, 19.6)
    assert tracker.period == HeatingPeriod(10.0, 5.0)
    tracker.observe(3600, 0, 23.0, 19.6)
    assert tracker.period is None
    # A short period says nothing.
    tracker.observe(4000, 100, 20.0, 19.0)
    tracker.observe(4600, 0, 22.0, 19.0)
    assert tracker.period is None
    # A long one is judged on its first hours, once.
    tracker.observe(5000, 100, 20.0, 19.0)
    tracker.observe(16000, 100, 21.0, 19.0)
    assert tracker.period == HeatingPeriod(None, 1.0)
    tracker.observe(16300, 100, 21.0, 19.0)
    assert tracker.period is None


def test_balance_names_the_radiator_that_lags_behind():
    def stats(rise, periods=3):
        item = RadiatorStats()
        for _ in range(periods):
            item.add(HeatingPeriod(30.0, rise))
        return item

    assert balance_verdict({}) == ("Keine Heizkörper mit Temperaturmessung", [])
    assert balance_verdict({"Sofa": stats(5)})[0].startswith("Nur ein Heizkörper")
    assert balance_verdict({"Sofa": stats(5), "Tisch": stats(5, 1)})[0] == (
        "Sammelt Daten (1 von 3 Heizphasen)"
    )
    assert balance_verdict({"Sofa": stats(5), "Tisch": stats(4)}) == (
        "Ausgeglichen", []
    )
    text, weak = balance_verdict(
        {"Sofa": stats(6), "Tisch": stats(5), "Wintergarten": stats(2)}
    )
    assert weak == ["Wintergarten"]
    assert text.startswith("Wintergarten wird nur 33 % so warm")
    restored = RadiatorStats.from_dict(stats(2).as_dict())
    assert restored.periods == 3 and restored.rise == 2.0


@pytest.mark.asyncio
async def test_room_learns_the_balance_only_while_the_boiler_delivers(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="17.0")
    _add_valve(hass, 18)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["climate_entity"] = "climate.living_room_trv"
    coordinator.config["comfort_temperature"] = 21.0
    tracker_id = "climate.living_room_trv"
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        coordinator.quick_mode = "comfort"
        await coordinator.async_refresh()
        tracker = coordinator._radiators[tracker_id]
        # A cold period (boiler off) teaches nothing.
        tracker.heating_since -= 3 * 3600 + 60
        await coordinator.async_refresh()
        assert coordinator.radiator_stats[tracker_id].periods == 0
        coordinator._radiators.clear()
        await coordinator.async_refresh()
        tracker = coordinator._radiators[tracker_id]
        hass.states.async_set("sensor.living_room_trv_device_temperature", "24")
        await coordinator.async_refresh()
        tracker.heating_since -= 3 * 3600 + 60
        await coordinator.async_refresh()
    assert coordinator.radiator_stats[tracker_id].periods == 1
    assert coordinator.data["radiator_balance"].startswith("Nur ein Heizkörper")


# 8 – Kurz wärmer


@pytest.mark.asyncio
async def test_warm_up_raises_for_an_hour_and_stacks(hass, enable_custom_integrations):
    _set_up_test_entities(hass, room_temperature="20.0")
    entry, coordinator = await _setup_integration(hass)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        coordinator.quick_mode = "comfort"
        await coordinator.async_refresh()
        base = coordinator.data["target_temperature"]
        await coordinator.async_warm_up()
        assert coordinator.quick_mode == "manual"
        assert coordinator.quick_temperature == pytest.approx(base + 1)
        left = coordinator.quick_until - dt_util.utcnow()
        assert timedelta(minutes=59) < left <= timedelta(hours=1)
        await coordinator.async_warm_up()
        await coordinator.async_warm_up()
        await coordinator.async_warm_up()
        assert coordinator.quick_temperature == pytest.approx(base + 3)
        assert coordinator.data["target_temperature"] == pytest.approx(base + 3)
        assert coordinator.last_change_source == "Kurz wärmer"


@pytest.mark.asyncio
async def test_day_plan_reads_a_real_schedule_helper(hass, enable_custom_integrations):
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(
        hass,
        "schedule",
        {
            "schedule": {
                "plan_test": {
                    "name": "Plan test",
                    **{
                        day: [
                            {"from": "06:00:00", "to": "08:00:00",
                             "data": {"temperature": 22}},
                            {"from": "18:00:00", "to": "24:00:00"},
                        ]
                        for day in (
                            "monday", "tuesday", "wednesday", "thursday",
                            "friday", "saturday", "sunday",
                        )
                    },
                }
            }
        },
    )
    await hass.async_block_till_done()
    _set_up_test_entities(hass)
    _, coordinator = await _setup_integration(hass)
    coordinator.config["schedule_entity"] = "schedule.plan_test"
    blocks = await coordinator._schedule_blocks(dt_util.utcnow())
    assert blocks
    assert {block.temperature for block in blocks} <= {22.0, None}
    assert any(block.temperature == 22.0 for block in blocks)
    assert all(block.end > block.start for block in blocks)
