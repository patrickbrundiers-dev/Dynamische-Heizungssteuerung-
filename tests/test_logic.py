"""Unit tests for the adaptive heating calculations."""

from datetime import UTC, datetime, timedelta

from custom_components.dynamic_heating.logic import (
    TrendSample,
    aggressive_setpoint,
    calendar_temperature,
    temperature_trend,
    select_schedule,
    apply_hysteresis,
    calculate_lead_minutes,
    calibration_offset,
    decide_heating_target,
    evaluate_heating_limit,
    evaluate_window_open,
    fallback_room_temperature,
    schedule_comfort_temperature,
    select_forecast_temperature,
    valve_maintenance_due,
    valve_maintenance_phase,
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


def _decide(**overrides):
    values = dict(
        now=datetime.now(UTC),
        schedule_active=False,
        next_event=None,
        room_temperature=17.0,
        outdoor_temperature=2.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
    )
    values.update(overrides)
    return decide_heating_target(**values)


def test_window_temperature_replaces_setback_while_open() -> None:
    decision = _decide(
        schedule_active=True, window_open=True, window_temperature=15.0
    )
    assert decision.mode == "window"
    assert decision.target_temperature == 15.0
    # Without it the previous behaviour (eco) stays.
    assert _decide(window_open=True).target_temperature == 18.0


def test_frost_protection_is_a_floor_for_every_mode() -> None:
    window = _decide(
        window_open=True, window_temperature=8.0, frost_protection_temperature=12.0
    )
    assert window.mode == "window"
    assert window.target_temperature == 12.0
    assert "Frostschutz" in window.status

    away = _decide(
        present=False, away_temperature=10.0, frost_protection_temperature=12.0
    )
    assert away.target_temperature == 12.0

    comfort = _decide(schedule_active=True, frost_protection_temperature=12.0)
    assert comfort.target_temperature == 21.0
    assert "Frostschutz" not in comfort.status


def test_window_debounce_waits_for_open_and_close_delays() -> None:
    # Opened shortly: not yet counted as open.
    assert not evaluate_window_open(True, 60, False, 300, 600)
    assert evaluate_window_open(True, 300, False, 300, 600)
    # Closed again: setback is held for the close delay.
    assert evaluate_window_open(False, 120, True, 300, 600)
    assert not evaluate_window_open(False, 600, True, 300, 600)
    # A closed window that never counted as open stays closed.
    assert not evaluate_window_open(False, 0, False, 300, 600)
    # Without delays the contact is followed directly.
    assert evaluate_window_open(True, 0, False, 0, 0)
    assert not evaluate_window_open(False, 0, True, 0, 0)


def test_heating_season_off_uses_thermostat_minimum_or_frost_floor() -> None:
    off = _decide(schedule_active=True, heating_season=False, off_temperature=5.0)
    assert off.mode == "season_off"
    assert off.target_temperature == 5.0

    frost = _decide(
        schedule_active=True,
        heating_season=False,
        off_temperature=5.0,
        frost_protection_temperature=12.0,
    )
    assert frost.mode == "season_off"
    assert frost.target_temperature == 12.0


def test_calibration_offset_follows_valve_error_and_is_bounded() -> None:
    assert calibration_offset(20.0, 23.0, 10.0) == 3.0
    assert calibration_offset(21.0, 20.0, 10.0) == -1.0
    assert calibration_offset(10.0, 40.0, 10.0) == 10.0


def test_valve_maintenance_runs_weekly_in_its_hour() -> None:
    now = datetime(2026, 10, 12, 9, 30, tzinfo=UTC)
    assert valve_maintenance_due(None, now, 11, 7, 11)
    assert not valve_maintenance_due(None, now, 10, 7, 11)
    assert not valve_maintenance_due(now - timedelta(days=3), now, 11, 7, 11)
    # A week minus a few minutes still counts, so the hour does not drift.
    assert valve_maintenance_due(
        now - timedelta(days=7, minutes=-5), now, 11, 7, 11
    )


def test_valve_maintenance_opens_then_closes_then_ends() -> None:
    start = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    assert valve_maintenance_phase(start, start, 300) == "open"
    assert valve_maintenance_phase(start, start + timedelta(seconds=301), 300) == "close"
    assert valve_maintenance_phase(start, start + timedelta(seconds=600), 300) is None


def test_hysteresis_keeps_previous_value_for_small_changes() -> None:
    assert apply_hysteresis(None, 2.3, 0.5) == 2.3
    assert apply_hysteresis(2.0, 2.4, 0.5) == 2.0
    assert apply_hysteresis(2.0, 2.5, 0.5) == 2.5
    assert apply_hysteresis(2.0, 1.4, 0.5) == 1.4
    assert apply_hysteresis(2.0, 2.1, 0.0) == 2.1


def test_fallback_room_temperature_averages_available_readings() -> None:
    assert fallback_room_temperature([18.6, None, 19.2]) == 18.9
    assert fallback_room_temperature([None, None]) is None
    assert fallback_room_temperature([]) is None


def _boost_decision(**overrides):
    values = dict(
        now=datetime(2026, 1, 1, 12, tzinfo=UTC),
        schedule_active=False,
        next_event=None,
        room_temperature=19.0,
        outdoor_temperature=5.0,
        comfort_temperature=21.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        boost_temperature=24.0,
    )
    values.update(overrides)
    return decide_heating_target(**values)


def test_boost_wins_over_schedule_presence_and_heating_limit() -> None:
    decision = _boost_decision(present=False, heating_limit_reached=True)
    assert decision.mode == "boost"
    assert decision.target_temperature == 24.0


def test_boost_yields_to_open_window_and_season_off() -> None:
    assert _boost_decision(window_open=True).mode == "window"
    assert _boost_decision(heating_season=False).mode == "season_off"
    assert _boost_decision(boost_temperature=None).mode != "boost"


def test_schedule_comfort_temperature_accepts_only_plausible_numbers() -> None:
    assert schedule_comfort_temperature(22) == 22.0
    assert schedule_comfort_temperature("21.5") == 21.5
    assert schedule_comfort_temperature(None) is None
    assert schedule_comfort_temperature("warm") is None
    assert schedule_comfort_temperature(45) is None


def test_preheat_is_timed_with_the_forecast_temperature() -> None:
    now = datetime(2026, 10, 12, 4, 0, tzinfo=UTC)
    event = now + timedelta(minutes=100)
    forecast = [
        {"datetime": (now + timedelta(hours=h)).isoformat(), "temperature": 10 - h * 4}
        for h in range(4)
    ]
    # Nearest point to the comfort start (in 1 h 40 min) is the one in 2 h.
    assert select_forecast_temperature(forecast, event, now) == 2
    assert select_forecast_temperature(forecast, now - timedelta(hours=1), now) is None
    assert select_forecast_temperature([{"datetime": "x", "temperature": 3}], event, now) is None

    common = dict(
        now=now, schedule_active=False, next_event=event, room_temperature=19.0,
        outdoor_temperature=10.0, comfort_temperature=21.0, eco_temperature=18.0,
        heating_rate_c_per_hour=1.2, max_preheat_minutes=240,
    )
    mild = decide_heating_target(**common)
    cold = decide_heating_target(**common, forecast_temperature=-5.0)
    # A cold morning starts earlier than the current mild reading suggests.
    assert cold.preheat_minutes > mild.preheat_minutes
    assert cold.mode == "preheat"


def _absent_decision(**kwargs):
    now = datetime.now(UTC)
    base = dict(
        now=now,
        schedule_active=True,
        next_event=now + timedelta(hours=2),
        room_temperature=19.0,
        outdoor_temperature=5.0,
        comfort_temperature=22.0,
        eco_temperature=18.0,
        heating_rate_c_per_hour=1.0,
        max_preheat_minutes=120,
        present=False,
    )
    base.update(kwargs)
    return decide_heating_target(**base)


def test_reduced_comfort_applies_only_while_the_schedule_asks_for_comfort() -> None:
    reduced = ("Raum leer – Komfort minus 3 °C", 19.0)
    decision = _absent_decision(reduced_comfort=reduced)
    assert (decision.mode, decision.target_temperature) == ("away_reduced", 19.0)
    off = _absent_decision(reduced_comfort=reduced, schedule_active=False)
    assert (off.mode, off.target_temperature) == ("away", 18.0)
    limit = _absent_decision(reduced_comfort=reduced, heating_limit_reached=True)
    assert limit.mode == "away"
    window = _absent_decision(reduced_comfort=reduced, window_open=True)
    assert window.mode == "window"


def test_long_absence_wins_over_reduced_comfort() -> None:
    decision = _absent_decision(
        reduced_comfort=("x", 19.0), long_absence_temperature=10.0
    )
    assert (decision.mode, decision.target_temperature) == ("long_absence", 10.0)
    present = _absent_decision(present=True, long_absence_temperature=10.0)
    assert present.mode == "comfort"


def test_maintenance_opens_valves_despite_window_and_season() -> None:
    decision = _absent_decision(
        maintenance_temperature=30.0,
        window_open=True,
        heating_season=False,
        frost_protection_temperature=8.0,
    )
    assert (decision.mode, decision.target_temperature) == ("maintenance", 30.0)


def test_aggressive_setpoint_pushes_outside_the_band() -> None:
    assert aggressive_setpoint(21.0, 20.0, 0.3, 2.0) == 23.0
    assert aggressive_setpoint(21.0, 21.2, 0.3, 2.0) == 21.0
    assert aggressive_setpoint(21.0, 21.5, 0.3, 2.0) == 19.0


def test_schedule_selection_by_id_number_or_name() -> None:
    schedules = [
        ("schedule.school", "Schulzeit"),
        ("schedule.holidays", "Ferien Leonie"),
    ]
    assert select_schedule(schedules, None) == "schedule.school"
    assert select_schedule(schedules, "schedule.holidays") == "schedule.holidays"
    assert select_schedule(schedules, "2") == "schedule.holidays"
    assert select_schedule(schedules, "ferien") == "schedule.holidays"
    assert select_schedule(schedules, "unbekannt") == "schedule.school"


def test_calendar_description_carries_a_temperature() -> None:
    assert calendar_temperature("Ferien\ntemperature: 22,5") == 22.5
    assert calendar_temperature("Temperature: 19") == 19.0
    assert calendar_temperature("keine Angabe") is None
    assert calendar_temperature(None) is None
    assert calendar_temperature("temperature: 80") is None


def test_temperature_trend_is_a_slope_per_hour() -> None:
    start = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
    samples = [(start + timedelta(minutes=m), 20.0 + m / 60) for m in range(0, 31, 5)]
    assert temperature_trend(samples, 600) == 1.0
    assert temperature_trend(samples[:2], 600) is None
    assert temperature_trend([], 600) is None


# --- 0.8.0 ---------------------------------------------------------------

from custom_components.dynamic_heating.logic import (  # noqa: E402
    external_temperature_due,
    match_schedule,
    mean_forecast_temperature,
    mean_history_temperature,
    name_temperature,
    paused_features,
    plausible_temperature,
)

_DUE = {
    "min_change": 0.11,
    "plateau_change": 0.05,
    "plateau_tolerance": 0.02,
    "plateau_seconds": 120,
    "resend_seconds": 1800,
}


def test_external_temperature_sends_big_changes_at_once() -> None:
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    assert external_temperature_due(None, None, 20.0, now, **_DUE) == (True, None)
    last = (20.0, now)
    assert external_temperature_due(last, None, 20.12, now, **_DUE) == (True, None)
    # Half an hour later the value goes out again even unchanged.
    later = now + timedelta(minutes=30)
    assert external_temperature_due(last, None, 20.0, later, **_DUE)[0] is True


def test_external_temperature_ignores_flicker_and_waits_for_a_plateau() -> None:
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    last = (20.0, now)
    # Noise below the plateau change is never sent.
    assert external_temperature_due(last, None, 20.04, now, **_DUE) == (False, None)
    # A small change starts a plateau ...
    due, pending = external_temperature_due(last, None, 20.08, now, **_DUE)
    assert due is False and pending == (20.08, now)
    # ... a jump inside it restarts the plateau ...
    later = now + timedelta(seconds=60)
    due, pending = external_temperature_due(last, pending, 20.05, later, **_DUE)
    assert due is False and pending == (20.05, later)
    # ... and once stable for two minutes it is sent.
    much_later = later + timedelta(seconds=121)
    assert external_temperature_due(
        last, pending, 20.06, much_later, **_DUE
    ) == (True, None)


def test_forecast_and_history_averages() -> None:
    now = datetime(2026, 10, 11, 12, tzinfo=UTC)
    forecast = [
        {"datetime": (now + timedelta(hours=hour)).isoformat(), "temperature": 10 + hour % 2 * 10}
        for hour in range(48)
    ]
    assert mean_forecast_temperature(forecast, now, 48, 12) == 15.0
    # Too few points: no average.
    assert mean_forecast_temperature(forecast[:5], now, 48, 12) is None
    samples = [(now + timedelta(hours=hour), 10.0 + hour) for hour in range(7)]
    assert mean_history_temperature(samples, 6 * 3600) == 13.0
    assert mean_history_temperature(samples[:3], 6 * 3600) is None


def test_plausible_room_temperature() -> None:
    assert plausible_temperature(20.5, -5, 45)
    assert not plausible_temperature(-40.0, -5, 45)
    assert not plausible_temperature(327.67, -5, 45)
    assert not plausible_temperature(None, -5, 45)


def test_paused_features_from_block_data_or_description() -> None:
    features = {"window": ("fenster", "window"), "presence": ("anwesenheit", "presence")}
    assert paused_features({"Fenster": "aus"}, None, features) == {"window"}
    assert paused_features({}, "anwesenheit: off\nfenster: an", features) == {"presence"}
    assert paused_features({"window": False}, None, features) == {"window"}
    assert paused_features({"temperature": 22}, None, features) == set()


def test_name_temperature() -> None:
    assert name_temperature("Party 23") == 23.0
    assert name_temperature("Gäste 21,5") == 21.5
    assert name_temperature("Party") is None
    assert name_temperature("Timer 99") is None


def test_match_schedule_without_fallback() -> None:
    schedules = [("schedule.alltag", "Alltag"), ("schedule.ferien", "Ferien Wohnzimmer")]
    assert match_schedule(schedules, "Ferien") == "schedule.ferien"
    assert match_schedule(schedules, "schedule.alltag") == "schedule.alltag"
    assert match_schedule(schedules, "Homeoffice") is None
    assert match_schedule(schedules, None) is None


def test_overshoot_makes_preheating_start_later() -> None:
    now = datetime(2026, 10, 11, 6, tzinfo=UTC)
    common = {
        "now": now,
        "schedule_active": False,
        "next_event": now + timedelta(minutes=100),
        "room_temperature": 19.0,
        "outdoor_temperature": 10.0,
        "comfort_temperature": 21.0,
        "eco_temperature": 18.0,
        "heating_rate_c_per_hour": 1.0,
        "max_preheat_minutes": 240,
    }
    # Two degrees at 1 °C/h plus margin (130 min): preheating starts now ...
    assert decide_heating_target(**common).mode == "preheat"
    # ... but with 1 °C overshoot the room only needs to be heated to 20 °C.
    assert decide_heating_target(**common, overshoot=1.0).mode == "eco"


def test_maintenance_on_a_weekday() -> None:
    monday = datetime(2026, 10, 12, 9, tzinfo=UTC)
    assert valve_maintenance_due(None, monday, 11, 7, 11, 0, 0)
    assert not valve_maintenance_due(None, monday, 11, 7, 11, 1, 0)
    # Already ran an hour ago today: not again.
    assert not valve_maintenance_due(
        monday - timedelta(hours=1), monday, 11, 7, 11, 0, 0
    )
