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
# A heating period shorter than this says nothing about a radiator; one
# longer than this is judged on its first hours (later it is warm anyway).
PERIOD_MIN_SECONDS = 2700
PERIOD_MAX_SECONDS = 10800
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


@dataclass(frozen=True, slots=True)
class HeatingPeriod:
    """What one radiator did in one heating period, for the balance check."""

    # Minutes until the radiator counted as warm; None if it never did.
    warmup_minutes: float | None
    # Highest rise of the valve's own temperature above its start value.
    rise: float


@dataclass(slots=True)
class RadiatorTracker:
    """Follow one radiator through a heating period."""

    heating_since: float | None = None
    baseline: float | None = None
    warm_at: float | None = None
    peak: float | None = None
    reported: bool = False
    # A new reading arrived since heating started: a valve that reported
    # "warm" long ago (it reports rarely while idle) proves nothing before.
    fresh: bool = False
    # A period that just ended (or ran long enough), to be picked up once.
    period: HeatingPeriod | None = None

    def _report(self, at: float) -> None:
        """Hand out the running period once, if it was long enough."""
        if (
            self.reported
            or self.heating_since is None
            or at - self.heating_since < PERIOD_MIN_SECONDS
            or self.peak is None
        ):
            return
        self.period = HeatingPeriod(
            None
            if self.warm_at is None
            else round((self.warm_at - self.heating_since) / 60, 1),
            round(max(0.0, self.peak), 2),
        )
        self.reported = True

    def observe(
        self, at: float, demand: float | None, device: float | None, room: float | None
    ) -> str:
        """The radiator's state now (``at`` in seconds, ``demand`` in %)."""
        self.period = None
        heating = heating_wanted(demand, self.heating_since is not None)
        if not heating:
            self._report(at)
            self.heating_since = None
            self.baseline = None
            self.warm_at = None
            self.peak = None
            self.reported = False
            self.fresh = False
        elif self.heating_since is None:
            self.heating_since = at
            self.baseline = device
            self.fresh = False
        elif self.baseline is None:
            self.baseline = device
        if heating and device is not None and self.baseline is not None:
            if device != self.baseline:
                self.fresh = True
            rise = device - self.baseline
            self.peak = rise if self.peak is None else max(self.peak, rise)
        if heating and at - (self.heating_since or at) >= PERIOD_MAX_SECONDS:
            self._report(at)
        if device is None or room is None:
            return UNKNOWN
        if (device >= room + WARM_ABOVE_ROOM and (not heating or self.fresh)) or (
            self.baseline is not None and device - self.baseline >= WARM_RISE
        ):
            if heating and self.warm_at is None:
                self.warm_at = at
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


# --- Does the room answer the open valves? ----------------------------------

# Valves count as asking for real heat from this heat demand (%) on ...
RESPONSE_DEMAND = 50
# ... while the room is at least this far below its target.
RESPONSE_GAP = 0.5
# The room is judged over this long a stretch of asking for heat.
RESPONSE_SECONDS = 3600
# Warmer by this much over the stretch: heat arrives.
RESPONSE_WARM_RISE = 0.08
# Colder by at least this much: nothing arrives. A room that just holds its
# temperature may be at the limit of its radiators, so only cooling counts.
RESPONSE_COLD_RISE = -0.04


@dataclass(slots=True)
class RoomResponse:
    """Judge the heat supply by the room itself.

    The housing temperature of a valve rises only a little when the water is
    hot, and a valve near a warm wall or window can look warm all night. The
    room does not lie: an hour with the valves wide open in which it keeps
    cooling means no hot water arrives, whatever the valves say.
    """

    readings: list[tuple[float, float]] = field(default_factory=list)

    def observe(
        self,
        at: float,
        demand: float | None,
        room: float | None,
        target: float | None,
    ) -> str:
        """``WARM``, ``COLD``, ``WAITING`` (not judged yet) or ``IDLE``."""
        if (
            demand is None
            or room is None
            or target is None
            or demand < RESPONSE_DEMAND
            or target - room < RESPONSE_GAP
        ):
            self.readings = []
            return IDLE
        self.readings.append((at, room))
        cutoff = at - RESPONSE_SECONDS
        # Keep one reading at or before the start of the stretch.
        while len(self.readings) > 1 and self.readings[1][0] <= cutoff:
            self.readings.pop(0)
        start_at, start = self.readings[0]
        if at - start_at < RESPONSE_SECONDS - 60:
            return WAITING
        rise = room - start
        if rise >= RESPONSE_WARM_RISE:
            return WARM
        if rise <= RESPONSE_COLD_RISE:
            return COLD
        return WAITING


def judged_supply(supply: str | None, asking: bool) -> str | None:
    """The room's verdict as evidence about the central heating.

    Only a room asking for heat says something about the boiler: an idle
    room's valve may still read warm from hours ago.
    """
    if asking or supply is None:
        return supply
    return SUPPLY_IDLE


def combined_supply(radiators: str | None, response: str) -> str | None:
    """The room's verdict from its radiators and its own warming.

    A room that keeps cooling with the valves open gets no heat, even
    if a radiator looks warm. A room without radiator readings is judged by
    its warming alone.
    """
    if response == COLD:
        return SUPPLY_COLD
    if radiators is None:
        return {
            WARM: SUPPLY_WARM,
            WAITING: SUPPLY_WAITING,
            IDLE: None,
        }.get(response)
    return radiators


def house_supply(verdicts: list[str | None]) -> str | None:
    """One verdict for the central heating from all rooms' verdicts.

    One warm room is enough: the boiler delivers. Only when every room that
    asks for heat stays cold, the boiler is the cause.
    """
    known = [verdict for verdict in verdicts if verdict is not None]
    for verdict in (SUPPLY_WARM, SUPPLY_PARTLY):
        if verdict in known:
            return SUPPLY_WARM
    for verdict in (SUPPLY_COLD, SUPPLY_WAITING, SUPPLY_IDLE):
        if verdict in known:
            return verdict
    return None


SUPPLY_ALPHA = 0.3
# Raised when the way the profile is learned changes: older profiles are
# dropped. 2: the room's own warming counts (valve housings alone took a
# boiler pause at night for delivery). 3: only rooms asking for heat count,
# a warm reading from before heating started does not (idle valves showed
# the night pause as delivery).
SUPPLY_VERSION = 3
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

    @property
    def known(self) -> bool:
        return any(value is not None for value in self.slots)

    def merge(self, other: SupplyProfile) -> None:
        """Fill hours this profile does not know yet from another one."""
        for hour, value in enumerate(other.slots):
            if self.slots[hour] is None and value is not None:
                self.slots[hour] = value

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


BALANCE_ALPHA = 0.3
# Heating periods each radiator needs before radiators are compared.
BALANCE_MIN_PERIODS = 3
# A radiator below this share of the best one's rise is called out.
BALANCE_WEAK_SHARE = 0.6


@dataclass(slots=True)
class RadiatorStats:
    """Learned behaviour of one radiator over many heating periods."""

    periods: int = 0
    cold_periods: int = 0
    rise: float | None = None
    warmup_minutes: float | None = None

    def add(self, period: HeatingPeriod) -> None:
        self.periods += 1
        self.rise = round(
            period.rise
            if self.rise is None
            else (1 - BALANCE_ALPHA) * self.rise + BALANCE_ALPHA * period.rise,
            2,
        )
        if period.warmup_minutes is None:
            self.cold_periods += 1
            return
        self.warmup_minutes = round(
            period.warmup_minutes
            if self.warmup_minutes is None
            else (1 - BALANCE_ALPHA) * self.warmup_minutes
            + BALANCE_ALPHA * period.warmup_minutes,
            1,
        )

    def as_dict(self) -> dict:
        return {
            "periods": self.periods,
            "cold_periods": self.cold_periods,
            "rise": self.rise,
            "warmup_minutes": self.warmup_minutes,
        }

    @classmethod
    def from_dict(cls, data: object) -> RadiatorStats:
        stats = cls()
        if not isinstance(data, dict):
            return stats
        for key in ("periods", "cold_periods"):
            value = data.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                setattr(stats, key, value)
        for key in ("rise", "warmup_minutes"):
            value = data.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                setattr(stats, key, float(value))
        return stats


def balance_verdict(stats: dict[str, RadiatorStats]) -> tuple[str, list[str]]:
    """(short text, weak radiators) comparing the radiators of one room.

    Radiators of different size heat differently, so this only points at a
    radiator that clearly lags behind the best one of the same room.
    """
    if not stats:
        return "Keine Heizkörper mit Temperaturmessung", []
    if len(stats) < 2:
        return "Nur ein Heizkörper – kein Vergleich möglich", []
    missing = min(stats.values(), key=lambda item: item.periods)
    if missing.periods < BALANCE_MIN_PERIODS:
        return (
            f"Sammelt Daten ({missing.periods} von {BALANCE_MIN_PERIODS} "
            "Heizphasen)",
            [],
        )
    best = max(item.rise or 0.0 for item in stats.values())
    if best <= 0:
        return "Sammelt Daten (Heizkörper noch nicht warm geworden)", []
    weak = sorted(
        (
            ((item.rise or 0.0) / best, name)
            for name, item in stats.items()
            if (item.rise or 0.0) / best < BALANCE_WEAK_SHARE
        ),
    )
    if not weak:
        return "Ausgeglichen", []
    share, name = weak[0]
    text = (
        f"{name} wird nur {round(share * 100)} % so warm wie der beste "
        "Heizkörper – entlüften oder Voreinstellung am Ventilunterteil prüfen"
    )
    if len(weak) > 1:
        text += f" (auch {', '.join(item[1] for item in weak[1:])})"
    return text, [item[1] for item in weak]
