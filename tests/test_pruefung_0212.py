"""0.21.2: a setback floor is rounded up to the thermostat step, never down."""

from homeassistant.core import State

from custom_components.dynamic_heating.coordinator import (
    DynamicHeatingCoordinator,
)


def _tuya(step: float = 1.0) -> State:
    return State(
        "climate.bad_v",
        "heat",
        {"min_temp": 5, "max_temp": 35, "target_temp_step": step},
    )


def test_normal_targets_round_to_nearest_step():
    fit = DynamicHeatingCoordinator._fit_to_thermostat
    assert fit(21.3, _tuya()) == 21
    assert fit(21.6, _tuya()) == 22
    assert fit(20.2, _tuya(0.5)) == 20.0


def test_floor_targets_round_up():
    # 22.11.: Bad eco "nur bis 21,3 °C abgesenkt" was held at 21 °C.
    fit = DynamicHeatingCoordinator._fit_to_thermostat
    assert fit(21.3, _tuya(), round_up=True) == 22
    assert fit(21.0, _tuya(), round_up=True) == 21
    assert fit(19.1, _tuya(0.5), round_up=True) == 19.5
    assert fit(19.0, _tuya(0.5), round_up=True) == 19.0
    # Still clamped to the thermostat limits.
    assert fit(35.2, _tuya(), round_up=True) == 35
