"""Constants and small helpers shared by the room coordinator and its parts."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.core import Context, HomeAssistant, State



# Bumped when the room model must forget what it learned: 2 = 0.9.3, which
# no longer learns from hours in which the radiators stayed cold.
ROOM_MODEL_VERSION = 2
# Bumped when learning from the recorder improved: 1 = 0.9.4, which also
# learns rooms without recorded heat demand (estimated from valve setpoints);
# 2 = 0.9.7, which counts hours with warm radiators as heating hours. A model
# that is not ready yet starts over from the recorder (no hour twice).
SEED_VERSION = 2
# A room warming this much faster (°C/h) than the model's full heat shows the
# model is wrong for now: no "reachable today" from it.
REACH_TREND_MARGIN = 0.2
# The forecast's current error is carried this many hours ahead, fading out.
FORECAST_CORRECTION_HOURS = 12
# The self-test runs this long after a start, and again while it fails.
SELFTEST_DELAY = timedelta(minutes=10)
SELFTEST_RETRY = timedelta(hours=1)
# A valve fed with the room temperature should show it within this much.
SELFTEST_VALVE_TOLERANCE = 0.5
# The day plan is recalculated this often; the schedule's week read this often.
PLAN_INTERVAL = timedelta(minutes=15)
SCHEDULE_WEEK_INTERVAL = timedelta(minutes=30)
# Modes the day plan describes; in others it is not checked against the room.
_PLAN_MODES = frozenset({"comfort", "eco", "preheat", "early_stop"})

_LOGGER = logging.getLogger(f"{__package__}.coordinator")


@dataclass(slots=True)
class _WrittenSetpoint:
    """Last setpoint written successfully to one thermostat."""

    target: float
    at: datetime
    # True once the thermostat reported the value; only then can a different
    # setpoint be attributed to a manual change.
    confirmed: bool = False
_INVALID_STATES = {"unknown", "unavailable", None}
# Targets that the room offset leaves alone: protection and fixed setpoints.
# Modes that aim for comfort; the status tells when comfort is out of reach.
_REACH_MODES = frozenset(
    {"comfort", "preheat", "boost", "away_reduced", "homecoming"}
)
# Modes that warm the room up ahead of time (device trigger "preheat_started").
_PREHEAT_MODES = frozenset({"preheat", "homecoming"})
_NO_OFFSET_MODES = frozenset(
    {
        "season_off",
        "outdoor_warm",
        "maintenance",
        "window",
        "quick_off",
        "quick_manual",
        "long_absence",
        "house_vacation",
    }
)


def _as_float(state: State | None) -> float | None:
    """Read a numeric state without raising on unavailable or malformed input."""
    if state is None or state.state in _INVALID_STATES:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _as_number(value: object) -> float | None:
    """A finite number from an attribute value, else None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def foreign_source(hass: HomeAssistant, context: Context | None) -> tuple[str, str] | None:
    """The automation or script whose run made a service call, if any.

    An automation writes its state (last_triggered) with the context its
    actions then run in, so the call's context names it.
    """
    if context is None:
        return None
    ids = {context.id, context.parent_id} - {None}
    for state in hass.states.async_all(("automation", "script")):
        if state.context.id in ids:
            return state.entity_id, state.name
    return None


def _de_number(value: float) -> str:
    """A number with two decimals the German way (0,31)."""
    return f"{value:.2f}".replace(".", ",")


def _foreign_issue_id(entry_id: str, source_id: str) -> str:
    return f"foreign_control_{entry_id}_{source_id.replace('.', '_')}"
