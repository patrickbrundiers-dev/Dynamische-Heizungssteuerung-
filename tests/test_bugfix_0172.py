"""0.17.2: rooms that only hold their temperature tell the house the boiler delivers."""

from custom_components.dynamic_heating.radiator import (
    IDLE,
    SUPPLY_IDLE,
    SUPPLY_WARM,
    WARM,
    RadiatorTracker,
    SupplyProfile,
    house_supply,
    judged_supply,
    room_supply,
)


def _judged(trackers: dict[str, RadiatorTracker], states: dict[str, str]) -> str | None:
    """Like the room coordinator: the room's verdict as evidence for the house."""
    return judged_supply(
        room_supply(states), any(tracker.asking for tracker in trackers.values())
    )


def test_holding_room_with_radiator_warming_up_counts_as_delivery():
    # 29.10. 20:35: Wohnzimmer holds with 10-18 % demand, radiator warm.
    tracker = RadiatorTracker()
    state = tracker.observe(0, 15, 23.0, 21.0)
    assert state == IDLE
    assert not tracker.asking
    state = tracker.observe(600, 15, 26.0, 21.0)
    assert state == WARM
    assert tracker.asking
    assert _judged({"a": tracker}, {"a": state}) == SUPPLY_WARM
    assert house_supply([_judged({"a": tracker}, {"a": state})]) == SUPPLY_WARM
    # Never cold while only holding: a lukewarm radiator is by design.
    for at in range(900, 9000, 300):
        assert tracker.observe(at, 15, 22.0, 21.0) == IDLE


def test_after_restart_a_holding_room_is_seen_once_the_radiator_rises():
    # Fresh tracker (restart) with 30 % demand: below the 50 % start.
    tracker = RadiatorTracker()
    tracker.observe(0, 30, 27.0, 21.0)
    assert not tracker.asking  # the first reading may be old
    tracker.observe(300, 30, 28.0, 21.0)
    assert tracker.asking


def test_stale_warm_valve_while_holding_says_nothing():
    tracker = RadiatorTracker()
    for at in range(0, 7200, 300):
        state = tracker.observe(at, 20, 26.0, 20.0)
        assert state == WARM  # shown as warm, as before
        assert not tracker.asking
        assert _judged({"a": tracker}, {"a": state}) == SUPPLY_IDLE


def test_radiator_cooling_in_the_night_pause_is_not_delivery():
    # Restart at night: the radiator is still warm but cools down.
    tracker = RadiatorTracker()
    for at, device in enumerate((30.0, 29.6, 29.0, 28.1, 27.5, 26.0)):
        tracker.observe(at * 600, 20, device, 19.0)
        assert not tracker.asking
    # Holding since the evening: warm while delivering, then the pause.
    tracker = RadiatorTracker()
    tracker.observe(0, 20, 24.0, 20.0)
    tracker.observe(600, 20, 30.0, 20.0)
    assert tracker.asking
    tracker.observe(1200, 20, 29.0, 20.0)
    assert not tracker.asking
    tracker.observe(1800, 20, 27.5, 20.0)
    assert not tracker.asking


def test_hold_stretch_ends_without_demand_and_with_full_heat():
    tracker = RadiatorTracker()
    tracker.observe(0, 20, 22.0, 20.0)
    tracker.observe(300, 20, 25.0, 20.0)
    assert tracker.asking
    tracker.observe(600, 5, 25.0, 20.0)
    assert not tracker.asking
    assert tracker.hold_first is None
    # Full heat runs its own period, as before.
    tracker.observe(900, 80, 25.0, 20.0)
    assert tracker.heating_since == 900
    assert tracker.hold_first is None
    assert tracker.asking


def test_holding_evening_is_learned_as_delivery_hours():
    profile = SupplyProfile()
    tracker = RadiatorTracker()
    device = 22.0
    for step in range(0, 13):
        device = min(device + 1.0, 30.0)
        state = tracker.observe(step * 300, 15, device, 21.0)
        profile.observe(20 if step < 12 else 21, _judged({"a": tracker}, {"a": state}), 300)
    assert profile.slots[20] is not None and profile.slots[20] > 0.9
