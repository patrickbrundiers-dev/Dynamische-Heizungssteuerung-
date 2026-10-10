"""Pure decision logic for adaptive heating.

This module intentionally has no Home Assistant imports so its calculations
can be tested independently of the runtime.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

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
) -> HeatingDecision:
    """Return the target and reason for the current conditions.

    ``window_temperature`` replaces the setback target while a window is open.
    ``frost_protection_temperature`` is a floor no decision may go below.
    Outside the ``heating_season`` the room is not heated: the target is
    ``off_temperature`` (the thermostat minimum), raised by frost protection.
    """
    if not heating_season:
        decision = HeatingDecision(
            "Heizperiode aus – nicht geheizt",
            "season_off",
            off_temperature if off_temperature is not None else eco_temperature,
            0,
        )
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

    if not present:
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

    minutes_until_event: float | None = None
    projected_temperature: float | None = None
    if next_event is not None and next_event > now:
        minutes_until_event = (next_event - now).total_seconds() / 60
        bounded_cooling_rate = max(0.0, min(float(cooling_rate_c_per_hour), 2.0))
        expected_cooling = bounded_cooling_rate * minutes_until_event / 60

        # Do not project the room below its current value if it is already
        # colder than setback, and do not project normal setback operation
        # below the eco target. This keeps the forecast conservative.
        lower_bound = min(room_temperature, eco_temperature)
        projected_temperature = max(
            lower_bound, room_temperature - expected_cooling
        )

    temperature_for_lead = (
        projected_temperature
        if projected_temperature is not None
        else room_temperature
    )
    lead = calculate_lead_minutes(
        temperature_for_lead,
        comfort_temperature,
        heating_rate_c_per_hour,
        outdoor_temperature,
        max_preheat_minutes,
    )

    solar_adjustment = 0
    if (
        next_event is not None
        and minutes_until_event is not None
        and minutes_until_event <= lead
    ):
        lead, solar_adjustment = apply_forecast_solar_adjustment(
            lead, forecast_condition, next_event
        )

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
            )

    return HeatingDecision(
        "Energiesparbetrieb",
        "eco",
        eco_temperature,
        lead,
        projected_temperature,
        forecast_condition,
        solar_adjustment,
    )


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
        if change <= -min_delta:
            # Moving the wrong way (e.g. thermal lag right after a valve opened):
            # start a fresh window at this sensor step instead of rejecting.
            self._restart(temperature, now, anchored=True)
            return "collecting", None
        if elapsed < min_seconds or change < min_delta:
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
