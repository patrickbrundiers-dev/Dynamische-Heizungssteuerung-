"""Does heat reach the radiators? And when does the central heating deliver?

Pure Python without Home Assistant imports, like ``logic`` and ``model``.

Valves such as the Aqara E1 report the temperature of their own housing,
which sits on the radiator. A cold radiator keeps it near room temperature;
hot water lifts it by several degrees. Valves that are open for an hour
without that lift mean no heat arrives: the central heating is off or in
setback, or one radiator is airlocked or its valve stuck.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# A radiator counts as warm this far above the room ...
WARM_ABOVE_ROOM = 3.5
# ... or when it rose this much since heating started.
WARM_RISE = 2.0
# Heating this long without getting warm means no heat arrives.
COLD_AFTER_SECONDS = 3600
# The room asks for heat from this heat demand (%) and stops below the lower.
HEATING_START_DEMAND = 50
HEATING_STOP_DEMAND = 10

WARM = "warm"
COLD = "cold"
WAITING = "waiting"
IDLE = "idle"
UNKNOWN = "unknown"

# Room verdicts.
SUPPLY_WARM = "warm"
SUPPLY_COLD = "cold"
SUPPLY_PARTLY = "partly"
SUPPLY_WAITING = "waiting"
SUPPLY_IDLE = "idle"


@dataclass(slots=True)
class RadiatorTracker:
    """Follow one radiator through a heating period."""

    heating_since: float | None = None
    baseline: float | None = None

    def observe(
        self, at: float, demand: float | None, device: float | None, room: float | None
    ) -> str:
        """The radiator's state now (``at`` in seconds, ``demand`` in %)."""
        heating = heating_wanted(demand, self.heating_since is not None)
        if not heating:
            self.heating_since = None
            self.baseline = None
        elif self.heating_since is None:
            self.heating_since = at
            self.baseline = device
        elif self.baseline is None:
            self.baseline = device
        if device is None or room is None:
            return UNKNOWN
        if device >= room + WARM_ABOVE_ROOM or (
            self.baseline is not None and device - self.baseline >= WARM_RISE
        ):
            return WARM
        # Close to its target a valve barely opens and the radiator stays
        # lukewarm by design: only a room asking for full heat is judged.
        if self.heating_since is None or (demand or 0) < HEATING_START_DEMAND:
            return IDLE
        if at - self.heating_since < COLD_AFTER_SECONDS:
            return WAITING
        return COLD


def heating_wanted(demand: float | None, was_heating: bool) -> bool:
    """Whether the room asks for heat, with a little hysteresis."""
    if demand is None:
        return False
    if was_heating:
        return demand > HEATING_STOP_DEMAND
    return demand >= HEATING_START_DEMAND


def room_supply(states: dict[str, str]) -> str | None:
    """One verdict for the room from its radiators; None without data."""
    known = [state for state in states.values() if state != UNKNOWN]
    if not known:
        return None
    if all(state == COLD for state in known):
        return SUPPLY_COLD
    if COLD in known:
        return SUPPLY_PARTLY
    if WARM in known:
        return SUPPLY_WARM
    if WAITING in known:
        return SUPPLY_WAITING
    return SUPPLY_IDLE


SUPPLY_ALPHA = 0.3
SUPPLY_MIN_SECONDS = 1200
SUPPLY_OFF_BELOW = 0.3
SUPPLY_ON_FROM = 0.5


@dataclass(slots=True)
class SupplyProfile:
    """How often the central heating delivered, per hour of the day (0..1).

    Only time in which the room asked for heat long enough to judge counts.
    """

    slots: list[float | None] = field(default_factory=lambda: [None] * 24)
    current: int | None = None
    warm_seconds: float = 0.0
    judged_seconds: float = 0.0

    def observe(self, hour: int, supply: str | None, seconds: float) -> bool:
        """Add time to the running hour; True when an hour was finished."""
        finished = False
        if self.current != hour:
            finished = self._finish()
            self.current = hour
            self.warm_seconds = 0.0
            self.judged_seconds = 0.0
        seconds = max(0.0, min(seconds, 300.0))
        if supply in (SUPPLY_WARM, SUPPLY_PARTLY):
            self.warm_seconds += seconds
            self.judged_seconds += seconds
        elif supply == SUPPLY_COLD:
            self.judged_seconds += seconds
        return finished

    def _finish(self) -> bool:
        if self.current is None or self.judged_seconds < SUPPLY_MIN_SECONDS:
            return False
        share = self.warm_seconds / self.judged_seconds
        old = self.slots[self.current]
        self.slots[self.current] = round(
            share if old is None else (1 - SUPPLY_ALPHA) * old + SUPPLY_ALPHA * share,
            3,
        )
        return True

    def usually_off(self, hour: int) -> bool:
        value = self.slots[hour]
        return value is not None and value < SUPPLY_OFF_BELOW

    def off_hours(self) -> list[int]:
        return [hour for hour in range(24) if self.usually_off(hour)]

    def next_on_hour(self, hour: int) -> int | None:
        """The next hour (after ``hour``) in which it usually delivers."""
        for step in range(1, 24):
            candidate = (hour + step) % 24
            value = self.slots[candidate]
            if value is not None and value >= SUPPLY_ON_FROM:
                return candidate
        return None

    def as_list(self) -> list[float | None]:
        return list(self.slots)

    @classmethod
    def from_list(cls, data: object) -> SupplyProfile:
        profile = cls()
        if isinstance(data, list) and len(data) == 24:
            for hour, value in enumerate(data):
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and 0.0 <= value <= 1.0
                ):
                    profile.slots[hour] = float(value)
        return profile
