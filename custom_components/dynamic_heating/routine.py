"""Punctuality, habits and long-term heating statistics.

Pure Python without Home Assistant imports, like ``logic`` and ``model``.

- ``Punctuality`` checks every morning whether the room reached its comfort
  target when the comfort block began, and learns a preheat correction.
- ``Habits`` remembers modes picked by hand and finds the ones repeated at
  about the same time, as suggestions for the schedule.
- ``HeatStats`` adds up full-load heating hours and heating degree days, so
  months can be compared independent of the weather.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

# --- Punctuality --------------------------------------------------------------

# Within this of the target counts as warm.
PUNCTUAL_TOLERANCE = 0.2
# At most this late or early still counts as on time.
PUNCTUAL_MINUTES = 10
# A room not warm this long after the start is recorded with this lateness.
PUNCTUAL_GIVE_UP_MINUTES = 180
# Only the time spent preheating (at most this) is looked back on.
PUNCTUAL_LOOKBACK_MINUTES = 300
PUNCTUAL_DAYS = 7
# Share of each morning's error taken into the correction.
PUNCTUAL_GAIN = 0.5
BIAS_MIN = -30.0
BIAS_MAX = 60.0
# Raised when what is learned changes: older results and correction are
# dropped. 2: mornings without heat from the central heating do not count.
PUNCTUALITY_VERSION = 2
# Mornings kept with their weather for the correction from similar mornings.
PUNCTUAL_HISTORY = 40
# At least this many judged mornings (not given up) before similar mornings
# are asked; until then the running correction applies.
PUNCTUAL_SIMILAR_MIN = 5
# At most this many of the most similar mornings count.
PUNCTUAL_SIMILAR_COUNT = 25
# A morning's weight halves about every three weeks (e^-age/30).
PUNCTUAL_DECAY_DAYS = 30.0
# Similarity: this many degrees outdoors weigh like one degree of warming up.
PUNCTUAL_OUTDOOR_SCALE = 5.0
# Without an outdoor value on either side, that distance is assumed.
PUNCTUAL_OUTDOOR_UNKNOWN = 0.5
# Of the similar mornings' needed corrections, this share is covered
# (weighted median); more if mornings were often late lately.
PUNCTUAL_PERCENTILE = 50
PUNCTUAL_PERCENTILE_CAREFUL = 80
# Of the last mornings, more than this share late makes planning careful.
PUNCTUAL_LATE_SHARE = 0.2
PUNCTUAL_RECENT = 10
# A given-up morning only says "at least this much more" (+20 %), and only
# as long as it is not older than this and similar enough.
PUNCTUAL_PARTIAL_FACTOR = 1.2
PUNCTUAL_PARTIAL_DAYS = 30
PUNCTUAL_PARTIAL_DISTANCE = 1.5


@dataclass(frozen=True, slots=True)
class MorningSample:
    """One judged morning with the conditions it was preheated in."""

    day: str
    # Outdoor temperature at the comfort start (forecast), if known.
    outdoor: float | None
    # Degrees the room had to warm up when preheating began.
    gap: float
    # Correction (minutes) that would have made this morning punctual.
    needed: float
    # Still not warm when judging gave up: ``needed`` is a lower bound.
    partial: bool
    late: int


def _weighted_percentile(values: list[tuple[float, float]], percentile: float) -> float:
    """``values`` as (value, weight); the value below which ``percentile`` lies."""
    ordered = sorted(values)
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    limit = total * percentile / 100
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running >= limit - 1e-9:
            return value
    return ordered[-1][0]


@dataclass(frozen=True, slots=True)
class Morning:
    """How warm the room was when a watched comfort block began."""

    day: str
    start: datetime
    room: float
    target: float
    # The central heating delivered no heat at some time while preheating.
    supply_missing: bool


@dataclass(slots=True)
class Punctuality:
    """Learns how much earlier (or later) preheating should start."""

    bias_minutes: float = 0.0
    # Most recent mornings: (date ISO, minutes late; negative = early).
    results: list[tuple[str, int]] = field(default_factory=list)
    # The comfort start being watched and the readings before it.
    watch_start: datetime | None = None
    readings: list[tuple[datetime, float]] = field(default_factory=list)
    preheated: bool = False
    supply_missing: bool = False
    # The latest comfort start, set once when it begins (picked up by the
    # morning report).
    morning: Morning | None = None
    # Judged mornings with their weather (persisted).
    history: list[MorningSample] = field(default_factory=list)
    # Conditions when preheating for the watched start began.
    context_outdoor: float | None = None
    context_gap: float | None = None
    context_bias: float = 0.0

    def observe(
        self,
        now: datetime,
        *,
        room: float | None,
        mode: str | None,
        next_event: datetime | None,
        target: float | None,
        supply_cold: bool = False,
        outdoor: float | None = None,
        bias: float | None = None,
    ) -> int | None:
        """Feed one cycle; returns the lateness when a morning was judged.

        ``mode`` is the control mode, ``next_event`` the next comfort start,
        ``target`` the current target. Mornings without preheating, with a
        window open or nobody home at the start are not judged. Neither are
        mornings on which the central heating delivered no heat while
        preheating (``supply_cold``): preheating earlier would not have
        helped, so nothing is learned from them. ``outdoor`` (at the comfort
        start) and ``bias`` (the correction in use) are kept with the morning
        so later mornings in similar weather can learn from it.
        """
        if room is None:
            return None
        if mode == "preheat" and next_event is not None and next_event > now:
            if self.watch_start != next_event:
                self.watch_start = next_event
                self.readings = []
                self.context_gap = (
                    None if target is None else max(0.0, float(target) - float(room))
                )
                self.context_outdoor = outdoor
                self.context_bias = self.bias_minutes if bias is None else float(bias)
            self.preheated = True
            if supply_cold:
                self.supply_missing = True
            if not self.readings or now - self.readings[-1][0] >= timedelta(minutes=1):
                self.readings.append((now, room))
            cutoff = now - timedelta(minutes=PUNCTUAL_LOOKBACK_MINUTES)
            self.readings = [item for item in self.readings if item[0] >= cutoff]
            return None
        start = self.watch_start
        if start is None or now < start:
            if start is not None and mode not in ("preheat", "eco"):
                # Something else took over before the start (window, away).
                self._reset()
            return None
        if mode != "comfort" or target is None or not self.preheated:
            self._reset()
            return None
        if supply_cold and now - start < timedelta(minutes=PUNCTUAL_GIVE_UP_MINUTES):
            self.supply_missing = True
        if self.morning is None or self.morning.start != start:
            self.morning = Morning(
                start.date().isoformat(),
                start,
                float(room),
                float(target),
                self.supply_missing,
            )
        goal = target - PUNCTUAL_TOLERANCE
        early = next((at for at, value in self.readings if value >= goal), None)
        late: int | None = None
        if early is not None:
            late = -round((start - early).total_seconds() / 60)
        elif room >= goal:
            late = round((now - start).total_seconds() / 60)
        elif now - start >= timedelta(minutes=PUNCTUAL_GIVE_UP_MINUTES):
            late = PUNCTUAL_GIVE_UP_MINUTES
        if late is None:
            return None
        if self.supply_missing and late > PUNCTUAL_MINUTES:
            # Late because there was no heat: not a lesson for preheating.
            self._reset()
            return None
        self._record(start.date(), late)
        self._remember(start.date(), late)
        self._reset()
        return late

    def _reset(self) -> None:
        self.watch_start = None
        self.readings = []
        self.preheated = False
        self.supply_missing = False
        self.context_gap = None
        self.context_outdoor = None
        self.context_bias = 0.0

    def _remember(self, day: date, late: int) -> None:
        """Keep the morning with its weather for similar mornings later."""
        if self.context_gap is None:
            return
        partial = late >= PUNCTUAL_GIVE_UP_MINUTES
        if partial:
            needed = self.context_bias + late * PUNCTUAL_PARTIAL_FACTOR
        else:
            needed = self.context_bias + _error(late)
        self.history = [item for item in self.history if item.day != day.isoformat()]
        self.history.append(
            MorningSample(
                day.isoformat(),
                None if self.context_outdoor is None else round(self.context_outdoor, 1),
                round(self.context_gap, 2),
                round(needed, 1),
                partial,
                late,
            )
        )
        self.history = self.history[-PUNCTUAL_HISTORY:]

    def bias_for(
        self,
        outdoor: float | None,
        gap: float | None,
        today: date | None = None,
    ) -> float:
        """The correction for a morning like this one (outdoor, degrees to go).

        From the most similar earlier mornings (fresh ones weigh more), the
        correction that would have made them punctual: their weighted median,
        or a careful 80 % when several of the last mornings were late. A
        morning that was never warm in time is a lower bound. Until enough
        mornings are known, the running correction applies.
        """
        complete = [item for item in self.history if not item.partial]
        if gap is None or len(complete) < PUNCTUAL_SIMILAR_MIN:
            return self.bias_minutes
        today = today or date.today()

        def age(item: MorningSample) -> float:
            try:
                return max(0, (today - date.fromisoformat(item.day)).days)
            except ValueError:
                return PUNCTUAL_DECAY_DAYS * 3

        def distance(item: MorningSample) -> float:
            value = abs(float(gap) - item.gap)
            if outdoor is None or item.outdoor is None:
                return value + PUNCTUAL_OUTDOOR_UNKNOWN
            return value + abs(float(outdoor) - item.outdoor) / PUNCTUAL_OUTDOOR_SCALE

        nearest = sorted(complete, key=distance)[:PUNCTUAL_SIMILAR_COUNT]
        weighted = [
            (
                item.needed,
                math.exp(-age(item) / PUNCTUAL_DECAY_DAYS) * math.exp(-distance(item)),
            )
            for item in nearest
        ]
        recent = self.history[-PUNCTUAL_RECENT:]
        late_share = sum(1 for item in recent if item.late > PUNCTUAL_MINUTES) / len(
            recent
        )
        percentile = (
            PUNCTUAL_PERCENTILE_CAREFUL
            if late_share > PUNCTUAL_LATE_SHARE
            else PUNCTUAL_PERCENTILE
        )
        value = _weighted_percentile(weighted, percentile)
        for item in self.history:
            if (
                item.partial
                and age(item) <= PUNCTUAL_PARTIAL_DAYS
                and distance(item) <= PUNCTUAL_PARTIAL_DISTANCE
            ):
                value = max(value, item.needed)
        return round(max(BIAS_MIN, min(BIAS_MAX, value)), 1)

    def similar_ready(self) -> bool:
        """True once the correction comes from similar mornings."""
        return sum(1 for item in self.history if not item.partial) >= PUNCTUAL_SIMILAR_MIN

    def _record(self, day: date, late: int) -> None:
        self.results = [item for item in self.results if item[0] != day.isoformat()]
        self.results.append((day.isoformat(), late))
        self.results = self.results[-PUNCTUAL_DAYS:]
        self.bias_minutes = round(
            max(
                BIAS_MIN,
                min(BIAS_MAX, self.bias_minutes + PUNCTUAL_GAIN * _error(late)),
            ),
            1,
        )

    def summary(self) -> str:
        if not self.results:
            return "Noch kein Morgen mit Vorheizen ausgewertet"
        on_time = sum(1 for _, late in self.results if abs(late) <= PUNCTUAL_MINUTES)
        late_values = [late for _, late in self.results if late > PUNCTUAL_MINUTES]
        text = f"{on_time} von {len(self.results)} Tagen pünktlich"
        if late_values:
            text += (
                f", wenn zu spät im Schnitt {round(sum(late_values) / len(late_values))}"
                " Minuten"
            )
        return text

    def as_dict(self) -> dict:
        return {
            "version": PUNCTUALITY_VERSION,
            "bias_minutes": self.bias_minutes,
            "results": [list(item) for item in self.results],
            "history": [
                [item.day, item.outdoor, item.gap, item.needed, item.partial, item.late]
                for item in self.history
            ],
        }

    @classmethod
    def from_dict(cls, data: object) -> Punctuality:
        result = cls()
        if not isinstance(data, dict) or data.get("version") != PUNCTUALITY_VERSION:
            return result
        bias = data.get("bias_minutes")
        if isinstance(bias, (int, float)) and math.isfinite(bias):
            result.bias_minutes = max(BIAS_MIN, min(BIAS_MAX, float(bias)))
        for item in data.get("results") or []:
            if (
                isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], int)
            ):
                result.results.append((item[0], item[1]))
        result.results = result.results[-PUNCTUAL_DAYS:]
        for item in data.get("history") or []:
            if not isinstance(item, list) or len(item) != 6:
                continue
            day, outdoor, gap, needed, partial, late = item
            if (
                not isinstance(day, str)
                or not (outdoor is None or isinstance(outdoor, (int, float)))
                or not isinstance(gap, (int, float))
                or not isinstance(needed, (int, float))
                or not math.isfinite(gap)
                or not math.isfinite(needed)
                or not isinstance(late, int)
            ):
                continue
            result.history.append(
                MorningSample(
                    day,
                    None if outdoor is None else float(outdoor),
                    float(gap),
                    float(needed),
                    bool(partial),
                    late,
                )
            )
        result.history = result.history[-PUNCTUAL_HISTORY:]
        return result


def _error(late: int) -> float:
    """Minutes a morning's start should have moved (0 within the tolerance)."""
    if late > PUNCTUAL_MINUTES:
        return float(late)
    if late < -PUNCTUAL_MINUTES:
        return float(late + PUNCTUAL_MINUTES)
    return 0.0


# --- Homecoming ---------------------------------------------------------------

# Only a return after at least this long away is a homecoming.
HOMECOMING_AWAY_MINUTES = 120
# Returns are looked for in this part of the day (local hours).
HOMECOMING_FROM_HOUR = 6
HOMECOMING_UNTIL_HOUR = 23
# Per weekday the latest this many returns, none older than this.
HOMECOMING_KEEP = 6
HOMECOMING_MAX_DAYS = 42
# At least this many returns within this of their median make a habit.
HOMECOMING_MIN = 3
HOMECOMING_SPREAD_MINUTES = 45
# Until a weekday has its own habit, workdays and weekend days are learned
# together: per weekday alone it takes weeks.
HOMECOMING_GROUPS = ((0, 1, 2, 3, 4), (5, 6))


@dataclass(slots=True)
class Homecoming:
    """Learns at what time somebody usually comes home on each weekday."""

    # Weekday (0 = Monday) -> [(date ISO, minute of the day)].
    arrivals: dict[int, list[tuple[str, int]]] = field(default_factory=dict)
    # Since when nobody is home (runtime only).
    away_since: datetime | None = None
    seen: bool = False

    def observe(self, now: datetime, home: bool) -> bool:
        """Feed whether anybody is home (``now`` local); True on a homecoming."""
        if not home:
            if self.away_since is None:
                # The first reading after a start is no departure.
                self.away_since = now if self.seen else None
            self.seen = True
            return False
        self.seen = True
        since, self.away_since = self.away_since, None
        if since is None:
            return False
        if now - since < timedelta(minutes=HOMECOMING_AWAY_MINUTES):
            return False
        if not HOMECOMING_FROM_HOUR <= now.hour < HOMECOMING_UNTIL_HOUR:
            return False
        self.record(now)
        return True

    def record(self, at: datetime) -> None:
        day = at.date().isoformat()
        items = [item for item in self.arrivals.get(at.weekday(), []) if item[0] != day]
        items.append((day, at.hour * 60 + at.minute))
        self.arrivals[at.weekday()] = sorted(items)[-HOMECOMING_KEEP:]

    def usual(self, weekday: int, today: date | None = None) -> int | None:
        """Usual minute of the day of coming home, None without a habit.

        The weekday's own returns decide once they make a habit; before
        that, those of all workdays (or both weekend days) together.
        """
        today = today or date.today()
        own = self._habit(self._minutes((weekday,), today))
        if own is not None:
            return own
        group = next(group for group in HOMECOMING_GROUPS if weekday in group)
        return self._habit(self._minutes(group, today))

    def _minutes(self, weekdays: tuple[int, ...], today: date) -> list[int]:
        minutes = []
        for weekday in weekdays:
            for day, minute in self.arrivals.get(weekday, []):
                try:
                    age = (today - date.fromisoformat(day)).days
                except ValueError:
                    continue
                if 0 <= age <= HOMECOMING_MAX_DAYS:
                    minutes.append(minute)
        return minutes

    @staticmethod
    def _habit(minutes: list[int]) -> int | None:
        if len(minutes) < HOMECOMING_MIN:
            return None
        minutes.sort()
        median = minutes[len(minutes) // 2]
        close = [
            minute for minute in minutes if abs(minute - median) <= HOMECOMING_SPREAD_MINUTES
        ]
        if len(close) < HOMECOMING_MIN:
            return None
        return close[len(close) // 2]

    def week(self, today: date | None = None) -> dict[str, str | None]:
        """Usual homecoming per weekday as "HH:MM" (None without a habit)."""
        names = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
        result: dict[str, str | None] = {}
        for weekday, name in enumerate(names):
            minute = self.usual(weekday, today)
            result[name] = None if minute is None else f"{minute // 60:02d}:{minute % 60:02d}"
        return result

    def count(self) -> int:
        return sum(len(items) for items in self.arrivals.values())

    def as_dict(self) -> dict:
        return {
            str(weekday): [list(item) for item in items]
            for weekday, items in self.arrivals.items()
        }

    @classmethod
    def from_dict(cls, data: object) -> Homecoming:
        result = cls()
        if not isinstance(data, dict):
            return result
        for key, items in data.items():
            try:
                weekday = int(key)
            except (TypeError, ValueError):
                continue
            if not 0 <= weekday <= 6 or not isinstance(items, list):
                continue
            kept = [
                (item[0], item[1])
                for item in items
                if isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], int)
                and 0 <= item[1] < 24 * 60
            ]
            if kept:
                result.arrivals[weekday] = sorted(kept)[-HOMECOMING_KEEP:]
        return result


def homecomings_from_history(
    changes: list[tuple[datetime, str, bool]], people: int
) -> Homecoming:
    """Learn from (local time, person, home) changes of the last weeks."""
    learner = Homecoming(seen=True)
    home: dict[str, bool] = {}
    for at, person, at_home in sorted(changes, key=lambda item: item[0]):
        home[person] = at_home
        if len(home) < people:
            continue
        learner.observe(at, any(home.values()))
    learner.away_since = None
    return learner


# --- Habits -------------------------------------------------------------------

HABIT_DAYS = 21
# Picked by hand on at least this many different days ...
HABIT_MIN_DAYS = 3
# ... within this many minutes of the same time of day.
HABIT_WINDOW_MINUTES = 45
HABIT_MAX_EVENTS = 200
_WEEKDAY_NAMES = (
    "Montags", "Dienstags", "Mittwochs", "Donnerstags", "Freitags",
    "Samstags", "Sonntags",
)


@dataclass(slots=True)
class Habits:
    """Modes picked by hand: (local time, mode key, label)."""

    events: list[tuple[datetime, str, str]] = field(default_factory=list)
    notified: list[str] = field(default_factory=list)

    def record(self, at: datetime, mode: str, label: str) -> None:
        cutoff = at - timedelta(days=HABIT_DAYS)
        self.events = [item for item in self.events if item[0] >= cutoff]
        self.events.append((at, mode, label))
        self.events = self.events[-HABIT_MAX_EVENTS:]

    def suggestions(
        self,
        now: datetime,
        describe: Callable[[str, str, str, int], str] | None = None,
    ) -> list[dict]:
        """Repeated hand picks, most frequent first.

        ``describe(when, clock, label, days)`` words a suggestion; the
        default is the one for modes picked by hand.
        """
        cutoff = now - timedelta(days=HABIT_DAYS)
        events = [item for item in self.events if item[0] >= cutoff]
        found: dict[str, dict] = {}
        for at, mode, label in events:
            weekend = at.weekday() >= 5
            minute = at.hour * 60 + at.minute
            near = [
                item for item in events
                if item[1] == mode
                and (item[0].weekday() >= 5) == weekend
                and abs(item[0].hour * 60 + item[0].minute - minute)
                <= HABIT_WINDOW_MINUTES
            ]
            days = {item[0].date() for item in near}
            if len(days) < HABIT_MIN_DAYS:
                continue
            minutes = sorted(item[0].hour * 60 + item[0].minute for item in near)
            median = minutes[len(minutes) // 2]
            rounded = int(round(median / 15) * 15) % (24 * 60)
            weekdays = {item[0].weekday() for item in near}
            if len(weekdays) == 1:
                when = _WEEKDAY_NAMES[next(iter(weekdays))]
            elif weekend:
                when = "Am Wochenende"
            else:
                when = "Montag bis Freitag"
            clock = f"{rounded // 60:02d}:{rounded % 60:02d}"
            key = f"{mode}|{'we' if weekend else 'wd'}|{clock}"
            if key in found or any(
                other["mode"] == mode and other["weekend"] == weekend
                and abs(other["minute"] - rounded) <= HABIT_WINDOW_MINUTES
                for other in found.values()
            ):
                continue
            found[key] = {
                "key": key,
                "mode": mode,
                "weekend": weekend,
                "minute": rounded,
                "count": len(days),
                "text": (
                    describe(when, clock, label, len(days))
                    if describe is not None
                    else f"{when} gegen {clock} Uhr „{label}“ "
                    f"({len(days)}× von Hand in {HABIT_DAYS // 7} Wochen) – "
                    "in den Zeitplan übernehmen?"
                ),
            }
        return sorted(found.values(), key=lambda item: -item["count"])

    def as_dict(self) -> dict:
        return {
            "events": [[at.isoformat(), mode, label] for at, mode, label in self.events],
            "notified": list(self.notified[-50:]),
        }

    @classmethod
    def from_dict(cls, data: object) -> Habits:
        result = cls()
        if not isinstance(data, dict):
            return result
        for item in data.get("events") or []:
            if isinstance(item, list) and len(item) == 3:
                try:
                    at = datetime.fromisoformat(str(item[0]))
                except ValueError:
                    continue
                if at.tzinfo is None:
                    continue
                result.events.append((at, str(item[1]), str(item[2])))
        result.notified = [str(item) for item in data.get("notified") or []][-50:]
        return result


# --- Showers -------------------------------------------------------------------


@dataclass
class ShowerWatch:
    """Showers in a bathroom, read from its humidity.

    A shower is a rise of ``rise`` points within ``window`` seconds (a
    bathroom's slow rise over hours is not); one per ``cooldown``.
    """

    rise: float
    window: float
    cooldown: float
    samples: list[tuple[float, float]] = field(default_factory=list)
    last: float | None = None

    def observe(self, at: float, humidity: float) -> bool:
        cutoff = at - self.window
        self.samples = [item for item in self.samples if item[0] >= cutoff]
        self.samples.append((at, humidity))
        if self.last is not None and at - self.last < self.cooldown:
            return False
        if humidity - min(value for _, value in self.samples) >= self.rise:
            self.last = at
            return True
        return False


def showers_from_history(
    watch: ShowerWatch,
    readings: list[tuple[float, float]],
    end: float,
    step: float = 60.0,
) -> list[float]:
    """Showers in recorded humidity changes, replayed minute by minute.

    The recorder keeps only changes; a value holds until the next one.
    """
    found: list[float] = []
    if not readings:
        return found
    readings = sorted(readings)
    index = 0
    value = readings[0][1]
    at = readings[0][0]
    while at <= end:
        while index < len(readings) and readings[index][0] <= at:
            value = readings[index][1]
            index += 1
        if watch.observe(at, value):
            found.append(at)
        at += step
    return found


_SCHEDULE_DAYS = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
)


def _minutes(value: object) -> int | None:
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    text = str(value or "")
    try:
        hour, minute = text.split(":")[:2]
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def schedule_covers(weekly: object, weekend: bool, minute: int) -> bool:
    """Is ``minute`` (of the day) comfort time on all such days of the week?"""
    if not isinstance(weekly, dict):
        return False
    days = _SCHEDULE_DAYS[5:] if weekend else _SCHEDULE_DAYS[:5]
    for day in days:
        covered = False
        for item in weekly.get(day) or []:
            if not isinstance(item, dict):
                continue
            begin = _minutes(item.get("from"))
            end = _minutes(item.get("to"))
            if begin is None or end is None:
                continue
            if end <= begin or item.get("to") == time.max:
                end = 24 * 60
            if begin <= minute < end:
                covered = True
                break
        if not covered:
            return False
    return True


# --- Statistics ---------------------------------------------------------------

# Heating degree days after VDI 3807: 20 °C indoors, heating below 15 °C.
DEGREE_INDOOR = 20.0
DEGREE_LIMIT = 15.0
STATS_DAYS = 31
STATS_WINDOW_DAYS = 7
STATS_MAX_GAP_SECONDS = 900


@dataclass(slots=True)
class HeatStats:
    """Running totals of full-load heating hours, degree days and heat."""

    heating_hours: float = 0.0
    degree_days: float = 0.0
    # Estimated heat given off by the radiators in kWh.
    energy_kwh: float = 0.0
    # Per local day: [full-load hours, degree days, kWh].
    days: dict[str, list[float]] = field(default_factory=dict)
    last_at: datetime | None = None
    last_demand: float | None = None
    last_outdoor: float | None = None
    last_power_kw: float = 0.0
    last_supplied: bool = True

    def observe(
        self,
        now: datetime,
        demand: float | None,
        outdoor: float | None,
        power_kw: float = 0.0,
        supplied: bool = True,
    ) -> None:
        """Add the time since the last cycle at the previous readings.

        ``now`` is local time, ``demand`` the heat demand in % (0..100),
        ``power_kw`` the radiators' output at full demand and ``supplied``
        False while they stay cold (no heat although the valves are open).
        """
        if self.last_at is not None:
            seconds = (now - self.last_at).total_seconds()
            if 0 < seconds <= STATS_MAX_GAP_SECONDS:
                hours = 0.0
                degrees = 0.0
                if self.last_demand is not None:
                    hours = max(0.0, min(self.last_demand, 100.0)) / 100 * seconds / 3600
                if self.last_outdoor is not None and self.last_outdoor < DEGREE_LIMIT:
                    degrees = (DEGREE_INDOOR - self.last_outdoor) * seconds / 86400
                energy = hours * self.last_power_kw if self.last_supplied else 0.0
                self.heating_hours = round(self.heating_hours + hours, 4)
                self.degree_days = round(self.degree_days + degrees, 4)
                self.energy_kwh = round(self.energy_kwh + energy, 4)
                day = self.days.setdefault(
                    self.last_at.date().isoformat(), [0.0, 0.0, 0.0]
                )
                day[0] = round(day[0] + hours, 4)
                day[1] = round(day[1] + degrees, 4)
                day[2] = round(day[2] + energy, 4)
                if len(self.days) > STATS_DAYS:
                    for key in sorted(self.days)[: len(self.days) - STATS_DAYS]:
                        del self.days[key]
        self.last_at = now
        self.last_demand = demand
        self.last_outdoor = outdoor
        self.last_power_kw = max(0.0, power_kw)
        self.last_supplied = supplied

    def energy_between(self, first: date, last: date) -> float:
        """Estimated kWh of the local days ``first`` to ``last``."""
        total = 0.0
        day = first
        while day <= last:
            item = self.days.get(day.isoformat())
            if item is not None:
                total += item[2]
            day += timedelta(days=1)
        return round(total, 2)

    def hours_per_degree_day(self, today: date) -> float | None:
        """Full-load hours per degree day over the last complete days."""
        hours = 0.0
        degrees = 0.0
        for offset in range(1, STATS_WINDOW_DAYS + 1):
            item = self.days.get((today - timedelta(days=offset)).isoformat())
            if item is not None:
                hours += item[0]
                degrees += item[1]
        if degrees < 1.0:
            return None
        return round(hours / degrees, 3)

    def as_dict(self) -> dict:
        return {
            "heating_hours": self.heating_hours,
            "degree_days": self.degree_days,
            "energy_kwh": self.energy_kwh,
            "days": {key: list(value) for key, value in self.days.items()},
        }

    @classmethod
    def from_dict(cls, data: object) -> HeatStats:
        result = cls()
        if not isinstance(data, dict):
            return result
        for key in ("heating_hours", "degree_days", "energy_kwh"):
            value = data.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
                setattr(result, key, float(value))
        days = data.get("days")
        if isinstance(days, dict):
            for key, value in days.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, list)
                    and len(value) in (2, 3)
                    and all(isinstance(item, (int, float)) for item in value)
                ):
                    # Days before the heat meter (0.13.0) have no kWh.
                    result.days[key] = [float(item) for item in value] + [0.0] * (
                        3 - len(value)
                    )
        return result


# --- Fallback schedule in the valves ------------------------------------------

_ALL_DAYS = "mon,tue,wed,thu,fri,sat,sun"


def _half(value: float) -> str:
    return f"{max(5.0, min(30.0, round(value * 2) / 2)):.1f}"


def fallback_schedule(
    blocks: list[tuple[datetime, datetime, float]], eco: float
) -> str:
    """Aqara E1 ``schedule_settings``: four switch points for every day.

    ``blocks`` are the comfort blocks (local start, end, temperature) of the
    next day; the first two are used. Without a block the valve keeps eco.
    """

    def clock(moment: datetime) -> int:
        return moment.hour * 60 + moment.minute

    points: list[tuple[int, float]] = []
    usable = [
        (clock(start), clock(end), temperature)
        for start, end, temperature in blocks
        if clock(end) > clock(start)
    ]
    if len(usable) >= 2:
        (start1, end1, temp1), (start2, end2, temp2) = sorted(usable[:2])
        if end1 < start2:
            points = [(start1, temp1), (end1, eco), (start2, temp2), (end2, eco)]
    if not points and usable:
        start, end, temperature = usable[0]
        points = [(0, eco), (start, temperature), (end, eco), (23 * 60 + 59, eco)]
        if start == 0 or end >= 23 * 60 + 59:
            points = []
    if not points:
        points = [(0, eco), (6 * 60, eco), (12 * 60, eco), (23 * 60 + 59, eco)]
    return _ALL_DAYS + "".join(
        f"|{minute // 60}:{minute % 60:02d},{_half(temperature)}"
        for minute, temperature in points
    )


# Tuya valves (e.g. TS0601 via Zigbee2MQTT) keep a week program of their own:
# one text per weekday with six switch points "HH:MM/temperature". It runs
# when the valve is set to "auto".
TUYA_DAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
TUYA_POINTS = 6


def _minutes(raw: object) -> int | None:
    if isinstance(raw, time):
        # Inside Home Assistant schedule.get_schedule returns time objects;
        # a block running to midnight ends at 23:59:59.
        if raw >= time(23, 59, 59):
            return 1440
        return raw.hour * 60 + raw.minute
    if not isinstance(raw, str):
        return None
    parts = raw.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return None
    if not (0 <= hour <= 24 and 0 <= minute < 60) or hour * 60 + minute > 1440:
        return None
    return hour * 60 + minute


def tuya_day_schedule(
    items: object,
    comfort: float,
    eco: float,
    step: float = 0.5,
    temperature_of=None,
    level_of=None,
) -> str:
    """Six switch points for one day from a schedule helper's blocks.

    ``items`` is one weekday of ``schedule.get_schedule`` (list of blocks
    with ``from``, ``to`` and optional ``data.temperature``). At most three
    comfort blocks fit; the time between them is eco.
    """
    step = step if step and step > 0 else 0.5

    def degrees(value: float) -> float:
        return max(5.0, min(30.0, round(value / step) * step))

    blocks: list[tuple[int, int, float]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        start, end = _minutes(item.get("from")), _minutes(item.get("to"))
        if start is None or end is None or end <= start:
            continue
        temperature = comfort
        data = item.get("data")
        if temperature_of is not None and isinstance(data, dict):
            value = temperature_of(data.get("temperature"))
            if value is None and level_of is not None:
                value = level_of(data)
            if value is not None:
                temperature = value
        blocks.append((start, end, temperature))
    blocks.sort()
    points: list[tuple[int, float]] = []
    for start, end, temperature in blocks[:3]:
        points.append((start, temperature))
        if end < 1440:
            points.append((end, eco))
    if not points or points[0][0] > 0:
        points.insert(0, (0, eco))
    merged: list[tuple[int, float]] = []
    for minute, temperature in points:
        if merged and merged[-1][0] == minute:
            merged[-1] = (minute, temperature)
        else:
            merged.append((minute, temperature))
    merged = merged[:TUYA_POINTS]
    while len(merged) < TUYA_POINTS:
        last_minute, last_temperature = merged[-1]
        missing = TUYA_POINTS - len(merged)
        minute = max(last_minute + 1, 1440 - missing)
        merged.append((min(minute, 1439), last_temperature))
    return " ".join(
        f"{minute // 60:02d}:{minute % 60:02d}/{degrees(temperature):.1f}"
        for minute, temperature in merged
    )


def tuya_week_schedule(
    weekly: object,
    comfort: float,
    eco: float,
    step: float = 0.5,
    temperature_of=None,
    level_of=None,
) -> dict[str, str]:
    """Weekday -> text for a Tuya valve from a schedule helper's week."""
    week = weekly if isinstance(weekly, dict) else {}
    return {
        day: tuya_day_schedule(
            week.get(day), comfort, eco, step, temperature_of, level_of
        )
        for day in TUYA_DAYS
    }
