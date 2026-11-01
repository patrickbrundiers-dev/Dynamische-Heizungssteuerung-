"""Unusual heat loss of a room, judged against its room model (0.18.0).

Pure Python without Home Assistant imports, like ``model``.

Idea from Heating Analytics ("deviation"): the room model knows how fast a
room cools without heat and warms with full heat at today's weather. A room
that over two hours loses far more than that, with every window contact
closed, probably has a tilted window, an open door or the like; one that
barely warms with the valves open probably has a cold radiator.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import (
    UNUSUAL_HEAT_SHARE,
    UNUSUAL_LOSS_FACTOR,
    UNUSUAL_LOSS_MARGIN,
    UNUSUAL_MIN_DROP,
    UNUSUAL_MIN_RISE,
    UNUSUAL_STRETCH_SECONDS,
)
from .model import ModelView

LOSS = "loss"
HEAT = "heat"
# A stretch counts as "heating" from this demand (0..1), as "no heat" up to
# this one.
HEAT_DEMAND = 0.8
IDLE_DEMAND = 0.1


@dataclass(slots=True)
class Finding:
    """One unusual stretch: what, observed and expected change in °C."""

    kind: str
    observed: float
    expected: float
    started_at: float


@dataclass(slots=True)
class HeatLossWatch:
    """Follows stretches without heat and with full heat (runtime only)."""

    kind: str | None = None
    started_at: float | None = None
    start_temperature: float | None = None
    # Local day (ISO) of the last finding per kind, for one push a day.
    told: dict[str, str] | None = None
    last: Finding | None = None

    def reset(self) -> None:
        self.kind = None
        self.started_at = None
        self.start_temperature = None

    def observe(
        self,
        at: float,
        room: float | None,
        demand: float | None,
        usable: bool,
        view: ModelView | None,
    ) -> Finding | None:
        """Feed one cycle; a finding once a stretch turns out unusual.

        ``demand`` is 0..1, ``usable`` False while a window is open, the
        radiators are known cold, the room is in a special mode, etc.
        ``view`` must carry the weather of the stretch (trusted model).
        """
        if not usable or room is None or demand is None or view is None:
            self.reset()
            return None
        kind = HEAT if demand >= HEAT_DEMAND else LOSS if demand <= IDLE_DEMAND else None
        if kind is None:
            self.reset()
            return None
        if kind != self.kind or self.started_at is None or self.start_temperature is None:
            self.kind = kind
            self.started_at = at
            self.start_temperature = room
            return None
        seconds = at - self.started_at
        if seconds < UNUSUAL_STRETCH_SECONDS:
            return None
        hours = seconds / 3600
        start = self.start_temperature
        finding = None
        if kind == LOSS:
            observed = start - room
            expected = max(0.0, start - view.temperature_after(start, hours, 0.0))
            if observed >= UNUSUAL_MIN_DROP and observed >= max(
                expected * UNUSUAL_LOSS_FACTOR, expected + UNUSUAL_LOSS_MARGIN
            ):
                finding = Finding(LOSS, round(observed, 1), round(expected, 1), self.started_at)
        else:
            observed = room - start
            expected = view.temperature_after(start, hours, 1.0) - start
            if expected >= UNUSUAL_MIN_RISE and observed < expected * UNUSUAL_HEAT_SHARE:
                finding = Finding(HEAT, round(observed, 1), round(expected, 1), self.started_at)
        # The next stretch starts here, either way.
        self.started_at = at
        self.start_temperature = room
        if finding is not None:
            self.last = finding
        return finding

    def first_today(self, kind: str, day: str) -> bool:
        """True (and remembered) the first time ``kind`` is told on ``day``."""
        told = self.told if self.told is not None else {}
        if told.get(kind) == day:
            return False
        told[kind] = day
        self.told = told
        return True
