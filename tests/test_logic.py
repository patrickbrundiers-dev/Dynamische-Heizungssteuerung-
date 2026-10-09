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
    mild = calculate_lead_minutes(18.0, 21.0, 1.0, outdoor_temperature=15.0)
    cold = calculate_lead_minutes(18.0, 21.0, 1.0, outdoor_temperature=-5.0)
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
