"""Unit tests for the adaptive heating calculations."""

from datetime import UTC, datetime, timedelta

from custom_components.dynamic_heating.logic import (
    calculate_lead_minutes,
    decide_heating_target,
)


def test_lead_time_is_bounded_and_accounts_for_temperature_gap() -> None:
    assert calculate_lead_minutes(20.9, 21.0, 1.0) == 0
    assert calculate_lead_minutes(20.0, 21.0, 1.0) == 70
    assert calculate_lead_minutes(15.0, 21.0, 1.0, max_preheat_minutes=90) == 90


def test_cold_outdoor_temperature_does_not_reduce_lead_time() -> None:
    mild = calculate_lead_minutes(
        18.0, 21.0, 1.0, outdoor_temperature=15.0, max_preheat_minutes=300
    )
    cold = calculate_lead_minutes(
        18.0, 21.0, 1.0, outdoor_temperature=-5.0, max_preheat_minutes=300
    )
    assert cold > mild


def test_window_open_always_selects_eco_target() -> None:
    now = datetime.now(UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=True,
        next_event=None,
        room_temperature=17.0,
        outdoor_temperature=2.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        window_open=True,
        present=True,
    )
    assert decision.mode == "window"
    assert decision.target_temperature == 18.0


def test_absence_prevents_preheating() -> None:
    now = datetime.now(UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(minutes=5),
        room_temperature=17.0,
        outdoor_temperature=0.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        present=False,
    )
    assert decision.mode == "away"
    assert decision.target_temperature == 18.0


def test_heating_starts_early_when_schedule_event_is_near() -> None:
    now = datetime.now(UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(minutes=30),
        room_temperature=18.0,
        outdoor_temperature=3.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
    )
    assert decision.mode == "preheat"
    assert decision.target_temperature == 21.0
    assert decision.preheat_minutes >= 30


def test_active_schedule_uses_comfort_temperature() -> None:
    now = datetime.now(UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=True,
        next_event=now + timedelta(hours=1),
        room_temperature=18.5,
        outdoor_temperature=4.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
    )
    assert decision.mode == "comfort"
    assert decision.target_temperature == 21.0


def test_no_preheat_too_early_or_when_target_already_reached() -> None:
    now = datetime.now(UTC)
    too_early = decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(hours=8),
        room_temperature=18.0,
        outdoor_temperature=10.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=90,
    )
    already_warm = decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(minutes=5),
        room_temperature=20.9,
        outdoor_temperature=10.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=90,
    )
    assert too_early.mode == "eco"
    assert already_warm.mode == "eco"


def test_learned_cooling_rate_is_used_for_preheat_forecast() -> None:
    now = datetime.now(UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(hours=1),
        room_temperature=20.0,
        outdoor_temperature=8.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        cooling_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
    )

    assert decision.projected_temperature == 19.0
    assert decision.mode == "preheat"
    assert decision.preheat_minutes == 120


def test_forecast_does_not_project_room_below_existing_setback_floor() -> None:
    now = datetime.now(UTC)
    decision = decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(hours=1),
        room_temperature=17.0,
        outdoor_temperature=8.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        cooling_rate_c_per_hour=2.0,
        max_preheat_minutes=120,
    )

    assert decision.projected_temperature == 17.0
    assert decision.mode == "preheat"



def test_sunny_daytime_forecast_conservatively_reduces_preheat_lead() -> None:
    from custom_components.dynamic_heating.logic import apply_forecast_solar_adjustment

    target = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    adjusted, reduction = apply_forecast_solar_adjustment(120, "sunny", target)
    assert adjusted == 105
    assert reduction == 15


def test_cloudy_or_night_forecast_does_not_adjust_preheat() -> None:
    from custom_components.dynamic_heating.logic import apply_forecast_solar_adjustment

    daytime = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    night = datetime(2026, 10, 10, 23, 0, tzinfo=UTC)
    assert apply_forecast_solar_adjustment(80, "cloudy", daytime) == (80, 0)
    assert apply_forecast_solar_adjustment(80, "sunny", night) == (80, 0)
    assert apply_forecast_solar_adjustment(80, None, daytime) == (80, 0)


def test_partial_clouds_use_smaller_bounded_adjustment() -> None:
    from custom_components.dynamic_heating.logic import apply_forecast_solar_adjustment

    target = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    adjusted, reduction = apply_forecast_solar_adjustment(60, "partlycloudy", target)
    assert reduction == 5
    assert adjusted == 55


def test_select_forecast_condition_chooses_nearest_hour_and_rejects_stale() -> None:
    from custom_components.dynamic_heating.logic import select_forecast_condition

    now = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
    forecast = [
        {"datetime": "2026-10-10T09:00:00+00:00", "condition": "cloudy"},
        {"datetime": "2026-10-10T10:00:00+00:00", "condition": "sunny"},
    ]
    assert select_forecast_condition(forecast, now + timedelta(minutes=55), now) == "cloudy"
    assert select_forecast_condition(forecast, now + timedelta(hours=6), now) is None
