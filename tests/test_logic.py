"""Unit tests for the adaptive heating calculations."""

from datetime import UTC, datetime, timedelta

from custom_components.dynamic_heating.logic import (
    TrendSample,
    calculate_lead_minutes,
    decide_heating_target,
    evaluate_heating_limit,
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


def test_away_temperature_applies_only_while_nobody_is_home() -> None:
    now = datetime.now(UTC)
    common = dict(
        now=now,
        schedule_active=True,
        next_event=None,
        room_temperature=17.0,
        outdoor_temperature=0.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        away_temperature=16.0,
    )
    away = decide_heating_target(**common, present=False)
    assert away.mode == "away"
    assert away.target_temperature == 16.0

    # Coming home during a comfort period heats straight back to comfort.
    home = decide_heating_target(**common, present=True)
    assert home.mode == "comfort"
    assert home.target_temperature == 21.0

    # An open window keeps eco while home, but never heats above away.
    assert decide_heating_target(
        **common, present=True, window_open=True
    ).target_temperature == 18.0
    assert decide_heating_target(
        **common, present=False, window_open=True
    ).target_temperature == 16.0


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


def _near_comfort_decision(*, preheat_started: bool):
    now = datetime.now(UTC)
    return decide_heating_target(
        now=now,
        schedule_active=False,
        next_event=now + timedelta(minutes=10),
        room_temperature=20.9,
        outdoor_temperature=5.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        preheat_started=preheat_started,
    )


def test_started_preheat_holds_comfort_until_the_event() -> None:
    """A warm room must not drop back to eco between preheat and comfort."""
    assert _near_comfort_decision(preheat_started=False).mode == "eco"
    held = _near_comfort_decision(preheat_started=True)
    assert held.mode == "preheat"
    assert held.target_temperature == 21.0


def _observe_heating(sample: TrendSample, temperature: float, now: datetime):
    return sample.observe(
        temperature,
        now,
        direction=1,
        min_seconds=300,
        max_seconds=21600,
        min_delta=0.2,
        max_delta=2.5,
    )


def test_trend_sample_is_not_biased_by_coarse_sensor_steps() -> None:
    """0.5 °C/h with 0.1 °C sensor steps, polled every 10 s, reads as 0.5 °C/h."""
    start = datetime(2026, 1, 1, 6, 0, tzinfo=UTC)
    sample = TrendSample()
    results = []
    # The run starts mid-step: the true temperature is 18.04 and reads 18.0.
    for second in range(0, 3 * 3600, 10):
        true_temperature = 18.04 + 0.5 * second / 3600
        reading = round(true_temperature, 1)
        outcome, rate = _observe_heating(
            sample, reading, start + timedelta(seconds=second)
        )
        if outcome == "complete":
            results.append(rate)

    assert results
    for rate in results:
        assert abs(rate - 0.5) < 0.05


def test_trend_sample_rejects_jumps_and_overlong_windows() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    sample = TrendSample()
    assert _observe_heating(sample, 18.0, start)[0] == "started"
    assert _observe_heating(sample, 18.1, start + timedelta(seconds=10))[0] == "started"
    assert _observe_heating(sample, 20.7, start + timedelta(seconds=20))[0] == "implausible"

    sample.reset()
    _observe_heating(sample, 18.0, start)
    _observe_heating(sample, 18.1, start + timedelta(seconds=10))
    assert _observe_heating(sample, 18.1, start + timedelta(hours=7))[0] == "too_long"


def test_trend_sample_restarts_when_the_room_moves_the_wrong_way() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    sample = TrendSample()
    _observe_heating(sample, 18.0, start)
    _observe_heating(sample, 18.1, start + timedelta(seconds=10))
    outcome, _ = _observe_heating(sample, 17.9, start + timedelta(minutes=10))
    assert outcome == "collecting"
    assert sample.temperature == 17.9


def test_heating_limit_engages_at_limit_and_releases_with_hysteresis() -> None:
    assert evaluate_heating_limit(16.0, None, False) is False
    assert evaluate_heating_limit(None, 16.0, True) is False
    assert evaluate_heating_limit(15.9, 16.0, False) is False
    assert evaluate_heating_limit(16.0, 16.0, False) is True
    # Hovering just below the limit keeps it reached until 1 °C below.
    assert evaluate_heating_limit(15.5, 16.0, True) is True
    assert evaluate_heating_limit(15.0, 16.0, True) is False


def test_heating_limit_holds_eco_during_comfort_and_skips_preheat() -> None:
    now = datetime.now(UTC)
    common = dict(
        now=now,
        room_temperature=19.0,
        outdoor_temperature=18.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        heating_limit_reached=True,
    )
    comfort = decide_heating_target(
        schedule_active=True, next_event=None, **common
    )
    assert comfort.mode == "heating_limit"
    assert comfort.target_temperature == 18.0

    before_event = decide_heating_target(
        schedule_active=False,
        next_event=now + timedelta(minutes=10),
        preheat_started=True,
        **common,
    )
    assert before_event.mode == "heating_limit"
    assert before_event.preheat_minutes == 0


def test_window_and_absence_take_precedence_over_heating_limit() -> None:
    now = datetime.now(UTC)
    common = dict(
        now=now,
        schedule_active=True,
        next_event=None,
        room_temperature=19.0,
        outdoor_temperature=18.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        heating_limit_reached=True,
    )
    assert decide_heating_target(window_open=True, **common).mode == "window"
    away = decide_heating_target(present=False, away_temperature=16.0, **common)
    assert away.mode == "away"
    assert away.target_temperature == 16.0
