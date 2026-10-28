"""Pure decision logic for adaptive heating.

This module intentionally has no Home Assistant imports so its calculations
can be tested independently of the runtime.
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from .model import ModelView

TrendResult = Literal["started", "collecting", "too_long", "implausible", "complete"]


@dataclass(frozen=True, slots=True)
class HeatingDecision:
    """Result of a single heating decision."""

    status: str
    mode: str
    target_temperature: float | None
    preheat_minutes: int
    projected_temperature: float | None = None
    forecast_condition: str | None = None
    solar_adjustment_minutes: int = 0
    # How the preheat time came about (see ``preheat_parts``).
    preheat_parts: dict | None = None


def preheat_parts_text(parts: dict) -> str:
    """One line such as "Raummodell 62 min (18,4 → 21,0 °C, außen 3,0 °C), …"."""

    def number(value: float) -> str:
        return f"{value:.1f}".replace(".", ",")

    def signed(value: int) -> str:
        return f"+{value}" if value > 0 else f"−{-value}"

    source = "Raummodell" if parts.get("source") == "model" else "Aufheizrate"
    text = f"{source} {parts['base_minutes']} min"
    details = [f"{number(parts['start_temperature'])} → {number(parts['target'])} °C"]
    if parts.get("outdoor") is not None:
        details.append(f"außen {number(parts['outdoor'])} °C")
    text += f" ({', '.join(details)})"
    for key, label in (
        ("overshoot_minutes", "Überschwingen"),
        ("punctuality_minutes", "Pünktlichkeit"),
        ("sun_minutes", "Sonne"),
    ):
        value = int(parts.get(key) or 0)
        if value:
            text += f", {label} {signed(value)}"
    if parts.get("supply_wait_until"):
        text += f", wartet auf die Zentralheizung bis {parts['supply_wait_until']} Uhr"
    text += f" → {parts['final_minutes']} min"
    if parts.get("limited"):
        text += f" (gedeckelt auf {parts['limit_minutes']})"
    return text


def calculate_lead_minutes(
    current_temperature: float,
    target_temperature: float,
    heating_rate_c_per_hour: float,
    outdoor_temperature: float | None = None,
    max_preheat_minutes: int = 120,
    margin_minutes: int = 10,
) -> int:
    """Estimate how early heating should start, with conservative bounds."""
    if current_temperature >= target_temperature - 0.1:
        return 0

    rate = max(0.2, min(float(heating_rate_c_per_hour), 4.0))
    temperature_gap = target_temperature - current_temperature
    minutes = temperature_gap / rate * 60 + margin_minutes

    # Cold weather modestly increases the estimate. This is a heuristic, not
    # a claim that outdoor temperature alone predicts room heat loss.
    if outdoor_temperature is not None:
        weather_factor = max(
            0.85, min(1.30, 1.0 + (10.0 - outdoor_temperature) * 0.012)
        )
        minutes *= weather_factor

    return max(0, min(round(minutes), max_preheat_minutes))


def model_lead_minutes(
    room_model: ModelView,
    start_temperature: float,
    target_temperature: float,
    max_preheat_minutes: int,
    margin_minutes: int = 10,
) -> int:
    """Preheat time from the room equation; the maximum if never reached."""
    if start_temperature >= target_temperature - 0.1:
        return 0
    hours = room_model.hours_to_reach(start_temperature, target_temperature)
    if hours is None:
        return max_preheat_minutes
    return max(0, min(round(hours * 60) + margin_minutes, max_preheat_minutes))


def decide_heating_target(
    *,
    now: datetime,
    schedule_active: bool,
    next_event: datetime | None,
    room_temperature: float,
    outdoor_temperature: float | None,
    comfort_temperature: float,
    eco_temperature: float,
    heating_rate_c_per_hour: float,
    max_preheat_minutes: int,
    cooling_rate_c_per_hour: float = 0.0,
    forecast_condition: str | None = None,
    window_open: bool = False,
    present: bool = True,
    preheat_started: bool = False,
    away_temperature: float | None = None,
    heating_limit_reached: bool = False,
    window_temperature: float | None = None,
    frost_protection_temperature: float | None = None,
    heating_season: bool = True,
    off_temperature: float | None = None,
    boost_temperature: float | None = None,
    quick_mode: tuple[str, str, float] | None = None,
    forecast_temperature: float | None = None,
    maintenance_temperature: float | None = None,
    reduced_comfort: tuple[str, float] | None = None,
    long_absence_temperature: float | None = None,
    overshoot: float = 0.0,
    room_model: ModelView | None = None,
    setback_floor: float | None = None,
    household_present: bool = False,
    lead_bias_minutes: int = 0,
    outdoor_warmer: bool = False,
) -> HeatingDecision:
    """Return the target and reason for the current conditions.

    ``window_temperature`` replaces the setback target while a window is open.
    ``frost_protection_temperature`` is a floor no decision may go below.
    Outside the ``heating_season`` the room is not heated: the target is
    ``off_temperature`` (the thermostat minimum), raised by frost protection.
    A ``boost_temperature`` wins over schedule, presence and heating limit,
    but not over an open window or the end of the heating season.
    A ``quick_mode`` (mode, status, target) picked by hand has the same rank.
    ``forecast_temperature`` is the outdoor temperature forecast for the start
    of the next comfort period; preheating is timed with it when known.
    ``maintenance_temperature`` opens every valve fully and wins over
    everything, open windows and the end of the heating season included.
    ``reduced_comfort`` (status, target) replaces the setback while nobody is
    in the room but the schedule asks for comfort; ``long_absence_temperature``
    replaces it after a long absence. Both apply only without presence.
    ``overshoot`` is how far the room keeps warming after heating stops;
    preheating aims that much lower so it ends earlier.
    ``room_model`` (the learned room equation with the weather at the next
    comfort start) times preheating physically instead of with a fixed rate.
    ``setback_floor`` raises the setback outside comfort time so the room can
    still reach comfort in time. With ``household_present`` somebody is home
    although the room is empty: outside comfort time it is then preheated
    like an occupied room. ``lead_bias_minutes`` is the learned correction
    from mornings the room was warm too late (positive) or too early.
    With ``outdoor_warmer`` it is warmer outside than in the room: the room
    is not heated (like outside the heating season), unless a window is open
    or heating was asked for by hand (boost, quick mode).
    """
    if maintenance_temperature is not None:
        return HeatingDecision(
            "Wartung – Ventile voll geöffnet", "maintenance", maintenance_temperature, 0
        )
    if not heating_season:
        decision = HeatingDecision(
            "Heizperiode aus – nicht geheizt",
            "season_off",
            off_temperature if off_temperature is not None else eco_temperature,
            0,
        )
    elif (
        outdoor_warmer
        and not window_open
        and boost_temperature is None
        and (quick_mode is None or not _picked_by_hand(quick_mode[0]))
    ):
        decision = HeatingDecision(
            "Außen wärmer als innen – nicht geheizt",
            "outdoor_warm",
            off_temperature if off_temperature is not None else eco_temperature,
            0,
        )
    elif boost_temperature is not None and not window_open:
        decision = HeatingDecision("Boost", "boost", boost_temperature, 0)
    elif quick_mode is not None and not window_open:
        mode, status, target = quick_mode
        decision = HeatingDecision(status, mode, target, 0)
    else:
        decision = _decide(
            now=now,
            schedule_active=schedule_active,
            next_event=next_event,
            room_temperature=room_temperature,
            outdoor_temperature=outdoor_temperature,
            comfort_temperature=comfort_temperature,
            eco_temperature=eco_temperature,
            heating_rate_c_per_hour=heating_rate_c_per_hour,
            max_preheat_minutes=max_preheat_minutes,
            cooling_rate_c_per_hour=cooling_rate_c_per_hour,
            forecast_condition=forecast_condition,
            window_open=window_open,
            present=present,
            preheat_started=preheat_started,
            away_temperature=away_temperature,
            heating_limit_reached=heating_limit_reached,
            window_temperature=window_temperature,
            forecast_temperature=forecast_temperature,
            reduced_comfort=reduced_comfort,
            long_absence_temperature=long_absence_temperature,
            overshoot=overshoot,
            room_model=room_model,
            setback_floor=setback_floor,
            household_present=household_present,
            lead_bias_minutes=lead_bias_minutes,
        )
    if (
        frost_protection_temperature is not None
        and decision.target_temperature is not None
        and decision.target_temperature < frost_protection_temperature
    ):
        return replace(
            decision,
            status=f"{decision.status} (Frostschutz)",
            target_temperature=frost_protection_temperature,
        )
    return decision


def _decide(
    *,
    now: datetime,
    schedule_active: bool,
    next_event: datetime | None,
    room_temperature: float,
    outdoor_temperature: float | None,
    comfort_temperature: float,
    eco_temperature: float,
    heating_rate_c_per_hour: float,
    max_preheat_minutes: int,
    cooling_rate_c_per_hour: float,
    forecast_condition: str | None,
    window_open: bool,
    present: bool,
    preheat_started: bool,
    away_temperature: float | None,
    heating_limit_reached: bool,
    window_temperature: float | None,
    forecast_temperature: float | None = None,
    reduced_comfort: tuple[str, float] | None = None,
    long_absence_temperature: float | None = None,
    overshoot: float = 0.0,
    room_model: ModelView | None = None,
    setback_floor: float | None = None,
    household_present: bool = False,
    lead_bias_minutes: int = 0,
) -> HeatingDecision:
    """Decide without the frost-protection floor.

    ``preheat_started`` tells the decision that preheating for ``next_event``
    already began. Preheating then continues until the event instead of being
    re-evaluated from the (now warmer) room, which would otherwise drop back
    to eco shortly before the comfort period and toggle the setpoint.

    ``away_temperature`` is used while nobody is home; without it the eco
    temperature applies, as before.
    """
    away_target = (
        eco_temperature
        if present or away_temperature is None
        else away_temperature
    )

    if window_open:
        # Without its own window temperature, an open window never heats
        # above the away setpoint.
        return HeatingDecision(
            "Fenster offen – abgesenkt",
            "window",
            min(eco_temperature, away_target)
            if window_temperature is None
            else window_temperature,
            0,
        )

    # Somebody is home, only this room is empty: outside comfort time the
    # room is set back and preheated as if it were occupied.
    room_only_empty = not present and household_present and not schedule_active
    if not present and not room_only_empty:
        if long_absence_temperature is not None:
            return HeatingDecision(
                "Lange niemand zuhause – Frostschutz",
                "long_absence",
                long_absence_temperature,
                0,
            )
        if (
            reduced_comfort is not None
            and schedule_active
            and not heating_limit_reached
        ):
            status, target = reduced_comfort
            return HeatingDecision(status, "away_reduced", target, 0)
        return HeatingDecision(
            "Keine Anwesenheit – abgesenkt", "away", away_target, 0
        )

    if heating_limit_reached:
        return HeatingDecision(
            "Heizgrenze erreicht – abgesenkt", "heating_limit", eco_temperature, 0
        )

    if schedule_active:
        return HeatingDecision(
            "Komfortbetrieb", "comfort", comfort_temperature, 0
        )

    setback = eco_temperature
    if setback_floor is not None and setback_floor > eco_temperature:
        setback = min(setback_floor, comfort_temperature)

    minutes_until_event: float | None = None
    projected_temperature: float | None = None
    if next_event is not None and next_event > now:
        minutes_until_event = (next_event - now).total_seconds() / 60
        # Do not project the room below its current value if it is already
        # colder than setback, and do not project normal setback operation
        # below the setback target. This keeps the forecast conservative.
        lower_bound = min(room_temperature, setback)
        if room_model is not None:
            cooled = room_model.temperature_after(
                room_temperature, minutes_until_event / 60, 0.0
            )
        else:
            bounded_cooling_rate = max(0.0, min(float(cooling_rate_c_per_hour), 2.0))
            cooled = room_temperature - bounded_cooling_rate * minutes_until_event / 60
        projected_temperature = max(lower_bound, min(room_temperature, cooled))

    temperature_for_lead = (
        projected_temperature
        if projected_temperature is not None
        else room_temperature
    )
    lead_target = comfort_temperature - max(0.0, overshoot)
    lead_outdoor = (
        forecast_temperature if forecast_temperature is not None else outdoor_temperature
    )

    def base_lead(target: float) -> int:
        if room_model is not None:
            return model_lead_minutes(
                room_model, temperature_for_lead, target, max_preheat_minutes
            )
        return calculate_lead_minutes(
            temperature_for_lead,
            target,
            heating_rate_c_per_hour,
            lead_outdoor,
            max_preheat_minutes,
        )

    lead = base_lead(lead_target)
    without_overshoot = base_lead(comfort_temperature) if overshoot > 0 else lead
    after_overshoot = lead
    if lead > 0 and lead_bias_minutes:
        lead = max(0, min(lead + int(lead_bias_minutes), max_preheat_minutes))
    after_bias = lead

    solar_adjustment = 0
    if (
        next_event is not None
        and minutes_until_event is not None
        and minutes_until_event <= lead
    ):
        lead, solar_adjustment = apply_forecast_solar_adjustment(
            lead, forecast_condition, next_event
        )
    parts: dict | None = None
    if minutes_until_event is not None and without_overshoot > 0:
        parts = {
            "source": "model" if room_model is not None else "rate",
            "start_temperature": round(temperature_for_lead, 1),
            "target": round(comfort_temperature, 1),
            "outdoor": None if lead_outdoor is None else round(float(lead_outdoor), 1),
            "base_minutes": without_overshoot,
            "overshoot_minutes": after_overshoot - without_overshoot,
            "punctuality_minutes": after_bias - after_overshoot,
            "sun_minutes": -int(solar_adjustment),
            "limit_minutes": max_preheat_minutes,
            "limited": without_overshoot >= max_preheat_minutes
            or after_bias >= max_preheat_minutes,
            "final_minutes": lead,
        }

    if minutes_until_event is not None:
        should_preheat = minutes_until_event > 0 and (
            preheat_started
            or (
                minutes_until_event <= lead
                and room_temperature < comfort_temperature - 0.2
            )
        )
        if should_preheat:
            return HeatingDecision(
                "Vorausschauendes Vorheizen",
                "preheat",
                comfort_temperature,
                lead,
                projected_temperature,
                forecast_condition,
                solar_adjustment,
                parts,
            )

    if setback > eco_temperature:
        value = f"{setback:.1f}".replace(".", ",")
        return HeatingDecision(
            f"Energiesparbetrieb – nur bis {value} °C abgesenkt, sonst wird es "
            "zum Komfortbeginn nicht warm",
            "eco",
            setback,
            lead,
            projected_temperature,
            forecast_condition,
            solar_adjustment,
            parts,
        )
    return HeatingDecision(
        "Energiesparbetrieb",
        "eco",
        eco_temperature,
        lead,
        projected_temperature,
        forecast_condition,
        solar_adjustment,
        parts,
    )


def evaluate_outdoor_warmer(
    outdoor_temperature: float | None,
    room_temperature: float | None,
    currently_warmer: bool,
    margin: float = 0.0,
    hysteresis: float = 0.5,
) -> bool:
    """Return whether it is warm enough outside that the room needs no heat.

    Reached once the outdoor temperature is at least the room temperature
    minus ``margin``; released only ``hysteresis`` below that, so the room
    does not toggle while both are about equal. Without either value the
    room is heated as usual.
    """
    if outdoor_temperature is None or room_temperature is None:
        return False
    threshold = room_temperature - max(0.0, margin)
    if outdoor_temperature >= threshold:
        return True
    return currently_warmer and outdoor_temperature > threshold - hysteresis


def evaluate_heating_limit(
    outdoor_temperature: float | None,
    limit_temperature: float | None,
    currently_reached: bool,
    hysteresis: float = 1.0,
) -> bool:
    """Return whether it is warm enough outside to stop comfort heating.

    The limit is reached at ``limit_temperature`` and released only once the
    outdoor temperature drops ``hysteresis`` below it, so a value hovering
    around the limit does not toggle the setpoint. Without a limit or an
    outdoor reading, heating continues as normal.
    """
    if limit_temperature is None or outdoor_temperature is None:
        return False
    if outdoor_temperature >= limit_temperature:
        return True
    return currently_reached and outdoor_temperature > limit_temperature - hysteresis


def select_forecast_condition(
    forecast: list[dict], target_time: datetime | None, now: datetime
) -> str | None:
    """Select the nearest forecast condition to the next target time."""
    wanted = target_time if target_time is not None and target_time > now else now
    nearest_condition: str | None = None
    nearest_delta: float | None = None

    for item in forecast:
        raw_datetime = item.get("datetime")
        condition = item.get("condition")
        if not isinstance(raw_datetime, str) or not isinstance(condition, str):
            continue
        try:
            forecast_time = datetime.fromisoformat(
                raw_datetime.replace("Z", "+00:00")
            )
        except ValueError:
            continue

        comparison_time = wanted
        if forecast_time.tzinfo is None and comparison_time.tzinfo is not None:
            forecast_time = forecast_time.replace(tzinfo=comparison_time.tzinfo)
        elif forecast_time.tzinfo is not None and comparison_time.tzinfo is None:
            comparison_time = comparison_time.replace(tzinfo=forecast_time.tzinfo)

        delta = abs((forecast_time - comparison_time).total_seconds())
        if nearest_delta is None or delta < nearest_delta:
            nearest_delta = delta
            nearest_condition = condition.lower().replace("_", "")

    # Do not trust stale or distant forecast points for a control decision.
    if nearest_delta is None or nearest_delta > 90 * 60:
        return None
    return nearest_condition


def detect_temperature_drop(
    samples: list[tuple[datetime, float]],
    now: datetime,
    window_seconds: float,
    drop: float,
) -> bool:
    """True when the room fell by ``drop`` within the last ``window_seconds``."""
    recent = [
        temperature
        for moment, temperature in samples
        if (now - moment).total_seconds() <= window_seconds
    ]
    if len(recent) < 2:
        return False
    return max(recent) - recent[-1] >= drop


def select_forecast_temperature(
    forecast: list[dict], target_time: datetime | None, now: datetime
) -> float | None:
    """Forecast outdoor temperature nearest to the next target time."""
    if target_time is None or target_time <= now:
        return None
    nearest: float | None = None
    nearest_delta: float | None = None
    for item in forecast:
        raw_datetime = item.get("datetime")
        raw_temperature = item.get("temperature")
        if not isinstance(raw_datetime, str) or isinstance(raw_temperature, bool):
            continue
        try:
            temperature = float(raw_temperature)
            forecast_time = datetime.fromisoformat(raw_datetime.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(temperature):
            continue
        comparison_time = target_time
        if forecast_time.tzinfo is None and comparison_time.tzinfo is not None:
            forecast_time = forecast_time.replace(tzinfo=comparison_time.tzinfo)
        elif forecast_time.tzinfo is not None and comparison_time.tzinfo is None:
            comparison_time = comparison_time.replace(tzinfo=forecast_time.tzinfo)
        delta = abs((forecast_time - comparison_time).total_seconds())
        if nearest_delta is None or delta < nearest_delta:
            nearest_delta = delta
            nearest = temperature
    if nearest_delta is None or nearest_delta > 90 * 60:
        return None
    return nearest


def apply_forecast_solar_adjustment(
    lead_minutes: int,
    forecast_condition: str | None,
    target_time: datetime | None,
) -> tuple[int, int]:
    """Conservatively reduce the lead only for sunny daytime forecast points.

    This is a transparent heuristic rather than a room-specific solar model.
    The maximum reduction is capped at 15 minutes.
    """
    if lead_minutes <= 0 or target_time is None:
        return lead_minutes, 0
    if not 8 <= target_time.hour < 17:
        return lead_minutes, 0

    condition = (forecast_condition or "").lower().replace("_", "")
    if condition == "sunny":
        factor = 0.15
    elif condition == "partlycloudy":
        factor = 0.08
    else:
        return lead_minutes, 0

    reduction = min(15, round(lead_minutes * factor))
    adjusted = max(0, lead_minutes - reduction)
    return adjusted, lead_minutes - adjusted


@dataclass(slots=True)
class TrendSample:
    """Temperature trend window aligned to changes of the sensor reading.

    Room sensors usually report in 0.1 °C steps. Measuring from an arbitrary
    moment to the next step overstates slow rates heavily (a single 0.1 °C
    step after five minutes reads as 1.2 °C/h). The window therefore starts
    at the first change of the reading and is evaluated only once the reading
    moved by ``min_delta``, so both ends sit on a sensor step.
    """

    temperature: float | None = None
    started_at: datetime | None = None
    anchored: bool = False

    def reset(self) -> None:
        """Discard the current window."""
        self.temperature = None
        self.started_at = None
        self.anchored = False

    def _restart(self, temperature: float, now: datetime, anchored: bool) -> None:
        self.temperature = temperature
        self.started_at = now
        self.anchored = anchored

    def observe(
        self,
        temperature: float,
        now: datetime,
        *,
        direction: int,
        min_seconds: float,
        max_seconds: float,
        min_delta: float,
        max_delta: float,
    ) -> tuple[TrendResult, float | None]:
        """Advance the window; return the outcome and, when complete, the rate.

        ``direction`` is +1 for heating and -1 for cooling; the returned rate
        is always positive in that direction, in °C per hour.
        """
        if self.temperature is None or self.started_at is None:
            self._restart(temperature, now, anchored=False)
            return "started", None

        if not self.anchored:
            if abs(temperature - self.temperature) > 1e-6:
                self._restart(temperature, now, anchored=True)
            return "started", None

        elapsed = (now - self.started_at).total_seconds()
        change = (temperature - self.temperature) * direction
        if elapsed > max_seconds:
            self._restart(temperature, now, anchored=False)
            return "too_long", None
        if change > max_delta:
            self._restart(temperature, now, anchored=False)
            return "implausible", None
        # Readings like 19.3 - 19.1 come out a hair below 0.2 in floating point.
        epsilon = 1e-6
        if change <= -min_delta + epsilon:
            # Moving the wrong way (e.g. thermal lag right after a valve opened):
            # start a fresh window at this sensor step instead of rejecting.
            self._restart(temperature, now, anchored=True)
            return "collecting", None
        if elapsed < min_seconds or change < min_delta - epsilon:
            return "collecting", None

        self._restart(temperature, now, anchored=False)
        return "complete", change / (elapsed / 3600)


def evaluate_window_open(
    contact_open: bool,
    seconds_since_change: float,
    previously_open: bool,
    open_delay_seconds: int,
    close_delay_seconds: int,
) -> bool:
    """Debounce a window contact.

    A window counts as open only after it stayed open for the open delay, and
    stays open for the close delay after closing, so short airing or a door
    draft does not toggle the setpoint and the room air settles before heating
    resumes.
    """
    if contact_open:
        return previously_open or seconds_since_change >= open_delay_seconds
    return previously_open and seconds_since_change < close_delay_seconds


def calibration_offset(
    room_temperature: float,
    thermostat_temperature: float,
    max_offset: float,
) -> float:
    """Offset that makes a thermostat regulate on the room sensor.

    A valve that reads 23 °C near the radiator while the room has 20 °C
    closes 3 °C too early, so its setpoint is raised by that difference.
    """
    offset = thermostat_temperature - room_temperature
    return max(-max_offset, min(offset, max_offset))


def schedule_comfort_temperature(
    value: object, minimum: float = 5.0, maximum: float = 30.0
) -> float | None:
    """Comfort temperature from a schedule block's data, if it holds a valid one."""
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return None
    if temperature != temperature or not minimum <= temperature <= maximum:
        return None
    return temperature


def apply_hysteresis(
    previous: float | None, new: float, hysteresis: float
) -> float:
    """Keep ``previous`` unless ``new`` moved at least ``hysteresis`` away."""
    if previous is None or abs(new - previous) >= hysteresis:
        return new
    return previous


def fallback_room_temperature(readings: list[float | None]) -> float | None:
    """Mean of the thermostats' own readings when the room sensor is gone.

    Better Thermostat calls this degraded mode: regulating on the radiator
    temperature is less accurate, but better than not regulating at all.
    """
    values = [value for value in readings if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def valve_maintenance_due(
    last_run: datetime | None,
    now: datetime,
    local_hour: int,
    interval_days: int,
    start_hour: int,
    local_weekday: int | None = None,
    weekday: int | None = None,
) -> bool:
    """True in the maintenance hour once the interval since the last run passed.

    An hour of slack keeps a weekly run on the same hour despite small delays.
    With a ``weekday`` (0 = Monday) it runs only on that day, at most once.
    """
    if local_hour != start_hour:
        return False
    if weekday is not None:
        return local_weekday == weekday and (
            last_run is None or now - last_run >= timedelta(hours=2)
        )
    return last_run is None or now - last_run >= timedelta(
        days=interval_days, hours=-1
    )


def valve_maintenance_phase(
    started_at: datetime, now: datetime, phase_seconds: int
) -> str | None:
    """Return "open", then "close", then None once maintenance is over."""
    elapsed = (now - started_at).total_seconds()
    if elapsed < phase_seconds:
        return "open"
    if elapsed < 2 * phase_seconds:
        return "close"
    return None


def aggressive_setpoint(
    target: float, room_temperature: float, band: float, offset: float
) -> float:
    """Push a sluggish valve: target +/- offset outside target +/- band."""
    if room_temperature < target - band:
        return target + offset
    if room_temperature > target + band:
        return target - offset
    return target


def select_schedule(
    schedules: list[tuple[str, str]], choice: str | None
) -> str:
    """The schedule entity picked by ``choice`` from (entity_id, name) pairs.

    ``choice`` may be an entity id, a 1-based number or a (partial) name;
    anything else picks the first schedule.
    """
    if not choice:
        return schedules[0][0]
    text = choice.strip().casefold()
    for entity_id, _name in schedules:
        if entity_id.casefold() == text:
            return entity_id
    if text.isdigit() and 1 <= int(text) <= len(schedules):
        return schedules[int(text) - 1][0]
    for entity_id, name in schedules:
        if name.casefold() == text:
            return entity_id
    for entity_id, name in schedules:
        if text and text in name.casefold():
            return entity_id
    return schedules[0][0]


def description_value(description: object, keys: tuple[str, ...]) -> str | None:
    """The value of the first ``key: value`` line naming one of ``keys``."""
    if not isinstance(description, str):
        return None
    for line in description.splitlines():
        name, sep, value = line.partition(":")
        if sep and name.strip().casefold() in keys:
            return value.strip()
    return None


def calendar_temperature(description: object, key: str = "temperature") -> float | None:
    """Read ``temperature: 22`` from a calendar event description."""
    value = description_value(description, (key,))
    if value is None:
        return None
    return schedule_comfort_temperature(value.replace(",", "."))


# Modes picked by hand (every quick_* preset and the calibration run) still
# heat when it is warmer outside than in.
def _picked_by_hand(mode: str) -> bool:
    return mode.startswith("quick_") or mode == "learn_run"


_OFF_WORDS = frozenset({"off", "aus", "false", "nein", "no", "0", "disabled"})
_ON_WORDS = frozenset({"on", "an", "ein", "true", "ja", "yes", "1", "enabled"})


def is_off_word(value: object) -> bool:
    """True for "aus", "off", false and the like (schedule data, descriptions)."""
    if isinstance(value, bool):
        return not value
    return isinstance(value, (str, int)) and str(value).strip().casefold() in _OFF_WORDS


def is_on_word(value: object) -> bool:
    """True for "an", "on", true and the like."""
    if isinstance(value, bool):
        return value
    return isinstance(value, (str, int)) and str(value).strip().casefold() in _ON_WORDS


def paused_features(
    data: dict[str, object] | None,
    description: object,
    features: dict[str, tuple[str, ...]],
) -> set[str]:
    """Features a schedule block or calendar event switches off.

    ``features`` maps a feature to the keys that name it, e.g. ``window`` to
    ``("fenster", "window")``; ``fenster: aus`` in the block's data or in the
    event's description pauses it.
    """
    paused: set[str] = set()
    lowered = {str(key).casefold(): value for key, value in (data or {}).items()}
    for feature, keys in features.items():
        value = next((lowered[key] for key in keys if key in lowered), None)
        if value is None:
            value = description_value(description, keys)
        if value is not None and is_off_word(value):
            paused.add(feature)
    return paused


def name_temperature(name: object) -> float | None:
    """A temperature at the end of a name, e.g. "Party 23" or "Gäste 21,5"."""
    if not isinstance(name, str):
        return None
    last = name.strip().rsplit(" ", 1)[-1].replace(",", ".").removesuffix("°C")
    return schedule_comfort_temperature(last.removesuffix("°")) if last else None


def mean_forecast_temperature(
    forecast: list[dict], now: datetime, hours: float, min_points: int
) -> float | None:
    """Mean forecast temperature over the next ``hours``, if enough points."""
    end = now + timedelta(hours=hours)
    values: list[float] = []
    for item in forecast:
        raw_datetime = item.get("datetime")
        raw_temperature = item.get("temperature")
        if not isinstance(raw_datetime, str) or isinstance(raw_temperature, bool):
            continue
        try:
            temperature = float(raw_temperature)
            moment = datetime.fromisoformat(raw_datetime.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(temperature):
            continue
        if moment.tzinfo is None and now.tzinfo is not None:
            moment = moment.replace(tzinfo=now.tzinfo)
        if now - timedelta(hours=1) <= moment <= end:
            values.append(temperature)
    if len(values) < min_points:
        return None
    return round(sum(values) / len(values), 1)


def mean_history_temperature(
    samples: list[tuple[datetime, float]], min_span_seconds: float
) -> float | None:
    """Mean of past outdoor readings once they span ``min_span_seconds``."""
    if len(samples) < 2:
        return None
    if (samples[-1][0] - samples[0][0]).total_seconds() < min_span_seconds:
        return None
    return round(sum(value for _, value in samples) / len(samples), 1)


def external_temperature_due(
    last: tuple[float, datetime] | None,
    pending: tuple[float, datetime] | None,
    value: float,
    now: datetime,
    *,
    min_change: float,
    plateau_change: float,
    plateau_tolerance: float,
    plateau_seconds: float,
    resend_seconds: float,
) -> tuple[bool, tuple[float, datetime] | None]:
    """Whether to send ``value`` to a valve's external input, and the plateau.

    Sent at once when nothing was sent yet, the change reaches ``min_change``
    or the last value is older than ``resend_seconds``. A smaller change of at
    least ``plateau_change`` is sent once the reading stayed within
    ``plateau_tolerance`` for ``plateau_seconds``. Changes in one direction
    add up because they are measured against the last value sent.
    """
    if last is None or (now - last[1]).total_seconds() >= resend_seconds:
        return True, None
    change = abs(value - last[0])
    if change >= min_change - 1e-9:
        return True, None
    if change < plateau_change:
        return False, None
    if pending is None or abs(pending[0] - value) > plateau_tolerance:
        return False, (value, now)
    if (now - pending[1]).total_seconds() >= plateau_seconds:
        return True, None
    return False, pending


def plausible_temperature(value: float | None, minimum: float, maximum: float) -> bool:
    """True for a reading a room sensor can really report."""
    return value is not None and minimum <= value <= maximum


def temperature_trend(
    samples: list[tuple[datetime, float]], min_span_seconds: float
) -> float | None:
    """Least-squares slope of the samples in °C per hour, if they span enough."""
    if len(samples) < 2:
        return None
    start = samples[0][0]
    span = (samples[-1][0] - start).total_seconds()
    if span < min_span_seconds:
        return None
    xs = [(at - start).total_seconds() / 3600 for at, _ in samples]
    ys = [value for _, value in samples]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
    return round(slope, 2)


def match_schedule(schedules: list[tuple[str, str]], name: str | None) -> str | None:
    """The schedule an outside source names, or None when none matches.

    Unlike ``select_schedule`` there is no fallback to the first schedule:
    a house calendar event naming "Ferien" leaves rooms without such a
    schedule alone.
    """
    if not name or not name.strip():
        return None
    text = name.strip().casefold()
    for entity_id, schedule_name in schedules:
        if text in (entity_id.casefold(), schedule_name.casefold()):
            return entity_id
    for entity_id, schedule_name in schedules:
        if text in schedule_name.casefold() or schedule_name.casefold() in text:
            return entity_id
    return None


def _vapour_pressure(temperature: float) -> float:
    """Saturation vapour pressure over water in hPa (Magnus, WMO)."""
    return 6.112 * math.exp(17.62 * temperature / (243.12 + temperature))


def absolute_humidity(temperature: float, relative: float) -> float:
    """Water in the air in g/m³ from temperature (°C) and humidity (%)."""
    return 216.7 * relative / 100 * _vapour_pressure(temperature) / (273.15 + temperature)


def dew_point(temperature: float, relative: float) -> float:
    """Dew point in °C (Magnus formula)."""
    gamma = math.log(max(relative, 0.1) / 100) + 17.62 * temperature / (
        243.12 + temperature
    )
    return 243.12 * gamma / (17.62 - gamma)


def airing_advice(
    indoor: float | None,
    indoor_humidity: float | None,
    outdoor: float | None,
    outdoor_humidity: float | None,
    *,
    humid_percent: float,
    min_difference: float,
) -> dict | None:
    """Is airing worth it for the humidity? Display only, nothing is changed.

    Indoor air above ``humid_percent`` is worth drying. Airing helps when the
    outdoor air holds at least ``min_difference`` g/m³ less water; then it
    also says how humid the room would be with the outdoor air warmed up and
    how long to air in the cold. ``None`` without indoor readings.
    """
    if indoor is None or indoor_humidity is None:
        return None
    inside = absolute_humidity(indoor, indoor_humidity)
    result: dict = {
        "relative_humidity": round(indoor_humidity),
        "absolute_humidity": round(inside, 1),
        "dew_point": round(dew_point(indoor, indoor_humidity), 1),
        "outdoor_absolute_humidity": None,
        "humidity_after_airing": None,
    }
    if outdoor is not None and outdoor_humidity is not None:
        outside = absolute_humidity(outdoor, outdoor_humidity)
        result["outdoor_absolute_humidity"] = round(outside, 1)
        # Outdoor air warmed up to the room: its relative humidity there.
        result["humidity_after_airing"] = round(
            min(100.0, outside / inside * indoor_humidity)
        )
    else:
        outside = None
    if indoor_humidity <= humid_percent:
        result["state"] = "not_needed"
        result["text"] = "Nicht nötig"
    elif outside is None:
        result["state"] = "unknown"
        result["text"] = "Luft feucht – Außenfeuchte fehlt"
    elif outside <= inside - min_difference:
        minutes = 5 if outdoor < 5 else 10 if outdoor < 15 else 15
        result["state"] = "helps"
        result["text"] = f"Lüften hilft – {minutes} Minuten stoßlüften"
        result["minutes"] = minutes
    else:
        result["state"] = "useless"
        result["text"] = "Lüften bringt nichts – draußen ähnlich feucht"
    return result
