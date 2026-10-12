"""Thermal room model and room usage profile.

Pure Python without Home Assistant imports, like ``logic``.

The room is described by one equation (a first-order RC model):

    dT/dt = h * u - (k + w * wind) * (T - T_out) + s * I

``u`` is the heat demand (0..1), ``I`` the solar radiation in kW/m² and
``wind`` the wind speed in m/s. The model learns ``h`` (heat output at full
demand, °C/h), ``k`` (heat loss per hour and Kelvin to outside), ``s`` (solar
gain) and ``w`` (extra loss per m/s of wind) from every hour of normal
operation with a decaying least-squares fit. A weak prior keeps the result
sensible while there is little data.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .radiator import SUPPLY_COLD, SUPPLY_WARM, RadiatorTracker, room_supply

# Parameter order: heat output, loss, solar gain, wind loss.
PRIOR = (0.5, 0.02, 0.0, 0.0)
# A typical size of each feature, to weigh the prior like a few samples.
_TYPICAL = (1.0, 10.0, 0.2, 50.0)
_PRIOR_SAMPLES = 2.0
# About a week of hourly samples carry the fit.
DECAY = 0.995
BOUNDS = ((0.05, 6.0), (0.002, 0.3), (0.0, 10.0), (0.0, 0.004))

SAMPLE_SECONDS = 3600
# Readings further apart than this break a sample (missing data).
SAMPLE_MAX_GAP_SECONDS = 900
MIN_SAMPLES = 12
MIN_HEATING_SAMPLES = 3
MIN_IDLE_SAMPLES = 3
HEATING_SAMPLE_DEMAND = 0.5
# With radiators shown warm, less demand already counts as a heating hour.
WARM_SAMPLE_DEMAND = 0.25
IDLE_SAMPLE_DEMAND = 0.1
# Setback limits, reachability and the sun pause need a model that has
# proven itself: enough hours and a small prediction error.
TRUSTED_SAMPLES = 48
TRUSTED_ERROR = 0.12
# Reachable means within this many hours of full heating, not in theory.
REACH_HOURS = 6.0
# A room changing faster than this within an hour is not normal operation.
MAX_SAMPLE_RATE = 4.0


def _features(
    demand: float, room: float, outdoor: float, solar_kw: float, wind: float
) -> tuple[float, float, float, float]:
    difference = room - outdoor
    return (demand, -difference, solar_kw, -difference * wind)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting."""
    size = len(vector)
    rows = [list(matrix[index]) + [vector[index]] for index in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for row in range(column + 1, size):
            factor = rows[row][column] / rows[column][column]
            for index in range(column, size + 1):
                rows[row][index] -= factor * rows[column][index]
    result = [0.0] * size
    for row in range(size - 1, -1, -1):
        total = rows[row][size] - sum(
            rows[row][index] * result[index] for index in range(row + 1, size)
        )
        result[row] = total / rows[row][row]
    return result


@dataclass(frozen=True, slots=True)
class ModelView:
    """Learned parameters plus the current weather, for predictions."""

    heat_output: float
    loss: float
    solar_gain: float
    wind_loss: float
    outdoor: float
    solar_kw: float = 0.0
    wind: float = 0.0

    @property
    def effective_loss(self) -> float:
        return self.loss + self.wind_loss * self.wind

    def with_weather(
        self,
        outdoor: float | None = None,
        solar_kw: float | None = None,
        wind: float | None = None,
    ) -> ModelView:
        return ModelView(
            self.heat_output,
            self.loss,
            self.solar_gain,
            self.wind_loss,
            self.outdoor if outdoor is None else outdoor,
            self.solar_kw if solar_kw is None else solar_kw,
            self.wind if wind is None else wind,
        )

    def equilibrium(self, demand: float = 1.0) -> float:
        """Temperature the room settles at with this heat demand."""
        return self.outdoor + (
            self.heat_output * demand + self.solar_gain * self.solar_kw
        ) / self.effective_loss

    def reachable(self, room: float, hours: float = REACH_HOURS) -> float:
        """Warmest room within ``hours`` of full heating.

        The settling temperature alone extrapolates far beyond anything the
        room has shown; a few hours ahead the model is reliable.
        """
        return max(room, self.temperature_after(room, hours, 1.0))

    def rate(self, room: float, demand: float) -> float:
        """Temperature change in °C per hour right now."""
        return (
            self.heat_output * demand
            - self.effective_loss * (room - self.outdoor)
            + self.solar_gain * self.solar_kw
        )

    def temperature_after(self, room: float, hours: float, demand: float) -> float:
        """Room temperature after ``hours`` at a constant heat demand."""
        settle = self.equilibrium(demand)
        return settle - (settle - room) * math.exp(-self.effective_loss * hours)

    def hours_to_reach(self, room: float, target: float) -> float | None:
        """Hours of full heating from ``room`` to ``target``; None if never."""
        if room >= target:
            return 0.0
        settle = self.equilibrium(1.0)
        if settle <= target + 0.05:
            return None
        return math.log((settle - room) / (settle - target)) / self.effective_loss

    def lowest_start(self, target: float, hours: float) -> float:
        """Coldest room that full heating still brings to ``target`` in time."""
        settle = self.equilibrium(1.0)
        if settle <= target:
            return target
        return settle - (settle - target) * math.exp(self.effective_loss * hours)


@dataclass(slots=True)
class RoomModel:
    """Decaying least-squares fit of the room equation."""

    matrix: list[list[float]] = field(
        default_factory=lambda: [[0.0] * 4 for _ in range(4)]
    )
    vector: list[float] = field(default_factory=lambda: [0.0] * 4)
    samples: int = 0
    heating_samples: int = 0
    idle_samples: int = 0
    last_error: float | None = None
    mean_error: float | None = None

    def add(
        self,
        rate: float,
        demand: float,
        room: float,
        outdoor: float,
        solar_kw: float = 0.0,
        wind: float = 0.0,
        warm: bool = False,
    ) -> bool:
        """Learn one hourly sample; False when it is not plausible.

        ``warm``: the radiators were seen warm during the hour.
        """
        values = (rate, demand, room, outdoor, solar_kw, wind)
        if not all(math.isfinite(value) for value in values):
            return False
        if abs(rate) > MAX_SAMPLE_RATE or not 0.0 <= demand <= 1.0:
            return False
        parameters = self.parameters()
        features = _features(demand, room, outdoor, max(0.0, solar_kw), max(0.0, wind))
        predicted = sum(p * x for p, x in zip(parameters, features, strict=True))
        error = abs(predicted - rate)
        self.last_error = round(error, 3)
        self.mean_error = round(
            error if self.mean_error is None else 0.9 * self.mean_error + 0.1 * error,
            3,
        )
        for row in range(4):
            self.vector[row] = DECAY * self.vector[row] + features[row] * rate
            for column in range(4):
                self.matrix[row][column] = (
                    DECAY * self.matrix[row][column] + features[row] * features[column]
                )
        self.samples += 1
        if demand >= HEATING_SAMPLE_DEMAND or (warm and demand >= WARM_SAMPLE_DEMAND):
            self.heating_samples += 1
        elif demand <= IDLE_SAMPLE_DEMAND:
            self.idle_samples += 1
        return True

    def parameters(self) -> tuple[float, float, float, float]:
        """Fitted (heat output, loss, solar gain, wind loss), within bounds."""
        matrix = [list(row) for row in self.matrix]
        vector = list(self.vector)
        for index in range(4):
            weight = _PRIOR_SAMPLES * _TYPICAL[index] ** 2
            matrix[index][index] += weight
            vector[index] += weight * PRIOR[index]
        solution = _solve(matrix, vector) or list(PRIOR)
        return tuple(
            max(low, min(high, value))
            for value, (low, high) in zip(solution, BOUNDS, strict=True)
        )

    @property
    def ready(self) -> bool:
        return (
            self.samples >= MIN_SAMPLES
            and self.heating_samples >= MIN_HEATING_SAMPLES
            and self.idle_samples >= MIN_IDLE_SAMPLES
        )

    @property
    def trusted(self) -> bool:
        return (
            self.ready
            and self.samples >= TRUSTED_SAMPLES
            and self.mean_error is not None
            and self.mean_error <= TRUSTED_ERROR
        )

    def view(
        self, outdoor: float, solar_kw: float = 0.0, wind: float = 0.0
    ) -> ModelView:
        heat_output, loss, solar_gain, wind_loss = self.parameters()
        return ModelView(
            heat_output, loss, solar_gain, wind_loss, outdoor, solar_kw, wind
        )

    def as_dict(self) -> dict:
        return {
            "matrix": [list(row) for row in self.matrix],
            "vector": list(self.vector),
            "samples": self.samples,
            "heating_samples": self.heating_samples,
            "idle_samples": self.idle_samples,
            "last_error": self.last_error,
            "mean_error": self.mean_error,
        }

    @classmethod
    def from_dict(cls, data: object) -> RoomModel:
        model = cls()
        if not isinstance(data, dict):
            return model
        matrix = data.get("matrix")
        vector = data.get("vector")
        try:
            if (
                isinstance(matrix, list)
                and len(matrix) == 4
                and all(isinstance(row, list) and len(row) == 4 for row in matrix)
                and isinstance(vector, list)
                and len(vector) == 4
            ):
                parsed_matrix = [[float(value) for value in row] for row in matrix]
                parsed_vector = [float(value) for value in vector]
                if all(
                    math.isfinite(value)
                    for row in parsed_matrix
                    for value in row
                ) and all(math.isfinite(value) for value in parsed_vector):
                    model.matrix = parsed_matrix
                    model.vector = parsed_vector
                    for key in ("samples", "heating_samples", "idle_samples"):
                        value = data.get(key)
                        if isinstance(value, int) and value >= 0:
                            setattr(model, key, value)
        except (TypeError, ValueError):
            return cls()
        for key in ("last_error", "mean_error"):
            value = data.get(key)
            if isinstance(value, (int, float)) and math.isfinite(value):
                setattr(model, key, float(value))
        return model


@dataclass(slots=True)
class SampleCollector:
    """Average the inputs over one hour and turn them into a model sample."""

    started_at: float | None = None
    start_room: float | None = None
    last_at: float | None = None
    weight: float = 0.0
    # Time-weighted sums of demand, room, outdoor, solar and wind.
    sums: list[float] = field(default_factory=lambda: [0.0] * 5)
    last_inputs: tuple[float, float, float, float, float] | None = None
    # Heat was asked for but the radiators stayed cold during this hour.
    no_heat: bool = False
    # The radiators were seen warm during this hour.
    warm: bool = False
    # ``warm`` of the hour that made the last finished sample.
    last_warm: bool = False

    def reset(self) -> None:
        self.started_at = None
        self.start_room = None
        self.last_at = None
        self.weight = 0.0
        self.sums = [0.0] * 5
        self.last_inputs = None
        self.no_heat = False
        self.warm = False

    def _start(self, at: float, inputs: tuple[float, float, float, float, float]) -> None:
        self.reset()
        self.started_at = at
        self.start_room = inputs[1]
        self.last_at = at
        self.last_inputs = inputs

    def observe(
        self,
        at: float,
        room: float,
        demand: float,
        outdoor: float,
        solar_kw: float,
        wind: float,
        no_heat: bool = False,
        warm: bool = False,
    ) -> tuple[float, float, float, float, float, float] | None:
        """Feed one reading (``at`` in seconds); return a finished sample.

        A sample is (rate °C/h, demand, room, outdoor, solar kW/m², wind m/s),
        with every input averaged over the hour. ``no_heat`` marks a reading
        in which the radiators stayed cold although heat was asked for: such
        an hour shows the central heating, not the room, and is dropped.
        """
        inputs = (demand, room, outdoor, solar_kw, wind)
        if self.started_at is None or self.last_at is None or self.last_inputs is None:
            self._start(at, inputs)
            self.no_heat = no_heat
            self.warm = warm
            return None
        gap = at - self.last_at
        if gap < 0 or gap > SAMPLE_MAX_GAP_SECONDS:
            self._start(at, inputs)
            self.no_heat = no_heat
            self.warm = warm
            return None
        self.no_heat = self.no_heat or no_heat
        self.warm = self.warm or warm
        # The previous inputs held until now.
        for index, value in enumerate(self.last_inputs):
            self.sums[index] += value * gap
        self.weight += gap
        self.last_at = at
        self.last_inputs = inputs
        if at - self.started_at < SAMPLE_SECONDS or self.weight <= 0:
            return None
        hours = (at - self.started_at) / 3600
        rate = (room - float(self.start_room)) / hours
        demand_mean, room_mean, outdoor_mean, solar_mean, wind_mean = (
            total / self.weight for total in self.sums
        )
        dropped = self.no_heat and demand_mean > IDLE_SAMPLE_DEMAND
        self.last_warm = self.warm
        self._start(at, inputs)
        self.no_heat = no_heat
        self.warm = warm
        if dropped:
            return None
        return (rate, demand_mean, room_mean, outdoor_mean, solar_mean, wind_mean)


HISTORY_STEP_SECONDS = 300


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def solar_to_kw(value: float, unit: str) -> float:
    """Solar radiation in kW/m² (about 120 lx per W/m² of sunlight)."""
    if unit == "lx":
        return value / 120000
    if unit.startswith("kw"):
        return value
    return value / 1000


def wind_to_ms(value: float, unit: str) -> float:
    """Wind speed in m/s."""
    factor = {"km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444, "ft/s": 0.3048}
    return value * factor.get(unit, 1.0)


def seed_room_model(
    model: RoomModel,
    history: dict[str, list[tuple[float, str]]],
    *,
    room_id: str,
    outdoor_id: str,
    demand_id: str,
    window_ids: list[str],
    solar_id: str | None,
    wind_id: str | None,
    units: dict[str, str],
    start: float,
    end: float,
    radiator_ids: list[str] | None = None,
    setpoint_ids: list[str] | None = None,
    full_gap: float = 2.0,
) -> int:
    """Learn hourly samples from recorded states; return how many.

    ``history`` maps entity ids to (timestamp, state) in time order. A state
    holds until the next one. Hours with an open window, an unknown reading
    or without heat demand data (control off) are skipped, and so are hours
    in which the radiators (``radiator_ids``, the valves' own temperature)
    stayed cold although heat was asked for.

    Without a recorded heat demand (a room set up only now) the demand is
    estimated from the valves' setpoints (``setpoint_ids``: a number, or
    ``off``) like the live estimate: the gap to the room over ``full_gap``.
    """
    series = {
        entity_id: sorted(items, key=lambda item: item[0])
        for entity_id, items in history.items()
    }
    positions = dict.fromkeys(series, 0)

    def value_at(entity_id: str | None, at: float) -> str | None:
        if not entity_id or entity_id not in series:
            return None
        items = series[entity_id]
        index = positions[entity_id]
        while index + 1 < len(items) and items[index + 1][0] <= at:
            index += 1
        positions[entity_id] = index
        if not items or items[index][0] > at:
            return None
        return items[index][1]

    collector = SampleCollector()
    trackers = {entity_id: RadiatorTracker() for entity_id in radiator_ids or []}
    added = 0
    at = start
    while at <= end:
        room = _number(value_at(room_id, at))
        outdoor = _number(value_at(outdoor_id, at))
        demand = _number(value_at(demand_id, at))
        if demand is None and room is not None and setpoint_ids:
            demand = estimate_demand(
                [value_at(entity_id, at) for entity_id in setpoint_ids],
                room,
                full_gap,
            )
        window_open = any(value_at(entity_id, at) == "on" for entity_id in window_ids)
        if room is None or outdoor is None or demand is None or window_open:
            collector.reset()
        else:
            solar = _number(value_at(solar_id, at)) if solar_id else None
            wind = _number(value_at(wind_id, at)) if wind_id else None
            supply = room_supply({
                entity_id: tracker.observe(
                    at, demand, _number(value_at(entity_id, at)), room
                )
                for entity_id, tracker in trackers.items()
            })
            sample = collector.observe(
                at,
                room,
                max(0.0, min(demand, 100.0)) / 100,
                outdoor,
                0.0 if solar is None or solar < 0
                else min(solar_to_kw(solar, units.get(solar_id or "", "")), 1.5),
                0.0 if wind is None or wind < 0
                else min(wind_to_ms(wind, units.get(wind_id or "", "")), 40.0),
                supply == SUPPLY_COLD,
                supply == SUPPLY_WARM,
            )
            if sample is not None and model.add(*sample, warm=collector.last_warm):
                added += 1
        at += HISTORY_STEP_SECONDS
    return added


def estimate_demand(
    setpoints: list[str | None], room: float, full_gap: float
) -> float | None:
    """Heat demand in % estimated from valve setpoints; None without data."""
    shares = []
    for raw in setpoints:
        if raw == "off":
            shares.append(0.0)
            continue
        setpoint = _number(raw)
        if setpoint is None:
            continue
        shares.append(max(0.0, min(1.0, (setpoint - room) / full_gap)))
    if not shares:
        return None
    return 100 * sum(shares) / len(shares)


USAGE_ALPHA = 0.3
USAGE_MIN_SECONDS = 1800
USAGE_THRESHOLD = 0.5


@dataclass(slots=True)
class UsageProfile:
    """How often the room is used, per weekday and hour (0..1)."""

    slots: list[list[float | None]] = field(
        default_factory=lambda: [[None] * 24 for _ in range(7)]
    )
    current: tuple[int, int] | None = None
    present_seconds: float = 0.0
    observed_seconds: float = 0.0

    def observe(self, weekday: int, hour: int, present: bool, seconds: float) -> bool:
        """Add time to the running slot; True when a slot was finished."""
        finished = False
        slot = (weekday, hour)
        if self.current != slot:
            finished = self._finish()
            self.current = slot
            self.present_seconds = 0.0
            self.observed_seconds = 0.0
        seconds = max(0.0, min(seconds, 300.0))
        self.observed_seconds += seconds
        if present:
            self.present_seconds += seconds
        return finished

    def pause(self) -> None:
        """Nobody is home: this time says nothing about room usage."""
        self.current = None
        self.present_seconds = 0.0
        self.observed_seconds = 0.0

    def _finish(self) -> bool:
        if self.current is None or self.observed_seconds < USAGE_MIN_SECONDS:
            return False
        weekday, hour = self.current
        share = self.present_seconds / self.observed_seconds
        old = self.slots[weekday][hour]
        self.slots[weekday][hour] = round(
            share if old is None else (1 - USAGE_ALPHA) * old + USAGE_ALPHA * share, 3
        )
        return True

    def usage(self, weekday: int, hour: int) -> float | None:
        return self.slots[weekday][hour]

    def usually_used(self, weekday: int, hour: int) -> bool:
        value = self.slots[weekday][hour]
        return value is not None and value >= USAGE_THRESHOLD

    def as_list(self) -> list[list[float | None]]:
        return [list(day) for day in self.slots]

    @classmethod
    def from_list(cls, data: object) -> UsageProfile:
        profile = cls()
        if isinstance(data, list) and len(data) == 7:
            for weekday, day in enumerate(data):
                if isinstance(day, list) and len(day) == 24:
                    for hour, value in enumerate(day):
                        if (
                            isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            and 0.0 <= value <= 1.0
                        ):
                            profile.slots[weekday][hour] = float(value)
        return profile
