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
            )

    return HeatingDecision(
        "Energiesparbetrieb",
        "eco",
        eco_temperature,
        lead,
        projected_temperature,
    )
