"""Pure decision logic for adaptive heating.

This module intentionally has no Home Assistant imports so its calculations
can be tested independently of the runtime.
"""

from dataclasses import dataclass
from datetime import datetime


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
) -> HeatingDecision:
    """Return the target and reason for the current conditions."""
    if window_open:
        return HeatingDecision(
            "Fenster offen – abgesenkt", "window", eco_temperature, 0
        )

    if not present:
        return HeatingDecision(
            "Keine Anwesenheit – abgesenkt", "away", eco_temperature, 0
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
        should_preheat = (
            minutes_until_event > 0
            and minutes_until_event <= lead
            and room_temperature < comfort_temperature - 0.2
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
