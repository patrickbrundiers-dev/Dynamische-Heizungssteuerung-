"""0.9.3: does heat reach the radiators, and when does the central heating deliver?"""

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)

from custom_components.dynamic_heating.model import (
    RoomModel,
    SampleCollector,
    seed_room_model,
)
from custom_components.dynamic_heating.radiator import (
    COLD,
    IDLE,
    SUPPLY_COLD,
    SUPPLY_IDLE,
    SUPPLY_PARTLY,
    SUPPLY_WAITING,
    SUPPLY_WARM,
    UNKNOWN,
    WAITING,
    WARM,
    RadiatorTracker,
    SupplyProfile,
    room_supply,
)


def test_radiator_that_stays_cold_for_an_hour_of_full_heat_is_cold():
    """Like 11.10. afternoon: valves open, housing stays at 21 °C, room 20 °C."""
    tracker = RadiatorTracker()
    assert tracker.observe(0, 100, 21.0, 20.0) == WAITING
    assert tracker.observe(1800, 100, 21.0, 20.0) == WAITING
    assert tracker.observe(3600, 100, 22.0, 20.0) == COLD
    # The central heating comes on: the housing climbs to 25 °C.
    assert tracker.observe(4000, 100, 23.0, 20.1) == WARM
    assert tracker.observe(4300, 100, 25.0, 20.2) == WARM


def test_radiator_judgement_needs_a_room_asking_for_full_heat():
    tracker = RadiatorTracker()
    # Barely below target: the valve hardly opens, lukewarm is fine.
    assert tracker.observe(0, 30, 21.0, 20.0) == IDLE
    assert tracker.observe(7200, 30, 21.0, 20.0) == IDLE
    # Full demand starts the clock; a short dip does not restart it.
    assert tracker.observe(7300, 100, 21.0, 20.0) == WAITING
    assert tracker.observe(9000, 40, 21.0, 20.0) == IDLE
    assert tracker.observe(11000, 100, 21.0, 20.0) == COLD
    # Heating stops: the clock ends.
    assert tracker.observe(11300, 0, 21.0, 20.0) == IDLE
    assert tracker.observe(11600, 100, 21.0, 20.0) == WAITING
    assert tracker.observe(11900, 100, None, 20.0) == UNKNOWN


def test_room_verdict_from_its_radiators():
    assert room_supply({}) is None
    assert room_supply({"a": UNKNOWN}) is None
    assert room_supply({"a": COLD, "b": COLD, "c": UNKNOWN}) == SUPPLY_COLD
    assert room_supply({"a": COLD, "b": WARM}) == SUPPLY_PARTLY
    assert room_supply({"a": WARM, "b": WAITING}) == SUPPLY_WARM
    assert room_supply({"a": WAITING, "b": IDLE}) == SUPPLY_WAITING
    assert room_supply({"a": IDLE}) == SUPPLY_IDLE


def test_supply_profile_learns_when_the_central_heating_is_off():
    profile = SupplyProfile()
    for _day in range(3):
        for hour in range(24):
            supply = SUPPLY_COLD if hour < 6 else SUPPLY_WARM
            for _step in range(12):
                profile.observe(hour, supply, 300)
    profile.observe(0, None, 300)
    assert profile.usually_off(5)
    assert not profile.usually_off(6)
    assert profile.off_hours() == [0, 1, 2, 3, 4, 5]
    assert profile.next_on_hour(3) == 6
    # Hours without a judgement leave the slot alone.
    for _step in range(12):
        profile.observe(7, SUPPLY_IDLE, 300)
    profile.observe(8, None, 300)
    assert profile.slots[7] == 1.0
    restored = SupplyProfile.from_list(profile.as_list())
    assert restored.off_hours() == profile.off_hours()
    assert SupplyProfile.from_list("kaputt").off_hours() == []


def test_hour_with_cold_radiators_teaches_the_model_nothing():
    collector = SampleCollector()

    def hour(start, room_from, room_to, demand, cold_at=None):
        sample = None
        for step in range(7):
            at = start + step * 600
            room = room_from + (room_to - room_from) * step / 6
            sample = collector.observe(
                at, room, demand, 10.0, 0.0, 0.0, at == cold_at
            )
        return sample

    assert hour(0, 20.0, 20.0, 1.0, cold_at=1800) is None
    # The next hour has heat again and is learned.
    sample = hour(3600, 20.0, 20.6, 1.0)
    assert sample is not None
    assert sample[0] == pytest.approx(0.6)
    # Without heat demand a cold radiator is normal and the hour counts.
    assert hour(7200, 20.6, 20.4, 0.0, cold_at=9000) is not None


def _history_with_cold_central_heating(days=3):
    """Heat asked for 6-20 h; the central heating only delivers from 14 h."""
    room = 19.0
    states = {
        "sensor.room": [],
        "sensor.outdoor": [(0.0, "10.0")],
        "sensor.demand": [],
        "sensor.valve": [],
    }
    for step in range(days * 24 * 12):
        at = step * 300.0
        hour = (step // 12) % 24
        demand = 100.0 if 6 <= hour < 20 else 0.0
        delivered = demand if hour >= 14 else 0.0
        rate = 0.6 * delivered / 100 - 0.02 * (room - 10.0)
        room += rate / 12
        states["sensor.room"].append((at, f"{room:.2f}"))
        states["sensor.demand"].append((at, str(demand)))
        states["sensor.valve"].append((at, f"{room + (6.0 if delivered else 1.0):.0f}"))
    return states


def _seed(states, radiators):
    model = RoomModel()
    added = seed_room_model(
        model,
        states,
        room_id="sensor.room",
        outdoor_id="sensor.outdoor",
        demand_id="sensor.demand",
        window_ids=[],
        solar_id=None,
        wind_id=None,
        units={},
        start=0.0,
        end=3 * 24 * 3600.0,
        radiator_ids=radiators,
    )
    return model, added


def test_seed_skips_hours_in_which_the_central_heating_did_not_deliver():
    states = _history_with_cold_central_heating()
    blind, blind_added = _seed(states, [])
    model, added = _seed(states, ["sensor.valve"])
    assert added < blind_added
    assert model.ready
    # Without the radiators the cold mornings drag the heat output down.
    assert blind.parameters()[0] < 0.45
    assert model.parameters()[0] == pytest.approx(0.6, abs=0.12)


def _add_valve(hass, device_temperature):
    trv_entry = MockConfigEntry(domain="mqtt")
    trv_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=trv_entry.entry_id, identifiers={("mqtt", "trv_1")}
    )
    registry = er.async_get(hass)
    for domain, unique_id, object_id in (
        ("climate", "trv_1_climate", "living_room_trv"),
        ("sensor", "trv_1_device_temperature", "living_room_trv_device_temperature"),
    ):
        registry.async_get_or_create(
            domain,
            "mqtt",
            unique_id,
            suggested_object_id=object_id,
            device_id=device.id,
            config_entry=trv_entry,
        )
    hass.states.async_set(
        "climate.living_room_trv",
        "heat",
        {"temperature": 18.0, "min_temp": 5, "max_temp": 30, "friendly_name": "Sofa"},
    )
    hass.states.async_set(
        "sensor.living_room_trv_device_temperature", str(device_temperature)
    )


@pytest.mark.asyncio
async def test_room_reports_cold_radiators_and_learns_the_hours(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass, room_temperature="17.0")
    _add_valve(hass, 18)
    entry, coordinator = await _setup_integration(hass)
    coordinator.config["climate_entity"] = "climate.living_room_trv"
    coordinator.config["comfort_temperature"] = 21.0
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        coordinator.quick_mode = "comfort"
        await coordinator.async_refresh()
        assert coordinator.data["heat_demand"] == 100
        assert coordinator.data["radiator_status"] == "Werden warm"

        # An hour later the radiator is still cold.
        tracker = coordinator._radiators["climate.living_room_trv"]
        tracker.heating_since -= 3700
        await coordinator.async_refresh()
        data = coordinator.data
        assert data["radiator_supply"] == SUPPLY_COLD
        assert data["radiator_status"].startswith("Kalt – die Zentralheizung")
        assert data["status"].endswith("Heizkörper bleiben kalt")
        assert data["radiators"] == {"Sofa": COLD}

        # The central heating comes on.
        hass.states.async_set("sensor.living_room_trv_device_temperature", "24")
        await coordinator.async_refresh()
        assert coordinator.data["radiator_status"] == "Warm"

    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.test_wohnzimmer_heizkorper") or next(
        state
        for state in hass.states.async_all("sensor")
        if state.attributes.get("friendly_name", "").endswith("Heizkörper")
    )
    assert sensor.state == "Warm"
    assert sensor.attributes["radiators"] == {"Sofa": WARM}


@pytest.mark.asyncio
async def test_cold_radiators_at_their_usual_off_time_send_no_alarm(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    entry, coordinator = await _setup_integration(hass)
    result = {
        "heating_problem": True,
        "heating_problem_detail": "17,0 statt 21,0 °C",
        "radiator_supply": SUPPLY_COLD,
        "supply_usually_off": False,
    }
    message = coordinator._alert_conditions(result)["heating"][1]
    assert "Heizkörper bleiben kalt" in message
    assert "Zentralheizung" in message
    result["supply_usually_off"] = True
    assert "heating" not in coordinator._alert_conditions(result)
    # At its usual off time a partly cold room says nothing about a radiator.
    result.update(radiator_supply=SUPPLY_PARTLY, radiator_status="Sofa bleibt kalt")
    assert "radiator" not in coordinator._alert_conditions(result)
    result["supply_usually_off"] = False
    conditions = coordinator._alert_conditions(result)
    assert "Sofa bleibt kalt" in conditions["radiator"][1]
    assert "Ventile und Heizung" in conditions["heating"][1]


@pytest.mark.asyncio
async def test_model_learned_with_the_old_rule_is_learned_again(
    hass, enable_custom_integrations
):
    _set_up_test_entities(hass)
    entry, coordinator = await _setup_integration(hass)
    coordinator.room_model.samples = 30
    coordinator._model_seeded = True
    coordinator.supply.slots[3] = 0.0
    await coordinator._save_learning()
    await coordinator.async_load_learning()
    # Same version: kept.
    assert coordinator.room_model.samples == 30
    stored = await coordinator._store.async_load()
    assert stored["room_model_version"] == 2
    assert stored["supply_profile"][3] == 0.0

    # Written by 0.9.2 (no version): the model starts over, the rest stays.
    stored.pop("room_model_version")
    await coordinator._store.async_save(stored)
    await coordinator.async_load_learning()
    assert coordinator.room_model.samples == 0
    assert not coordinator._model_seeded
    assert coordinator.supply.usually_off(3)


def test_week_summary_names_saving_and_cold_hours():
    from custom_components.dynamic_heating.coordinator import (
        DynamicHeatingCoordinator,
    )
    from custom_components.dynamic_heating.routine import HeatStats

    class Room:
        room_name = "Wohnzimmer"
        room_model = RoomModel()
        config = {}
        heat_stats = HeatStats()
        _week = {
            **DynamicHeatingCoordinator._empty_week(),
            "heating_s": 36000.0,
            "temperature_sum": 20.0 * 36000,
            "temperature_s": 36000.0,
            "no_heat_s": 7200.0,
            "loss_actual": 8.0 * 36000,
            "loss_comfort": 10.0 * 36000,
        }

    text = DynamicHeatingCoordinator.week_summary(Room())
    assert "ca. 20% weniger Wärme als bei Dauer-Komfort" in text
    assert "2 h Heizkörper kalt trotz Heizbedarf" in text
    assert "Raummodell lernt noch (0 h)" in text
