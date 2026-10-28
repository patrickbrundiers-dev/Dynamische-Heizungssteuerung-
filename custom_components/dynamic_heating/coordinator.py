"""State collection, learning and guarded thermostat control."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from collections.abc import Callable
from typing import Any

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Context, Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WARM_UP_DURATION,
    CONF_WARM_UP_STEP,
    DEFAULT_WARM_UP_DURATION,
    DEFAULT_WARM_UP_STEP,
    CONF_EARLY_STOP,
    CONF_LEARN_USAGE,
    CONF_PREHEAT_WHEN_HOME,
    CONF_RECOVERY_LIMIT,
    CONF_ROOM_EMPTY_GRACE,
    CONF_ROOM_EMPTY_RECOVERY,
    CONF_ROOM_MODEL,
    CONF_SOLAR_RADIATION_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DEFAULT_EARLY_STOP,
    DEFAULT_LEARN_USAGE,
    DEFAULT_PREHEAT_WHEN_HOME,
    DEFAULT_RECOVERY_LIMIT,
    DEFAULT_ROOM_EMPTY_GRACE,
    DEFAULT_ROOM_EMPTY_RECOVERY,
    DEFAULT_ROOM_MODEL,
    EARLY_STOP_DROP,
    MODEL_HISTORY_DAYS,
    RECOVERY_REACH_MARGIN,
    SOLAR_PAUSE_MIN_GAIN,
    BLOCK_PRESENCE_KEYS,
    BLOCK_WINDOW_KEYS,
    CONF_COMMAND_DELAY,
    CONF_DOOR_CLOSE_DELAY,
    CONF_DOOR_ENTITIES,
    CONF_DOOR_OPEN_DELAY,
    CONF_FOLLOW_HOUSE_CALENDAR,
    CONF_FORCE_COMFORT_ENTITIES,
    CONF_FORCE_ECO_ENTITIES,
    CONF_HEATING_LIMIT_AVERAGE,
    CONF_HEATING_LIMIT_FALLBACK_OFF,
    CONF_OUTDOOR_WARMER_MARGIN,
    CONF_OUTDOOR_WARMER_STOP,
    CONF_HUMIDITY_ENTITY,
    CONF_MAINTENANCE_DURATION,
    CONF_MAINTENANCE_HOUR,
    CONF_MAINTENANCE_WEEKDAY,
    CONF_WINDOW_CHANGE,
    CONF_ZONE_WINDOW_CLOSE_DELAY,
    CONF_ZONE_WINDOW_ENTITIES,
    CONF_ZONE_WINDOW_OPEN_DELAY,
    DEFAULT_COMMAND_DELAY,
    DEFAULT_DOOR_CLOSE_DELAY,
    DEFAULT_DOOR_OPEN_DELAY,
    DEFAULT_FOLLOW_HOUSE_CALENDAR,
    DEFAULT_HEATING_LIMIT_AVERAGE,
    DEFAULT_OUTDOOR_WARMER_MARGIN,
    DEFAULT_OUTDOOR_WARMER_STOP,
    DEFAULT_ZONE_WINDOW_CLOSE_DELAY,
    DEFAULT_ZONE_WINDOW_OPEN_DELAY,
    EVENT_DEVICE_TRIGGER,
    EXTERNAL_TEMPERATURE_PLATEAU_CHANGE,
    EXTERNAL_TEMPERATURE_PLATEAU_SECONDS,
    EXTERNAL_TEMPERATURE_PLATEAU_TOLERANCE,
    HEATING_LIMIT_AVERAGE_HOURS,
    OUTDOOR_WARMER_HYSTERESIS,
    HEATING_LIMIT_MIN_FORECAST_POINTS,
    HUMIDITY_HIGH_PERCENT,
    HUMIDITY_HYSTERESIS,
    MAINTENANCE_ANY_DAY,
    MAX_OVERSHOOT,
    OUTDOOR_HISTORY_INTERVAL_SECONDS,
    OUTDOOR_HISTORY_MIN_SPAN_SECONDS,
    OVERSHOOT_DROP,
    OVERSHOOT_MAX_SECONDS,
    ROOM_TEMPERATURE_PLAUSIBLE_MAX,
    ROOM_TEMPERATURE_PLAUSIBLE_MIN,
    TARGET_REACHED_MARGIN,
    TRIGGER_HEATING_STARTED,
    TRIGGER_HEATING_STOPPED,
    TRIGGER_HUMIDITY_HIGH,
    TRIGGER_TARGET_REACHED,
    TRIGGER_WINDOW_CLOSED,
    TRIGGER_WINDOW_OPENED,
    VALVE_DIVERGENCE_MIN,
    VALVE_DIVERGENCE_SECONDS,
    WINDOW_CHANGE_DISCARD,
    CALENDAR_TEMPERATURE_KEY,
    CONF_ADDITIONAL_WINDOW_ENTITIES,
    CONF_LOCK_VALVES,
    ROOM_OFFSET_MAX,
    ROOM_OFFSET_MIN,
    TREND_MIN_SPAN_SECONDS,
    TREND_WINDOW_SECONDS,
    VALVE_OFFSET_MAX,
    VALVE_OFFSET_MIN,
    CONF_ADDITIONAL_SCHEDULE_ENTITIES,
    CONF_AGGRESSIVE_OFFSET,
    CONF_AGGRESSIVE_RANGE,
    CONF_AWAY_OFFSET,
    CONF_AWAY_SCHEDULE_MODE,
    CONF_DISABLE_TRV_WINDOW_DETECTION,
    CONF_ECO_SCHEDULE_ENTITY,
    CONF_FROST_AFTER_ABSENCE,
    CONF_SYNC_MANUAL_CHANGE,
    DEFAULT_AGGRESSIVE_OFFSET,
    DEFAULT_FROST_AFTER_ABSENCE,
    DEFAULT_SYNC_MANUAL_CHANGE,
    EVENT_MODE_CHANGED,
    QUICK_MAINTENANCE,
    QUICK_LABELS,
    TRV_WINDOW_DETECTION_SUFFIX,
    CONF_AWAY_TEMPERATURE,
    CALIBRATION_INTERVAL_SECONDS,
    CONF_ADDITIONAL_CLIMATE_ENTITIES,
    CONF_CALIBRATION,
    CONF_BOOST_DURATION,
    CONF_BOOST_TEMPERATURE,
    CONF_EXTERNAL_TEMPERATURE,
    DEFAULT_BOOST_DURATION,
    DEFAULT_BOOST_TEMPERATURE,
    SCHEDULE_TEMPERATURE_ATTRIBUTE,
    CONF_HYSTERESIS,
    EXTERNAL_TEMPERATURE_MIN_CHANGE,
    EXTERNAL_TEMPERATURE_RESEND_SECONDS,
    EXTERNAL_TEMPERATURE_RETRIES,
    EXTERNAL_TEMPERATURE_RETRY_SECONDS,
    EXTERNAL_TEMPERATURE_VERIFY_SECONDS,
    EXTERNAL_TEMPERATURE_VERIFY_TOLERANCE,
    HEATING_WATCHDOG_GAP,
    MODEL_ASKING_DEMAND,
    SETBACK_FLOOR_STEP,
    THERMOSTAT_UNREACHABLE_GRACE_SECONDS,
    HEATING_WATCHDOG_MIN_RISE,
    HEATING_WATCHDOG_SECONDS,
    IGNORED_PROBLEM_ENTITY_SUFFIXES,
    LOW_BATTERY_PERCENT,
    BATTERY_HISTORY_DAYS,
    CONF_NOTIFY_AWAY,
    CONF_PREHEAT_EXTENSION,
    CONF_PUNCTUALITY,
    CONF_VALVE_FALLBACK,
    CONF_RADIATOR_POWER,
    RADIATOR_POWER_PER_THERMOSTAT_W,
    SAVINGS_DAYS,
    CONF_VALVE_SENSOR_CALIBRATION,
    CONF_HOLD_BEFORE_PAUSE,
    CONF_MORNING_REPORT,
    DEFAULT_DEVICE_NAME,
    DEFAULT_NOTIFY_AWAY,
    DEFAULT_PREHEAT_EXTENSION,
    DEFAULT_PUNCTUALITY,
    DEFAULT_VALVE_FALLBACK,
    DEFAULT_VALVE_SENSOR_CALIBRATION,
    DEFAULT_HOLD_BEFORE_PAUSE,
    DEFAULT_MORNING_REPORT,
    MODE_SWITCH_GRACE_SECONDS,
    MORNING_REPORT_HOUR,
    MORNING_REPORT_SHORTFALL,
    OUTDOOR_FALLBACK_GRACE_SECONDS,
    VALVE_SENSOR_CALIBRATION_INTERVAL,
    VALVE_SENSOR_CALIBRATION_WINDOW,
    LEARN_RUN_DURATION_SECONDS,
    LEARN_RUN_RISE,
    NOTIFY_ACTION_PREFIX,
    NOTIFY_AWAY_SECONDS,
    NOTIFY_SNOOZE_SECONDS,
    CONF_NOTIFY_SERVICE,
    NOTIFY_FROST_FALLBACK_TEMPERATURE,
    NOTIFY_FROST_MARGIN,
    NOTIFY_PROBLEM_DELAY_SECONDS,
    NOTIFY_WINDOW_SECONDS,
    HEAT_DEMAND_FULL_GAP,
    HEAT_DEMAND_KEYS,
    HOUSE_AWAY,
    HOUSE_DATA_KEY,
    HOUSE_VACATION,
    CONF_ACTIVITY_TEMPERATURE,
    CONF_HOME_TEMPERATURE,
    CONF_SLEEP_TEMPERATURE,
    DEFAULT_ACTIVITY_TEMPERATURE,
    DEFAULT_HOME_TEMPERATURE,
    DEFAULT_SLEEP_TEMPERATURE,
    QUICK_ACTIVITY,
    QUICK_AUTO,
    QUICK_AWAY,
    QUICK_DURATIONS,
    QUICK_HOME,
    QUICK_MANUAL,
    QUICK_SLEEP,
    QUICK_MODES,
    QUICK_MORNING_HOUR,
    QUICK_UNTIL_1H,
    QUICK_UNTIL_3H,
    QUICK_UNTIL_FOREVER,
    QUICK_UNTIL_MORNING,
    QUICK_UNTIL_SCHEDULE,
    QUICK_BOOST,
    QUICK_COMFORT,
    QUICK_ECO,
    ROOM_FALLBACK_GRACE_SECONDS,
    ROOM_SENSOR_STALE_SECONDS,
    DEFAULT_HYSTERESIS,
    CONF_VALVE_MAINTENANCE,
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_FROST_PROTECTION_TEMPERATURE,
    CONF_HEATING_LIMIT_TEMPERATURE,
    CONF_HEATING_SEASON_ENTITY,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_TEMPERATURE,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_PERSON_ENTITIES,
    CONF_GUEST_ENTITY,
    CONF_ENTER_HOME_DURATION,
    CONF_LEAVING_HOME_DURATION,
    CONF_PROXIMITY_ENTITY,
    CONF_PROXIMITY_ZONE,
    CONF_PROXIMITY_DIRECTION_ENTITY,
    CONF_PROXIMITY_MAX_AGE,
    CONF_PROXIMITY_DURATION,
    CONF_PROXIMITY_DISTANCE,
    CONF_PRESENCE_SCHEDULE_ENTITY,
    CONF_PRESENCE_ON_DURATION,
    CONF_PRESENCE_OFF_DURATION,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WINDOW_DROP_DETECTION,
    CONF_WINDOW_ENTITY,
    WINDOW_DROP_DEGREES,
    WINDOW_DROP_HOLD_SECONDS,
    WINDOW_DROP_SECONDS,
    CONF_WEATHER_ENTITY,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_COOLING_RATE,
    DEFAULT_ECO_TEMPERATURE,
    DEFAULT_ENTER_HOME_DURATION,
    DEFAULT_LEAVING_HOME_DURATION,
    PREHEAT_LEAVE_GRACE_SECONDS,
    DEFAULT_PROXIMITY_DURATION,
    DEFAULT_PROXIMITY_DISTANCE,
    DEFAULT_PROXIMITY_MAX_AGE,
    MAX_HEATING_SAMPLE_SECONDS,
    MAX_COOLING_SAMPLE_SECONDS,
    MAX_HEATING_SAMPLE_DELTA,
    MAX_COOLING_SAMPLE_DELTA,
    MIN_SAMPLE_DELTA,
    INFERRED_HEATING_MARGIN,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
    HEATING_LIMIT_HYSTERESIS,
    MAX_CALIBRATION_OFFSET,
    VALVE_MAINTENANCE_HOUR,
    VALVE_MAINTENANCE_INTERVAL_DAYS,
    VALVE_MAINTENANCE_PHASE_SECONDS,
    SETPOINT_RESEND_SECONDS,
    FORECAST_EVALUATION_GRACE_SECONDS,
    DEFAULT_PRESENCE_ON_DURATION,
    DEFAULT_PRESENCE_OFF_DURATION,
    DEFAULT_HEATING_RATE,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DOMAIN,
    MAX_LEARNED_COOLING_RATE,
    MAX_LEARNED_HEATING_RATE,
    MIN_COOLING_SAMPLE_SECONDS,
    MIN_LEARNED_COOLING_RATE,
    MIN_LEARNED_HEATING_RATE,
    MIN_SAMPLE_SECONDS,
    CONF_MANUAL_MAX_TEMPERATURE,
    CONF_MANUAL_MAX_DURATION,
    CONF_SCHOOL_FREE_ENTITY,
    CONF_SCHOOL_FREE_SCHEDULE,
    CONF_WORKDAY_ENTITY,
    CONF_SCHOOL_HOLIDAY_CALENDAR,
    SCHOOL_HOLIDAY_WORDS,
    CONF_SHOWER_LEARNING,
    DEFAULT_SHOWER_LEARNING,
    SHOWER_RISE_PERCENT,
    SHOWER_RISE_WINDOW_SECONDS,
    SHOWER_COOLDOWN_SECONDS,
    SHOWER_MODEL_PAUSE_SECONDS,
    SHOWER_HISTORY_DAYS,
    SHOWER_LEAD_MINUTES,
    FOREIGN_CONTROL_NOTIFY_SECONDS,
)
from .logic import (
    HeatingDecision,
    TrendSample,
    external_temperature_due,
    match_schedule,
    mean_forecast_temperature,
    mean_history_temperature,
    name_temperature,
    paused_features,
    plausible_temperature,
    calendar_temperature,
    temperature_trend,
    aggressive_setpoint,
    select_schedule,
    apply_hysteresis,
    calibration_offset,
    fallback_room_temperature,
    calculate_lead_minutes,
    schedule_comfort_temperature,
    decide_heating_target,
    evaluate_heating_limit,
    evaluate_outdoor_warmer,
    evaluate_window_open,
    detect_temperature_drop,
    select_forecast_condition,
    select_forecast_temperature,
    valve_maintenance_due,
    valve_maintenance_phase,
)
from .model import (
    TRUSTED_SAMPLES,
    CoolingCorrection,
    ModelView,
    RoomModel,
    SampleCollector,
    UsageProfile,
    heat_load,
    seed_room_model,
    solar_to_kw,
    wind_to_ms,
)
from .radiator import (
    COLD,
    SUPPLY_COLD,
    SUPPLY_IDLE,
    SUPPLY_PARTLY,
    SUPPLY_VERSION,
    SUPPLY_WAITING,
    SUPPLY_WARM,
    RadiatorStats,
    RadiatorTracker,
    RoomResponse,
    SupplyProfile,
    IDLE,
    balance_verdict,
    combined_supply,
    judged_supply,
    room_supply,
)
from .battery import BatteryWatch
from .routine import (
    HABIT_DAYS,
    TUYA_DAYS,
    Habits,
    ShowerWatch,
    schedule_covers,
    showers_from_history,
    HeatStats,
    Punctuality,
    fallback_schedule,
    tuya_week_schedule,
)
from .pending_push import hold_if_missing
from .plan import (
    CHECK_ALPHA,
    CHECK_HOURS,
    Block,
    blocks_from_schedule,
    blocks_switched_at,
    compare_plans,
    shifted_blocks,
    savings_text,
    simulate,
    summary as plan_summary,
    temperature_at,
)

# Bumped when the room model must forget what it learned: 2 = 0.9.3, which
# no longer learns from hours in which the radiators stayed cold.
ROOM_MODEL_VERSION = 2
# Bumped when learning from the recorder improved: 1 = 0.9.4, which also
# learns rooms without recorded heat demand (estimated from valve setpoints);
# 2 = 0.9.7, which counts hours with warm radiators as heating hours. A model
# that is not ready yet starts over from the recorder (no hour twice).
SEED_VERSION = 2
# A room warming this much faster (°C/h) than the model's full heat shows the
# model is wrong for now: no "reachable today" from it.
REACH_TREND_MARGIN = 0.2
# The forecast's current error is carried this many hours ahead, fading out.
FORECAST_CORRECTION_HOURS = 12
# The self-test runs this long after a start, and again while it fails.
SELFTEST_DELAY = timedelta(minutes=10)
SELFTEST_RETRY = timedelta(hours=1)
# A valve fed with the room temperature should show it within this much.
SELFTEST_VALVE_TOLERANCE = 0.5
# The day plan is recalculated this often; the schedule's week read this often.
PLAN_INTERVAL = timedelta(minutes=15)
SCHEDULE_WEEK_INTERVAL = timedelta(minutes=30)
# Modes the day plan describes; in others it is not checked against the room.
_PLAN_MODES = frozenset({"comfort", "eco", "preheat", "early_stop"})

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _WrittenSetpoint:
    """Last setpoint written successfully to one thermostat."""

    target: float
    at: datetime
    # True once the thermostat reported the value; only then can a different
    # setpoint be attributed to a manual change.
    confirmed: bool = False
_INVALID_STATES = {"unknown", "unavailable", None}
# Targets that the room offset leaves alone: protection and fixed setpoints.
# Modes that aim for comfort; the status tells when comfort is out of reach.
_REACH_MODES = frozenset({"comfort", "preheat", "boost", "away_reduced"})
_NO_OFFSET_MODES = frozenset(
    {
        "season_off",
        "outdoor_warm",
        "maintenance",
        "window",
        "quick_off",
        "quick_manual",
        "long_absence",
        "house_vacation",
    }
)


def _as_float(state: State | None) -> float | None:
    """Read a numeric state without raising on unavailable or malformed input."""
    if state is None or state.state in _INVALID_STATES:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _as_number(value: object) -> float | None:
    """A finite number from an attribute value, else None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def foreign_source(hass: HomeAssistant, context: Context | None) -> tuple[str, str] | None:
    """The automation or script whose run made a service call, if any.

    An automation writes its state (last_triggered) with the context its
    actions then run in, so the call's context names it.
    """
    if context is None:
        return None
    ids = {context.id, context.parent_id} - {None}
    for state in hass.states.async_all(("automation", "script")):
        if state.context.id in ids:
            return state.entity_id, state.name
    return None


def _foreign_issue_id(entry_id: str, source_id: str) -> str:
    return f"foreign_control_{entry_id}_{source_id.replace('.', '_')}"


class DynamicHeatingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate learning, schedule prediction and optional thermostat control."""

    # Moment (monotonic clock) of the last command to any valve of any room,
    # so the command delay also spaces out several rooms switching at once.
    _last_command: float | None = None

    def __init__(self, hass: HomeAssistant, config: dict[str, Any], entry_id: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            # Presence and geofencing use short debounce durations; poll often
            # enough to honour them without creating unbounded service traffic.
            update_interval=timedelta(seconds=10),
        )
        self.hass = hass
        self.config = config
        self.entry_id = entry_id
        self.enabled = False
        # True while the room sensor is unavailable and the thermostats'
        # own readings stand in for it.
        self._room_fallback = False
        # End of a running boost (UTC), None when no boost is active.
        self.boost_until: datetime | None = None
        self.heating_rate = DEFAULT_HEATING_RATE
        self.cooling_rate = DEFAULT_COOLING_RATE
        # Heating and cooling right now as the room model sees them; once it is
        # ready they replace the rates measured by the old sample learner.
        self._model_rates: tuple[float, float] | None = None
        self._store = Store(hass, 1, f"{DOMAIN}_{entry_id}_learning")
        self._heating_sample = TrendSample()
        self._cooling_sample = TrendSample()
        # Comfort event for which preheating already started (see logic).
        self._preheat_event: datetime | None = None
        # Kept between updates so the heating limit releases with hysteresis.
        self._heating_limit_reached = False
        self._outdoor_warmer = False
        # Debounced window state, kept so the close delay can run out.
        self._window_open = False
        # Window detection from a temperature drop: recent room readings and
        # until when the room is held as if a window were open.
        self._temperature_samples: list[tuple[datetime, float]] = []
        self._drop_until: datetime | None = None
        # Per thermostat: last setpoint written successfully, to avoid
        # re-sending it every update to thermostats that store a slightly
        # different value and to detect manual changes.
        self._written: dict[str, _WrittenSetpoint] = {}
        # Per thermostat: calibration offset and when it was computed.
        self._calibration: dict[str, tuple[float, datetime]] = {}
        # Thermostats currently regulating on the room temperature we feed
        # them, and the last value sent to each external-temperature input.
        self._external_fed: set[str] = set()
        self._external_sent: dict[str, tuple[float, datetime]] = {}
        # Value sent again because the valve did not show it: how often, when.
        self._external_retried: dict[str, tuple[float, int, datetime]] = {}
        # Valve maintenance: last start (persisted) and the running one.
        self._maintenance_last: datetime | None = None
        self._maintenance_started: datetime | None = None
        # (mode, target) during which a manual setpoint change is respected.
        self._manual_override: tuple[str, float] | None = None
        self._forecast_items: list[dict[str, Any]] = []
        self._forecast_fetched_at: datetime | None = None
        # Per proximity source: since when it has been approaching.
        self._proximity_approaching: dict[str, datetime] = {}
        self._proximity_distance_m: float | None = None
        self._proximity_direction: str | None = None
        self._proximity_age_seconds: float | None = None
        self._proximity_status = "Proximity nicht konfiguriert"
        # Last settled decision of the presence sensor; held while a new
        # sensor state is still inside its on/off stability window.
        self._sensor_present: bool | None = None
        # Heating watchdog: since when the room has been well below its target
        # without warming up, and the temperature at that moment.
        self._shortfall_since: datetime | None = None
        self._shortfall_temperature: float | None = None
        self.heating_problem = False
        self.heating_problem_detail: str | None = None
        # Quick selection: the mode picked by hand and when it ends (UTC);
        # a boost is tracked by boost_until instead.
        self.quick_mode = QUICK_AUTO
        self.quick_until: datetime | None = None
        self.quick_duration = QUICK_UNTIL_SCHEDULE
        # Temperature of the manual mode (set on the room thermostat entity).
        self.quick_temperature: float | None = None
        self._next_event: datetime | None = None
        # Comfort schedule picked with the "Zeitplan" select (None = first).
        self.schedule_choice: str | None = None
        # Why nobody counts as present: "none", "room_empty" (somebody is
        # home, the room is empty) or "house_empty"; and since when nobody
        # has been home, for frost protection after a long absence.
        self._absence = "none"
        self._absent_since: datetime | None = None
        # When each person of the room was last seen at home (leaving delay).
        self._seen_home: dict[str, datetime] = {}
        # School-free days (runde 10): today's state as last followed, and
        # whether tomorrow is free (asked once a day).
        self._school_free: bool | None = None
        self._free_tomorrow_cache: tuple[Any, bool] | None = None
        self._tomorrow_note: str | None = None
        # Weeks of the schedule helpers as read for the day plan.
        self._schedule_weekly: dict[str, dict] = {}
        # A hand change above the cap: the value that was asked for.
        self._manual_capped_from: float | None = None
        # Room offset (all targets) and per-valve offsets, both persisted.
        self.room_offset = 0.0
        self.valve_offsets: dict[str, float] = {}
        # Room readings of the last half hour for the temperature trend.
        self._trend_samples: list[tuple[datetime, float]] = []
        # Last (mode, target) announced on the event bus.
        self._last_event_key: tuple[Any, Any] | None = None
        # Per thermostat switch: when turning off its own window detection
        # was last tried, so a failing device is not called every cycle.
        self._trv_window_attempts: dict[str, datetime] = {}
        # Mode, boost, alerts and the presence decision survive a restart.
        self._state_store = Store(hass, 1, f"{DOMAIN}_{entry_id}_state")
        self._saved_state: dict[str, Any] | None = None
        self._week_saved_at: datetime | None = None
        # Figures for the weekly report since its last sending.
        self._week = self._empty_week()
        self._week_last: datetime | None = None
        self._week_window = False
        # Notifications: since when each alert condition holds and whether
        # it was already sent.
        self._alerts: dict[str, tuple[datetime, bool]] = {}
        self._proximity_categories: dict[str, str] = {}
        self._proximity_metrics_dirty = False
        self._proximity_last_state_update: datetime | None = None
        self._proximity_last_update_at: str | None = None
        self._proximity_updates_seen = 0
        self._proximity_update_interval_count = 0
        self._proximity_average_update_interval_s: float | None = None
        self._proximity_stale_events = 0
        self._proximity_invalid_events = 0
        self._proximity_out_of_range_events = 0
        self._proximity_approach_attempts = 0
        self._proximity_confirmed_approaches = 0

        # The model retains only compact quality metrics, not raw location or
        # temperature histories. The pending forecast is ephemeral per event.
        self._heating_samples = 0
        self._cooling_samples = 0
        self._rejected_samples = 0
        self._last_observed_heating_rate: float | None = None
        self._last_observed_cooling_rate: float | None = None
        self._last_learning_type = "none"
        self._last_learning_status = "Noch keine Lernmessung"
        self._last_learning_sample_at: str | None = None
        self._forecast_evaluations = 0
        self._forecast_mae_c: float | None = None
        self._last_forecast_error_c: float | None = None
        self._last_forecast_predicted_temperature: float | None = None
        self._last_forecast_actual_temperature: float | None = None
        self._last_forecast_event: str | None = None
        self._last_forecast_error_at: str | None = None
        self._pending_forecast_event: datetime | None = None
        self._pending_forecast_temperature: float | None = None
        # Outdoor readings of the last two days for the heating limit.
        self._outdoor_history: list[tuple[datetime, float]] = []
        # Per external input: a small change waiting to prove it is stable.
        self._external_pending: dict[str, tuple[float, datetime]] = {}
        # Debounced state of each contact group (windows, doors, zone).
        self._contact_open: dict[str, bool] = {}
        # A room reading outside the plausible range (value, sensor) and
        # whether a Repairs issue is open for it.
        self._implausible: tuple[float, str] | None = None
        self._issue_open = False
        # Per valve: since when its setpoint differs from what was written.
        self._divergent_since: dict[str, datetime] = {}
        self._divergence: dict[str, str] = {}
        # Valves left out of control (persisted) and the ones already closed.
        self.skipped_valves: set[str] = set()
        self._skip_closed: set[str] = set()
        # What set the target last ("Zeitplan", "Raum-Thermostat", ...).
        self.last_change_source: str | None = None
        self.last_change_at: datetime | None = None
        self._pending_source: str | None = None
        # Last state of each device trigger condition (None = not known yet).
        self._trigger_state: dict[str, bool] = {}
        self._trigger_target: float | None = None
        # Overshoot: learned value, number of measurements, and the running
        # measurement (room target, peak, start) after heating stopped.
        self.overshoot = 0.0
        self._overshoot_samples = 0
        self._overshoot_track: tuple[float, float, datetime] | None = None
        self._was_heating = False
        # Valve maintenance started by hand, and valves woken up for it.
        self._maintenance_requested = False
        self._maintenance_woken: set[str] = set()
        # House calendar in effect for this room (shown in the status).
        self._house_calendar: str | None = None
        # Learned room equation, its running hourly sample and where it
        # learned last (persisted with the learning data).
        self.room_model = RoomModel()
        # How much faster the room cools without heat than the model says.
        self.cooling = CoolingCorrection()
        self._model_collector = SampleCollector()
        self._model_seeded = False
        # Whether heat reaches each radiator, and per hour of the day how
        # often the central heating delivered (persisted).
        self._radiators: dict[str, RadiatorTracker] = {}
        # Whether the room itself warms while the valves are open.
        self._response = RoomResponse()
        self.supply = SupplyProfile()
        self._supply_at: datetime | None = None
        # How often the room is used per weekday and hour (persisted).
        self.usage = UsageProfile()
        self._usage_at: datetime | None = None
        # How each radiator heats up, to compare them (persisted).
        self.radiator_stats: dict[str, RadiatorStats] = {}
        self._seed_version = 0
        # Day plan, the schedule's week behind it and how well it predicted.
        self.plan_points: list = []
        self.plan_info: dict[str, Any] = {}
        self._plan_at: datetime | None = None
        self._plan_key: tuple | None = None
        self._schedule_week: list[Block] | None = None
        self._schedule_week_key: tuple[str | None, str] | None = None
        self._schedule_week_at: datetime | None = None
        self._plan_checks: dict[datetime, float] = {}
        self._plan_check_hour: int | None = None
        self.plan_error: float | None = None
        self.plan_checked = 0
        # Self-test after a start: due time, last result, repair and push.
        self._selftest_due: datetime | None = dt_util.utcnow() + SELFTEST_DELAY
        self.selftest: dict[str, Any] | None = None
        self._selftest_issue = False
        self._selftest_sent: tuple[str, ...] = ()
        # "Kurz wärmer": its starting target, steps taken and end.
        self._warm_up_base: float | None = None
        self._warm_up_steps = 0
        self._warm_up_until: datetime | None = None
        # Somebody of the household is home (from the presence evaluation).
        self._household_present = False
        # Start of the running comfort block, for the empty-room grace time.
        self._schedule_was_active: bool | None = None
        self._comfort_ended_at: datetime | None = None
        self._started_at = dt_util.utcnow()
        self._setback_floor: float | None = None
        # Thermostat -> since when it is unreachable.
        self._unreachable_since: dict[str, datetime] = {}
        # Day (ISO) of the last comfort start told in the morning report.
        self._morning_reported: str | None = None
        self._comfort_started_at: datetime | None = None
        # Comfort block that already ended heating early, and the sun pause.
        self._early_stop_event: datetime | None = None
        self._solar_pause = False
        # Calibration run of the room model: planned start and running end.
        self.learn_run_at: datetime | None = None
        self.learn_run_until: datetime | None = None
        self._learn_run_target: float | None = None
        # Warm on time, modes picked by hand, long-term figures (persisted).
        self.punctuality = Punctuality()
        self.habits = Habits()
        # Showers seen in the room's humidity (bathrooms, runde 10).
        self.showers = Habits()
        self.batteries = BatteryWatch()
        self._battery_seed_at: datetime | None = None
        self._showers_seeded = False
        self._shower_watch = ShowerWatch(
            SHOWER_RISE_PERCENT, SHOWER_RISE_WINDOW_SECONDS, SHOWER_COOLDOWN_SECONDS
        )
        self._shower_until: datetime | None = None
        self.heat_stats = HeatStats()
        self._habits_at: datetime | None = None
        self._habit_suggestions: list[dict] = []
        # Push actions: window reminder put off, window ignored until closed,
        # heating alerts muted for today.
        self._window_ignored = False
        self._heating_muted_until: datetime | None = None
        self._unsub_actions: Callable[[], None] | None = None
        # Automations and scripts that set this room's valves (runde 10):
        # automation entity id -> what it did; when each was last pushed.
        self._unsub_foreign: Callable[[], None] | None = None
        self.foreign_control: dict[str, dict[str, Any]] = {}
        self._foreign_notified: dict[str, datetime] = {}
        # Valves whose own schedule was switched on at the last shutdown.
        self._fallback_armed: list[str] = []
        # Tuya valves switched to their own week program on shutdown.
        self._fallback_auto: list[str] = []
        # Valves switched back from their own program: when, per entity.
        self._mode_switched_at: dict[str, datetime] = {}
        self._week_written_at: datetime | None = None
        self._week_written_key: tuple | None = None
        # Valve sensor calibration: (time, room minus raw valve reading).
        self._valve_cal_samples: dict[str, list[tuple[datetime, float]]] = {}
        self._valve_cal_at: dict[str, datetime] = {}
        # (error before, change, value before) of the last write, to see that
        # the reading follows; valves whose reading does not are left alone.
        self._valve_cal_check: dict[str, tuple[float, float, float]] = {}
        self._valve_cal_off: set[str] = set()

    def _runtime_state(self) -> dict[str, Any]:
        """What has to survive a restart of Home Assistant."""
        return {
            "quick_mode": self.quick_mode,
            "quick_until": self.quick_until.isoformat() if self.quick_until else None,
            "quick_duration": self.quick_duration,
            "quick_temperature": self.quick_temperature,
            "boost_until": self.boost_until.isoformat() if self.boost_until else None,
            "alerts": {
                key: [since.isoformat(), sent]
                for key, (since, sent) in self._alerts.items()
            },
            "sensor_present": self._sensor_present,
            "schedule_choice": self.schedule_choice,
            "room_offset": self.room_offset,
            "valve_offsets": dict(self.valve_offsets),
            "absent_since": (
                self._absent_since.isoformat() if self._absent_since else None
            ),
            "skipped_valves": sorted(self.skipped_valves),
            "last_change_source": self.last_change_source,
            "last_change_at": (
                self.last_change_at.isoformat() if self.last_change_at else None
            ),
            "outdoor_history": [
                [at.isoformat(), value] for at, value in self._outdoor_history
            ],
            "shortfall": (
                [
                    self._shortfall_since.isoformat(),
                    self._shortfall_temperature,
                    self.heating_problem,
                ]
                if self._shortfall_since is not None
                and self._shortfall_temperature is not None
                else None
            ),
            "learn_run_at": self.learn_run_at.isoformat() if self.learn_run_at else None,
            "learn_run_until": (
                self.learn_run_until.isoformat() if self.learn_run_until else None
            ),
            "learn_run_target": self._learn_run_target,
            "morning_reported": self._morning_reported,
            "heating_muted_until": (
                self._heating_muted_until.isoformat()
                if self._heating_muted_until else None
            ),
            "fallback_armed": list(self._fallback_armed),
            "fallback_auto": list(self._fallback_auto),
        }

    def _save_runtime_state(self) -> None:
        """Write the runtime state when it changed (debounced).

        The weekly figures change every cycle; they are written along, and on
        their own at most every 15 minutes.
        """
        state = self._runtime_state()
        now = dt_util.utcnow()
        if state != self._saved_state or (
            self._week_saved_at is None
            or now - self._week_saved_at >= timedelta(minutes=15)
        ):
            self._saved_state = state
            self._week_saved_at = now
            data = {
                **state,
                "week": dict(self._week),
                "heat_stats": self.heat_stats.as_dict(),
            }
            self._state_store.async_delay_save(lambda: data, 2)

    @staticmethod
    def _empty_week() -> dict[str, Any]:
        return {
            "since": dt_util.utcnow().isoformat(),
            "heating_s": 0.0,
            "temperature_sum": 0.0,
            "temperature_s": 0.0,
            "window_events": 0,
            "alerts": 0,
            # Radiators cold although heat was asked for.
            "no_heat_s": 0.0,
            # Room minus outdoor temperature over time, actual and as if the
            # room had been held at comfort: heat loss follows it.
            "loss_actual": 0.0,
            "loss_comfort": 0.0,
        }

    def _track_week(self, result: dict[str, Any]) -> None:
        """Add this cycle to the weekly figures."""
        now = dt_util.utcnow()
        seconds = (
            0.0 if self._week_last is None
            else max(0.0, min((now - self._week_last).total_seconds(), 60.0))
        )
        self._week_last = now
        room = result.get("room_temperature")
        if room is not None and seconds:
            self._week["temperature_sum"] += float(room) * seconds
            self._week["temperature_s"] += seconds
        if self.enabled and (result.get("heat_demand") or 0) > 0:
            self._week["heating_s"] += seconds
        if result.get("radiator_supply") == SUPPLY_COLD:
            self._week["no_heat_s"] += seconds
        outdoor = result.get("outdoor_temperature")
        comfort = result.get("comfort_temperature")
        if (
            self.enabled
            and result.get("heating_season", True)
            and room is not None
            and outdoor is not None
            and comfort is not None
            and float(comfort) > float(outdoor)
        ):
            self._week["loss_actual"] += max(0.0, float(room) - float(outdoor)) * seconds
            self._week["loss_comfort"] += (float(comfort) - float(outdoor)) * seconds
        window = bool(result.get("window_open")) and result.get("heating_season", True)
        if window and not self._week_window:
            self._week["window_events"] += 1
        self._week_window = window

    def week_summary(self) -> str:
        """One line for the weekly report."""
        week = self._week
        hours = week["heating_s"] / 3600
        parts = [f"{hours:.0f} h geheizt".replace(".", ",")]
        today = dt_util.now().date()
        energy = self.heat_stats.energy_between(today - timedelta(days=6), today)
        if energy >= 0.5:
            parts.append(f"ca. {energy:.0f} kWh Wärme (geschätzt)")
        if week["temperature_s"]:
            average = week["temperature_sum"] / week["temperature_s"]
            parts.append(f"Ø {average:.1f} °C".replace(".", ","))
        if week["loss_comfort"] > 0:
            saving = 1 - week["loss_actual"] / week["loss_comfort"]
            if saving >= 0.01:
                parts.append(f"ca. {saving:.0%} weniger Wärme als bei Dauer-Komfort")
        if week["no_heat_s"] >= 1800:
            parts.append(
                f"{week['no_heat_s'] / 3600:.0f} h Heizkörper kalt trotz Heizbedarf"
            )
        if week["window_events"]:
            parts.append(f"{week['window_events']}× Fenster offen beim Heizen")
        if week["alerts"]:
            parts.append(
                f"{week['alerts']} Meldung" + ("en" if week["alerts"] > 1 else "")
            )
        model = self.room_model
        if model.trusted and model.mean_error is not None:
            parts.append(
                f"Raummodell liegt im Schnitt {model.mean_error:.2f} °C/h daneben"
                .replace(".", ",")
            )
        elif self.config.get(CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL):
            parts.append(f"Raummodell lernt noch ({model.samples} h)")
        return f"{self.room_name}: " + ", ".join(parts)

    def reset_week(self) -> None:
        self._week = self._empty_week()
        self._week_saved_at = None
        self._save_runtime_state()

    async def async_load_state(self) -> None:
        """Restore mode, boost, alerts and presence from before a restart."""
        stored = await self._state_store.async_load()
        if not isinstance(stored, dict):
            return
        now = dt_util.utcnow()

        def moment(value: object) -> datetime | None:
            parsed = dt_util.parse_datetime(value) if isinstance(value, str) else None
            return dt_util.as_utc(parsed) if parsed is not None else None

        if stored.get("quick_duration") in QUICK_DURATIONS:
            self.quick_duration = stored["quick_duration"]
        boost_until = moment(stored.get("boost_until"))
        if boost_until is not None and boost_until > now:
            self.boost_until = boost_until
        quick_until = moment(stored.get("quick_until"))
        quick_temperature = _as_number(stored.get("quick_temperature"))
        mode = stored.get("quick_mode")
        if (
            (mode in QUICK_MODES or (mode == QUICK_MANUAL and quick_temperature is not None))
            and mode not in (QUICK_AUTO, QUICK_BOOST)
            and (quick_until is None or quick_until > now)
        ):
            self.quick_mode = mode
            self.quick_until = quick_until
            if mode == QUICK_MANUAL:
                self.quick_temperature = quick_temperature
        alerts = stored.get("alerts")
        if isinstance(alerts, dict):
            for key, value in alerts.items():
                if isinstance(value, list) and len(value) == 2:
                    since = moment(value[0])
                    if since is not None:
                        self._alerts[str(key)] = (since, bool(value[1]))
        if isinstance(stored.get("sensor_present"), bool):
            self._sensor_present = stored["sensor_present"]
        offset = _as_number(stored.get("room_offset"))
        if offset is not None:
            self.room_offset = max(ROOM_OFFSET_MIN, min(offset, ROOM_OFFSET_MAX))
        valve_offsets = stored.get("valve_offsets")
        if isinstance(valve_offsets, dict):
            for entity_id, value in valve_offsets.items():
                number = _as_number(value)
                if number is not None:
                    self.valve_offsets[str(entity_id)] = max(
                        VALVE_OFFSET_MIN, min(number, VALVE_OFFSET_MAX)
                    )
        if isinstance(stored.get("schedule_choice"), str):
            self.schedule_choice = stored["schedule_choice"]
        self._absent_since = moment(stored.get("absent_since"))
        skipped = stored.get("skipped_valves")
        if isinstance(skipped, list):
            self.skipped_valves = {str(item) for item in skipped}
        if isinstance(stored.get("last_change_source"), str):
            self.last_change_source = stored["last_change_source"][:100]
        self.last_change_at = moment(stored.get("last_change_at"))
        history = stored.get("outdoor_history")
        if isinstance(history, list):
            cutoff = now - timedelta(hours=HEATING_LIMIT_AVERAGE_HOURS)
            for item in history:
                if isinstance(item, list) and len(item) == 2:
                    at = moment(item[0])
                    value = _as_number(item[1])
                    if at is not None and value is not None and at >= cutoff:
                        self._outdoor_history.append((at, value))
        shortfall = stored.get("shortfall")
        if isinstance(shortfall, list) and len(shortfall) == 3:
            since = moment(shortfall[0])
            temperature = _as_number(shortfall[1])
            if since is not None and temperature is not None:
                self._shortfall_since = since
                self._shortfall_temperature = temperature
                self.heating_problem = shortfall[2] is True
        reported = stored.get("morning_reported")
        self._morning_reported = reported if isinstance(reported, str) else None
        self.learn_run_at = moment(stored.get("learn_run_at"))
        learn_until = moment(stored.get("learn_run_until"))
        if learn_until is not None and learn_until > now:
            self.learn_run_until = learn_until
            self._learn_run_target = _as_number(stored.get("learn_run_target"))
        muted = moment(stored.get("heating_muted_until"))
        if muted is not None and muted > now:
            self._heating_muted_until = muted
        armed = stored.get("fallback_armed")
        if isinstance(armed, list):
            self._fallback_armed = [str(item) for item in armed]
        auto = stored.get("fallback_auto")
        if isinstance(auto, list):
            self._fallback_auto = [str(item) for item in auto]
        self.heat_stats = HeatStats.from_dict(stored.get("heat_stats"))
        week = stored.get("week")
        if isinstance(week, dict):
            for key, default in self._empty_week().items():
                value = week.get(key, default)
                if isinstance(default, str):
                    self._week[key] = value if isinstance(value, str) else default
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    self._week[key] = type(default)(value)
        self._saved_state = self._runtime_state()
        self._week_saved_at = now

    async def async_load_learning(self) -> None:
        """Restore learned rates, validating persisted values before using them."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return

        try:
            heating_rate = float(stored.get("heating_rate", DEFAULT_HEATING_RATE))
        except (TypeError, ValueError):
            heating_rate = DEFAULT_HEATING_RATE
        if math.isfinite(heating_rate):
            self.heating_rate = max(
                MIN_LEARNED_HEATING_RATE,
                min(heating_rate, MAX_LEARNED_HEATING_RATE),
            )

        try:
            cooling_rate = float(stored.get("cooling_rate", DEFAULT_COOLING_RATE))
        except (TypeError, ValueError):
            cooling_rate = DEFAULT_COOLING_RATE
        if math.isfinite(cooling_rate):
            self.cooling_rate = max(
                MIN_LEARNED_COOLING_RATE,
                min(cooling_rate, MAX_LEARNED_COOLING_RATE),
            )

        self._heating_samples = self._stored_count(stored.get("heating_samples"))
        self._cooling_samples = self._stored_count(stored.get("cooling_samples"))
        self._rejected_samples = self._stored_count(stored.get("rejected_samples"))
        self._forecast_evaluations = self._stored_count(
            stored.get("forecast_evaluations")
        )
        self._forecast_mae_c = self._stored_float(stored.get("forecast_mae_c"))
        self._last_forecast_error_c = self._stored_float(
            stored.get("last_forecast_error_c")
        )
        self._last_forecast_predicted_temperature = self._stored_float(
            stored.get("last_forecast_predicted_temperature")
        )
        self._last_forecast_actual_temperature = self._stored_float(
            stored.get("last_forecast_actual_temperature")
        )
        self._last_forecast_event = self._stored_string(stored.get("last_forecast_event"))
        self._last_forecast_error_at = self._stored_string(
            stored.get("last_forecast_error_at")
        )
        self._last_observed_heating_rate = self._stored_float(
            stored.get("last_observed_heating_rate")
        )
        self._last_observed_cooling_rate = self._stored_float(
            stored.get("last_observed_cooling_rate")
        )
        self._last_learning_type = self._stored_string(
            stored.get("last_learning_type")
        ) or "none"
        self._last_learning_status = self._stored_string(
            stored.get("last_learning_status")
        ) or "Noch keine Lernmessung"
        self._last_learning_sample_at = self._stored_string(
            stored.get("last_learning_sample_at")
        )

        self._proximity_updates_seen = self._stored_count(
            stored.get("proximity_updates_seen")
        )
        self._proximity_update_interval_count = self._stored_count(
            stored.get("proximity_update_interval_count")
        )
        self._proximity_average_update_interval_s = self._stored_float(
            stored.get("proximity_average_update_interval_s")
        )
        self._proximity_stale_events = self._stored_count(
            stored.get("proximity_stale_events")
        )
        self._proximity_invalid_events = self._stored_count(
            stored.get("proximity_invalid_events")
        )
        self._proximity_out_of_range_events = self._stored_count(
            stored.get("proximity_out_of_range_events")
        )
        self._proximity_approach_attempts = self._stored_count(
            stored.get("proximity_approach_attempts")
        )
        self._proximity_confirmed_approaches = self._stored_count(
            stored.get("proximity_confirmed_approaches")
        )
        raw_update = self._stored_string(stored.get("proximity_last_state_update"))
        parsed_update = dt_util.parse_datetime(raw_update) if raw_update else None
        self._proximity_last_state_update = (
            dt_util.as_utc(parsed_update) if parsed_update else None
        )
        self._proximity_last_update_at = self._stored_string(
            stored.get("proximity_last_update_at")
        )
        overshoot = self._stored_float(stored.get("overshoot"))
        if overshoot is not None:
            self.overshoot = max(0.0, min(overshoot, MAX_OVERSHOOT))
        self._overshoot_samples = self._stored_count(stored.get("overshoot_samples"))
        if stored.get("room_model_version") == ROOM_MODEL_VERSION:
            self.room_model = RoomModel.from_dict(stored.get("room_model"))
            self._model_seeded = stored.get("room_model_seeded") is True
        else:
            # Learned with an older rule: start over and learn again from
            # the recorder.
            self.room_model = RoomModel()
            self._model_seeded = False
        self.cooling = CoolingCorrection.from_dict(stored.get("cooling_correction"))
        self.supply = (
            SupplyProfile.from_list(stored.get("supply_profile"))
            if stored.get("supply_version") == SUPPLY_VERSION
            else SupplyProfile()
        )
        self.usage = UsageProfile.from_list(stored.get("usage_profile"))
        self._seed_version = self._stored_count(stored.get("seed_version"))
        raw_stats = stored.get("radiator_stats")
        if isinstance(raw_stats, dict):
            self.radiator_stats = {
                str(entity_id): RadiatorStats.from_dict(data)
                for entity_id, data in raw_stats.items()
            }
        self.plan_error = self._stored_float(stored.get("plan_error"))
        self.plan_checked = self._stored_count(stored.get("plan_checked"))
        self.punctuality = Punctuality.from_dict(stored.get("punctuality"))
        self.habits = Habits.from_dict(stored.get("habits"))
        self.showers = Habits.from_dict(stored.get("showers"))
        self.batteries = BatteryWatch.from_dict(stored.get("batteries"))
        self._showers_seeded = bool(stored.get("showers_seeded"))
        raw_maintenance = self._stored_string(stored.get("valve_maintenance_last"))
        parsed_maintenance = (
            dt_util.parse_datetime(raw_maintenance) if raw_maintenance else None
        )
        self._maintenance_last = (
            dt_util.as_utc(parsed_maintenance) if parsed_maintenance else None
        )

    @staticmethod
    def _climate_setpoint(state: State | None) -> float | None:
        """Read the thermostat setpoint if it is finite and numeric."""
        if state is None:
            return None
        try:
            value = float(state.attributes.get("temperature"))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    @staticmethod
    def _fit_to_thermostat(target: float, climate_state: State) -> float:
        """Clamp to the thermostat limits and round to its setpoint step.

        Without rounding, a thermostat with 0.5 °C steps stores 21.0 for a
        requested 21.2 and the difference triggers a new write every update.
        """
        attributes = climate_state.attributes
        try:
            min_temp = float(attributes.get("min_temp", target))
            max_temp = float(attributes.get("max_temp", target))
        except (TypeError, ValueError):
            min_temp = max_temp = target
        if not min_temp <= max_temp:
            min_temp = max_temp = target

        try:
            step = float(attributes.get("target_temp_step") or 0)
        except (TypeError, ValueError):
            step = 0
        if math.isfinite(step) and step > 0:
            target = round(round(target / step) * step, 2)
        return max(min_temp, min(target, max_temp))

    @staticmethod
    def _is_heating(
        climate_state: State | None,
        room_temperature: float,
        setpoint: float | None,
    ) -> bool:
        """Return whether the thermostat is heating.

        Some thermostats do not report ``hvac_action``. For those, a heating
        mode with a setpoint clearly above the room counts as a heating phase;
        the margin keeps the valve's own control band out of the measurement.
        """
        if climate_state is None:
            return False
        action = climate_state.attributes.get("hvac_action")
        if action is not None:
            return action == "heating"
        return (
            climate_state.state in ("heat", "heat_cool", "auto")
            and setpoint is not None
            and setpoint - room_temperature >= INFERRED_HEATING_MARGIN
        )

    def _state(self, key: str) -> State | None:
        entity_id = self.config.get(key)
        return self.hass.states.get(entity_id) if entity_id else None

    @staticmethod
    def _valid(state: State | None) -> bool:
        return state is not None and state.state not in _INVALID_STATES

    def _parse_next_event(self, schedule_state: State | None) -> datetime | None:
        """Parse the schedule integration's next_event attribute."""
        raw = schedule_state.attributes.get("next_event") if schedule_state else None
        if isinstance(raw, datetime):
            event = raw
        elif isinstance(raw, str):
            event = dt_util.parse_datetime(raw)
        else:
            return None
        if event is None:
            return None
        if event.tzinfo is None:
            timezone = dt_util.get_time_zone(self.hass.config.time_zone or "UTC")
            if timezone is None:
                return None
            event = event.replace(tzinfo=timezone)
        return event

    def _parse_local_time(self, raw: object) -> datetime | None:
        """A calendar's naive local start/end time as an aware datetime."""
        if isinstance(raw, datetime):
            moment = raw
        elif isinstance(raw, str):
            moment = dt_util.parse_datetime(raw)
        else:
            return None
        if moment is None:
            return None
        if moment.tzinfo is None:
            timezone = dt_util.get_time_zone(self.hass.config.time_zone or "UTC")
            if timezone is None:
                return None
            moment = moment.replace(tzinfo=timezone)
        return moment

    def _schedule_view(
        self, state: State
    ) -> tuple[bool, datetime | None, float | None]:
        """(active, next switch, block temperature) of a schedule or calendar.

        A calendar counts as active during an event; its description may hold
        ``temperature: 22`` like the additional data of a schedule block.
        """
        active = state.state == "on"
        if state.domain == "calendar":
            next_event = self._parse_local_time(
                state.attributes.get("end_time" if active else "start_time")
            )
            if next_event is not None and next_event <= dt_util.now():
                next_event = None
            temperature = (
                calendar_temperature(
                    state.attributes.get("description"), CALENDAR_TEMPERATURE_KEY
                )
                if active
                else None
            )
            return active, next_event, temperature
        temperature = (
            schedule_comfort_temperature(
                state.attributes.get(SCHEDULE_TEMPERATURE_ATTRIBUTE)
            )
            if active
            else None
        )
        return active, self._parse_next_event(state), temperature

    def _contact_groups(self) -> list[tuple[str, list[str], bool, int, int]]:
        """(name, contacts, main required, open delay, close delay) per group.

        Windows (the main contact must be available), doors and contacts
        shared with other rooms, each with their own delays.
        """
        def ids(key: str) -> list[str]:
            value = self.config.get(key) or []
            return [value] if isinstance(value, str) else list(value)

        def seconds(key: str, default: int) -> int:
            value = self.config.get(key)
            return int(default if value is None else value)

        window_id = self.config.get(CONF_WINDOW_ENTITY)
        windows = ([window_id] if window_id else []) + [
            entity_id
            for entity_id in ids(CONF_ADDITIONAL_WINDOW_ENTITIES)
            if entity_id != window_id
        ]
        groups = [
            (
                "window",
                windows,
                bool(window_id),
                seconds(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY),
                seconds(CONF_WINDOW_CLOSE_DELAY, DEFAULT_WINDOW_CLOSE_DELAY),
            ),
            (
                "door",
                ids(CONF_DOOR_ENTITIES),
                False,
                seconds(CONF_DOOR_OPEN_DELAY, DEFAULT_DOOR_OPEN_DELAY),
                seconds(CONF_DOOR_CLOSE_DELAY, DEFAULT_DOOR_CLOSE_DELAY),
            ),
            (
                "zone",
                ids(CONF_ZONE_WINDOW_ENTITIES),
                False,
                seconds(CONF_ZONE_WINDOW_OPEN_DELAY, DEFAULT_ZONE_WINDOW_OPEN_DELAY),
                seconds(CONF_ZONE_WINDOW_CLOSE_DELAY, DEFAULT_ZONE_WINDOW_CLOSE_DELAY),
            ),
        ]
        return [group for group in groups if group[1]]

    def _contacts_state(
        self, contacts: list[str], main_required: bool
    ) -> tuple[bool, float] | None:
        """(any contact open, seconds in that state) or None when unknown.

        With ``main_required`` the first contact must be available; the
        others count as closed when they drop out. Open: the longest-open
        contact; closed: since the last one closed.
        """
        now = dt_util.utcnow()
        states: list[State] = []
        for index, entity_id in enumerate(contacts):
            state = self.hass.states.get(entity_id)
            if self._valid(state):
                states.append(state)
            elif index == 0 and main_required:
                return None
        if not states:
            return False, 0.0
        opened = [s for s in states if s.state == "on"]
        if opened:
            return True, max((now - s.last_changed).total_seconds() for s in opened)
        return False, min((now - s.last_changed).total_seconds() for s in states)

    def _evaluate_contacts(self) -> tuple[bool, bool] | None:
        """(debounced open, any contact open now), None if the main is unknown."""
        debounced = False
        raw = False
        for name, contacts, main_required, open_delay, close_delay in (
            self._contact_groups()
        ):
            state = self._contacts_state(contacts, main_required)
            if state is None:
                return None
            contact_open, contact_seconds = state
            group_open = evaluate_window_open(
                contact_open,
                contact_seconds,
                self._contact_open.get(name, False),
                open_delay,
                close_delay,
            )
            self._contact_open[name] = group_open
            debounced = debounced or group_open
            raw = raw or contact_open
        return debounced, raw

    def _track_trend(self, room_temperature: float) -> float | None:
        """Keep the last half hour of room readings; return the trend."""
        now = dt_util.utcnow()
        self._trend_samples.append((now, room_temperature))
        cutoff = now - timedelta(seconds=TREND_WINDOW_SECONDS)
        self._trend_samples = [
            sample for sample in self._trend_samples if sample[0] >= cutoff
        ]
        return temperature_trend(self._trend_samples, TREND_MIN_SPAN_SECONDS)

    def _device_switch(self, entity_id: str, suffix: str) -> str | None:
        """A switch of the thermostat's device whose id ends in ``suffix``."""
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if entry is None or not entry.device_id:
            return None
        for device_entry in er.async_entries_for_device(registry, entry.device_id):
            if device_entry.domain == "switch" and device_entry.entity_id.endswith(
                suffix
            ):
                return device_entry.entity_id
        return None

    def _device_entity(self, entity_id: str, domain: str, suffix: str) -> str | None:
        """An entity of the thermostat's device in ``domain`` ending in ``suffix``."""
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if entry is None or not entry.device_id:
            return None
        for device_entry in er.async_entries_for_device(registry, entry.device_id):
            if device_entry.domain == domain and device_entry.entity_id.endswith(
                f"_{suffix}"
            ):
                return device_entry.entity_id
        return None

    def _tuya_week_texts(self, entity_id: str) -> dict[str, str] | None:
        """Weekday -> text entity of a valve's own week program, if it has one
        and can run it (``auto``)."""
        state = self.hass.states.get(entity_id)
        modes = state.attributes.get("hvac_modes") if state else None
        if not modes or "auto" not in modes:
            return None
        texts = {}
        for day in TUYA_DAYS:
            text_id = self._device_entity(entity_id, "text", f"schedule_{day}")
            if text_id is None:
                return None
            texts[day] = text_id
        return texts

    async def _sync_valve_week_schedule(self) -> None:
        """Keep the week program of Tuya valves at the room's schedule.

        Written while running (a few times a day, only what changed), so on
        shutdown the valves only need to be switched to ``auto``.
        """
        if not self.enabled or not self.config.get(
            CONF_VALVE_FALLBACK, DEFAULT_VALVE_FALLBACK
        ):
            return
        schedule_id = self.active_schedule
        if not schedule_id or not schedule_id.startswith("schedule."):
            return
        comfort = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        eco = float(self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE))
        now = dt_util.utcnow()
        key = (schedule_id, comfort, eco)
        if (
            key == self._week_written_key
            and self._week_written_at is not None
            and now - self._week_written_at < timedelta(hours=6)
        ):
            return
        valves = {
            entity_id: texts
            for entity_id in self._thermostat_ids()
            if (texts := self._tuya_week_texts(entity_id))
        }
        for texts in valves.values():
            for text_id in texts.values():
                text = self.hass.states.get(text_id)
                if text is None or text.state in ("unavailable", "unknown"):
                    # Right after a start the valves are not there yet; a
                    # write now would be lost, so try again next cycle.
                    return
        self._week_written_at = now
        self._week_written_key = key
        if not valves:
            return
        try:
            response = await self.hass.services.async_call(
                "schedule",
                "get_schedule",
                {"entity_id": schedule_id},
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, TypeError, ValueError) as err:
            _LOGGER.debug("Schedule %s not readable: %s", schedule_id, err)
            return
        weekly = response.get(schedule_id) if isinstance(response, dict) else None
        if not isinstance(weekly, dict):
            return
        for entity_id, texts in valves.items():
            state = self.hass.states.get(entity_id)
            try:
                step = float(state.attributes.get("target_temp_step") or 0.5)
            except (AttributeError, TypeError, ValueError):
                step = 0.5
            week = tuya_week_schedule(
                weekly, comfort, eco, step, schedule_comfort_temperature
            )
            for day, text_id in texts.items():
                current = self.hass.states.get(text_id)
                if current is not None and current.state == week[day]:
                    continue
                await self._call(
                    "text", "set_value", {"entity_id": text_id, "value": week[day]}
                )

    async def _calibrate_valve_sensors(self, result: dict[str, Any]) -> None:
        """Set the valves' own calibration so they read the room temperature.

        Only valves without an input for the room temperature: their reading
        is what their own control (and the week program in a fallback) works
        with. The offset is the median over the last hours, written in whole
        steps and not more often than every few hours.
        """
        if not self.enabled or not self.config.get(
            CONF_VALVE_SENSOR_CALIBRATION, DEFAULT_VALVE_SENSOR_CALIBRATION
        ):
            return
        room = result.get("room_temperature")
        if room is None or self._room_fallback or result.get("window_open"):
            return
        now = dt_util.utcnow()
        for entity_id in self._thermostat_ids():
            if self._external_temperature_entities(entity_id) is not None:
                continue
            number_id = self._device_entity(
                entity_id, "number", "local_temperature_calibration"
            )
            state = self.hass.states.get(entity_id)
            number = self.hass.states.get(number_id) if number_id else None
            reading = _as_number(state.attributes.get("current_temperature")) if state else None
            current = _as_float(number)
            if number_id is None or reading is None or current is None:
                continue
            if entity_id in self._valve_cal_off:
                continue
            samples = self._valve_cal_samples.setdefault(entity_id, [])
            # How far the valve's (calibrated) reading is off the room.
            samples.append((now, float(room) - reading))
            cutoff = now - timedelta(seconds=VALVE_SENSOR_CALIBRATION_WINDOW)
            samples[:] = [item for item in samples if item[0] >= cutoff]
            last = self._valve_cal_at.get(entity_id)
            if last is not None and (
                now - last
            ).total_seconds() < VALVE_SENSOR_CALIBRATION_INTERVAL:
                continue
            if len(samples) < 6 or (now - samples[0][0]) < timedelta(hours=1):
                continue
            ordered = sorted(value for _, value in samples)
            error = ordered[len(ordered) // 2]
            check = self._valve_cal_check.pop(entity_id, None)
            if check is not None:
                before, change, previous = check
                if abs(before - error) < abs(change) / 2:
                    # The reading did not follow the calibration: this valve
                    # reports its raw value. Put it back and leave it alone.
                    await self._call(
                        "number", "set_value", {"entity_id": number_id, "value": previous}
                    )
                    self._valve_cal_off.add(entity_id)
                    self._log(
                        f"Ventilfühler {self._friendly_name(entity_id)}: "
                        "Kalibrierung wirkt nicht, zurückgesetzt"
                    )
                    continue
            try:
                step = float(number.attributes.get("step") or 1)
                low = float(number.attributes.get("min", -9))
                high = float(number.attributes.get("max", 9))
            except (TypeError, ValueError):
                step, low, high = 1.0, -9.0, 9.0
            step = step if step > 0 else 1.0
            wanted = max(low, min(high, current + round(error / step) * step))
            if abs(wanted - current) < step - 1e-6:
                continue
            if await self._call(
                "number", "set_value", {"entity_id": number_id, "value": wanted}
            ):
                self._valve_cal_at[entity_id] = now
                self._valve_cal_check[entity_id] = (error, wanted - current, current)
                # Readings before the change mean something else now.
                samples.clear()
                self._log(
                    f"Ventilfühler {self._friendly_name(entity_id)} kalibriert: "
                    + f"{wanted:+.1f}".replace(".", ",")
                    + " °C"
                )

    async def async_arm_valve_fallback(self) -> None:
        """Home Assistant shuts down: let the valves run on their own.

        Each valve that has its own schedule (Aqara E1: ``schedule`` switch and
        ``schedule_settings``) gets today's comfort and eco times and switches
        to it and to its own temperature sensor, so it does not hold the last
        target on a room value nobody updates any more.
        """
        if not self.enabled or not self.config.get(
            CONF_VALVE_FALLBACK, DEFAULT_VALVE_FALLBACK
        ):
            return
        now = dt_util.utcnow()
        comfort = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        eco = float(self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE))
        try:
            blocks = await asyncio.wait_for(self._schedule_blocks(now), 5)
        except TimeoutError:
            blocks = None
        settings = fallback_schedule(
            [
                (block.start, block.end, comfort if block.temperature is None
                 else block.temperature)
                for block in blocks or []
            ],
            eco,
        )
        armed: list[str] = []
        auto: list[str] = []
        for entity_id in self._thermostat_ids():
            switch_id = self._device_entity(entity_id, "switch", "schedule")
            text_id = self._device_entity(entity_id, "text", "schedule_settings")
            if switch_id is None or text_id is None:
                if self._tuya_week_texts(entity_id) and await self._call(
                    "climate",
                    "set_hvac_mode",
                    {"entity_id": entity_id, "hvac_mode": "auto"},
                ):
                    # Its week program was kept up to date while running.
                    auto.append(entity_id)
                continue
            if await self._call(
                "text", "set_value", {"entity_id": text_id, "value": settings}
            ) and await self._call("switch", "turn_on", {"entity_id": switch_id}):
                armed.append(switch_id)
        if armed:
            await self._sync_external_temperature(release=True)
        self._fallback_armed = armed
        self._fallback_auto = auto
        self._save_runtime_state()

    async def _disarm_valve_fallback(self) -> None:
        """After the start the integration controls the valves again."""
        for entity_id in list(self._fallback_auto):
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unavailable", "unknown"):
                # Right after a start the valve reports ``unknown`` before its
                # real mode arrives; taking that for "not auto" left the valves
                # running their own program all day (13.10.).
                break
            if state.state != "auto" or await self._call(
                "climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": "heat"}
            ):
                if state.state == "auto":
                    # Tuya valves take their stored manual setpoint on the
                    # switch; that jump is not a turn of the knob.
                    self._mode_switched_at[entity_id] = dt_util.utcnow()
                self._fallback_auto.remove(entity_id)
                if not self._fallback_auto:
                    self._log("Wochenprogramm der Ventile wieder ausgeschaltet")
                    self._save_runtime_state()
        if not self._fallback_armed:
            return
        for switch_id in self._fallback_armed:
            state = self.hass.states.get(switch_id)
            if state is None or state.state == "unavailable":
                return
        for switch_id in list(self._fallback_armed):
            if await self._call("switch", "turn_off", {"entity_id": switch_id}):
                self._fallback_armed.remove(switch_id)
        if not self._fallback_armed:
            self._log("Notprogramm der Ventile wieder ausgeschaltet")

    def child_lock_switches(self) -> list[str]:
        """Child-lock switches of the room's thermostats."""
        switches = [
            self._device_switch(entity_id, "_child_lock")
            for entity_id in self._thermostat_ids()
        ]
        return [switch for switch in switches if switch]

    async def async_set_child_lock(self, locked: bool) -> None:
        """Lock or unlock the buttons of every thermostat of the room."""
        for switch_id in self.child_lock_switches():
            await self._call(
                "switch", "turn_on" if locked else "turn_off", {"entity_id": switch_id}
            )

    async def async_set_room_offset(self, offset: float) -> None:
        """Shift every target of the room by ``offset``."""
        self.room_offset = max(ROOM_OFFSET_MIN, min(float(offset), ROOM_OFFSET_MAX))
        await self.async_refresh()

    async def async_set_valve_offset(self, entity_id: str, offset: float) -> None:
        """Shift the setpoint of one valve against the others."""
        self.valve_offsets[entity_id] = max(
            VALVE_OFFSET_MIN, min(float(offset), VALVE_OFFSET_MAX)
        )
        self._written.pop(entity_id, None)
        await self.async_refresh()

    async def async_set_option(self, key: str, value: Any) -> None:
        """Change one setting from an entity, without reloading the room."""
        self.config[key] = value
        await self.async_refresh()

    @staticmethod
    def _stored_count(value: object) -> int:
        """Read a non-negative persisted counter."""
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _stored_float(value: object) -> float | None:
        """Read a finite persisted float or return none."""
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _stored_string(value: object) -> str | None:
        """Read a bounded string from persisted learning metadata."""
        return value[:200] if isinstance(value, str) else None

    def _learning_diagnostics(self) -> dict[str, Any]:
        """Expose compact model quality metrics for sensors and diagnostics."""
        return {
            "heating_samples": self._heating_samples,
            "cooling_samples": self._cooling_samples,
            "rejected_samples": self._rejected_samples,
            "last_observed_heating_rate": self._last_observed_heating_rate,
            "last_observed_cooling_rate": self._last_observed_cooling_rate,
            "last_learning_type": self._last_learning_type,
            "learning_status": self._last_learning_status,
            "last_learning_sample_at": self._last_learning_sample_at,
            "forecast_evaluations": self._forecast_evaluations,
            "forecast_mae_c": self._forecast_mae_c,
            "last_forecast_error_c": self._last_forecast_error_c,
            "last_forecast_predicted_temperature": (
                self._last_forecast_predicted_temperature
            ),
            "last_forecast_actual_temperature": self._last_forecast_actual_temperature,
            "last_forecast_event": self._last_forecast_event,
            "last_forecast_error_at": self._last_forecast_error_at,
            "proximity_updates_seen": self._proximity_updates_seen,
            "proximity_update_interval_count": self._proximity_update_interval_count,
            "proximity_average_update_interval_s": self._proximity_average_update_interval_s,
            "proximity_stale_events": self._proximity_stale_events,
            "proximity_invalid_events": self._proximity_invalid_events,
            "proximity_out_of_range_events": self._proximity_out_of_range_events,
            "proximity_approach_attempts": self._proximity_approach_attempts,
            "proximity_confirmed_approaches": self._proximity_confirmed_approaches,
            "proximity_last_update_at": self._proximity_last_update_at,
            "overshoot": self.overshoot,
            "overshoot_samples": self._overshoot_samples,
        }

    async def _save_learning(self) -> None:
        """Persist rates and compact quality metrics together."""
        await self._store.async_save(
            {
                "heating_rate": self.heating_rate,
                "cooling_rate": self.cooling_rate,
                "heating_samples": self._heating_samples,
                "cooling_samples": self._cooling_samples,
                "rejected_samples": self._rejected_samples,
                "last_observed_heating_rate": self._last_observed_heating_rate,
                "last_observed_cooling_rate": self._last_observed_cooling_rate,
                "last_learning_type": self._last_learning_type,
                "last_learning_status": self._last_learning_status,
                "last_learning_sample_at": self._last_learning_sample_at,
                "forecast_evaluations": self._forecast_evaluations,
                "forecast_mae_c": self._forecast_mae_c,
                "last_forecast_error_c": self._last_forecast_error_c,
                "last_forecast_predicted_temperature": (
                    self._last_forecast_predicted_temperature
                ),
                "last_forecast_actual_temperature": (
                    self._last_forecast_actual_temperature
                ),
                "last_forecast_event": self._last_forecast_event,
                "last_forecast_error_at": self._last_forecast_error_at,
                "proximity_updates_seen": self._proximity_updates_seen,
                "proximity_update_interval_count": self._proximity_update_interval_count,
                "proximity_average_update_interval_s": self._proximity_average_update_interval_s,
                "proximity_stale_events": self._proximity_stale_events,
                "proximity_invalid_events": self._proximity_invalid_events,
                "proximity_out_of_range_events": self._proximity_out_of_range_events,
                "proximity_approach_attempts": self._proximity_approach_attempts,
                "proximity_confirmed_approaches": self._proximity_confirmed_approaches,
                "proximity_last_state_update": (
                    self._proximity_last_state_update.isoformat()
                    if self._proximity_last_state_update else None
                ),
                "proximity_last_update_at": self._proximity_last_update_at,
                "valve_maintenance_last": (
                    self._maintenance_last.isoformat()
                    if self._maintenance_last else None
                ),
                "overshoot": self.overshoot,
                "overshoot_samples": self._overshoot_samples,
                "room_model": self.room_model.as_dict(),
                "room_model_seeded": self._model_seeded,
                "room_model_version": ROOM_MODEL_VERSION,
                "supply_profile": self.supply.as_list(),
                "supply_version": SUPPLY_VERSION,
                "cooling_correction": self.cooling.as_dict(),
                "usage_profile": self.usage.as_list(),
                "seed_version": self._seed_version,
                "radiator_stats": {
                    entity_id: stats.as_dict()
                    for entity_id, stats in self.radiator_stats.items()
                },
                "plan_error": self.plan_error,
                "plan_checked": self.plan_checked,
                "punctuality": self.punctuality.as_dict(),
                "habits": self.habits.as_dict(),
                "showers": self.showers.as_dict(),
                "showers_seeded": self._showers_seeded,
                "batteries": self.batteries.as_dict(),
            }
        )

    async def _learn(
        self,
        room_temperature: float,
        climate_state: State | None,
        *,
        window_open: bool,
        schedule_active: bool,
        eco_temperature: float,
    ) -> None:
        """Learn from plausible temperature trends and reject outlier samples."""
        attributes = climate_state.attributes if climate_state else {}
        setpoint_value = self._stored_float(attributes.get("temperature"))
        last = self.data or {}
        if (
            self.enabled
            and last.get("target_temperature") is not None
            and not last.get("manual_override")
        ):
            # Under control the valve setpoint carries calibration and valve
            # offsets; the room target is what the room really heats towards.
            setpoint_value = float(last["target_temperature"])
        is_heating = self._is_heating(climate_state, room_temperature, setpoint_value)
        now = dt_util.utcnow()
        await self._track_overshoot(
            room_temperature, is_heating, window_open=window_open, now=now
        )
        if self._model_rates is not None:
            # The room model learns from every hour; single samples add nothing.
            self._heating_sample.reset()
            self._cooling_sample.reset()
            self._last_learning_status = "Raummodell übernimmt"
            return

        # Absence only lowers the target; the room still heats and cools
        # normally, and the night setback is the main cooling phase to learn.
        if window_open:
            self._heating_sample.reset()
            self._cooling_sample.reset()
            self._last_learning_status = "Lernen pausiert: Fenster offen"
            return

        if is_heating:
            self._cooling_sample.reset()
            if setpoint_value is None or room_temperature >= setpoint_value - 0.1:
                self._heating_sample.reset()
                self._last_learning_status = "Warte auf aktive Heizphase unter Solltemperatur"
                return

            outcome, observed_rate = self._heating_sample.observe(
                room_temperature,
                now,
                direction=1,
                min_seconds=MIN_SAMPLE_SECONDS,
                max_seconds=MAX_HEATING_SAMPLE_SECONDS,
                min_delta=MIN_SAMPLE_DELTA,
                max_delta=MAX_HEATING_SAMPLE_DELTA,
            )
            if outcome == "started":
                self._last_learning_type = "heating"
                self._last_learning_status = "Sammle Aufheizmessung"
                return
            if outcome == "collecting":
                self._last_learning_status = "Sammle weitere Aufheizdaten"
                return
            if outcome == "too_long":
                self._rejected_samples += 1
                self._last_learning_status = "Aufheizmessung verworfen: Messintervall zu lang"
                await self._save_learning()
                return
            if outcome == "implausible" or observed_rate is None:
                self._rejected_samples += 1
                self._last_learning_status = "Aufheizmessung verworfen: Temperaturänderung unplausibel"
                await self._save_learning()
                return

            self._last_observed_heating_rate = round(observed_rate, 3)
            # A room heating slower than the model's floor is real and
            # important to know (preheating has to start early): learn the
            # floor instead of throwing the measurement away.
            observed_rate = max(observed_rate, MIN_LEARNED_HEATING_RATE)
            if observed_rate > MAX_LEARNED_HEATING_RATE:
                self._rejected_samples += 1
                self._last_learning_status = "Aufheizmessung verworfen: Rate außerhalb plausibler Grenzen"
                await self._save_learning()
                return

            self.heating_rate = round(
                0.8 * self.heating_rate + 0.2 * observed_rate, 3
            )
            self._heating_samples += 1
            self._last_learning_type = "heating"
            self._last_learning_sample_at = now.isoformat()
            self._last_learning_status = "Aufheizrate aktualisiert"
            await self._save_learning()
            return

        self._heating_sample.reset()
        can_learn_cooling = (
            setpoint_value is not None
            and room_temperature > setpoint_value + 0.2
            and setpoint_value <= eco_temperature + 0.5
            and not schedule_active
        )
        if not can_learn_cooling:
            self._cooling_sample.reset()
            self._last_learning_status = "Warte auf stabile Abkühlphase im Absenkbetrieb"
            return

        outcome, observed_rate = self._cooling_sample.observe(
            room_temperature,
            now,
            direction=-1,
            min_seconds=MIN_COOLING_SAMPLE_SECONDS,
            max_seconds=MAX_COOLING_SAMPLE_SECONDS,
            min_delta=MIN_SAMPLE_DELTA,
            max_delta=MAX_COOLING_SAMPLE_DELTA,
        )
        if outcome == "started":
            self._last_learning_type = "cooling"
            self._last_learning_status = "Sammle Abkühlmessung"
            return
        if outcome == "collecting":
            self._last_learning_status = "Sammle weitere Abkühldaten"
            return
        if outcome == "too_long":
            self._rejected_samples += 1
            self._last_learning_status = "Abkühlmessung verworfen: Messintervall zu lang"
            await self._save_learning()
            return
        if outcome == "implausible" or observed_rate is None:
            self._rejected_samples += 1
            self._last_learning_status = "Abkühlmessung verworfen: Temperaturänderung unplausibel"
            await self._save_learning()
            return

        self._last_observed_cooling_rate = round(observed_rate, 3)
        if not MIN_LEARNED_COOLING_RATE <= observed_rate <= MAX_LEARNED_COOLING_RATE:
            self._rejected_samples += 1
            self._last_learning_status = "Abkühlmessung verworfen: Rate außerhalb plausibler Grenzen"
            await self._save_learning()
            return

        self.cooling_rate = round(
            0.8 * self.cooling_rate + 0.2 * observed_rate, 3
        )
        self._cooling_samples += 1
        self._last_learning_type = "cooling"
        self._last_learning_sample_at = now.isoformat()
        self._last_learning_status = "Abkühlrate aktualisiert"
        await self._save_learning()

    async def _track_overshoot(
        self,
        room_temperature: float,
        is_heating: bool,
        *,
        window_open: bool,
        now: datetime,
    ) -> None:
        """Measure how far the room keeps warming after heating stopped.

        A measurement starts when heating stops near the room's target and
        ends once the room cooled a little below its peak (or after 90
        minutes). New heating or an open window discard it.
        """
        if window_open or is_heating:
            self._overshoot_track = None
            self._was_heating = is_heating and not window_open
            return
        target = (self.data or {}).get("target_temperature")
        if (
            self._was_heating
            and target is not None
            and room_temperature >= float(target) - 0.3
        ):
            self._overshoot_track = (float(target), room_temperature, now)
        self._was_heating = False
        if self._overshoot_track is None:
            return
        target_value, peak, started = self._overshoot_track
        peak = max(peak, room_temperature)
        self._overshoot_track = (target_value, peak, started)
        if (
            room_temperature > peak - OVERSHOOT_DROP
            and (now - started).total_seconds() < OVERSHOOT_MAX_SECONDS
        ):
            return
        observed = max(0.0, min(peak - target_value, MAX_OVERSHOOT))
        self.overshoot = round(
            observed
            if self._overshoot_samples == 0
            else 0.8 * self.overshoot + 0.2 * observed,
            2,
        )
        self._overshoot_samples += 1
        self._overshoot_track = None
        await self._save_learning()

    async def _evaluate_pending_forecast(
        self,
        *,
        now: datetime,
        room_temperature: float,
        schedule_active: bool,
        present: bool,
        window_open: bool,
    ) -> None:
        """Compare a stored pre-schedule temperature projection with reality."""
        event = self._pending_forecast_event
        predicted = self._pending_forecast_temperature
        if event is None or predicted is None:
            return

        seconds_after_event = (now - event).total_seconds()
        if seconds_after_event > FORECAST_EVALUATION_GRACE_SECONDS:
            self._pending_forecast_event = None
            self._pending_forecast_temperature = None
            return
        if (
            seconds_after_event < 0
            or not schedule_active
            or not present
            or window_open
        ):
            return

        error = round(room_temperature - predicted, 3)
        absolute_error = abs(error)
        self._forecast_evaluations += 1
        if self._forecast_mae_c is None or self._forecast_evaluations == 1:
            self._forecast_mae_c = round(absolute_error, 3)
        else:
            self._forecast_mae_c = round(
                self._forecast_mae_c
                + (absolute_error - self._forecast_mae_c)
                / self._forecast_evaluations,
                3,
            )
        self._last_forecast_error_c = error
        self._last_forecast_predicted_temperature = round(predicted, 2)
        self._last_forecast_actual_temperature = round(room_temperature, 2)
        self._last_forecast_event = event.isoformat()
        self._last_forecast_error_at = now.isoformat()
        self._last_learning_status = (
            f"Vorhersage ausgewertet: Fehler {error:+.1f} °C "
            f"(MAE {self._forecast_mae_c:.1f} °C)"
        )
        self._pending_forecast_event = None
        self._pending_forecast_temperature = None
        await self._save_learning()

    def _update_pending_forecast(
        self,
        *,
        now: datetime,
        next_event: datetime | None,
        projected_temperature: float | None,
        schedule_active: bool,
        present: bool,
        window_open: bool,
    ) -> None:
        """Keep the latest forecast until its scheduled comfort transition."""
        if self._pending_forecast_event is not None and (
            now - self._pending_forecast_event
        ).total_seconds() > FORECAST_EVALUATION_GRACE_SECONDS:
            self._pending_forecast_event = None
            self._pending_forecast_temperature = None

        if (
            schedule_active
            or not present
            or window_open
            or next_event is None
            or projected_temperature is None
            or next_event <= now
        ):
            return
        self._pending_forecast_event = next_event
        self._pending_forecast_temperature = projected_temperature

    def _heating_limit_basis(
        self, current: float | None, forecast_items: list[dict[str, Any]]
    ) -> tuple[float | None, str | None]:
        """The outdoor value the heating limit is judged by, and its source.

        With averaging (default): the mean forecast of the next two days,
        else the mean of the outdoor readings of the last two days, else the
        current value.
        """
        now = dt_util.utcnow()
        if current is not None and (
            not self._outdoor_history
            or (now - self._outdoor_history[-1][0]).total_seconds()
            >= OUTDOOR_HISTORY_INTERVAL_SECONDS
        ):
            self._outdoor_history.append((now, current))
        cutoff = now - timedelta(hours=HEATING_LIMIT_AVERAGE_HOURS)
        self._outdoor_history = [
            sample for sample in self._outdoor_history if sample[0] >= cutoff
        ]
        if not self.config.get(CONF_HEATING_LIMIT_AVERAGE, DEFAULT_HEATING_LIMIT_AVERAGE):
            return current, None if current is None else "current"
        average = mean_forecast_temperature(
            forecast_items,
            dt_util.now(),
            HEATING_LIMIT_AVERAGE_HOURS,
            HEATING_LIMIT_MIN_FORECAST_POINTS,
        )
        if average is not None:
            return average, "forecast"
        average = mean_history_temperature(
            self._outdoor_history, OUTDOOR_HISTORY_MIN_SPAN_SECONDS
        )
        if average is not None:
            return average, "history"
        return current, None if current is None else "current"

    def _outdoor_temperature(self) -> float | None:
        """Read the outdoor sensor, falling back to the weather entity."""
        temperature = _as_float(self._state(CONF_OUTDOOR_TEMPERATURE_ENTITY))
        if temperature is not None:
            return temperature
        if (
            self.config.get(CONF_OUTDOOR_TEMPERATURE_ENTITY)
            and (dt_util.utcnow() - self._started_at).total_seconds()
            < OUTDOOR_FALLBACK_GRACE_SECONDS
        ):
            # Right after a start the own sensor comes a moment later; the
            # weather entity in between can be degrees off and would show up
            # in the heating limit's average.
            return None
        weather_id = self.config.get(CONF_WEATHER_ENTITY)
        weather_state = self.hass.states.get(weather_id) if weather_id else None
        if not self._valid(weather_state):
            return None
        try:
            value = float(weather_state.attributes.get("temperature"))
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    async def _async_get_forecast_items(self) -> list[dict[str, Any]]:
        """Fetch hourly forecast at most every 30 minutes, if configured."""
        entity_id = self.config.get(CONF_WEATHER_ENTITY)
        if not entity_id:
            return []

        now = dt_util.utcnow()
        if (
            self._forecast_fetched_at is not None
            and now - self._forecast_fetched_at < timedelta(minutes=30)
        ):
            return self._forecast_items

        self._forecast_fetched_at = now
        if not self._valid(self.hass.states.get(entity_id)):
            self._forecast_items = []
            return []

        try:
            response = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entity_id, "type": "hourly"},
                blocking=True,
                return_response=True,
            )
            entity_result = response.get(entity_id, {}) if isinstance(response, dict) else {}
            items = entity_result.get("forecast", []) if isinstance(entity_result, dict) else []
            self._forecast_items = (
                [item for item in items if isinstance(item, dict)]
                if isinstance(items, list)
                else []
            )
        except (HomeAssistantError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.warning(
                "Hourly weather forecast unavailable for %s: %s", entity_id, err
            )
            self._forecast_items = []

        return self._forecast_items

    def _waiting_result(
        self,
        status: str,
        room_temperature: float | None,
        outdoor_temperature: float | None,
    ) -> dict[str, Any]:
        """Return a consistent no-control result for unavailable prerequisites."""
        return {
            "status": status,
            "mode": "waiting",
            "target_temperature": None,
            "current_setpoint": None,
            "room_temperature": room_temperature,
            "outdoor_temperature": outdoor_temperature,
            "heating_rate": self.heating_rate,
            "cooling_rate": self.cooling_rate,
            "preheat_minutes": 0,
            "projected_temperature": None,
            "forecast_condition": None,
            "solar_adjustment_minutes": 0,
            "enabled": self.enabled,
            "proximity_status": self._proximity_status,
            "proximity_distance_m": self._proximity_distance_m,
            "proximity_direction": self._proximity_direction,
            "proximity_age_seconds": self._proximity_age_seconds,
            **self._learning_diagnostics(),
        }

    def _left_home_within(
        self, entity_id: str, state: State, now: datetime, delay_seconds: int
    ) -> bool:
        """True while a person left home less than ``delay_seconds`` ago."""
        if delay_seconds <= 0:
            return False
        seen = self._seen_home.get(entity_id)
        if seen is not None:
            gone = (now - seen).total_seconds()
        elif state.state == "not_home":
            # Not seen at home since the start: the state's age tells.
            gone = (now - state.last_changed).total_seconds()
        else:
            return False
        return gone < delay_seconds

    def _presence_is_active(
        self, state: State, expected: bool, delay_seconds: int
    ) -> bool:
        """Apply a configurable stability delay to an on/off presence state."""
        current = state.state in ("on", "home")
        if current != expected:
            return False
        age = (dt_util.utcnow() - state.last_changed).total_seconds()
        return delay_seconds <= 0 or age >= delay_seconds

    @staticmethod
    def _distance_to_meters(value: float, unit: str | None) -> float | None:
        """Normalize supported distance units to meters."""
        normalized = (unit or "m").strip().lower()
        factors = {
            "m": 1.0,
            "meter": 1.0,
            "meters": 1.0,
            "metre": 1.0,
            "metres": 1.0,
            "km": 1000.0,
            "kilometer": 1000.0,
            "kilometers": 1000.0,
            "kilometre": 1000.0,
            "kilometres": 1000.0,
            "mi": 1609.344,
            "mile": 1609.344,
            "miles": 1609.344,
            "ft": 0.3048,
            "foot": 0.3048,
            "feet": 0.3048,
            "yd": 0.9144,
            "yard": 0.9144,
            "yards": 0.9144,
        }
        factor = factors.get(normalized)
        if factor is None:
            return None
        result = value * factor
        return result if math.isfinite(result) and result >= 0 else None

    def _record_proximity_category(self, category: str, key: str = "") -> None:
        """Count only changes between meaningful geofence states.

        Per source: with two people in the zone their states differ, and one
        shared state counted every cycle as a change (2526 "stale" events).
        """
        if category == self._proximity_categories.get(key):
            return
        self._proximity_categories[key] = category
        if category == "stale":
            self._proximity_stale_events += 1
            self._proximity_metrics_dirty = True
        elif category == "invalid":
            self._proximity_invalid_events += 1
            self._proximity_metrics_dirty = True
        elif category == "out_of_range":
            self._proximity_out_of_range_events += 1
            self._proximity_metrics_dirty = True
        elif category == "approaching":
            self._proximity_approach_attempts += 1
            self._proximity_metrics_dirty = True
        elif category == "confirmed":
            self._proximity_confirmed_approaches += 1
            self._proximity_metrics_dirty = True

    def _observe_proximity_update(self, distance_state: State) -> None:
        """Measure actual device update cadence without storing location history."""
        updated_at = dt_util.as_utc(distance_state.last_updated)
        if self._proximity_last_state_update == updated_at:
            return
        if self._proximity_last_state_update is not None:
            interval = (updated_at - self._proximity_last_state_update).total_seconds()
            if 0 < interval <= 7 * 24 * 60 * 60:
                count = self._proximity_update_interval_count
                average = self._proximity_average_update_interval_s
                self._proximity_update_interval_count += 1
                self._proximity_average_update_interval_s = (
                    interval if average is None
                    else average + (interval - average) / (count + 1)
                )
        self._proximity_last_state_update = updated_at
        self._proximity_last_update_at = updated_at.isoformat()
        self._proximity_updates_seen += 1
        self._proximity_metrics_dirty = True

    def _proximity_is_active(
        self,
        distance_state: State | None,
        direction_state: State | None,
        key: str = "",
        *,
        observe: bool = True,
    ) -> tuple[bool | None, str]:
        """Validate freshness, unit, direction and distance before inferring arrival."""
        self._proximity_distance_m = None
        self._proximity_direction = None
        self._proximity_age_seconds = None

        if not self._valid(distance_state):
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Entfernung nicht verfügbar"

        if observe:
            self._observe_proximity_update(distance_state)

        now = dt_util.utcnow()
        age = (now - dt_util.as_utc(distance_state.last_updated)).total_seconds()
        self._proximity_age_seconds = round(max(age, 0), 1)
        max_age = max(
            0,
            int(self.config.get(CONF_PROXIMITY_MAX_AGE, DEFAULT_PROXIMITY_MAX_AGE)),
        )
        if age < -60 or age > max_age:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("stale", key)
            return (
                None,
                # No age in the text: a status that changes every minute
                # fills the history; the age has its own sensor.
                "Standortdaten veraltet – Proximity wird nicht für Anfahrt "
                "verwendet",
            )

        legacy_direction = distance_state.attributes.get("dir_of_travel")
        if distance_state.domain == "proximity" or legacy_direction is not None:
            raw_direction = legacy_direction
        elif direction_state is not None and self._valid(direction_state):
            raw_direction = direction_state.state
        elif self.config.get(CONF_PROXIMITY_DIRECTION_ENTITY):
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Richtung nicht verfügbar"
        else:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Richtung fehlt: bitte Richtungssensor auswählen"

        direction = str(raw_direction or "").strip().lower()
        self._proximity_direction = direction or None
        if direction == "unknown" or direction in _INVALID_STATES or not direction:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Richtung ist unbekannt"

        raw_distance = _as_float(distance_state)
        if raw_distance is None:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Entfernung ist kein gültiger Zahlenwert"

        distance_m = self._distance_to_meters(
            raw_distance,
            distance_state.attributes.get("unit_of_measurement"),
        )
        if distance_m is None:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Einheit nicht unterstützt"
        self._proximity_distance_m = round(distance_m, 1)

        maximum_distance = max(
            0.0,
            float(self.config.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE)),
        )
        if direction == "arrived" or distance_m <= 0:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("confirmed", key)
            return True, "Proximity meldet Ankunft"
        if direction in ("away_from", "stationary"):
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("not_approaching", key)
            return False, (
                "Bewegung weg vom Zuhause" if direction == "away_from"
                else "Standort stationär – keine Anfahrt"
            )
        if direction != "towards":
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, f"Unbekannte Bewegungsrichtung: {direction}"

        if distance_m > maximum_distance:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("out_of_range", key)
            return False, "Noch außerhalb der Anfahrtsentfernung"

        if key not in self._proximity_approaching:
            self._proximity_approaching[key] = now
            self._record_proximity_category("approaching", key)
        duration = max(
            0,
            int(self.config.get(CONF_PROXIMITY_DURATION, DEFAULT_PROXIMITY_DURATION)),
        )
        elapsed = (now - self._proximity_approaching[key]).total_seconds()
        if elapsed < duration:
            return False, (
                f"Anfahrt erkannt – Wartezeit {round(duration - elapsed)} s"
            )
        self._record_proximity_category("confirmed", key)
        return True, "Anfahrt bestätigt"

    def _zone_sources(
        self, zone_entry_id: str, people: list[str]
    ) -> list[tuple[str, str, str]]:
        """Distance and direction sensors of a proximity zone for this room.

        With people configured, only their own sensors of the zone are used;
        otherwise the zone's nearest-person sensors.
        """
        registry = er.async_get(self.hass)
        by_unique_id = {
            entry.unique_id: entry.entity_id
            for entry in er.async_entries_for_config_entry(registry, zone_entry_id)
            if entry.domain == "sensor"
        }
        if not people:
            identifiers = [("", "")]
        else:
            identifiers = []
            for entity_id in people:
                entry = registry.async_get(entity_id)
                identifiers.append(
                    (self._friendly_name(entity_id), f"{entry.id if entry else entity_id}_")
                )
        sources = []
        for name, prefix in identifiers:
            distance_id = by_unique_id.get(f"{zone_entry_id}_{prefix}dist_to_zone")
            direction_id = by_unique_id.get(f"{zone_entry_id}_{prefix}dir_of_travel")
            if distance_id and direction_id:
                sources.append((name, distance_id, direction_id))
        return sources

    def _zone_is_active(self, zone_entry_id: str, people: list[str]) -> tuple[bool, str]:
        """Arrival of anyone of this room, read from a proximity zone.

        Missing or old location data never blocks the room: nobody is home,
        so without a confirmed arrival the room simply stays lowered.
        """
        sources = self._zone_sources(zone_entry_id, people)
        if not sources:
            self._proximity_approaching.clear()
            self._record_proximity_category("invalid")
            if self.hass.config_entries.async_get_entry(zone_entry_id) is None:
                return False, "Proximity-Zone nicht gefunden"
            return False, "Die Zone erfasst keine Person dieses Raums"
        newest = max(
            sources,
            key=lambda source: (
                state.last_updated
                if (state := self.hass.states.get(source[1])) is not None
                else datetime.min.replace(tzinfo=dt_util.UTC)
            ),
        )
        results = []
        for name, distance_id, direction_id in sources:
            active, status = self._proximity_is_active(
                self.hass.states.get(distance_id),
                self.hass.states.get(direction_id),
                distance_id,
                observe=distance_id == newest[1],
            )
            results.append((active, f"{name}: {status}" if name else status))
        for active, status in results:
            if active:
                return True, status
        for _active, status in results:
            if "Anfahrt erkannt" in status:
                return False, status
        return False, results[0][1]

    def _evaluate_presence(self) -> tuple[bool | None, str]:
        """Combine person, guest, proximity and scheduled presence signals."""
        people = self.config.get(CONF_PERSON_ENTITIES) or []
        if isinstance(people, str):
            people = [people]

        guest_id = self.config.get(CONF_GUEST_ENTITY)
        zone_id = self.config.get(CONF_PROXIMITY_ZONE)
        proximity_id = None if zone_id else self.config.get(CONF_PROXIMITY_ENTITY)
        direction_id = self.config.get(CONF_PROXIMITY_DIRECTION_ENTITY)
        presence_id = self.config.get(CONF_PRESENCE_ENTITY)
        has_household_source = bool(people or guest_id or proximity_id or zone_id)
        has_any_source = has_household_source or bool(presence_id)
        household_home = not has_any_source
        invalid_people = False
        enter_delay = int(
            self.config.get(CONF_ENTER_HOME_DURATION, DEFAULT_ENTER_HOME_DURATION)
        )
        leave_delay = int(
            self.config.get(CONF_LEAVING_HOME_DURATION, DEFAULT_LEAVING_HOME_DURATION)
        )
        if leave_delay > 0 and (self.data or {}).get("mode") == "preheat":
            # Heat already put in is not thrown away for a short absence
            # (0 = react at once, kept as set).
            leave_delay = max(leave_delay, PREHEAT_LEAVE_GRACE_SECONDS)

        now = dt_util.utcnow()
        for entity_id in people:
            state = self.hass.states.get(entity_id)
            if not self._valid(state):
                invalid_people = True
            elif state.state == "home":
                self._seen_home[entity_id] = now
                if self._presence_is_active(state, True, enter_delay):
                    household_home = True
            elif self._left_home_within(entity_id, state, now, leave_delay):
                # Left just now, also straight into another zone ("Arbeit"):
                # still counts as home for the leaving delay.
                household_home = True

        if guest_id:
            guest = self.hass.states.get(guest_id)
            if not self._valid(guest):
                return None, "Gastmodus-Entität nicht verfügbar – keine Sollwertänderung"
            household_home = household_home or guest.state == "on"

        proximity_home = False
        self._proximity_status = "Proximity nicht konfiguriert"
        if zone_id and household_home:
            # Somebody of this room is home: arrivals don't matter now.
            self._proximity_approaching.clear()
            self._proximity_distance_m = None
            self._proximity_direction = None
            self._proximity_age_seconds = None
            self._proximity_status = "Proximity schlummert – jemand ist zuhause"
        elif zone_id:
            proximity_home, self._proximity_status = self._zone_is_active(
                zone_id, people
            )
        elif proximity_id:
            distance_state = self.hass.states.get(proximity_id)
            direction_state = (
                self.hass.states.get(direction_id) if direction_id else None
            )
            proximity_home, self._proximity_status = self._proximity_is_active(
                distance_state, direction_state
            )
            if proximity_home is None:
                # A person/guest tracker is more authoritative than an old GPS
                # estimate. When it already confirms home, ignore stale Proximity
                # data instead of blocking otherwise valid local presence.
                if household_home:
                    proximity_home = False
                    self._proximity_status += " – bekannte Anwesenheit hat Vorrang"
                else:
                    return None, (
                        self._proximity_status
                        + " – keine Sollwertänderung aus unbekannten Standortdaten"
                    )

        household_present = household_home or proximity_home
        self._household_present = household_present and has_household_source
        if invalid_people and not household_present:
            return None, "Personen-/Geräte-Tracker nicht verfügbar – keine Sollwertänderung"

        use_presence = bool(presence_id)
        schedule_id = self.config.get(CONF_PRESENCE_SCHEDULE_ENTITY)
        presence_schedule_off = False
        if schedule_id and presence_id:
            schedule = self.hass.states.get(schedule_id)
            if not self._valid(schedule):
                return None, "Präsenzzeitplan nicht verfügbar – keine Sollwertänderung"
            presence_schedule_off = schedule.state != "on"
            use_presence = use_presence and not presence_schedule_off

        if use_presence:
            state = self.hass.states.get(presence_id)
            if not self._valid(state):
                return None, "Anwesenheitssensor nicht verfügbar – keine Sollwertänderung"
            on_delay = int(
                self.config.get(
                    CONF_PRESENCE_ON_DURATION, DEFAULT_PRESENCE_ON_DURATION
                )
            )
            off_delay = int(
                self.config.get(
                    CONF_PRESENCE_OFF_DURATION, DEFAULT_PRESENCE_OFF_DURATION
                )
            )
            if state.state not in ("on", "off"):
                return None, "Anwesenheitssensor liefert ungültigen Zustand – keine Sollwertänderung"
            sensor_on = state.state == "on"
            if self._presence_is_active(
                state, sensor_on, on_delay if sensor_on else off_delay
            ):
                self._sensor_present = sensor_on
            elif self._sensor_present is None:
                # Nothing settled yet (fresh start): an unconfirmed "on" is not
                # presence yet, a fresh "off" still counts as presence.
                self._sensor_present = not sensor_on
            # A short flicker keeps the last settled decision instead of
            # flipping to the opposite one.
            sensor_present = self._sensor_present

            present = (
                household_present and sensor_present
                if has_household_source
                else sensor_present
            )
        elif presence_id and presence_schedule_off and not has_household_source:
            present = False
        else:
            present = household_present

        if present:
            self._absence = "none"
        elif household_present or not has_household_source:
            # Somebody is home (or only the room sensor is known): the room
            # itself is empty.
            self._absence = "room_empty"
        else:
            self._absence = "house_empty"
        # A long absence: nobody home, or no presence in a room known only by
        # its sensor.
        long_absence = not present and (
            self._absence == "house_empty" or not has_household_source
        )
        if not long_absence:
            self._absent_since = None
        elif self._absent_since is None:
            self._absent_since = dt_util.utcnow()
        return present, (
            "Anwesenheit erkannt" if present else "Keine Anwesenheit – abgesenkt"
        )

    def _thermostat_ids(self) -> list[str]:
        """Primary thermostat first, then additional ones of the same room."""
        ids = [self.config[CONF_CLIMATE_ENTITY]]
        for entity_id in self.config.get(CONF_ADDITIONAL_CLIMATE_ENTITIES) or []:
            if entity_id not in ids:
                ids.append(entity_id)
        return ids

    def _thermostat_warnings(self) -> dict[str, list[str]]:
        """Problems reported by the room's thermostats or their devices.

        Looks at the thermostat itself (unreachable) and at the battery and
        problem entities of the same device, as Better Thermostat shows them.
        """
        registry = er.async_get(self.hass)
        warnings: dict[str, list[str]] = {}
        for entity_id in self._thermostat_ids():
            found: list[str] = []
            if not self._valid(self.hass.states.get(entity_id)):
                since = self._unreachable_since.setdefault(entity_id, dt_util.utcnow())
                if (
                    dt_util.utcnow() - since
                ).total_seconds() >= THERMOSTAT_UNREACHABLE_GRACE_SECONDS:
                    found.append("nicht erreichbar")
            else:
                self._unreachable_since.pop(entity_id, None)
            entry = registry.async_get(entity_id)
            device_entries = (
                er.async_entries_for_device(registry, entry.device_id)
                if entry is not None and entry.device_id
                else []
            )
            for device_entry in device_entries:
                state = self.hass.states.get(device_entry.entity_id)
                if not self._valid(state):
                    continue
                device_class = state.attributes.get("device_class")
                if device_entry.domain == "sensor" and device_class == "battery":
                    level = self._stored_float(state.state)
                    if level is not None and level <= LOW_BATTERY_PERCENT:
                        found.append(f"Batterie schwach ({level:.0f} %)")
                elif device_entry.domain == "binary_sensor" and state.state == "on":
                    if device_entry.entity_id.endswith(IGNORED_PROBLEM_ENTITY_SUFFIXES):
                        continue
                    if device_class == "battery":
                        found.append("Batterie schwach")
                    elif device_class == "problem":
                        name = state.attributes.get("friendly_name") or state.entity_id
                        found.append(f"meldet Problem ({name})")
            if entity_id in self._divergence:
                found.append(f"übernimmt den Sollwert nicht ({self._divergence[entity_id]})")
            if found:
                warnings[entity_id] = found
        return warnings

    def _battery_entities(self) -> dict[str, str]:
        """Battery level sensors on the devices of the room's valves and room
        sensor (entity id -> name)."""
        registry = er.async_get(self.hass)
        sources = list(self._thermostat_ids())
        if room_sensor := self.config.get(CONF_ROOM_TEMPERATURE_ENTITY):
            sources.append(room_sensor)
        found: dict[str, str] = {}
        for source in sources:
            entry = registry.async_get(source)
            if entry is None or not entry.device_id:
                continue
            for device_entry in er.async_entries_for_device(registry, entry.device_id):
                if device_entry.domain != "sensor":
                    continue
                state = self.hass.states.get(device_entry.entity_id)
                # The registry keeps the class while the sensor is unavailable.
                device_class = (
                    device_entry.device_class
                    or device_entry.original_device_class
                    or (state.attributes.get("device_class") if state else None)
                )
                if device_class != "battery":
                    continue
                found[device_entry.entity_id] = str(
                    (state.attributes.get("friendly_name") if state else None)
                    or device_entry.entity_id
                )
        return found

    def _observe_batteries(self, result: dict[str, Any]) -> bool:
        """Battery levels and when each will need changing; True when the
        stored history changed."""
        entities = self._battery_entities()
        changed = bool(set(self.batteries.days) - set(entities))
        self.batteries.forget_others(set(entities))
        today = dt_util.now().date()
        batteries = []
        for entity_id, name in sorted(entities.items()):
            level = _as_float(self.hass.states.get(entity_id))
            if level is not None and 0 <= level <= 100:
                changed = self.batteries.observe(entity_id, today, level) or changed
            batteries.append(
                {
                    "entity_id": entity_id,
                    "name": name,
                    "level": level,
                    "days_left": self.batteries.days_left(
                        entity_id, today, LOW_BATTERY_PERCENT
                    ),
                }
            )
        result["batteries"] = batteries
        if any(entity_id not in self.batteries.seeded for entity_id in entities) and (
            self._battery_seed_at is None
            or (dt_util.utcnow() - self._battery_seed_at).total_seconds() >= 3600
        ):
            # A valve that shows up after the start gets its history too.
            self._battery_seed_at = dt_util.utcnow()
            self.hass.async_create_task(self.async_seed_batteries())
        result["battery_days_left"] = min(
            (item["days_left"] for item in batteries if item["days_left"] is not None),
            default=None,
        )
        return changed

    async def async_seed_batteries(self) -> None:
        """Battery levels of the last months from the recorder, once per
        battery, so the forecast does not wait weeks."""
        self._battery_seed_at = dt_util.utcnow()
        entity_ids = [
            entity_id
            for entity_id in self._battery_entities()
            if entity_id not in self.batteries.seeded
        ]
        if not entity_ids or "recorder" not in self.hass.config.components:
            return
        from homeassistant.components.recorder import get_instance, history
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )

        end = dt_util.utcnow()
        start = end - timedelta(days=BATTERY_HISTORY_DAYS)
        recorder = get_instance(self.hass)
        try:
            # Long-term statistics outlive the recorder's few days of states.
            daily = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass,
                start,
                end,
                set(entity_ids),
                "day",
                None,
                {"min"},
            )
            missing = [entity_id for entity_id in entity_ids if not daily.get(entity_id)]
            states = (
                await recorder.async_add_executor_job(
                    history.get_significant_states,
                    self.hass,
                    start,
                    end,
                    missing,
                    None,
                    True,
                    False,
                    False,
                    True,
                )
                if missing
                else {}
            )
        except Exception:  # noqa: BLE001 - history is a bonus, never fatal
            _LOGGER.debug("Battery history not available", exc_info=True)
            return
        for entity_id in entity_ids:
            # What was seen live already goes on top of the recorder's days.
            live = self.batteries.days.pop(entity_id, [])
            readings: list[tuple[date, float | None]] = [
                (
                    dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date(),
                    _as_number(row.get("min")),
                )
                for row in daily.get(entity_id, [])
            ] + [
                (dt_util.as_local(state.last_changed).date(), _as_float(state))
                for state in states.get(entity_id, [])
                if isinstance(state, State)
            ]
            for day, level in readings:
                if level is not None and 0 <= level <= 100:
                    self.batteries.observe(entity_id, day, level)
            for day, level in live:
                self.batteries.observe(entity_id, date.fromisoformat(day), level)
            self.batteries.seeded.add(entity_id)
        await self._save_learning()

    def _room_temperature(self) -> float | None:
        """The room sensor's reading, or None when it failed or went silent.

        A reading outside the plausible range (typical of a dying battery)
        is dropped and remembered for the Repairs issue.
        """
        state = self._state(CONF_ROOM_TEMPERATURE_ENTITY)
        value = _as_float(state)
        if value is None:
            return None
        if not plausible_temperature(
            value, ROOM_TEMPERATURE_PLAUSIBLE_MIN, ROOM_TEMPERATURE_PLAUSIBLE_MAX
        ):
            self._implausible = (value, state.entity_id)
            return None
        self._implausible = None
        reported = getattr(state, "last_reported", None) or state.last_updated
        if (dt_util.utcnow() - reported).total_seconds() > ROOM_SENSOR_STALE_SECONDS:
            return None
        return value

    def _update_repair_issue(self) -> None:
        """Show an implausible room reading under Settings → Repairs."""
        issue_id = f"implausible_room_temperature_{self.entry_id}"
        if self._implausible is not None:
            value, entity_id = self._implausible
            if not self._issue_open:
                _LOGGER.warning(
                    "Room sensor %s reports an implausible %.1f °C; ignoring it",
                    entity_id,
                    value,
                )
                self._log(
                    f"Raumfühler meldet unplausible {value:.1f} °C – Wert wird ignoriert"
                )
                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="implausible_room_temperature",
                    translation_placeholders={
                        "room": self.room_name,
                        "entity": entity_id,
                        "value": f"{value:.1f}",
                    },
                )
                self._issue_open = True
        elif self._issue_open:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            self._issue_open = False
            self._log("Raumfühler liefert wieder plausible Werte")

    def _thermostat_temperature(self, entity_id: str) -> float | None:
        """The thermostat's own temperature reading, if it reports one."""
        state = self.hass.states.get(entity_id)
        if not self._valid(state):
            return None
        return self._stored_float(state.attributes.get("current_temperature"))

    def _changed_manually(self, entity_id: str, state: State) -> bool:
        """True when a confirmed setpoint was changed at the thermostat."""
        written = self._written.get(entity_id)
        current = self._climate_setpoint(state)
        if written is None or current is None:
            return False
        if abs(current - written.target) < 0.2:
            written.confirmed = True
            return False
        switched = self._mode_switched_at.get(entity_id)
        if (
            switched is not None
            and (dt_util.utcnow() - switched).total_seconds()
            < MODE_SWITCH_GRACE_SECONDS
        ):
            # The valve set its own value when its mode changed (13.10.:
            # Bad 22 -> 20 °C right after "heat"): send the target again.
            self._written.pop(entity_id, None)
            return False
        return written.confirmed

    @property
    def effective_heating_rate(self) -> float:
        """°C per hour of full heating: the room model's, else the measured one."""
        return self.heating_rate if self._model_rates is None else self._model_rates[0]

    @property
    def effective_cooling_rate(self) -> float:
        """°C per hour without heating: the room model's, else the measured one."""
        return self.cooling_rate if self._model_rates is None else self._model_rates[1]

    async def _write_setpoint(
        self, entity_id: str, state: State, target: float, now: datetime
    ) -> bool:
        """Send ``target`` unless the thermostat already has it; False on error."""
        target = round(target, 1)
        written = self._written.get(entity_id)
        if (
            written is not None
            and written.target == target
            and (now - written.at).total_seconds() < SETPOINT_RESEND_SECONDS
        ):
            return True
        current = self._climate_setpoint(state)
        if current is not None and abs(current - target) < 0.2:
            # Already there (e.g. after a restart): remember it as confirmed,
            # otherwise a later turn of the knob would not count as manual
            # and the next cycle would silently set the valve back.
            if written is None or written.target != target:
                self._written[entity_id] = _WrittenSetpoint(target, now, confirmed=True)
            return True
        await self._pace()
        try:
            await self.hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": entity_id, "temperature": target},
                blocking=True,
            )
        except HomeAssistantError as err:
            # Keep the coordinator healthy and retry on the next update.
            _LOGGER.warning(
                "Could not set target temperature %.1f for %s: %s",
                target,
                entity_id,
                err,
            )
            return False
        self._written[entity_id] = _WrittenSetpoint(target, now)
        return True

    def _calibrated(
        self,
        entity_id: str,
        state: State,
        target: float,
        room_temperature: float,
        now: datetime,
    ) -> float:
        """Shift ``target`` by the valve's measurement error, if enabled."""
        if (
            not self.config.get(CONF_CALIBRATION)
            or entity_id in self._external_fed
            or (
                self.config.get(CONF_EXTERNAL_TEMPERATURE)
                and self._external_temperature_entities(entity_id) is not None
            )
        ):
            # A thermostat fed with the room temperature needs no offset, also
            # in the moments after a restart before it is fed again: an offset
            # from its own sensor would be written and taken back right away.
            return target
        cached = self._calibration.get(entity_id)
        if self._room_fallback:
            # The room value is derived from the valves themselves, so a new
            # offset would be meaningless; keep the last one.
            return target + (0.0 if cached is None else cached[0])
        if cached is None or (
            (now - cached[1]).total_seconds() >= CALIBRATION_INTERVAL_SECONDS
        ):
            try:
                valve_temperature = float(state.attributes.get("current_temperature"))
            except (TypeError, ValueError):
                valve_temperature = None
            if valve_temperature is None or not math.isfinite(valve_temperature):
                # Without the valve's reading, use the plain target.
                self._calibration.pop(entity_id, None)
                return target
            offset = calibration_offset(
                room_temperature, valve_temperature, MAX_CALIBRATION_OFFSET
            )
            hysteresis = float(
                self.config.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS) or 0
            )
            cached = (
                apply_hysteresis(
                    None if cached is None else cached[0], offset, hysteresis
                ),
                now,
            )
            self._calibration[entity_id] = cached
        return target + cached[0]

    def _maintenance_due(self, now: datetime) -> bool:
        """Whether the scheduled valve maintenance should start now."""
        if not self.config.get(CONF_VALVE_MAINTENANCE):
            return False
        weekday_value = self.config.get(CONF_MAINTENANCE_WEEKDAY)
        weekday = (
            None
            if weekday_value in (None, "", MAINTENANCE_ANY_DAY)
            else int(weekday_value)
        )
        hour_value = self.config.get(CONF_MAINTENANCE_HOUR)
        local = dt_util.as_local(now)
        return valve_maintenance_due(
            self._maintenance_last,
            now,
            local.hour,
            VALVE_MAINTENANCE_INTERVAL_DAYS,
            VALVE_MAINTENANCE_HOUR if hour_value is None else int(hour_value),
            local.weekday(),
            weekday,
        )

    async def async_start_valve_maintenance(self) -> None:
        """Exercise the valves now (button "Ventilwartung starten")."""
        if not self.enabled:
            raise ServiceValidationError(
                "Die Regelung ist aus – Ventilwartung nur bei aktiver Regelung."
            )
        self._maintenance_requested = True
        await self.async_refresh()

    async def _run_valve_maintenance(
        self, window_open: bool, result: dict[str, Any]
    ) -> bool:
        """Exercise the valves; True while maintenance owns the valves.

        Switched-off thermostats are switched to heating for it and back off
        afterwards, so they are exercised too.
        """
        now = dt_util.utcnow()
        if self._maintenance_started is None:
            requested = self._maintenance_requested
            self._maintenance_requested = False
            if not requested and (
                window_open
                or self._manual_override is not None
                or not self._maintenance_due(now)
            ):
                return False
            self._maintenance_started = now
            self._maintenance_last = now
            self._log("Ventilwartung gestartet")
            await self._save_learning()

        phase_seconds = int(
            self.config.get(CONF_MAINTENANCE_DURATION) or VALVE_MAINTENANCE_PHASE_SECONDS
        )
        phase = valve_maintenance_phase(self._maintenance_started, now, phase_seconds)
        if phase is None:
            # Done: forget the maintenance setpoints so they are not taken
            # for manual changes, and write the normal target again.
            self._maintenance_started = None
            self._written.clear()
            self._skip_closed.clear()
            for entity_id in sorted(self._maintenance_woken):
                await self._call(
                    "climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": "off"}
                )
            self._maintenance_woken.clear()
            return False

        result["valve_maintenance"] = phase
        result["status"] = (
            "Ventilwartung – Ventile öffnen"
            if phase == "open"
            else "Ventilwartung – Ventile schließen"
        )
        for entity_id in self._thermostat_ids():
            state = self.hass.states.get(entity_id)
            if not self._valid(state):
                continue
            if state.state == "off":
                if entity_id not in self._maintenance_woken:
                    modes = state.attributes.get("hvac_modes") or []
                    mode = (
                        "heat"
                        if not modes or "heat" in modes
                        else next((item for item in modes if item != "off"), None)
                    )
                    if mode is not None and await self._call(
                        "climate",
                        "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": mode},
                    ):
                        self._maintenance_woken.add(entity_id)
                continue
            limit = "max_temp" if phase == "open" else "min_temp"
            try:
                setpoint = float(state.attributes[limit])
            except (KeyError, TypeError, ValueError):
                continue
            if not await self._write_setpoint(entity_id, state, setpoint, now):
                result["control_error"] = True
        return True

    async def _apply_target(
        self,
        decision_mode: str,
        target: float,
        room_temperature: float,
        result: dict[str, Any],
    ) -> None:
        """Write the decision to every thermostat of the room."""
        override_key = (decision_mode, round(target, 1))
        if self._manual_override is not None and self._manual_override != override_key:
            # The decision moved on: resume control and write the new target.
            self._manual_override = None
            self._written.clear()

        states = {
            entity_id: self.hass.states.get(entity_id)
            for entity_id in self._thermostat_ids()
        }
        available = {
            entity_id: state
            for entity_id, state in states.items()
            if self._valid(state)
        }
        unavailable = [entity_id for entity_id in states if entity_id not in available]
        result["unavailable_thermostats"] = unavailable
        for entity_id in unavailable:
            # After a dropout (Zigbee, restart) the thermostat may come back with
            # another setpoint. That is not a manual change: forget what was
            # written so the target is sent again once it is reachable.
            self._written.pop(entity_id, None)

        skipped = self._effective_skipped(available)
        now = dt_util.utcnow()
        for entity_id in list(self._skip_closed):
            if entity_id not in skipped:
                # Back in the room: send the normal target again.
                self._skip_closed.discard(entity_id)
                self._written.pop(entity_id, None)
        for entity_id in skipped:
            state = available[entity_id]
            if entity_id in self._skip_closed or state.state == "off":
                continue
            minimum = _as_number(state.attributes.get("min_temp"))
            if minimum is not None and await self._write_setpoint(
                entity_id, state, minimum, now
            ):
                self._skip_closed.add(entity_id)
        result["skipped_valves"] = sorted(skipped)
        available = {
            entity_id: state
            for entity_id, state in available.items()
            if entity_id not in skipped
        }

        sync_manual = self.config.get(
            CONF_SYNC_MANUAL_CHANGE, DEFAULT_SYNC_MANUAL_CHANGE
        )
        lock = bool(self.config.get(CONF_LOCK_VALVES))
        if self._manual_override is None:
            for entity_id, state in available.items():
                if not self._changed_manually(entity_id, state):
                    continue
                if decision_mode == "window" and not lock:
                    # Turned while a window is open: never heat now; keep the
                    # value for when the window is closed, or drop it.
                    self._written.pop(entity_id, None)
                    turned = self._climate_setpoint(state)
                    if self.config.get(CONF_WINDOW_CHANGE) == WINDOW_CHANGE_DISCARD:
                        result["window_change"] = "discarded"
                        result["status"] = (
                            f"{result['status']} – Änderung am Ventil verworfen"
                        )
                        self._log(
                            f"{self._friendly_name(entity_id)} bei offenem Fenster "
                            "verstellt – verworfen"
                        )
                        continue
                    manual = self._adopt_manual_change(entity_id, state)
                    if manual is not None:
                        value = f"{manual:g}".replace(".", ",")
                        self._pending_source = f"Ventil {self._friendly_name(entity_id)}"
                        result["window_change"] = "kept"
                        result["quick_mode"] = QUICK_MANUAL
                        result["status"] = (
                            f"{result['status']} – {value} °C gemerkt, gilt nach "
                            "dem Schließen"
                        )
                        _LOGGER.info(
                            "Setpoint of %s turned to %s while a window is open; "
                            "holding %.1f °C once it is closed",
                            entity_id,
                            turned,
                            manual,
                        )
                    break
                if lock:
                    # Set back below: forget the write so it is sent again.
                    _LOGGER.info(
                        "Setpoint of %s turned to %s; locked, setting it back",
                        entity_id,
                        state.attributes.get("temperature"),
                    )
                    self._written.pop(entity_id, None)
                    result["valve_reset"] = entity_id
                    continue
                manual = (
                    self._adopt_manual_change(entity_id, state)
                    if sync_manual and decision_mode != "maintenance"
                    else None
                )
                if manual is not None:
                    self._pending_source = f"Ventil {self._friendly_name(entity_id)}"
                    # The whole room follows the valve that was turned.
                    _LOGGER.info(
                        "Setpoint of %s turned to %s; holding %.1f °C in the room",
                        entity_id,
                        state.attributes.get("temperature"),
                        manual,
                    )
                    self._written.clear()
                    # The knob may still be turning: its value counts as
                    # confirmed, so the next click is taken over as well
                    # instead of being set back to this intermediate value.
                    turned = self._climate_setpoint(state)
                    if turned is not None:
                        self._written[entity_id] = _WrittenSetpoint(
                            round(turned, 1), now, confirmed=True
                        )
                    decision_mode, target = "quick_manual", manual
                    value = f"{manual:g}".replace(".", ",")
                    result["mode"] = decision_mode
                    result["target_temperature"] = manual
                    result["quick_mode"] = QUICK_MANUAL
                    result["quick_until"] = (
                        self.quick_until.isoformat() if self.quick_until else None
                    )
                    result["status"] = result["decision_status"] = (
                        f"{value} °C am Thermostat eingestellt"
                    )
                    if self._manual_capped_from is not None:
                        turned_text = f"{self._manual_capped_from:g}".replace(".", ",")
                        result["status"] = result["decision_status"] = (
                            f"{turned_text} °C gedreht – auf {value} °C begrenzt"
                        )
                else:
                    self._manual_override = override_key
                    _LOGGER.info(
                        "Setpoint of %s changed manually to %s; pausing control",
                        entity_id,
                        state.attributes.get("temperature"),
                    )
                break
        if self._manual_override is not None:
            result["manual_override"] = True
            result["status"] = (
                "Manuell übersteuert – Regelung pausiert bis zum "
                "nächsten Moduswechsel"
            )
            self._divergent_since.clear()
            self._divergence = {}
            return

        active = {
            entity_id: state
            for entity_id, state in available.items()
            if state.state != "off"
        }
        if not active:
            result["status"] = "Thermostat ausgeschaltet – keine Sollwertänderung"
            return

        failed = False
        # Outside the heating season the valve stays at its minimum, and
        # maintenance opens it fully: neither is calibrated or pushed.
        calibrate = decision_mode not in ("season_off", "outdoor_warm", "maintenance")
        sent = target
        band = self.config.get(CONF_AGGRESSIVE_RANGE)
        if calibrate and band is not None:
            sent = aggressive_setpoint(
                target,
                room_temperature,
                float(band),
                float(
                    self.config.get(CONF_AGGRESSIVE_OFFSET)
                    or DEFAULT_AGGRESSIVE_OFFSET
                ),
            )
            result["aggressive_setpoint"] = sent
        setpoints: dict[str, float] = {}
        for entity_id, state in active.items():
            setpoint = self._fit_to_thermostat(
                self._calibrated(entity_id, state, sent, room_temperature, now)
                + self.valve_offsets.get(entity_id, 0.0)
                if calibrate
                else sent,
                state,
            )
            setpoints[entity_id] = setpoint
            if not await self._write_setpoint(entity_id, state, setpoint, now):
                failed = True
        result["thermostat_setpoints"] = setpoints
        self._track_divergence(active, now)
        result["valve_divergence"] = dict(self._divergence)
        if failed:
            result["control_error"] = True
            result["status"] = (
                "Thermostat konnte Sollwert nicht übernehmen – "
                "erneuter Versuch beim nächsten Update"
            )
        elif unavailable:
            result["status"] = (
                f"{result['status']} – {len(unavailable)} Thermostat(e) "
                "nicht verfügbar"
            )

    def _effective_skipped(self, available: dict[str, State]) -> set[str]:
        """Skipped valves that are reachable; at least one valve stays in."""
        skipped = {entity_id for entity_id in self.skipped_valves if entity_id in available}
        if skipped and skipped >= set(available):
            first = next(iter(available))
            skipped.discard(first)
        return skipped

    def _track_divergence(self, active: dict[str, State], now: datetime) -> None:
        """Note valves that report another setpoint than the one written."""
        divergence: dict[str, str] = {}
        for entity_id, state in active.items():
            written = self._written.get(entity_id)
            current = self._climate_setpoint(state)
            if (
                written is None
                or current is None
                or abs(current - written.target) < VALVE_DIVERGENCE_MIN
            ):
                self._divergent_since.pop(entity_id, None)
                continue
            since = self._divergent_since.setdefault(entity_id, now)
            if (now - since).total_seconds() >= VALVE_DIVERGENCE_SECONDS:
                divergence[entity_id] = (
                    f"{current:.1f} statt {written.target:.1f} °C".replace(".", ",")
                )
        for entity_id in list(self._divergent_since):
            if entity_id not in active:
                self._divergent_since.pop(entity_id)
        self._divergence = divergence

    async def async_set_valve_skipped(self, entity_id: str, skipped: bool) -> None:
        """Leave one valve out of control (closed once) or take it back."""
        if skipped:
            self.skipped_valves.add(entity_id)
        else:
            self.skipped_valves.discard(entity_id)
        await self.async_refresh()

    def _update_heating_watchdog(
        self, target: float | None, room_temperature: float, *, watch: bool
    ) -> None:
        """Flag a room that stays well below its target without warming up.

        The room is judged every two hours: it has to warm up by the minimum
        rise in that time. Rising in small steps does not start the clock
        again, so a room creeping up 0.1 °C an hour is caught too.
        """
        now = dt_util.utcnow()
        last = self.data if isinstance(self.data, dict) else {}
        # While the boiler delivers nothing (the whole house, or the usual
        # night pause without a warm radiator here) the room cannot warm up;
        # the house tells about the boiler itself.
        boiler_off = last.get("radiator_supply") != SUPPLY_WARM and (
            last.get("house_supply") == SUPPLY_COLD
            or bool(last.get("supply_usually_off"))
        )
        if (
            not watch
            or boiler_off
            or target is None
            or target - room_temperature < HEATING_WATCHDOG_GAP
        ):
            self._shortfall_since = None
            self._shortfall_temperature = None
            self.heating_problem = False
            self.heating_problem_detail = None
            return
        if self._shortfall_since is None or self._shortfall_temperature is None:
            self._shortfall_since = now
            self._shortfall_temperature = room_temperature
            return
        rise = room_temperature - self._shortfall_temperature
        if rise >= HEATING_WATCHDOG_MIN_RISE:
            # Warming up as it should: judge the next two hours from here.
            self._shortfall_since = now
            self._shortfall_temperature = room_temperature
            self.heating_problem = False
            self.heating_problem_detail = None
            return
        if (now - self._shortfall_since).total_seconds() < HEATING_WATCHDOG_SECONDS:
            return
        if not self.heating_problem:
            _LOGGER.warning(
                "Room stays at %.1f °C, well below its target of %.1f °C, "
                "without warming up",
                room_temperature,
                target,
            )
        self.heating_problem = True
        hours = (now - self._shortfall_since).total_seconds() / 3600
        self.heating_problem_detail = (
            f"{room_temperature:.1f} statt {target:.1f} °C, in {hours:.0f} h "
            f"nur {max(rise, 0.0):.1f} °C wärmer"
        ).replace(".", ",")

    async def async_start_boost(self) -> None:
        """Heat to the boost temperature for the configured duration."""
        self._pending_source = "Boost"
        duration = int(self.config.get(CONF_BOOST_DURATION) or DEFAULT_BOOST_DURATION)
        self.boost_until = dt_util.utcnow() + timedelta(seconds=duration)
        self.quick_mode = QUICK_AUTO
        self.quick_until = None
        await self.async_request_refresh()

    @property
    def current_quick_mode(self) -> str:
        """The quick selection as shown: a running boost wins."""
        return QUICK_BOOST if self.boost_until is not None else self.quick_mode

    async def async_set_quick_mode(self, mode: str, source: str = "Betriebsart") -> None:
        """Pick a mode by hand; it holds until the next schedule switch."""
        self._pending_source = source
        if mode == QUICK_BOOST:
            duration = int(
                self.config.get(CONF_BOOST_DURATION) or DEFAULT_BOOST_DURATION
            )
            self.boost_until = dt_util.utcnow() + timedelta(seconds=duration)
            self.quick_mode = QUICK_AUTO
            self.quick_until = None
        else:
            if mode == QUICK_MANUAL:
                # Picked without a temperature: hold the current target.
                current = (self.data or {}).get("target_temperature")
                self.quick_temperature = float(
                    current
                    if current is not None
                    else self.config.get(
                        CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE
                    )
                )
            self.boost_until = None
            self.quick_mode = mode
            self.quick_until = None if mode == QUICK_AUTO else self._quick_end()
            if mode not in (QUICK_AUTO, QUICK_MAINTENANCE) and source != "Push-Meldung":
                self._record_habit(mode, QUICK_LABELS.get(mode, mode))
        # A tap on the dashboard should act at once, not after the debounce.
        await self.async_refresh()

    async def async_set_manual_temperature(self, temperature: float) -> None:
        """Hold a temperature set by hand for the chosen Betriebsart-Dauer.

        While a window is open the value waits for it to close, or is
        refused when the room drops changes made during airing.
        """
        if (
            (self.data or {}).get("mode") == "window"
            and self.config.get(CONF_WINDOW_CHANGE) == WINDOW_CHANGE_DISCARD
        ):
            raise ServiceValidationError(
                "Das Fenster ist offen – Änderungen beim Lüften werden verworfen."
            )
        self._pending_source = "Raum-Thermostat"
        self.boost_until = None
        self.quick_mode = QUICK_MANUAL
        self.quick_temperature = self._manual_capped(float(temperature))
        self.quick_until = self._manual_until(self._quick_end())
        # A temperature set directly is meant as is (as in Climate Group Helper).
        self.room_offset = 0.0
        value = f"{float(temperature):g}"
        self._record_habit(f"manual:{value}", f"{value.replace('.', ',')} °C")
        await self.async_refresh()

    def _record_habit(self, mode: str, label: str) -> None:
        """Remember a mode picked by hand, for schedule suggestions."""
        self.habits.record(dt_util.now(), mode, label)
        self._habits_at = None
        self.hass.async_create_task(self._save_learning())

    def _update_habits(self, result: dict[str, Any]) -> str | None:
        """Schedule suggestions from repeated hand picks; a new one to push."""
        now = dt_util.now()
        if self._habits_at is None or now - self._habits_at >= timedelta(hours=1):
            self._habits_at = now
            self._habit_suggestions = (
                self.habits.suggestions(now) + self._shower_suggestions(now)
            )
        suggestions = self._habit_suggestions
        result["schedule_suggestion"] = (
            suggestions[0]["text"] if suggestions else "Keine Vorschläge"
        )
        result["schedule_suggestions"] = [item["text"] for item in suggestions]
        for item in suggestions:
            if item["key"] not in self.habits.notified:
                self.habits.notified.append(item["key"])
                return str(item["text"])
        return None

    def _shower_suggestions(self, now: datetime) -> list[dict]:
        """Usual shower times that the schedule does not warm the room for."""
        if not self.config.get(CONF_SHOWER_LEARNING, DEFAULT_SHOWER_LEARNING):
            return []

        profile = self.supply_profile

        def lead_start(minute: int) -> tuple[int, int | None]:
            """Comfort start for a shower at ``minute``, and the hour the
            boiler starts when it is later than the usual lead (heating
            earlier would be in vain)."""
            start = (minute - SHOWER_LEAD_MINUTES) % (24 * 60)
            if not profile.usually_off(start // 60):
                return start, None
            on_hour = profile.next_on_hour(start // 60)
            if on_hour is None or not start < on_hour * 60 <= minute:
                return start, None
            return on_hour * 60, on_hour

        def describe(when: str, clock: str, _label: str, days: int) -> str:
            hour, minute = (int(part) for part in clock.split(":"))
            start, on_hour = lead_start(hour * 60 + minute)
            text = (
                f"{when} gegen {clock} Uhr wird geduscht ({days}× in "
                f"{HABIT_DAYS // 7} Wochen) – Komfort im Bad ab "
                f"{start // 60:02d}:{start % 60:02d} Uhr in den Zeitplan?"
            )
            if on_hour is not None:
                text += f" (die Zentralheizung liefert erst ab {on_hour}:00 Uhr)"
            return text

        weekly = self._schedule_weekly.get(self.config.get(CONF_SCHEDULE_ENTITY) or "")
        return [
            item
            for item in self.showers.suggestions(now, describe)
            if not schedule_covers(
                weekly, item["weekend"], lead_start(item["minute"])[0]
            )
        ]

    def _observe_shower(self, result: dict[str, Any]) -> bool:
        """A shower in the room's humidity; True when one was seen."""
        result["shower_until"] = (
            self._shower_until.isoformat() if self._shower_until else None
        )
        if not self.config.get(CONF_SHOWER_LEARNING, DEFAULT_SHOWER_LEARNING):
            return False
        humidity = _as_float(self._state(CONF_HUMIDITY_ENTITY))
        if humidity is None:
            return False
        now = dt_util.utcnow()
        if not self._shower_watch.observe(now.timestamp(), humidity):
            return False
        self.showers.record(dt_util.now(), "shower", "Duschen")
        self._shower_until = now + timedelta(seconds=SHOWER_MODEL_PAUSE_SECONDS)
        self._habits_at = None
        result["shower_until"] = self._shower_until.isoformat()
        self._log("Duschen erkannt (Luftfeuchte steigt schnell)")
        return True

    async def async_seed_showers(self) -> None:
        """Showers of the last days from the recorder, once."""
        humidity_id = self.config.get(CONF_HUMIDITY_ENTITY)
        if (
            self._showers_seeded
            or not humidity_id
            or not self.config.get(CONF_SHOWER_LEARNING, DEFAULT_SHOWER_LEARNING)
            or "recorder" not in self.hass.config.components
        ):
            return
        from homeassistant.components.recorder import get_instance, history

        end = dt_util.utcnow()
        start = end - timedelta(days=SHOWER_HISTORY_DAYS)
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start,
                end,
                [humidity_id],
                None,
                True,
                False,
                False,
                True,
            )
        except Exception:  # noqa: BLE001 - history is a bonus, never fatal
            _LOGGER.debug("Humidity history not available", exc_info=True)
            return
        readings = []
        for state in states.get(humidity_id, []):
            if not isinstance(state, State):
                continue
            try:
                readings.append((state.last_changed.timestamp(), float(state.state)))
            except (TypeError, ValueError):
                continue
        watch = ShowerWatch(
            SHOWER_RISE_PERCENT, SHOWER_RISE_WINDOW_SECONDS, SHOWER_COOLDOWN_SECONDS
        )
        found = showers_from_history(watch, readings, end.timestamp())
        for at in found:
            self.showers.record(
                dt_util.as_local(dt_util.utc_from_timestamp(at)), "shower", "Duschen"
            )
        self._showers_seeded = True
        self._habits_at = None
        if found:
            self._log(f"{len(found)}× Duschen aus dem Verlauf erkannt")
        await self._save_learning()

    async def async_start_learn_run(self, at: datetime | None = None) -> None:
        """Plan the calibration run for ``at``, or start it now."""
        now = dt_util.utcnow()
        if at is not None and dt_util.as_utc(at) > now:
            self.learn_run_at = dt_util.as_utc(at)
        else:
            self.learn_run_at = now
        self._pending_source = "Kalibrierlauf"
        await self.async_refresh()

    async def async_cancel_learn_run(self) -> None:
        """Drop a planned or running calibration run."""
        self.learn_run_at = None
        self.learn_run_until = None
        self._learn_run_target = None
        await self.async_refresh()

    def _learn_run(
        self, room_temperature: float, max_temperature: float | None
    ) -> tuple[str, str, float] | None:
        """(mode, status, target) while the calibration run heats fully."""
        now = dt_util.utcnow()
        if (
            self.learn_run_until is None
            and self.learn_run_at is not None
            and now >= self.learn_run_at
        ):
            self.learn_run_at = None
            self.learn_run_until = now + timedelta(seconds=LEARN_RUN_DURATION_SECONDS)
            self._learn_run_target = None
            self._log("Kalibrierlauf gestartet")
        if self.learn_run_until is None:
            return None
        if now >= self.learn_run_until:
            self.learn_run_until = None
            self._learn_run_target = None
            self._log("Kalibrierlauf beendet")
            return None
        if self._learn_run_target is None:
            top = max_temperature if max_temperature is not None else 30.0
            self._learn_run_target = min(
                top, round((room_temperature + LEARN_RUN_RISE) * 2) / 2
            )
        end = dt_util.as_local(self.learn_run_until).strftime("%H:%M")
        return (
            "learn_run",
            f"Kalibrierlauf – heizt voll bis {end} Uhr, das Raummodell lernt",
            self._learn_run_target,
        )

    def _quick_end(self) -> datetime | None:
        """When a mode picked now ends, after the chosen duration."""
        now = dt_util.utcnow()
        if self.quick_duration == QUICK_UNTIL_1H:
            return now + timedelta(hours=1)
        if self.quick_duration == QUICK_UNTIL_3H:
            return now + timedelta(hours=3)
        if self.quick_duration == QUICK_UNTIL_MORNING:
            local = dt_util.as_local(now)
            morning = local.replace(
                hour=QUICK_MORNING_HOUR, minute=0, second=0, microsecond=0
            )
            if morning <= local:
                morning += timedelta(days=1)
            return dt_util.as_utc(morning)
        if self.quick_duration == QUICK_UNTIL_FOREVER:
            return None
        return self._next_event

    async def async_set_quick_duration(self, duration: str) -> None:
        """Choose how long a hand-picked mode holds; a running one is re-timed."""
        self.quick_duration = duration
        if self.quick_mode != QUICK_AUTO:
            self.quick_until = self._quick_end()
        await self.async_refresh()

    async def async_stop_boost(self) -> None:
        """End a running boost early."""
        self.boost_until = None
        await self.async_request_refresh()

    def _quick_target(
        self,
        comfort_temperature: float,
        eco_temperature: float,
        frost_value: object,
        off_temperature: float | None,
        away_temperature: float | None = None,
        max_temperature: float | None = None,
    ) -> tuple[str, str, float] | None:
        """The (mode, status, target) of a hand-picked quick mode, if any."""
        if self.quick_mode != QUICK_AUTO and self.quick_until is not None and (
            dt_util.utcnow() >= self.quick_until
        ):
            self.quick_mode = QUICK_AUTO
            self.quick_until = None
        if self.quick_mode == QUICK_AUTO:
            return None
        if self.quick_until is not None:
            local = dt_util.as_local(self.quick_until)
            days = (local.date() - dt_util.now().date()).days
            day = (
                "" if days <= 0
                else " morgen" if days == 1
                else f" {local.strftime('%d.%m.')}"
            )
            until = f" bis{day} {local.strftime('%H:%M')} Uhr"
        elif self.quick_duration == QUICK_UNTIL_FOREVER:
            until = " (dauerhaft)"
        else:
            until = ""
        if self.quick_mode == QUICK_MANUAL and self.quick_temperature is not None:
            value = f"{self.quick_temperature:g}".replace(".", ",")
            return (
                "quick_manual",
                f"{value} °C von Hand{until}",
                self.quick_temperature,
            )
        if self.quick_mode == QUICK_MAINTENANCE:
            return (
                "quick_maintenance",
                f"Wartung – Ventile voll geöffnet{until}",
                max_temperature if max_temperature is not None else 30.0,
            )
        if self.quick_mode == QUICK_COMFORT:
            return "quick_comfort", f"Komfort von Hand{until}", comfort_temperature
        if self.quick_mode == QUICK_ECO:
            return "quick_eco", f"Eco von Hand{until}", eco_temperature
        if self.quick_mode == QUICK_AWAY:
            away = away_temperature if away_temperature is not None else eco_temperature
            return "quick_away", f"Abwesend von Hand{until}", away
        for mode, label, key, default in (
            (QUICK_SLEEP, "Schlafen", CONF_SLEEP_TEMPERATURE, DEFAULT_SLEEP_TEMPERATURE),
            (QUICK_HOME, "Zuhause", CONF_HOME_TEMPERATURE, DEFAULT_HOME_TEMPERATURE),
            (
                QUICK_ACTIVITY,
                "Aktivität",
                CONF_ACTIVITY_TEMPERATURE,
                DEFAULT_ACTIVITY_TEMPERATURE,
            ),
        ):
            if self.quick_mode == mode:
                value = self.config.get(key)
                target = float(value) if value is not None else default
                return f"quick_{mode}", f"{label} von Hand{until}", target
        off = (
            float(frost_value)
            if frost_value is not None
            else off_temperature
            if off_temperature is not None
            else eco_temperature
        )
        return "quick_off", f"Aus von Hand{until}", off

    def _force_target(
        self, comfort_temperature: float, eco_temperature: float
    ) -> tuple[str, str, float] | None:
        """(mode, status, target) while an entity forces comfort or eco.

        Comfort wins over eco. A number at the end of the entity's name is
        the temperature, e.g. "Party 23".
        """
        for key, mode, label, default in (
            (CONF_FORCE_COMFORT_ENTITIES, "force_comfort", "Komfort", comfort_temperature),
            (CONF_FORCE_ECO_ENTITIES, "force_eco", "Eco", eco_temperature),
        ):
            entity_ids = self.config.get(key) or []
            if isinstance(entity_ids, str):
                entity_ids = [entity_ids]
            for entity_id in entity_ids:
                state = self.hass.states.get(entity_id)
                if state is None or state.state not in ("on", "active", "home"):
                    continue
                name = self._friendly_name(entity_id)
                temperature = name_temperature(name)
                return (
                    mode,
                    f"{label} erzwungen – {name}",
                    temperature if temperature is not None else default,
                )
        return None

    def _house_calendar_view(
        self,
    ) -> tuple[str | None, bool, float | None, datetime | None, str | None]:
        """What the house calendar asks of this room right now.

        Returns (schedule to use, comfort time, temperature, end, event name).
        """
        nothing = (None, False, None, None, None)
        if not self.config.get(
            CONF_FOLLOW_HOUSE_CALENDAR, DEFAULT_FOLLOW_HOUSE_CALENDAR
        ):
            return nothing
        house = self.hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)
        overlay = house.calendar_overlay() if house is not None else None
        if overlay is None:
            return nothing
        name, schedule_name, comfort, temperature, end = overlay
        schedule = match_schedule(self.schedule_options(), schedule_name or name)
        return schedule, comfort, temperature, end, name

    def schedule_options(self) -> list[tuple[str, str]]:
        """The room's comfort schedules as (entity_id, name), first = default."""
        ids = [self.config.get(CONF_SCHEDULE_ENTITY)]
        extra = self.config.get(CONF_ADDITIONAL_SCHEDULE_ENTITIES) or []
        if isinstance(extra, str):
            extra = [extra]
        extra = [*extra, self.config.get(CONF_SCHOOL_FREE_SCHEDULE)]
        ids = list(dict.fromkeys([*ids, *extra]))
        return [
            (entity_id, self._friendly_name(entity_id))
            for entity_id in ids
            if entity_id
        ]

    @property
    def active_schedule(self) -> str | None:
        """Entity id of the comfort schedule in use.

        A running house calendar event that names one of the room's
        schedules wins over the "Zeitplan" select.
        """
        options = self.schedule_options()
        if not options:
            return None
        override = self._house_calendar_view()[0]
        if override is not None:
            return override
        return select_schedule(options, self.schedule_choice)

    async def async_set_schedule(self, entity_id: str) -> None:
        """Use another of the room's comfort schedules."""
        self.schedule_choice = entity_id
        self._preheat_event = None
        await self.async_refresh()

    def _adopt_manual_change(self, entity_id: str, state: State) -> float | None:
        """Take a setpoint turned at a valve as quick mode Manuell.

        Returns the room temperature it stands for (calibration offset
        removed), or None when the value can't be read.
        """
        setpoint = self._climate_setpoint(state)
        if setpoint is None:
            return None
        cached = self._calibration.get(entity_id)
        if cached is not None and entity_id not in self._external_fed:
            setpoint -= cached[0]
        temperature = self._manual_capped(round(setpoint * 2) / 2)
        self.boost_until = None
        self.quick_mode = QUICK_MANUAL
        self.quick_temperature = temperature
        self.quick_until = self._manual_until(self._quick_end())
        return temperature

    def _manual_capped(self, temperature: float) -> float:
        """A temperature set by hand, at most the room's cap for hand changes."""
        cap = self.config.get(CONF_MANUAL_MAX_TEMPERATURE)
        if cap is None:
            self._manual_capped_from = None
            return temperature
        cap = float(cap)
        if temperature > cap:
            self._manual_capped_from = temperature
            self._log(
                f"{temperature:g} °C von Hand gewählt – auf {cap:g} °C begrenzt".replace(
                    ".", ","
                )
            )
            return cap
        self._manual_capped_from = None
        return temperature

    def _manual_until(self, until: datetime | None) -> datetime | None:
        """End of a hand change, at most the room's longest hand change."""
        seconds = int(self.config.get(CONF_MANUAL_MAX_DURATION) or 0)
        if seconds <= 0:
            return until
        latest = dt_util.utcnow() + timedelta(seconds=seconds)
        return latest if until is None or until > latest else until

    def _window_drop(self, room_temperature: float) -> bool:
        """An open window guessed from a fast temperature drop."""
        if not self.config.get(CONF_WINDOW_DROP_DETECTION) or self._room_fallback:
            self._temperature_samples.clear()
            self._drop_until = None
            return False
        now = dt_util.utcnow()
        if self._drop_until is not None:
            if now < self._drop_until:
                return True
            self._drop_until = None
        samples = [
            sample
            for sample in self._temperature_samples
            if (now - sample[0]).total_seconds() <= WINDOW_DROP_SECONDS
        ]
        if not samples or samples[-1][1] != room_temperature:
            samples.append((now, room_temperature))
        self._temperature_samples = samples
        if detect_temperature_drop(
            samples, now, WINDOW_DROP_SECONDS, WINDOW_DROP_DEGREES
        ):
            _LOGGER.info("Temperature drop in %s: treating as open window", self.entry_id)
            self._drop_until = now + timedelta(seconds=WINDOW_DROP_HOLD_SECONDS)
            # A new detection needs a new drop.
            self._temperature_samples = []
            return True
        return False

    def _valve_openings(self) -> list[float]:
        """Valve openings in percent, as far as the thermostats report them."""
        registry = er.async_get(self.hass)
        openings: list[float] = []
        for entity_id in self._thermostat_ids():
            state = self.hass.states.get(entity_id)
            if entity_id in self.skipped_valves or (
                state is not None and state.state == "off"
            ):
                continue
            value = None
            if state is not None:
                for key in HEAT_DEMAND_KEYS:
                    if key in state.attributes:
                        value = _as_number(state.attributes.get(key))
                        break
            entry = registry.async_get(entity_id)
            if value is None and entry is not None and entry.device_id:
                for device_entry in er.async_entries_for_device(registry, entry.device_id):
                    if device_entry.domain in ("sensor", "number") and any(
                        key in device_entry.entity_id for key in HEAT_DEMAND_KEYS[:2]
                    ):
                        value = _as_float(self.hass.states.get(device_entry.entity_id))
                        if value is not None:
                            break
            if value is not None:
                openings.append(max(0.0, min(100.0, value)))
        return openings

    def _heat_demand(
        self, target: float | None, room_temperature: float | None
    ) -> tuple[int | None, str]:
        """Heat demand of the room in percent and where it comes from."""
        if not self.enabled or target is None or room_temperature is None:
            return (0 if self.enabled else None), "keine Regelung"
        openings = self._valve_openings()
        if openings:
            return round(sum(openings) / len(openings)), "Ventile"
        gap = target - room_temperature
        return round(max(0.0, min(1.0, gap / HEAT_DEMAND_FULL_GAP)) * 100), "geschätzt"

    @property
    def room_name(self) -> str:
        return self._room_name()

    @property
    def radiator_power_w(self) -> int:
        """Output of the room's radiators at full demand (for the heat meter)."""
        configured = int(self.config.get(CONF_RADIATOR_POWER) or 0)
        if configured > 0:
            return configured
        return RADIATOR_POWER_PER_THERMOSTAT_W * max(1, len(self._thermostat_ids()))

    def heat_load(self, outdoor: float) -> dict[str, Any] | None:
        """The room's heat load at ``outdoor`` from the learned model, in kW
        of the configured radiator power; None until the model is ready."""
        if not self.room_model.ready:
            return None
        comfort = _as_number((self.data or {}).get("comfort_temperature"))
        if comfort is None:
            comfort = float(
                self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
            )
        load = heat_load(self.room_model.view(outdoor), comfort, outdoor)
        if load is None:
            return None
        power_kw = self.radiator_power_w / 1000
        return {
            "room": self.room_name,
            "comfort_temperature": comfort,
            "load_kw": round(load.share * power_kw, 2),
            "radiator_kw": round(power_kw, 2),
            "share_percent": round(load.share * 100),
            "holds_comfort_down_to": round(load.holds_down_to, 1),
            "verdict": load.verdict,
            # Below the trusted mark the figures are still rough.
            "trusted": self.room_model.trusted,
        }

    def _house_target(
        self,
        *,
        comfort_temperature: float,
        eco_temperature: float,
        away_temperature: float | None,
        frost_value: object,
        room_temperature: float,
        outdoor_temperature: float | None,
    ) -> tuple[str, str, float] | None:
        """The (mode, status, target) the house mode asks for, if any.

        Abwesend lowers to the away temperature (else eco). Urlaub holds frost
        protection (else away/eco) and heats up in time for the return.
        """
        house = self.hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)
        if house is None:
            return None
        setback = away_temperature if away_temperature is not None else eco_temperature
        if house.mode == HOUSE_AWAY:
            return "house_away", "Haus: Abwesend – abgesenkt", setback
        if house.mode != HOUSE_VACATION:
            return None
        until = house.vacation_until
        if until is not None:
            lead = calculate_lead_minutes(
                room_temperature,
                comfort_temperature,
                self.effective_heating_rate,
                outdoor_temperature,
                int(self.config.get(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)),
            )
            end = dt_util.as_local(until).strftime("%d.%m. %H:%M")
            if dt_util.utcnow() >= until - timedelta(minutes=lead):
                return (
                    "house_return",
                    f"Rückkehr aus dem Urlaub am {end} Uhr – vorgeheizt",
                    comfort_temperature,
                )
            status = f"Urlaub bis {end} Uhr"
        else:
            status = "Urlaub"
        target = float(frost_value) if frost_value is not None else setback
        return "house_vacation", status, target

    def _weather_inputs(self) -> tuple[float, float]:
        """Solar radiation in kW/m² and wind speed in m/s (0 when unknown)."""
        solar = 0.0
        solar_state = self._state(CONF_SOLAR_RADIATION_ENTITY)
        value = _as_float(solar_state)
        if value is not None and value > 0:
            unit = str(solar_state.attributes.get("unit_of_measurement") or "")
            solar = solar_to_kw(value, unit.lower())
        wind = 0.0
        wind_state = self._state(CONF_WIND_SPEED_ENTITY)
        value = _as_float(wind_state)
        if value is not None and value > 0:
            unit = str(wind_state.attributes.get("unit_of_measurement") or "")
            wind = wind_to_ms(value, unit.lower())
        return min(solar, 1.5), min(wind, 40.0)

    def _model_view(
        self, outdoor: float | None, solar_kw: float, wind: float
    ) -> ModelView | None:
        """The learned room equation with today's weather, once it is trusted."""
        if (
            outdoor is None
            or not self.config.get(CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL)
            or not self.room_model.ready
        ):
            return None
        return replace(
            self.room_model.view(outdoor, solar_kw, wind),
            cooling_factor=self.cooling.active_factor,
        )

    @staticmethod
    def _recovery_floor(
        view: ModelView, comfort: float, room: float, seconds: float
    ) -> float:
        """Lowest setback from which full heating gets back in ``seconds``.

        When comfort is out of reach today, the room has to get back to what
        it can reach instead.
        """
        reach = min(
            comfort, view.reachable(min(room, comfort)) - RECOVERY_REACH_MARGIN
        )
        return round(view.lowest_start(reach, seconds / 3600), 1)

    def _hold_comfort(self, now: datetime) -> str | None:
        """Why an empty room keeps comfort for now, or None."""
        if not self.config.get(CONF_PRESENCE_ENTITY):
            return None
        grace = int(
            self.config.get(CONF_ROOM_EMPTY_GRACE, DEFAULT_ROOM_EMPTY_GRACE) or 0
        )
        if (
            grace > 0
            and self._comfort_started_at is not None
            and (now - self._comfort_started_at).total_seconds() < grace
        ):
            end = dt_util.as_local(
                self._comfort_started_at + timedelta(seconds=grace)
            ).strftime("%H:%M")
            return f"Komfortbeginn – Raum noch leer, Komfort bis {end} Uhr gehalten"
        if self.config.get(CONF_LEARN_USAGE, DEFAULT_LEARN_USAGE):
            local = dt_util.as_local(now)
            if self.usage.usually_used(local.weekday(), local.hour):
                return "Raum um diese Zeit meist genutzt – Komfort gehalten"
        return None

    def _observe_usage(self, present: bool) -> bool:
        """Learn when the room is used; True when an hour was finished."""
        if not self.config.get(CONF_PRESENCE_ENTITY) or not self.config.get(
            CONF_LEARN_USAGE, DEFAULT_LEARN_USAGE
        ):
            return False
        now = dt_util.utcnow()
        seconds = (
            0.0 if self._usage_at is None else (now - self._usage_at).total_seconds()
        )
        self._usage_at = now
        if not self._household_present:
            # Nobody home: an empty room says nothing about its use.
            self.usage.pause()
            return False
        local = dt_util.as_local(now)
        return self.usage.observe(local.weekday(), local.hour, present, seconds)

    def _device_sensor(self, entity_id: str, suffix: str) -> str | None:
        """A sensor of the thermostat's device whose id ends in ``suffix``."""
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if entry is None or not entry.device_id:
            return None
        for device_entry in er.async_entries_for_device(registry, entry.device_id):
            if device_entry.domain == "sensor" and (
                device_entry.entity_id.endswith(suffix)
                or (device_entry.unique_id or "").endswith(suffix)
            ):
                return device_entry.entity_id
        return None

    def _radiator_sensors(self) -> dict[str, str]:
        """Valve -> sensor with the valve's own (radiator-side) temperature."""
        sensors = {}
        for entity_id in self._thermostat_ids():
            if entity_id in self.skipped_valves:
                continue
            sensor_id = self._device_sensor(entity_id, "device_temperature")
            if sensor_id:
                sensors[entity_id] = sensor_id
        return sensors

    def _observe_radiators(self, result: dict[str, Any]) -> bool:
        """Judge whether heat reaches the radiators; True when an hour of the
        central heating's times was learned."""
        sensors = self._radiator_sensors() if self.enabled else {}
        for entity_id in list(self._radiators):
            if entity_id not in sensors:
                self._radiators.pop(entity_id)
        room = result.get("room_temperature")
        demand = result.get("heat_demand")
        if (
            result.get("mode") in ("window", "maintenance", "season_off", "outdoor_warm")
            or result.get("window_open")
        ):
            demand = 0
        at = dt_util.utcnow().timestamp()
        states = {
            entity_id: self._radiators.setdefault(
                entity_id, RadiatorTracker()
            ).observe(
                at,
                demand,
                _as_float(self.hass.states.get(sensor_id)),
                None if room is None else float(room),
            )
            for entity_id, sensor_id in sensors.items()
        }
        target = result.get("target_temperature")
        response = self._response.observe(
            at,
            demand,
            None if room is None else float(room),
            None if target is None else float(target),
        )
        result["room_response"] = response
        supply = combined_supply(room_supply(states), response)
        asking = response != IDLE or any(
            tracker.heating_since is not None
            for entity_id, tracker in self._radiators.items()
            if entity_id in sensors
        )
        judged = judged_supply(supply, asking)
        result["supply_judged"] = judged
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        seconds = (
            0.0 if self._supply_at is None else (now - self._supply_at).total_seconds()
        )
        self._supply_at = now
        learned = self.supply.observe(local.hour, judged, seconds)
        house = self._house()
        house_verdict = (
            None if house is None else house.supply_verdict({self.entry_id: judged})
        )
        if SUPPLY_COLD not in (supply, house_verdict):
            # Without hot water in the house, cold radiators say nothing
            # about their balance.
            learned = self._learn_balance(sensors) or learned
        else:
            for tracker in self._radiators.values():
                tracker.period = None
        profile = self.supply_profile
        result["radiators"] = {
            self._friendly_name(entity_id): state for entity_id, state in states.items()
        }
        result["radiator_supply"] = supply
        result["house_supply"] = house_verdict
        result["supply_usually_off"] = profile.usually_off(local.hour)
        result["supply_off_hours"] = profile.off_hours()
        result["supply_today"] = profile.as_list()
        result["supply_source"] = "Haus" if profile is not self.supply else "Raum"
        result["radiator_status"] = self._radiator_text(
            states, supply, local.hour, house_verdict
        )
        if supply == SUPPLY_COLD and result.get("status"):
            result["status"] = f"{result['status']} – Heizkörper bleiben kalt"
        balance, weak = balance_verdict(
            {
                self._friendly_name(entity_id): self.radiator_stats.setdefault(
                    entity_id, RadiatorStats()
                )
                for entity_id in sensors
            }
        )
        result["radiator_balance"] = balance
        result["radiator_balance_weak"] = weak
        result["radiator_stats"] = {
            self._friendly_name(entity_id): self.radiator_stats[entity_id].as_dict()
            for entity_id in sensors
            if entity_id in self.radiator_stats
        }
        return learned

    def _house(self):
        """The house manager, if a house entry is set up."""
        return self.hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)

    @property
    def supply_profile(self) -> SupplyProfile:
        """When the central heating delivers: the house's view, else the room's."""
        house = self._house()
        profile = house.supply_profile() if house is not None else None
        return profile if profile is not None else self.supply

    def _learn_balance(self, sensors: dict[str, str]) -> bool:
        """Count finished heating periods per radiator; True when one was added.

        A period in which no radiator of the room got warm shows the central
        heating, not the radiators, and is skipped.
        """
        periods = {
            entity_id: tracker.period
            for entity_id, tracker in self._radiators.items()
            if entity_id in sensors and tracker.period is not None
        }
        if not periods or all(
            period.warmup_minutes is None for period in periods.values()
        ):
            return False
        for entity_id, period in periods.items():
            self.radiator_stats.setdefault(entity_id, RadiatorStats()).add(period)
        return True

    def _radiator_text(
        self,
        states: dict[str, str],
        supply: str | None,
        hour: int,
        house_verdict: str | None = None,
    ) -> str | None:
        """What the radiators say, in a few words."""
        if supply is None:
            return None
        if supply == SUPPLY_COLD and house_verdict == SUPPLY_WARM:
            return (
                "Kalt, obwohl die Zentralheizung liefert (andere Räume werden "
                "warm) – Ventile und Heizkörper prüfen"
            )
        if supply == SUPPLY_COLD:
            profile = self.supply_profile
            text = "Kalt – die Zentralheizung liefert keine Wärme"
            if profile.usually_off(hour):
                next_hour = profile.next_on_hour(hour)
                text += (
                    f" (um diese Zeit üblich, meist wieder ab {next_hour}:00 Uhr)"
                    if next_hour is not None
                    else " (um diese Zeit üblich)"
                )
            return text
        if supply == SUPPLY_PARTLY and house_verdict == SUPPLY_COLD:
            return "Kalt – die Zentralheizung liefert keine Wärme"
        if supply == SUPPLY_PARTLY:
            cold = ", ".join(
                self._friendly_name(entity_id)
                for entity_id, state in states.items()
                if state == COLD
            )
            return f"{cold} bleibt kalt – entlüften oder Ventil prüfen"
        return {
            SUPPLY_WARM: "Warm",
            SUPPLY_WAITING: "Werden warm",
            SUPPLY_IDLE: "Kein Heizbedarf",
        }.get(supply, supply)

    def _observe_cooling(self, result: dict[str, Any]) -> bool:
        """Compare stretches without heat with the model; True when one was."""
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        demand = result.get("heat_demand")
        target = result.get("target_temperature")
        # Only clearly above its target are the valves really closed; a
        # room held at its target still gets some heat.
        no_heat = (
            demand is not None
            and demand <= 10
            and room is not None
            and target is not None
            and float(room) - float(target) >= 0.3
        ) or SUPPLY_COLD in (
            result.get("radiator_supply"),
            result.get("house_supply"),
        )
        idle = (
            self.enabled
            and not self._room_fallback
            and room is not None
            and outdoor is not None
            and no_heat
            and not result.get("window_open")
            and result.get("mode") not in ("waiting", "maintenance", "window")
        )
        solar_kw, _wind = self._weather_inputs()
        learned = self.cooling.observe(
            dt_util.utcnow().timestamp(),
            float(room) if room is not None else 0.0,
            float(outdoor) if outdoor is not None else 0.0,
            bool(idle),
            self._model_view(
                None if outdoor is None else float(outdoor), 0.0, 0.0
            ),
            solar_kw,
        )
        result["cooling_factor"] = self.cooling.active_factor
        result["cooling_samples"] = self.cooling.samples
        return learned

    async def _observe_model(self, result: dict[str, Any]) -> bool:
        """Feed the hourly model sample; True when the model learned one."""
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        demand = result.get("heat_demand")
        if self._shower_until is not None and dt_util.utcnow() >= self._shower_until:
            self._shower_until = None
        if (
            not self.enabled
            or self._room_fallback
            or self._shower_until is not None
            or room is None
            or outdoor is None
            or demand is None
            or result.get("mode") in ("waiting", "maintenance", "window")
            or result.get("window_open")
            or result.get("manual_override")
            or result.get("valve_maintenance")
            or not result.get("thermostat_setpoints")
        ):
            self._model_collector.reset()
            return False
        solar_kw, wind = self._weather_inputs()
        radiators = result.get("radiator_supply")
        # Heat asked for while the boiler delivers nothing (the house says so,
        # or it is the usual night pause and nothing here got warm): such an
        # hour shows the boiler, not the room.
        no_heat = radiators == SUPPLY_COLD or (
            float(demand) >= MODEL_ASKING_DEMAND
            and radiators != SUPPLY_WARM
            and (
                result.get("house_supply") == SUPPLY_COLD
                or bool(result.get("supply_usually_off"))
            )
        )
        sample = self._model_collector.observe(
            dt_util.utcnow().timestamp(),
            float(room),
            float(demand) / 100,
            float(outdoor),
            solar_kw,
            wind,
            no_heat,
            radiators == SUPPLY_WARM,
        )
        return sample is not None and self.room_model.add(
            *sample, warm=self._model_collector.last_warm
        )

    async def async_seed_model(self) -> None:
        """Learn the room model from the recorder once, at its first start."""
        if self.room_model.ready or (
            self._model_seeded and self._seed_version >= SEED_VERSION
        ):
            return
        if "recorder" not in self.hass.config.components:
            return
        if self._model_seeded:
            # Learned from the recorder with an older rule: the recorder still
            # holds these hours, so start over instead of adding them twice.
            self.room_model = RoomModel()
        room_id = self.config.get(CONF_ROOM_TEMPERATURE_ENTITY)
        outdoor_id = self.config.get(CONF_OUTDOOR_TEMPERATURE_ENTITY)
        # A room set up only now has no recorded heat demand yet: the valves'
        # setpoints of the past days stand in for it.
        demand_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self.entry_id}_heat_demand"
        )
        if not room_id or not outdoor_id:
            return
        valves = [
            entity_id
            for entity_id in self._thermostat_ids()
            if entity_id not in self.skipped_valves
        ]
        from homeassistant.components.recorder import get_instance, history

        windows = [
            entity_id
            for _key, ids, _door, _open, _close in self._contact_groups()
            for entity_id in ids
        ]
        optional = [
            entity_id
            for entity_id in (
                self.config.get(CONF_SOLAR_RADIATION_ENTITY),
                self.config.get(CONF_WIND_SPEED_ENTITY),
            )
            if entity_id
        ]
        radiators = list(self._radiator_sensors().values())
        end = dt_util.utcnow()
        start = end - timedelta(days=MODEL_HISTORY_DAYS)
        ids = [
            entity_id
            for entity_id in (room_id, outdoor_id, demand_id, *windows, *optional, *radiators)
            if entity_id
        ]
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start,
                end,
                ids,
                None,
                True,
                False,
                False,
                True,
            )
            valve_states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start,
                end,
                valves,
                None,
                True,
                False,
                False,
                False,
            )
        except Exception:  # noqa: BLE001 - history is a bonus, never fatal
            _LOGGER.debug("Room model history not available", exc_info=True)
            return
        setpoints = {
            f"setpoint:{entity_id}": [
                (
                    state.last_updated.timestamp(),
                    "off" if state.state == "off" else str(
                        state.attributes.get("temperature")
                    ),
                )
                for state in valve_states.get(entity_id, [])
                if isinstance(state, State)
            ]
            for entity_id in valves
        }
        units = {
            entity_id: str(
                (self.hass.states.get(entity_id).attributes.get("unit_of_measurement"))
                if self.hass.states.get(entity_id) is not None
                else ""
            ).lower()
            for entity_id in optional
        }
        added = seed_room_model(
            self.room_model,
            {
                entity_id: [
                    (state.last_changed.timestamp(), state.state)
                    for state in states.get(entity_id, [])
                    if isinstance(state, State)
                ]
                for entity_id in ids
            }
            | setpoints,
            room_id=room_id,
            outdoor_id=outdoor_id,
            demand_id=demand_id or "",
            window_ids=windows,
            solar_id=self.config.get(CONF_SOLAR_RADIATION_ENTITY),
            wind_id=self.config.get(CONF_WIND_SPEED_ENTITY),
            units=units,
            start=start.timestamp(),
            end=end.timestamp(),
            radiator_ids=radiators,
            setpoint_ids=list(setpoints),
            full_gap=HEAT_DEMAND_FULL_GAP,
        )
        self._model_seeded = True
        self._seed_version = SEED_VERSION
        _LOGGER.debug("Room model learned %s hours from the recorder", added)
        if added:
            self._log(f"Raummodell hat {added} Stunden aus dem Verlauf gelernt")
        await self._save_learning()

    async def _schedule_blocks(self, now: datetime) -> list[Block] | None:
        """Comfort blocks of the active schedule in the next 24 hours.

        A schedule helper's week comes from ``schedule.get_schedule``, a
        calendar's events from ``calendar.get_events``; None when neither
        answers. When tomorrow is school-free (or not) and that needs another
        schedule, the blocks after midnight come from that one.
        """
        schedule_id = self.active_schedule
        tomorrow_id = await self._tomorrow_schedule(now)
        key = (
            schedule_id,
            tomorrow_id,
            dt_util.as_local(now).strftime("%Y-%m-%d %H"),
        )
        if (
            self._schedule_week is not None
            and self._schedule_week_key is not None
            and self._schedule_week_key[:2] == key[:2]
            and self._schedule_week_at is not None
            and now - self._schedule_week_at < SCHEDULE_WEEK_INTERVAL
        ):
            return [block for block in self._schedule_week if block.end > now]
        if not schedule_id:
            return None
        local = dt_util.as_local(now)
        blocks = await self._fetch_blocks(schedule_id, local)
        self._tomorrow_note = None
        if blocks is not None and tomorrow_id is not None and tomorrow_id != schedule_id:
            later = await self._fetch_blocks(tomorrow_id, local)
            if later is not None:
                midnight = (local + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                blocks = blocks_switched_at(blocks, later, midnight)
                self._tomorrow_note = (
                    "morgen schulfrei"
                    if tomorrow_id == self.config.get(CONF_SCHOOL_FREE_SCHEDULE)
                    else "morgen Schultag"
                )
        self._schedule_week = blocks
        self._schedule_week_key = key
        self._schedule_week_at = now
        return blocks

    async def _fetch_blocks(self, schedule_id: str, local: datetime) -> list[Block] | None:
        """The next 24 hours of one schedule helper or calendar."""
        blocks: list[Block] | None = None
        try:
            if schedule_id.startswith("schedule."):
                response = await self.hass.services.async_call(
                    "schedule",
                    "get_schedule",
                    {"entity_id": schedule_id},
                    blocking=True,
                    return_response=True,
                )
                weekly = response.get(schedule_id) if isinstance(response, dict) else None
                if isinstance(weekly, dict):
                    self._schedule_weekly[schedule_id] = weekly
                blocks = blocks_from_schedule(
                    weekly, local, schedule_comfort_temperature
                )
            elif schedule_id.startswith("calendar."):
                response = await self.hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": schedule_id,
                        "start_date_time": local.isoformat(),
                        "end_date_time": (local + timedelta(days=1)).isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
                events = (
                    (response.get(schedule_id) or {}).get("events")
                    if isinstance(response, dict)
                    else None
                )
                blocks = []
                for event in events or []:
                    start = self._parse_local_time(event.get("start"))
                    end = self._parse_local_time(event.get("end"))
                    if start is None or end is None or end <= start:
                        continue
                    blocks.append(
                        Block(
                            dt_util.as_local(start),
                            dt_util.as_local(end),
                            calendar_temperature(
                                event.get("description"), CALENDAR_TEMPERATURE_KEY
                            ),
                        )
                    )
                blocks.sort(key=lambda block: block.start)
        except (HomeAssistantError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.debug("Schedule of %s not readable for the day plan: %s", schedule_id, err)
            blocks = None
        return blocks

    def _follow_school_free(self) -> None:
        """Pick the school-free schedule on free days, the normal one else.

        Like the automation it replaces: on a change of the entity (and once
        after the start). Picking another schedule by hand holds until the
        next change.
        """
        entity_id = self.config.get(CONF_SCHOOL_FREE_ENTITY)
        free_schedule = self.config.get(CONF_SCHOOL_FREE_SCHEDULE)
        if not entity_id or not free_schedule:
            return
        state = self.hass.states.get(entity_id)
        if not self._valid(state):
            return
        free = state.state == "on"
        if free == self._school_free:
            return
        self._school_free = free
        choice = free_schedule if free else self.config.get(CONF_SCHEDULE_ENTITY)
        if choice and self.schedule_choice != choice:
            self.schedule_choice = choice
            self._preheat_event = None
            self._pending_source = "Schulfrei"
            self._log(
                f"Zeitplan {self._friendly_name(choice)} "
                + ("(schulfrei)" if free else "(Schultag)")
            )

    async def _tomorrow_schedule(self, now: datetime) -> str | None:
        """The schedule tomorrow needs when school-free days are set up.

        None when that is not known (no workday sensor or holiday calendar).
        """
        free_schedule = self.config.get(CONF_SCHOOL_FREE_SCHEDULE)
        if not self.config.get(CONF_SCHOOL_FREE_ENTITY) or not free_schedule:
            return None
        free = await self._free_tomorrow(now)
        if free is None:
            return None
        return free_schedule if free else self.config.get(CONF_SCHEDULE_ENTITY)

    async def _free_tomorrow(self, now: datetime) -> bool | None:
        """Is tomorrow school-free? Asked once a day (workday, holidays)."""
        day = (dt_util.as_local(now) + timedelta(days=1)).date()
        if self._free_tomorrow_cache is not None and self._free_tomorrow_cache[0] == day:
            return self._free_tomorrow_cache[1]
        workday_id = self.config.get(CONF_WORKDAY_ENTITY)
        calendar_id = self.config.get(CONF_SCHOOL_HOLIDAY_CALENDAR)
        if not workday_id and not calendar_id:
            return None
        free: bool | None = None
        try:
            if workday_id:
                response = await self.hass.services.async_call(
                    "workday",
                    "check_date",
                    {"entity_id": workday_id, "check_date": day},
                    blocking=True,
                    return_response=True,
                )
                value = (
                    (response.get(workday_id) or {}).get("workday")
                    if isinstance(response, dict)
                    else None
                )
                if isinstance(value, bool):
                    free = not value
            if calendar_id and not free:
                start = datetime.combine(day, datetime.min.time(), dt_util.get_default_time_zone())
                response = await self.hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": calendar_id,
                        "start_date_time": (start + timedelta(hours=8)).isoformat(),
                        "end_date_time": (start + timedelta(hours=16)).isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
                events = (
                    (response.get(calendar_id) or {}).get("events")
                    if isinstance(response, dict)
                    else None
                )
                if events is not None:
                    holiday = any(
                        word in str(event.get("summary") or "").casefold()
                        for event in events
                        for word in SCHOOL_HOLIDAY_WORDS
                    )
                    free = bool(free) or holiday
        except (HomeAssistantError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.debug("Could not tell whether tomorrow is school-free: %s", err)
            return None
        if free is not None:
            self._free_tomorrow_cache = (day, free)
        return free

    def _forecast_points(self) -> list[tuple[datetime, float]]:
        forecast: list[tuple[datetime, float]] = []
        for item in self._forecast_items:
            raw = item.get("datetime")
            moment = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
            value = _as_number(item.get("temperature"))
            if moment is not None and value is not None:
                forecast.append((dt_util.as_utc(moment), value))
        forecast.sort()
        return forecast

    def _forecast_correction(
        self, outdoor: float | None, at: datetime, now: datetime | None = None
    ) -> float:
        """What to add to the forecast for ``at``: the forecast's error now.

        The weather service's hourly value can be degrees off the own outdoor
        sensor (13.10.: 10.9 °C forecast, 8.4 °C measured). The error seen
        now is carried into the next hours, fading out over half a day.
        """
        if outdoor is None:
            return 0.0
        now = dt_util.utcnow() if now is None else dt_util.as_utc(now)
        forecast_now = None
        for start, temperature in self._forecast_points():
            if start > now:
                if forecast_now is None and start - now <= timedelta(hours=1):
                    forecast_now = temperature
                break
            forecast_now = temperature
        if forecast_now is None:
            return 0.0
        hours = max(0.0, (dt_util.as_utc(at) - now).total_seconds() / 3600)
        fade = max(0.0, 1 - hours / FORECAST_CORRECTION_HOURS)
        return (float(outdoor) - forecast_now) * fade

    def _outdoor_at(self, fallback: float) -> Any:
        """A function giving the forecast outdoor temperature for a time."""
        forecast = self._forecast_points()

        def outdoor_at(at: datetime) -> float:
            value = fallback
            moment = dt_util.as_utc(at)
            found = False
            for start, temperature in forecast:
                if start > moment:
                    break
                value = temperature
                found = True
            if found:
                value += self._forecast_correction(fallback, at)
            return value

        return outdoor_at

    async def _update_plan(self, result: dict[str, Any]) -> None:
        """Recalculate the day plan now and then and check it against the room."""
        now = dt_util.utcnow()
        room = result.get("room_temperature")
        self._check_plan(result, now)
        # Also at once when control is switched on (after a restart it comes
        # on a moment after the first cycle), room and outdoor temperature
        # arrive, the model gets ready or the schedule changes.
        key = (
            self.enabled,
            room is not None and result.get("outdoor_temperature") is not None,
            self.room_model.ready,
            self.active_schedule,
        )
        if (
            self._plan_at is None
            or now - self._plan_at >= PLAN_INTERVAL
            or key != self._plan_key
        ):
            self._plan_at = now
            self._plan_key = key
            self.plan_points, self.plan_info = await self._calculate_plan(result, now)
        result["day_plan"] = self.plan_info.get("text")
        result["plan_error"] = self.plan_error
        result["plan_checked"] = self.plan_checked
        local_hour = dt_util.as_local(now).hour
        if (
            self.plan_points
            and room is not None
            and local_hour != self._plan_check_hour
            and result.get("mode") in _PLAN_MODES
        ):
            self._plan_check_hour = local_hour
            at = now + timedelta(hours=CHECK_HOURS)
            predicted = temperature_at(self.plan_points, dt_util.as_local(at))
            if predicted is not None:
                self._plan_checks[at] = predicted

    def _check_plan(self, result: dict[str, Any], now: datetime) -> None:
        """Compare what the plan said a few hours ago with the room now."""
        room = result.get("room_temperature")
        for at in sorted(self._plan_checks):
            if at > now:
                break
            predicted = self._plan_checks.pop(at)
            if (
                room is None
                or now - at > PLAN_INTERVAL
                or result.get("mode") not in _PLAN_MODES
                or result.get("room_temperature_source") != "sensor"
            ):
                continue
            error = abs(float(room) - predicted)
            self.plan_error = round(
                error
                if self.plan_error is None
                else (1 - CHECK_ALPHA) * self.plan_error + CHECK_ALPHA * error,
                2,
            )
            self.plan_checked += 1

    async def _calculate_plan(
        self, result: dict[str, Any], now: datetime
    ) -> tuple[list, dict[str, Any]]:
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        if not self.enabled:
            return [], {"text": "Regelung aus – kein Tagesplan"}
        if room is None or outdoor is None:
            return [], {"text": "Raum- oder Außentemperatur fehlt – kein Tagesplan"}
        view = self._model_view(float(outdoor), 0.0, 0.0)
        if view is None:
            return [], {"text": "Raummodell lernt noch – Tagesplan folgt"}
        blocks = await self._schedule_blocks(now)
        if blocks is None:
            return [], {"text": "Zeitplan nicht lesbar – kein Tagesplan"}
        profile = self.supply_profile
        local = dt_util.as_local(now)
        comfort = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        eco = float(result.get("eco_temperature") or self.config.get(
            CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE
        ))
        points = simulate(
            view,
            now=local,
            room=float(room),
            comfort=comfort,
            eco=eco,
            blocks=blocks,
            outdoor_at=self._outdoor_at(float(outdoor)),
            supply_off=lambda at: profile.usually_off(dt_util.as_local(at).hour),
            max_preheat_minutes=int(
                self.config.get(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)
            )
            + self._preheat_extension_minutes(),
            lead_bias_minutes=self._lead_bias(),
        )
        info = plan_summary(points, blocks, local)
        if self._tomorrow_note:
            info["text"] = f"{info['text']} ({self._tomorrow_note})"
        if self.plan_error is not None and self.plan_checked >= 3:
            info["text"] = (
                f"{info['text']} (Abweichung bisher ±"
                + f"{self.plan_error:.1f}".replace(".", ",")
                + " °C)"
            )
        info["text"] = str(info.get("text") or "")[:250]
        return points, info

    async def async_estimate_savings(
        self,
        *,
        comfort: float | None = None,
        eco: float | None = None,
        shift_minutes: int = 0,
    ) -> dict[str, Any]:
        """Spar-Rechner: the next days with other temperatures or times.

        Both variants are replayed on the learned room model like the day
        plan (schedule, central heating's pauses, weather forecast); presence,
        windows and the sun are left out. Nothing is changed.
        """
        result = self.data or {}
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        base_comfort = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        base_eco = float(self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE))
        new_comfort = base_comfort if comfort is None else float(comfort)
        new_eco = base_eco if eco is None else float(eco)
        answer: dict[str, Any] = {
            "room": self.room_name,
            "comfort": base_comfort,
            "eco": base_eco,
            "new_comfort": new_comfort,
            "new_eco": new_eco,
            "shift_minutes": int(shift_minutes),
        }
        if new_eco >= new_comfort:
            answer["text"] = "Eco muss unter der Komforttemperatur liegen."
            return answer
        view = self._model_view(None if outdoor is None else float(outdoor), 0.0, 0.0)
        if room is None or outdoor is None:
            answer["text"] = "Raum- oder Außentemperatur fehlt – keine Rechnung möglich."
            return answer
        if view is None:
            answer["text"] = "Das Raummodell lernt noch – der Spar-Rechner folgt."
            return answer
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        days = SAVINGS_DAYS
        schedule_id = self.active_schedule or ""
        blocks = await self._schedule_blocks(now)
        weekly = self._schedule_weekly.get(schedule_id)
        if schedule_id.startswith("schedule.") and isinstance(weekly, dict):
            blocks = blocks_from_schedule(
                weekly, local, schedule_comfort_temperature, hours=days * 24
            )
        else:
            days = 1
        if blocks is None:
            answer["text"] = "Zeitplan nicht lesbar – keine Rechnung möglich."
            return answer
        delta = new_comfort - base_comfort
        new_blocks = shifted_blocks(
            [
                Block(
                    block.start,
                    block.end,
                    None if block.temperature is None else block.temperature + delta,
                )
                for block in blocks
            ],
            int(shift_minutes),
        )
        profile = self.supply_profile
        settings = {
            "view": view,
            "now": local,
            "room": float(room),
            "outdoor_at": self._outdoor_at(float(outdoor)),
            "supply_off": lambda at: profile.usually_off(dt_util.as_local(at).hour),
            "max_preheat_minutes": int(
                self.config.get(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)
            )
            + self._preheat_extension_minutes(),
            "hours": days * 24,
            "lead_bias_minutes": self._lead_bias(),
        }
        base = simulate(comfort=base_comfort, eco=base_eco, blocks=blocks, **settings)
        other = simulate(
            comfort=new_comfort, eco=new_eco, blocks=new_blocks, **settings
        )
        comparison = compare_plans(base, blocks, other, new_blocks, local)
        power_kw = self.radiator_power_w / 1000
        answer.update(comparison)
        answer["days"] = days
        answer["base_kwh"] = round(comparison["base_full_load_hours"] * power_kw, 1)
        answer["kwh"] = round(comparison["full_load_hours"] * power_kw, 1)
        answer["text"] = savings_text(answer)
        return answer

    def plan_attributes(self) -> dict[str, Any]:
        """The day plan for dashboards: times, target and expected temperature."""
        return {
            **{key: value for key, value in self.plan_info.items() if key != "text"},
            "plan_error": self.plan_error,
            "plan_checked": self.plan_checked,
            "calculated_at": self._plan_at.isoformat() if self._plan_at else None,
            "forecast": [
                {
                    "time": point.at.isoformat(),
                    "temperature": point.temperature,
                    "target": point.target,
                }
                for point in self.plan_points[::2]
            ],
        }

    async def async_run_selftest(self) -> None:
        """Run the self-test with the next cycle (button)."""
        self._selftest_due = dt_util.utcnow()
        await self.async_refresh()

    async def _maybe_selftest(self, result: dict[str, Any]) -> None:
        """Check after a start (and hourly while it fails) that all is wired up."""
        now = dt_util.utcnow()
        if self._selftest_due is None or now < self._selftest_due:
            result["selftest"] = self._selftest_state()
            return
        checks = self._selftest_checks(result)
        problems = [check for check in checks if check["ok"] is False]
        self.selftest = {
            "at": now.isoformat(),
            "checks": checks,
            "problems": [f"{check['name']}: {check['detail']}" for check in problems],
        }
        self._selftest_due = now + SELFTEST_RETRY if problems else None
        result["selftest"] = self._selftest_state()
        issue_id = f"selftest_{self.entry_id}"
        if problems:
            text = "; ".join(self.selftest["problems"])
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key="selftest_failed",
                translation_placeholders={"room": self.room_name, "problems": text},
            )
            self._selftest_issue = True
            names = tuple(sorted(check["name"] for check in problems))
            if names != self._selftest_sent:
                self._selftest_sent = names
                self._log(f"Selbsttest: {text}")
                await self._push_room(f"Selbsttest nach dem Start: {text}")
        else:
            if self._selftest_issue:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                self._selftest_issue = False
                if self._selftest_sent:
                    await self._push_room("Selbsttest: wieder alles in Ordnung.")
            self._selftest_sent = ()

    def _selftest_state(self) -> str | None:
        if self.selftest is None:
            return "Läuft 10 Minuten nach dem Start" if self._selftest_due else None
        problems = self.selftest["problems"]
        if not problems:
            return "Alles in Ordnung"
        return f"{len(problems)} Problem" + ("e" if len(problems) > 1 else "")

    async def _push_room(self, message: str) -> None:
        service = (self.config.get(CONF_NOTIFY_SERVICE) or "").strip()
        house = self._house()
        if not service and house is not None:
            service = (house._notify_service() or "").strip()
        if not service:
            return
        domain, _, name = service.partition(".")
        if not name:
            domain, name = "notify", domain
        await self._call(
            domain, name, {"title": f"Heizung {self._room_name()}", "message": message}
        )

    def _selftest_checks(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """One entry per check: name, ok (True, False, or None = info only), detail."""
        checks: list[dict[str, Any]] = []

        def add(name: str, ok: bool | None, detail: str) -> None:
            checks.append({"name": name, "ok": ok, "detail": detail})

        if not self.enabled:
            add("Regelung", None, "ausgeschaltet – nichts geprüft")
            return checks
        add("Regelung", True, "eingeschaltet")
        room = result.get("room_temperature")
        if self._room_fallback or room is None:
            add("Raumfühler", False, "liefert keine Werte")
        else:
            add("Raumfühler", True, f"{float(room):.1f} °C".replace(".", ","))
        schedule_id = self.active_schedule
        if not self._valid(self.hass.states.get(schedule_id) if schedule_id else None):
            add("Zeitplan", False, f"{schedule_id or 'keiner'} nicht verfügbar")
        else:
            add("Zeitplan", True, str(schedule_id))
        missing = [
            self._friendly_name(entity_id)
            for entity_id in self._thermostat_ids()
            if not self._valid(self.hass.states.get(entity_id))
        ]
        add(
            "Ventile",
            not missing,
            f"nicht erreichbar: {', '.join(missing)}" if missing
            else f"{len(self._thermostat_ids())} erreichbar",
        )
        if self.config.get(CONF_EXTERNAL_TEMPERATURE) and room is not None:
            wrong = []
            fed = 0
            for entity_id in self._thermostat_ids():
                if entity_id in self.skipped_valves or entity_id in missing:
                    continue
                pair = self._external_temperature_entities(entity_id)
                if pair is None:
                    continue
                fed += 1
                select_state = self.hass.states.get(pair[0])
                shown = self._thermostat_temperature(entity_id)
                name = self._friendly_name(entity_id)
                if select_state is None or select_state.state != "external":
                    wrong.append(f"{name} misst intern")
                elif shown is None or abs(shown - float(room)) > SELFTEST_VALVE_TOLERANCE:
                    wrong.append(
                        f"{name} zeigt {'?' if shown is None else f'{shown:.1f}'} °C"
                    )
            if fed:
                add(
                    "Raumtemperatur an den Ventilen",
                    not wrong,
                    "; ".join(wrong) if wrong else "kommt an",
                )
        contacts = [
            entity_id
            for _key, ids, _door, _open, _close in self._contact_groups()
            for entity_id in ids
        ]
        dead = [
            self._friendly_name(entity_id)
            for entity_id in contacts
            if not self._valid(self.hass.states.get(entity_id))
        ]
        if contacts:
            add(
                "Fensterkontakte",
                not dead,
                f"nicht erreichbar: {', '.join(dead)}" if dead
                else f"{len(contacts)} erreichbar",
            )
        if self.config.get(CONF_OUTDOOR_TEMPERATURE_ENTITY) or self.config.get(
            CONF_WEATHER_ENTITY
        ):
            outdoor = result.get("outdoor_temperature")
            add(
                "Außentemperatur",
                outdoor is not None,
                "fehlt" if outdoor is None else f"{float(outdoor):.1f} °C".replace(".", ","),
            )
        warnings = result.get("thermostat_warnings") or {}
        add(
            "Batterie und Funk",
            not warnings,
            "; ".join(
                f"{self._friendly_name(entity_id)}: {', '.join(items)}"
                for entity_id, items in warnings.items()
            )
            if warnings
            else "keine Meldungen",
        )
        add(
            "Raummodell",
            None,
            "bereit" if self.room_model.ready else
            f"lernt noch ({self.room_model.samples} Stunden)",
        )
        return checks

    async def async_warm_up(self) -> None:
        """Kurz wärmer: the current target plus a little, for a while.

        Pressed again while it runs, it adds once more (up to three steps)
        and starts the time again; then the room returns to automatic.
        """
        step = float(self.config.get(CONF_WARM_UP_STEP) or DEFAULT_WARM_UP_STEP)
        seconds = int(
            self.config.get(CONF_WARM_UP_DURATION) or DEFAULT_WARM_UP_DURATION
        )
        data = self.data or {}
        base = data.get("target_temperature")
        if base is None:
            base = self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        if (
            self._warm_up_base is not None
            and self.quick_mode == QUICK_MANUAL
            and self.quick_until is not None
            and self.quick_until == self._warm_up_until
        ):
            steps = min(self._warm_up_steps + 1, 3)
            base = self._warm_up_base
        else:
            steps = 1
            self._warm_up_base = float(base)
        self._warm_up_steps = steps
        self._pending_source = "Kurz wärmer"
        self.boost_until = None
        self.quick_mode = QUICK_MANUAL
        self.quick_temperature = round(float(base) + step * steps, 1)
        self.quick_until = dt_util.utcnow() + timedelta(seconds=seconds)
        self._warm_up_until = self.quick_until
        await self.async_refresh()

    def _punctual(self) -> bool:
        return bool(self.config.get(CONF_PUNCTUALITY, DEFAULT_PUNCTUALITY))

    def _lead_bias(self) -> int:
        """The learned preheat correction in minutes (0 when switched off)."""
        return round(self.punctuality.bias_minutes) if self._punctual() else 0

    def _preheat_extension_minutes(self) -> int:
        if not self._punctual():
            return 0
        value = self.config.get(CONF_PREHEAT_EXTENSION, DEFAULT_PREHEAT_EXTENSION)
        try:
            return max(0, int(float(value or 0) // 60))
        except (TypeError, ValueError):
            return 0

    def _preheat_limit(self, max_preheat: int, next_event: datetime | None) -> int:
        """Maximum preheat time, extended while the central heating delivers.

        The extra time is only allowed when none of its hours is one in which
        the central heating is usually off: heating then would be in vain.
        """
        extension = self._preheat_extension_minutes()
        if not extension or next_event is None:
            return max_preheat
        profile = self.supply_profile
        start = dt_util.as_local(next_event) - timedelta(minutes=max_preheat + extension)
        end = dt_util.as_local(next_event) - timedelta(minutes=max_preheat)
        at = start
        while at < end:
            if profile.usually_off(at.hour):
                return max_preheat
            at += timedelta(minutes=30)
        return max_preheat + extension

    def _supply_wait(
        self,
        decision: HeatingDecision,
        *,
        comfort_temperature: float,
        eco_temperature: float,
        schedule_active: bool,
    ) -> HeatingDecision:
        """Fit preheating and the evening to the central heating's pauses.

        Preheating in an hour in which the central heating usually delivers
        nothing only keeps the valves open in vain: it waits until the usual
        end of the pause (unless the radiators are warm right now). With
        the option on, comfort that ended shortly before the usual night
        pause is kept until the pause starts.
        """
        profile = self.supply_profile
        local = dt_util.now()
        hour = local.hour
        last = self.data if isinstance(self.data, dict) else {}
        if (
            decision.mode == "preheat"
            and profile.usually_off(hour)
            and last.get("house_supply") != SUPPLY_WARM
            and last.get("radiator_supply") != SUPPLY_WARM
        ):
            next_hour = profile.next_on_hour(hour)
            # Timed afresh once the central heating delivers again.
            self._preheat_event = None
            return replace(
                decision,
                status="Vorheizen wartet auf die Zentralheizung"
                + (
                    f" (liefert meist ab {next_hour}:00 Uhr)"
                    if next_hour is not None
                    else ""
                ),
                mode="eco",
                target_temperature=eco_temperature,
            )
        if (
            self.config.get(CONF_HOLD_BEFORE_PAUSE, DEFAULT_HOLD_BEFORE_PAUSE)
            and decision.mode == "eco"
            and not schedule_active
            and self._comfort_ended_at is not None
            and dt_util.utcnow() - self._comfort_ended_at <= timedelta(hours=2)
            and not profile.usually_off(hour)
            and any(profile.usually_off((hour + step) % 24) for step in (1, 2))
        ):
            return replace(
                decision,
                status="Komfort bis zur Nachtpause der Zentralheizung",
                mode="comfort",
                target_temperature=comfort_temperature,
            )
        return decision

    def _early_stop(
        self,
        decision: HeatingDecision,
        *,
        room_temperature: float,
        comfort_temperature: float,
        eco_temperature: float,
        next_event: datetime | None,
        schedule_active: bool,
        view: ModelView | None,
    ) -> HeatingDecision:
        """End heating before the comfort block ends if the room holds."""
        if self._early_stop_event is not None and self._early_stop_event != next_event:
            self._early_stop_event = None
        seconds = int(self.config.get(CONF_EARLY_STOP, DEFAULT_EARLY_STOP) or 0)
        if (
            seconds <= 0
            or not schedule_active
            or next_event is None
            or decision.mode != "comfort"
        ):
            return decision
        minutes_left = (next_event - dt_util.utcnow()).total_seconds() / 60
        if minutes_left <= 0 or minutes_left > seconds / 60:
            return decision
        lowest = comfort_temperature - EARLY_STOP_DROP
        if self._early_stop_event == next_event:
            if room_temperature < lowest:
                # Cooled faster than expected: heat again until the end.
                self._early_stop_event = None
                return decision
        else:
            hours = minutes_left / 60
            if view is not None:
                predicted = view.temperature_after(room_temperature, hours, 0.0)
            elif self._cooling_samples:
                predicted = room_temperature - self.cooling_rate * hours
            else:
                return decision
            if room_temperature < comfort_temperature - 0.2 or predicted < lowest:
                return decision
            self._early_stop_event = next_event
        end = dt_util.as_local(next_event).strftime("%H:%M")
        return replace(
            decision,
            status=f"Komfort endet um {end} Uhr – Heizung schon aus, "
            "der Raum hält die Wärme",
            mode="early_stop",
            target_temperature=min(eco_temperature, comfort_temperature),
            preheat_minutes=0,
        )

    def _sun_pause(
        self,
        decision: HeatingDecision,
        room_temperature: float,
        eco_temperature: float,
        view: ModelView | None,
    ) -> HeatingDecision:
        """Close the valves while the sun alone keeps the room at its target."""
        target = decision.target_temperature
        if (
            view is None
            or not self.config.get(CONF_SOLAR_RADIATION_ENTITY)
            or decision.mode not in ("comfort", "preheat", "away_reduced")
            or target is None
        ):
            self._solar_pause = False
            return decision
        gain = view.solar_gain * view.solar_kw
        predicted = view.temperature_after(room_temperature, 1.0, 0.0)
        if self._solar_pause:
            pause = (
                gain >= SOLAR_PAUSE_MIN_GAIN / 2
                and room_temperature >= target - 0.5
                and predicted >= target - 0.3
            )
        else:
            pause = (
                gain >= SOLAR_PAUSE_MIN_GAIN
                and room_temperature >= target - 0.3
                and predicted >= target
            )
        self._solar_pause = pause
        if not pause:
            return decision
        return replace(
            decision,
            status="Sonne wärmt den Raum – Heizung pausiert",
            mode="solar",
            target_temperature=min(eco_temperature, target),
            preheat_minutes=0,
        )

    def _model_diagnostics(self, view: ModelView | None) -> dict[str, Any]:
        """What the room model learned, for sensors and the status."""
        model = self.room_model
        heat_output, loss, solar_gain, wind_loss = model.parameters()
        if not self.config.get(CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL):
            status = "Raummodell aus"
        elif not model.ready:
            status = (
                f"Lernt noch: {model.samples} Stunden, davon "
                f"{model.heating_samples} mit und {model.idle_samples} ohne Heizen"
            )
        elif view is None:
            status = "Bereit – Außentemperatur fehlt"
        elif not model.trusted:
            error = (
                "–" if model.mean_error is None
                else f"{model.mean_error:.2f}".replace(".", ",")
            )
            status = (
                f"Aktiv fürs Vorheizen – Absenkung und Sonne ab {TRUSTED_SAMPLES} "
                f"Stunden und Fehler unter 0,12 °C/h (jetzt {model.samples} h, {error})"
            )
        else:
            status = "Aktiv"
        ready = model.ready
        local = dt_util.now()
        return {
            "model_status": status,
            "model_ready": ready,
            "model_trusted": model.trusted,
            "model_samples": model.samples,
            "model_heating_samples": model.heating_samples,
            "model_idle_samples": model.idle_samples,
            "model_error": model.mean_error,
            "heat_output": round(heat_output, 2) if ready else None,
            # °C per hour lost at 10 °C between room and outside.
            "heat_loss": round(loss * 10, 2) if ready else None,
            "solar_gain": round(solar_gain, 2) if ready else None,
            "wind_loss": round(wind_loss * 100, 3) if ready else None,
            "usage_now": self.usage.usage(local.weekday(), local.hour),
            "solar_pause": self._solar_pause,
        }

    async def _async_update_data(self) -> dict[str, Any]:
        """Run one control cycle and attach the thermostats' health."""
        await self._disarm_valve_fallback()
        await self._sync_external_temperature()
        await self._sync_trv_window_detection()
        await self._sync_valve_week_schedule()
        self._follow_school_free()
        result = await self._async_control_cycle()
        await self._calibrate_valve_sensors(result)
        self._update_repair_issue()
        self._check_foreign_control(result)
        self._announce_mode(result)
        self._pending_source = None
        result["last_change_source"] = self.last_change_source
        result["last_change_at"] = (
            self.last_change_at.isoformat() if self.last_change_at else None
        )
        result["thermostat_warnings"] = self._thermostat_warnings()
        result["heating_problem"] = self.heating_problem
        result["heating_problem_detail"] = self.heating_problem_detail
        result["heat_demand"], result["heat_demand_source"] = self._heat_demand(
            result.get("target_temperature"), result.get("room_temperature")
        )
        supply_learned = self._observe_radiators(result)
        supply_learned = self._observe_cooling(result) or supply_learned
        await self._update_plan(result)
        routine_learned = self._observe_routine(result)
        await self._morning_report(result)
        shower_seen = self._observe_shower(result)
        batteries_changed = self._observe_batteries(result)
        habit = self._update_habits(result)
        await self._maybe_selftest(result)
        await self._send_notifications(result)
        if habit is not None:
            await self._push_room(f"Zeitplan-Vorschlag: {habit}")
            routine_learned = True
        result["external_temperature_thermostats"] = sorted(self._external_fed)
        result["quick_duration"] = self.quick_duration
        if (
            await self._observe_model(result)
            or supply_learned
            or routine_learned
            or shower_seen
            or batteries_changed
        ):
            await self._save_learning()
        self._fire_triggers(result)
        self._track_week(result)
        self._save_runtime_state()
        return result

    def _observe_routine(self, result: dict[str, Any]) -> bool:
        """Punctuality and long-term figures; True when a morning was judged."""
        now = dt_util.now()
        demand = result.get("heat_demand") if self.enabled else None
        self.heat_stats.observe(
            now,
            demand,
            result.get("outdoor_temperature"),
            power_kw=self.radiator_power_w / 1000,
            supplied=SUPPLY_COLD
            not in (result.get("radiator_supply"), result.get("house_supply")),
        )
        result["heating_hours_total"] = round(self.heat_stats.heating_hours, 2)
        today = now.date()
        result["heat_energy_total"] = round(self.heat_stats.energy_kwh, 2)
        result["heat_energy_today"] = self.heat_stats.energy_between(today, today)
        result["heat_energy_yesterday"] = self.heat_stats.energy_between(
            today - timedelta(days=1), today - timedelta(days=1)
        )
        result["heat_energy_7_days"] = self.heat_stats.energy_between(
            today - timedelta(days=6), today
        )
        result["radiator_power_w"] = self.radiator_power_w
        result["degree_days_total"] = round(self.heat_stats.degree_days, 2)
        result["hours_per_degree_day"] = self.heat_stats.hours_per_degree_day(
            now.date()
        )
        result["learn_run_at"] = (
            self.learn_run_at.isoformat() if self.learn_run_at else None
        )
        result["learn_run_until"] = (
            self.learn_run_until.isoformat() if self.learn_run_until else None
        )
        judged = False
        if self.enabled and self._punctual() and not self._room_fallback:
            # In UTC: minutes early or late stay right across a clock change.
            late = self.punctuality.observe(
                dt_util.as_utc(now),
                room=result.get("room_temperature"),
                mode=result.get("mode"),
                next_event=(
                    dt_util.as_local(self._next_event) if self._next_event else None
                ),
                target=result.get("target_temperature"),
                supply_cold=SUPPLY_COLD
                in (result.get("radiator_supply"), result.get("house_supply"))
                or bool(result.get("supply_usually_off")),
            )
            if late is not None:
                judged = True
                if late > 0:
                    self._log(f"Komfortbeginn: {late} Minuten zu spät warm")
                elif late < 0:
                    self._log(f"Komfortbeginn: {-late} Minuten zu früh warm")
                else:
                    self._log("Komfortbeginn: pünktlich warm")
        result["punctuality"] = self.punctuality.summary()
        result["punctuality_bias"] = self._lead_bias()
        result["punctuality_results"] = [
            {"date": day, "minutes_late": late}
            for day, late in self.punctuality.results
        ]
        return judged

    async def _morning_report(self, result: dict[str, Any]) -> None:
        """One push in the morning when the room was not warm at comfort start."""
        morning = self.punctuality.morning
        if morning is None or morning.day == self._morning_reported:
            return
        now = dt_util.now()
        start = dt_util.as_local(morning.start)
        due = max(start, start.replace(hour=MORNING_REPORT_HOUR, minute=0, second=0))
        if now < due:
            return
        self._morning_reported = morning.day
        self._save_runtime_state()
        if (
            not self.config.get(CONF_MORNING_REPORT, DEFAULT_MORNING_REPORT)
            or now - due > timedelta(hours=3)
            or morning.target - morning.room < MORNING_REPORT_SHORTFALL
        ):
            return

        def degrees(value: float) -> str:
            return f"{value:.1f}".replace(".", ",")

        message = (
            f"Um {start.strftime('%H:%M')} Uhr erst {degrees(morning.room)} statt "
            f"{degrees(morning.target)} °C"
        )
        if morning.supply_missing:
            message += (
                " – die Zentralheizung lieferte beim Vorheizen noch keine Wärme"
            )
        elif self._punctual():
            message += " – das Vorheizen beginnt künftig früher"
        room = result.get("room_temperature")
        if room is not None:
            message += f". Jetzt {degrees(float(room))} °C."
        else:
            message += "."
        await self._push_room(message)

    def _announce_mode(self, result: dict[str, Any]) -> None:
        """Fire an event when the decided mode or target changed."""
        key = (result.get("mode"), result.get("target_temperature"))
        previous = self._last_event_key
        self._last_event_key = key
        # The first cycle after a start is no change.
        if previous is None or previous == key or key[0] is None:
            return
        self.last_change_source = self._pending_source or "Automatik"
        self.last_change_at = dt_util.utcnow()
        if previous[0] != key[0] and result.get("status"):
            self._log(str(result["status"]))
        self.hass.bus.async_fire(
            EVENT_MODE_CHANGED,
            {
                "entry_id": self.entry_id,
                "room": self.room_name,
                "mode": key[0],
                "previous_mode": previous[0],
                "target_temperature": key[1],
                "previous_target_temperature": previous[1],
                "status": result.get("status"),
                "present": result.get("present"),
                "window_open": result.get("window_open"),
                "active_schedule": result.get("active_schedule"),
                "quick_mode": result.get("quick_mode"),
                "source": self.last_change_source,
            },
        )

    def _trv_window_switches(self) -> list[str]:
        """The thermostats' own window-detection switches."""
        registry = er.async_get(self.hass)
        switches: list[str] = []
        for entity_id in self._thermostat_ids():
            entry = registry.async_get(entity_id)
            if entry is None or not entry.device_id:
                continue
            switches.extend(
                device_entry.entity_id
                for device_entry in er.async_entries_for_device(
                    registry, entry.device_id
                )
                if device_entry.domain == "switch"
                and device_entry.entity_id.endswith(TRV_WINDOW_DETECTION_SUFFIX)
            )
        return switches

    async def _sync_trv_window_detection(self) -> None:
        """Keep the valves' own window detection off where a contact exists.

        Only while control is on and the room has a window contact; a switch
        that could not be turned off is tried again after an hour.
        """
        if not (
            self.enabled
            and self.config.get(CONF_DISABLE_TRV_WINDOW_DETECTION)
            and (
                self.config.get(CONF_WINDOW_ENTITY)
                or self.config.get(CONF_ADDITIONAL_WINDOW_ENTITIES)
            )
        ):
            return
        now = dt_util.utcnow()
        for switch_id in self._trv_window_switches():
            state = self.hass.states.get(switch_id)
            if state is None or state.state != "on":
                continue
            last = self._trv_window_attempts.get(switch_id)
            if last is not None and now - last < timedelta(hours=1):
                continue
            self._trv_window_attempts[switch_id] = now
            if await self._call("switch", "turn_off", {"entity_id": switch_id}):
                _LOGGER.info("Turned off the own window detection of %s", switch_id)

    @property
    def device_name(self) -> str:
        """Name of the room's device: "<area> Heizung" when the area is known."""
        area = self._area_name()
        return f"{area} Heizung" if area else DEFAULT_DEVICE_NAME

    def _area_name(self) -> str | None:
        climate_id = self.config.get(CONF_CLIMATE_ENTITY)
        entry = er.async_get(self.hass).async_get(climate_id) if climate_id else None
        area_id = entry.area_id if entry is not None else None
        if entry is not None and area_id is None and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            area_id = device.area_id if device is not None else None
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        return area.name if area is not None else None

    def _room_name(self) -> str:
        """The area of the room's main thermostat, else the entry title."""
        climate_id = self.config.get(CONF_CLIMATE_ENTITY)
        entry = er.async_get(self.hass).async_get(climate_id) if climate_id else None
        area_id = entry.area_id if entry is not None else None
        if entry is not None and area_id is None and entry.device_id:
            device = dr.async_get(self.hass).async_get(entry.device_id)
            area_id = device.area_id if device is not None else None
        area = ar.async_get(self.hass).async_get_area(area_id) if area_id else None
        if area is not None:
            return area.name
        config_entry = self.hass.config_entries.async_get_entry(self.entry_id)
        return config_entry.title if config_entry is not None else "Heizung"

    def _alert_conditions(self, result: dict[str, Any]) -> dict[str, tuple[int, str]]:
        """Active alert conditions: key -> (delay in seconds, message)."""
        conditions: dict[str, tuple[int, str]] = {}
        warnings = result.get("thermostat_warnings") or {}
        if warnings:
            details = "; ".join(
                f"{self._friendly_name(entity_id)}: {', '.join(items)}"
                for entity_id, items in warnings.items()
            )
            conditions["thermostat"] = (
                NOTIFY_PROBLEM_DELAY_SECONDS,
                f"Thermostat-Problem – {details}",
            )
        supply = result.get("radiator_supply")
        if (
            supply == SUPPLY_PARTLY
            and result.get("house_supply") != SUPPLY_COLD
            and not result.get("supply_usually_off")
        ):
            conditions["radiator"] = (
                NOTIFY_PROBLEM_DELAY_SECONDS,
                f"Heizkörper: {result.get('radiator_status')}.",
            )
        muted = (
            self._heating_muted_until is not None
            and dt_util.utcnow() < self._heating_muted_until
        )
        if result.get("heating_problem") and not muted:
            detail = result.get("heating_problem_detail")
            if supply == SUPPLY_COLD and result.get("house_supply") == SUPPLY_WARM:
                conditions["heating"] = (
                    0,
                    "Der Raum kommt nicht auf Temperatur"
                    + (f" ({detail})" if detail else "")
                    + ": die Heizkörper hier bleiben kalt, obwohl die "
                    "Zentralheizung in anderen Räumen Wärme liefert. Ventile "
                    "prüfen (klemmt der Stift?) oder Heizkörper entlüften.",
                )
            elif supply == SUPPLY_COLD:
                # Expected when the central heating is usually off now; with a
                # house entry the house tells it once for all rooms.
                if not result.get("supply_usually_off") and self._house() is None:
                    conditions["heating"] = (
                        0,
                        "Der Raum kommt nicht auf Temperatur"
                        + (f" ({detail})" if detail else "")
                        + ": die Ventile sind offen, aber die Heizkörper bleiben "
                        "kalt. Die Zentralheizung liefert keine Wärme (aus oder "
                        "in Absenkung).",
                    )
            else:
                conditions["heating"] = (
                    0,
                    "Der Raum kommt nicht auf Temperatur, obwohl geheizt werden soll"
                    + (f" ({detail})" if detail else "")
                    + ". Ventile und Heizung (Vorlauftemperatur) prüfen.",
                )
        if result.get("mode") == "waiting":
            conditions["blocked"] = (
                NOTIFY_PROBLEM_DELAY_SECONDS,
                f"Die Regelung wartet: {result.get('status')}",
            )
        elif self._room_fallback:
            conditions["sensor"] = (
                NOTIFY_PROBLEM_DELAY_SECONDS,
                "Der Raumfühler liefert keine Werte – geregelt wird mit den "
                "Thermostat-Messwerten.",
            )
        if result.get("window_contact_open") and result.get("heating_season", True):
            conditions["window"] = (
                NOTIFY_WINDOW_SECONDS,
                "Das Fenster ist seit über einer Stunde offen.",
            )
        if (
            self._absence == "house_empty"
            and self.config.get(CONF_NOTIFY_AWAY, DEFAULT_NOTIFY_AWAY)
            and self._announces_house()
        ):
            conditions["away"] = (
                NOTIFY_AWAY_SECONDS,
                "Niemand zuhause erkannt – die Räume sind abgesenkt.",
            )
        frost_value = self.config.get(CONF_FROST_PROTECTION_TEMPERATURE)
        frost_limit = (
            float(frost_value) if frost_value is not None
            else NOTIFY_FROST_FALLBACK_TEMPERATURE
        ) + NOTIFY_FROST_MARGIN
        room_temperature = result.get("room_temperature")
        if room_temperature is not None and room_temperature < frost_limit:
            conditions["frost"] = (
                0,
                f"Frostgefahr: nur noch {room_temperature:.1f} °C im Raum.",
            )
        return conditions

    def _announces_house(self) -> bool:
        """Whether this room sends house-wide pushes (one room does)."""
        rooms = sorted(
            (
                room for room in self.hass.data.get(DOMAIN, {}).values()
                if isinstance(room, DynamicHeatingCoordinator)
                and (room.config.get(CONF_NOTIFY_SERVICE) or "").strip()
            ),
            key=lambda room: room.entry_id,
        )
        return bool(rooms) and rooms[0] is self

    def _notify_actions(self, key: str) -> list[dict[str, str]]:
        """Buttons of a push on the Home Assistant app."""
        choices = {
            "heating": (("boost", "Boost 1 Stunde"), ("mute", "Heute nicht mehr melden")),
            "window": (
                ("snooze", "In 15 Minuten erinnern"),
                ("ignore_window", "Heizung trotzdem an"),
            ),
            "away": (("home", "Stimmt nicht, ich bin da"),),
        }.get(key, ())
        return [
            {"action": f"{NOTIFY_ACTION_PREFIX}_{action}_{self.entry_id}", "title": title}
            for action, title in choices
        ]

    def async_listen_notify_actions(self) -> None:
        """Answer the buttons of the app's pushes."""
        if self._unsub_actions is None:
            self._unsub_actions = self.hass.bus.async_listen(
                "mobile_app_notification_action", self._async_notify_action
            )

    def async_stop_notify_actions(self) -> None:
        if self._unsub_actions is not None:
            self._unsub_actions()
            self._unsub_actions = None

    def async_watch_foreign_control(self) -> None:
        """Notice automations and scripts that set this room's valves."""
        if self._unsub_foreign is None:
            self._unsub_foreign = self.hass.bus.async_listen(
                EVENT_CALL_SERVICE, self._on_call_service
            )

    def async_stop_foreign_control(self) -> None:
        if self._unsub_foreign is not None:
            self._unsub_foreign()
            self._unsub_foreign = None

    @callback
    def _on_call_service(self, event: Event) -> None:
        data = event.data
        if data.get("domain") != "climate":
            return
        service_data = data.get("service_data") or {}
        target = service_data.get("entity_id")
        targets = {target} if isinstance(target, str) else set(target or [])
        valves = sorted(targets & set(self._thermostat_ids()))
        if not valves:
            return
        source = foreign_source(self.hass, event.context)
        if source is None:
            return
        source_id, source_name = source
        value = service_data.get("temperature")
        if value is None:
            value = service_data.get("hvac_mode") or data.get("service")
        self.foreign_control[source_id] = {
            "name": source_name,
            "at": dt_util.utcnow(),
            "valves": valves,
            "value": value,
        }
        self.hass.async_create_task(self._report_foreign_control(source_id))

    async def _report_foreign_control(self, source_id: str) -> None:
        """Repairs entry, logbook line and (once a day) a push."""
        info = self.foreign_control.get(source_id)
        if info is None:
            return
        valves = ", ".join(self._friendly_name(valve) for valve in info["valves"])
        value = info["value"]
        what = (
            f"auf {float(value):g} °C gestellt".replace(".", ",")
            if isinstance(value, int | float)
            else f"verstellt ({value})"
        )
        kind = "Automation" if source_id.startswith("automation.") else "Skript"
        text = f"{kind} „{info['name']}“ hat {valves} {what}"
        _LOGGER.info("%s set the valves of %s: %s", source_id, self.room_name, value)
        self._log(text)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            _foreign_issue_id(self.entry_id, source_id),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="foreign_control",
            translation_placeholders={
                "room": self.room_name,
                "source": f"{kind} „{info['name']}“ ({source_id})",
                "valves": valves,
                "value": what,
            },
        )
        now = dt_util.utcnow()
        last = self._foreign_notified.get(source_id)
        if last is None or (now - last).total_seconds() >= FOREIGN_CONTROL_NOTIFY_SECONDS:
            self._foreign_notified[source_id] = now
            await self._push_room(
                f"{text}. Sie arbeitet gegen die Regelung dieses Raums – "
                "bitte ausschalten, wenn sie nicht mehr gebraucht wird."
            )

    def _check_foreign_control(self, result: dict[str, Any]) -> None:
        """Forget an automation once it is off (or a script after a day)."""
        now = dt_util.utcnow()
        for source_id in list(self.foreign_control):
            info = self.foreign_control[source_id]
            state = self.hass.states.get(source_id)
            old = (now - info["at"]).total_seconds() >= FOREIGN_CONTROL_NOTIFY_SECONDS
            if (
                state is None
                or (source_id.startswith("automation.") and state.state == "off")
                or (not source_id.startswith("automation.") and old)
            ):
                del self.foreign_control[source_id]
                ir.async_delete_issue(
                    self.hass, DOMAIN, _foreign_issue_id(self.entry_id, source_id)
                )
        result["foreign_control"] = [
            {
                "source": source_id,
                "name": info["name"],
                "at": info["at"].isoformat(),
                "valves": info["valves"],
                "value": info["value"],
            }
            for source_id, info in self.foreign_control.items()
        ]

    async def _async_notify_action(self, event) -> None:
        action = str(event.data.get("action") or "")
        prefix = f"{NOTIFY_ACTION_PREFIX}_"
        suffix = f"_{self.entry_id}"
        if not action.startswith(prefix) or not action.endswith(suffix):
            return
        await self.async_handle_notify_action(action[len(prefix):-len(suffix)])

    async def async_handle_notify_action(self, action: str) -> None:
        """Do what a push button asks."""
        now = dt_util.utcnow()
        if action == "boost":
            self._pending_source = "Push-Meldung"
            await self.async_start_boost()
        elif action == "mute":
            local = dt_util.as_local(now)
            midnight = (local + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            self._heating_muted_until = dt_util.as_utc(midnight)
            self._log("Heizproblem-Meldungen für heute stummgeschaltet")
            await self.async_request_refresh()
        elif action == "snooze":
            # Sent again once the window was open the full time once more,
            # counted from 15 minutes before the delay ends.
            self._alerts["window"] = (
                now - timedelta(seconds=NOTIFY_WINDOW_SECONDS - NOTIFY_SNOOZE_SECONDS),
                False,
            )
        elif action == "ignore_window":
            self._window_ignored = True
            self._pending_source = "Push-Meldung"
            self._log("Fenster offen – auf Wunsch wird trotzdem geheizt")
            await self.async_request_refresh()
        elif action == "home":
            rooms = [
                room for room in self.hass.data.get(DOMAIN, {}).values()
                if isinstance(room, DynamicHeatingCoordinator) and room.enabled
            ] or [self]
            for room in rooms:
                await room.async_set_quick_mode(QUICK_HOME, source="Push-Meldung")

    def _friendly_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        name = state.attributes.get("friendly_name") if state is not None else None
        return str(name).strip(" -") if name else entity_id

    async def _send_notifications(self, result: dict[str, Any]) -> None:
        """Push new alerts (and their end) to the configured notify service."""
        service = (self.config.get(CONF_NOTIFY_SERVICE) or "").strip()
        if not service:
            self._alerts.clear()
            return
        if not self.enabled:
            # Kept as they are: right after a restart control is switched on
            # only once the switch is restored.
            return
        domain, _, name = service.partition(".")
        if not name:
            domain, name = "notify", domain
        now = dt_util.utcnow()
        title = f"Heizung {self._room_name()}"
        conditions = self._alert_conditions(result)
        for key in list(self._alerts):
            if key not in conditions:
                _, sent = self._alerts.pop(key)
                if sent and key != "away":
                    await self._call(
                        domain,
                        name,
                        {"title": title, "message": "Wieder in Ordnung: " + {
                            "thermostat": "die Thermostate melden kein Problem mehr.",
                            "heating": "kein Heizproblem mehr.",
                            "radiator": "alle Heizkörper werden wieder warm.",
                            "sensor": "der Raumfühler liefert wieder Werte.",
                            "blocked": "die Regelung arbeitet wieder.",
                            "frost": "keine Frostgefahr mehr.",
                            "window": "das Fenster ist wieder geschlossen.",
                        }.get(key, key)},
                    )
        for key, (delay, message) in conditions.items():
            since, sent = self._alerts.get(key, (now, False))
            if not sent and (now - since).total_seconds() >= delay:
                data: dict[str, Any] = {"title": title, "message": message}
                actions = self._notify_actions(key) if name.startswith("mobile_app") else []
                if actions:
                    data["data"] = {"actions": actions, "tag": f"dynheat_{key}_{self.entry_id}"}
                sent = await self._call(domain, name, data)
                if sent:
                    self._week["alerts"] += 1
            self._alerts[key] = (since, sent)

    def _external_temperature_entities(
        self, entity_id: str
    ) -> tuple[str, str] | None:
        """The (select, number) pair for feeding a thermostat, if it has one."""
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if entry is None or not entry.device_id:
            return None
        select_id = number_id = None
        for device_entry in er.async_entries_for_device(registry, entry.device_id):
            if device_entry.domain == "number" and (
                "external_temperature" in device_entry.entity_id
                or "external_temperature" in (device_entry.unique_id or "")
            ):
                number_id = device_entry.entity_id
            elif device_entry.domain == "select":
                state = self.hass.states.get(device_entry.entity_id)
                options = state.attributes.get("options") if state else None
                if options and {"internal", "external"} <= set(options):
                    select_id = device_entry.entity_id
        if select_id is None or number_id is None:
            return None
        return select_id, number_id

    async def _pace(self) -> None:
        """Wait the command delay since the last command to a valve."""
        delay = float(self.config.get(CONF_COMMAND_DELAY) or DEFAULT_COMMAND_DELAY)
        cls = DynamicHeatingCoordinator
        if delay > 0 and cls._last_command is not None:
            wait = cls._last_command + delay - time.monotonic()
            if wait > 0:
                await asyncio.sleep(min(wait, delay))
        cls._last_command = time.monotonic()

    def _log(self, message: str) -> None:
        """Write a line to the logbook of the room's status sensor."""
        if not self.hass.services.has_service("logbook", "log"):
            return
        data: dict[str, Any] = {
            "name": f"Heizung {self.room_name}",
            "message": message,
            "domain": DOMAIN,
        }
        entity_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self.entry_id}_status"
        )
        if entity_id:
            data["entity_id"] = entity_id
        self.hass.async_create_task(
            self.hass.services.async_call("logbook", "log", data, blocking=False)
        )

    def _device_id(self) -> str | None:
        """The room's device in the device registry."""
        # Looked up through the config entry: async_get_device by identifiers
        # is deprecated and stops working in Home Assistant 2027.8.
        registry = dr.async_get(self.hass)
        for device in dr.async_entries_for_config_entry(registry, self.entry_id):
            if (DOMAIN, self.entry_id) in device.identifiers:
                return device.id
        return None

    def _fire_triggers(self, result: dict[str, Any]) -> None:
        """Fire device-trigger events when a watched condition changes."""
        room = result.get("room_temperature")
        target = result.get("target_temperature")
        conditions: dict[str, bool | None] = {
            "heating": (
                (result.get("heat_demand") or 0) > 0 if self.enabled else None
            ),
            "reached": (
                None
                if room is None or target is None
                else room >= float(target) - TARGET_REACHED_MARGIN
            ),
            "window": bool(result.get("window_open")),
        }
        humidity = _as_float(self._state(CONF_HUMIDITY_ENTITY))
        if humidity is not None:
            previous = self._trigger_state.get("humid", False)
            limit = HUMIDITY_HIGH_PERCENT - (HUMIDITY_HYSTERESIS if previous else 0)
            conditions["humid"] = humidity >= limit
        else:
            conditions["humid"] = None
        events = {
            "heating": (TRIGGER_HEATING_STARTED, TRIGGER_HEATING_STOPPED),
            "reached": (TRIGGER_TARGET_REACHED, None),
            "window": (TRIGGER_WINDOW_OPENED, TRIGGER_WINDOW_CLOSED),
            "humid": (TRIGGER_HUMIDITY_HIGH, None),
        }
        # "Reached" only counts when the room warmed up to an unchanged
        # target, not when the target dropped below the room.
        target_changed = target != self._trigger_target
        self._trigger_target = target
        device_id = None
        for key, value in conditions.items():
            if value is None:
                self._trigger_state.pop(key, None)
                continue
            previous = self._trigger_state.get(key)
            self._trigger_state[key] = value
            if previous is None or previous == value:
                continue
            if key == "reached" and target_changed:
                continue
            trigger = events[key][0 if value else 1]
            if trigger is None:
                continue
            device_id = device_id or self._device_id()
            self.hass.bus.async_fire(
                EVENT_DEVICE_TRIGGER,
                {
                    "device_id": device_id,
                    "entry_id": self.entry_id,
                    "room": self.room_name,
                    "type": trigger,
                },
            )

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> bool:
        """Call a service; log and return False instead of raising."""
        if domain in ("climate", "number", "select", "switch"):
            await self._pace()
        if hold_if_missing(self.hass, self.entry_id, domain, service, data):
            return True
        try:
            await self.hass.services.async_call(domain, service, data, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not call %s.%s with %s: %s", domain, service, data, err)
            return False
        return True

    async def async_release_external_temperature(self) -> None:
        """Hand every fed thermostat back to its own sensor."""
        await self._sync_external_temperature(release=True)

    async def _sync_external_temperature(self, *, release: bool = False) -> None:
        """Feed the room temperature to thermostats that accept one.

        While control is on and the room sensor works, each supported
        thermostat is switched to its external sensor and receives the room
        temperature. Otherwise it is switched back to its internal sensor so it
        never regulates on a stale value. Without the option nothing is touched.
        """
        if not self.config.get(CONF_EXTERNAL_TEMPERATURE):
            self._external_fed.clear()
            return
        room_temperature = self._room_temperature()
        feed = self.enabled and room_temperature is not None and not release
        if room_temperature is not None:
            room_temperature = round(room_temperature, 1)
        now = dt_util.utcnow()
        fed: set[str] = set()
        for entity_id in self._thermostat_ids():
            entities = self._external_temperature_entities(entity_id)
            if entities is None:
                continue
            select_id, number_id = entities
            select_state = self.hass.states.get(select_id)
            if not self._valid(select_state):
                continue
            if feed:
                switched = False
                if select_state.state != "external":
                    # Switch first: a value sent while the thermostat still
                    # uses its own sensor is not applied after the switch.
                    if not await self._call(
                        "select",
                        "select_option",
                        {"entity_id": select_id, "option": "external"},
                    ):
                        continue
                    switched = True
                    self._external_sent.pop(number_id, None)
                    select_state = self.hass.states.get(select_id)
                    if select_state is None or select_state.state != "external":
                        # Zigbee confirms the switch a few seconds later; the
                        # value goes out once the valve reports it.
                        fed.add(entity_id)
                        continue
                last = self._external_sent.get(number_id)
                due, pending = external_temperature_due(
                    last,
                    self._external_pending.get(number_id),
                    room_temperature,
                    now,
                    min_change=EXTERNAL_TEMPERATURE_MIN_CHANGE,
                    plateau_change=EXTERNAL_TEMPERATURE_PLATEAU_CHANGE,
                    plateau_tolerance=EXTERNAL_TEMPERATURE_PLATEAU_TOLERANCE,
                    plateau_seconds=EXTERNAL_TEMPERATURE_PLATEAU_SECONDS,
                    resend_seconds=EXTERNAL_TEMPERATURE_RESEND_SECONDS,
                )
                if pending is None:
                    self._external_pending.pop(number_id, None)
                else:
                    self._external_pending[number_id] = pending
                retry = (
                    not due
                    and last is not None
                    and self._external_not_taken(entity_id, number_id, last, now)
                )
                if retry:
                    _value, count, _at = self._external_retried.get(
                        number_id, (room_temperature, 0, now)
                    )
                    self._external_retried[number_id] = (
                        room_temperature, count + 1, now
                    )
                elif due:
                    self._external_retried.pop(number_id, None)
                if due or retry:
                    if not await self._call(
                        "number",
                        "set_value",
                        {"entity_id": number_id, "value": room_temperature},
                    ):
                        # Retry on the next cycle; until then the valve keeps
                        # its own sensor instead of a stale external value.
                        self._external_sent.pop(number_id, None)
                        if switched:
                            await self._call(
                                "select",
                                "select_option",
                                {"entity_id": select_id, "option": "internal"},
                            )
                        continue
                    self._external_sent[number_id] = (room_temperature, now)
                fed.add(entity_id)
            else:
                self._external_sent.pop(number_id, None)
                self._external_pending.pop(number_id, None)
                self._external_retried.pop(number_id, None)
                if select_state.state != "internal":
                    await self._call(
                        "select",
                        "select_option",
                        {"entity_id": select_id, "option": "internal"},
                    )
        if fed != self._external_fed:
            # Offsets measured against the valve's own sensor no longer apply.
            self._calibration.clear()
        self._external_fed = fed

    def _external_not_taken(
        self,
        entity_id: str,
        number_id: str,
        last: tuple[float, datetime],
        now: datetime,
    ) -> bool:
        """Whether a valve still shows another temperature than the one sent."""
        if (now - last[1]).total_seconds() < EXTERNAL_TEMPERATURE_VERIFY_SECONDS:
            return False
        retried = self._external_retried.get(number_id)
        if retried is not None and (
            (now - retried[2]).total_seconds() < EXTERNAL_TEMPERATURE_RETRY_SECONDS
            # A valve that never shows the value it gets (another model) is
            # not chased forever: three tries per value.
            or retried[1] >= EXTERNAL_TEMPERATURE_RETRIES
        ):
            return False
        state = self.hass.states.get(entity_id)
        shown = _as_number(state.attributes.get("current_temperature")) if state else None
        return (
            shown is not None
            and abs(shown - last[0]) > EXTERNAL_TEMPERATURE_VERIFY_TOLERANCE
        )

    async def _async_control_cycle(self) -> dict[str, Any]:
        """Read Home Assistant states, calculate a target and optionally apply it."""
        room_temperature = self._room_temperature()
        schedule_id = self.active_schedule
        schedule_state = self.hass.states.get(schedule_id) if schedule_id else None
        climate_state = self._state(CONF_CLIMATE_ENTITY)
        outdoor_temperature = self._outdoor_temperature()

        self._room_fallback = room_temperature is None
        if (
            self._room_fallback
            and self.config.get(CONF_ROOM_TEMPERATURE_ENTITY)
            and (dt_util.utcnow() - self._started_at).total_seconds()
            < ROOM_FALLBACK_GRACE_SECONDS
        ):
            # Right after a start the room sensor comes a moment later; the
            # valves' readings next to the radiator (21–23 °C) would show up
            # as the room temperature and in its history.
            return self._waiting_result(
                "Temperatursensor nicht verfügbar – keine Sollwertänderung",
                None,
                outdoor_temperature,
            )
        if self._room_fallback:
            room_temperature = fallback_room_temperature(
                [self._thermostat_temperature(entity_id) for entity_id in self._thermostat_ids()]
            )
        if room_temperature is None:
            return self._waiting_result(
                "Temperatursensor nicht verfügbar – keine Sollwertänderung",
                None,
                outdoor_temperature,
            )

        if not self._valid(climate_state):
            return self._waiting_result(
                "Thermostat nicht verfügbar – keine Sollwertänderung",
                room_temperature,
                outdoor_temperature,
            )

        if not self._valid(schedule_state):
            return self._waiting_result(
                "Zeitplan nicht verfügbar – keine Sollwertänderung",
                room_temperature,
                outdoor_temperature,
            )

        schedule_active, next_event, slot_comfort = self._schedule_view(
            schedule_state
        )
        # A running block may pause the window contacts or presence, e.g.
        # "fenster: aus" for airing at full heat, "anwesenheit: aus" for guests.
        paused = (
            paused_features(
                dict(schedule_state.attributes),
                schedule_state.attributes.get("description"),
                {"window": BLOCK_WINDOW_KEYS, "presence": BLOCK_PRESENCE_KEYS},
            )
            if schedule_active
            else set()
        )

        contacts = self._evaluate_contacts()
        if contacts is None:
            return self._waiting_result(
                "Fensterkontakt nicht verfügbar – keine Sollwertänderung",
                room_temperature,
                outdoor_temperature,
            )
        window_open, window_contact_open = contacts
        self._window_open = window_open
        window_drop = self._window_drop(room_temperature)
        window_open = window_open or window_drop
        if "window" in paused:
            window_open = window_drop = False
            self._window_open = False
        if self._window_ignored:
            if window_contact_open:
                # "Heizung trotzdem an" on the window push: until it closes.
                window_open = window_drop = False
                self._window_open = False
                paused = set(paused) | {"window"}
            else:
                self._window_ignored = False

        present, presence_status = self._evaluate_presence()
        if present is not None and self._observe_usage(present):
            await self._save_learning()
        if self._proximity_metrics_dirty:
            self._proximity_metrics_dirty = False
            await self._save_learning()
        if "presence" in paused:
            present, presence_status = True, "Anwesenheit im Zeitplan-Block abgeschaltet"
            self._absence = "none"
            self._absent_since = None
        if present is None:
            return self._waiting_result(presence_status, room_temperature, outdoor_temperature)

        comfort_temperature = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        _schedule, house_comfort, house_temperature, house_end, house_event = (
            self._house_calendar_view()
        )
        self._house_calendar = house_event
        if house_comfort:
            if not schedule_active:
                schedule_active = True
                next_event = house_end
            if house_temperature is not None:
                slot_comfort = house_temperature
        if slot_comfort is not None:
            comfort_temperature = slot_comfort
        now_utc = dt_util.utcnow()
        if not schedule_active:
            self._comfort_started_at = None
            if self._schedule_was_active:
                self._comfort_ended_at = now_utc
        elif self._schedule_was_active is False:
            self._comfort_started_at = now_utc
        self._schedule_was_active = schedule_active
        solar_kw, wind = self._weather_inputs()
        view = self._model_view(outdoor_temperature, solar_kw, wind)
        # Preheat timing uses the model once it is ready; what changes the
        # setback or stops heating waits until it has proven itself.
        trusted = view if self.room_model.trusted else None
        self._model_rates = (
            None
            if view is None
            else (
                round(max(view.rate(room_temperature, 1.0), 0.0), 3),
                round(max(-view.rate(room_temperature, 0.0), 0.0), 3),
            )
        )
        if self.boost_until is not None and dt_util.utcnow() >= self.boost_until:
            self.boost_until = None
        boost_temperature = (
            float(self.config.get(CONF_BOOST_TEMPERATURE) or DEFAULT_BOOST_TEMPERATURE)
            if self.boost_until is not None
            else None
        )
        eco_temperature = float(
            self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE)
        )
        eco_schedule = self._state(CONF_ECO_SCHEDULE_ENTITY)
        slot_eco = (
            self._schedule_view(eco_schedule)[2]
            if self._valid(eco_schedule)
            else None
        )
        if slot_eco is not None:
            # Never above comfort: eco is the setback.
            eco_temperature = min(slot_eco, comfort_temperature)
        away_value = self.config.get(CONF_AWAY_TEMPERATURE)
        away_temperature = None if away_value is None else float(away_value)
        window_value = self.config.get(CONF_WINDOW_TEMPERATURE)
        frost_value = self.config.get(CONF_FROST_PROTECTION_TEMPERATURE)
        heating_season = True
        season_id = self.config.get(CONF_HEATING_SEASON_ENTITY)
        if season_id:
            season_state = self.hass.states.get(season_id)
            # An unknown season keeps heating; frost risk outweighs savings.
            if self._valid(season_state):
                heating_season = season_state.state == "on"
        try:
            off_temperature = float(climate_state.attributes.get("min_temp"))
        except (TypeError, ValueError):
            off_temperature = None
        try:
            max_temperature = float(climate_state.attributes.get("max_temp"))
        except (TypeError, ValueError):
            max_temperature = None
        if self._absence == "room_empty" and schedule_active:
            hold = self._hold_comfort(now_utc)
            if hold is not None:
                # Comfort just started or the room is usually used now: an
                # empty room keeps comfort for now.
                present, presence_status = True, hold
        reduced_comfort: tuple[str, float] | None = None
        away_offset = self.config.get(CONF_AWAY_OFFSET)
        if away_offset and (
            self._absence == "room_empty"
            or (
                self._absence == "house_empty"
                and self.config.get(CONF_AWAY_SCHEDULE_MODE)
            )
        ):
            reduced = max(eco_temperature, comfort_temperature - float(away_offset))
            value = f"{float(away_offset):g}".replace(".", ",")
            status = (
                f"Raum leer – Komfort minus {value} °C"
                if self._absence == "room_empty"
                else f"Niemand zuhause – Komfort minus {value} °C"
            )
            if self._absence == "room_empty" and trusted is not None and self.config.get(
                CONF_RECOVERY_LIMIT, DEFAULT_RECOVERY_LIMIT
            ):
                seconds = int(
                    self.config.get(CONF_ROOM_EMPTY_RECOVERY)
                    or DEFAULT_ROOM_EMPTY_RECOVERY
                )
                floor = self._recovery_floor(
                    trusted, comfort_temperature, room_temperature, seconds
                )
                if floor > reduced:
                    reduced = min(floor, comfort_temperature)
                    status = (
                        "Raum leer – nur bis "
                        + f"{reduced:.1f}".replace(".", ",")
                        + f" °C abgesenkt, in {seconds // 60} min wieder warm"
                    )
            reduced_comfort = (status, reduced)
        long_absence_temperature: float | None = None
        frost_after = int(
            self.config.get(CONF_FROST_AFTER_ABSENCE) or DEFAULT_FROST_AFTER_ABSENCE
        )
        if (
            frost_after > 0
            and self._absent_since is not None
            and (dt_util.utcnow() - self._absent_since).total_seconds() >= frost_after
        ):
            long_absence_temperature = (
                float(frost_value)
                if frost_value is not None
                else off_temperature
                if off_temperature is not None
                else eco_temperature
            )
        forecast_items = await self._async_get_forecast_items()
        limit_basis, limit_source = self._heating_limit_basis(
            outdoor_temperature, forecast_items
        )
        limit_value = self.config.get(CONF_HEATING_LIMIT_TEMPERATURE)
        if (
            limit_basis is None
            and limit_value is not None
            and self.config.get(CONF_HEATING_LIMIT_FALLBACK_OFF)
        ):
            # No outdoor temperature at all: heat or not, as configured.
            self._heating_limit_reached = True
            limit_source = "fallback"
        else:
            self._heating_limit_reached = evaluate_heating_limit(
                limit_basis,
                None if limit_value is None else float(limit_value),
                self._heating_limit_reached,
                HEATING_LIMIT_HYSTERESIS,
            )
        if heating_season and not self._room_fallback and self.config.get(
            CONF_OUTDOOR_WARMER_STOP, DEFAULT_OUTDOOR_WARMER_STOP
        ):
            # Judged by the current outdoor value, not the heating limit's
            # average: a warm afternoon outside needs no heat inside.
            self._outdoor_warmer = evaluate_outdoor_warmer(
                outdoor_temperature,
                room_temperature,
                self._outdoor_warmer,
                float(
                    self.config.get(
                        CONF_OUTDOOR_WARMER_MARGIN, DEFAULT_OUTDOOR_WARMER_MARGIN
                    )
                    or 0.0
                ),
                OUTDOOR_WARMER_HYSTERESIS,
            )
        else:
            self._outdoor_warmer = False

        # Valve readings are not the room temperature: never learn from them.
        if not self._room_fallback:
            await self._evaluate_pending_forecast(
                now=dt_util.utcnow(),
                room_temperature=room_temperature,
                schedule_active=schedule_active,
                present=present,
                window_open=window_open,
            )

            await self._learn(
                room_temperature,
                climate_state,
                window_open=window_open,
                schedule_active=schedule_active,
                eco_temperature=eco_temperature,
            )

        self._next_event = next_event
        if self._preheat_event is not None and self._preheat_event != next_event:
            self._preheat_event = None
        # Durations to the next block are taken in UTC: two local times on
        # either side of a clock change subtract to the wrong length.
        utc_now = dt_util.utcnow()
        forecast_condition = select_forecast_condition(
            forecast_items, next_event, utc_now
        )
        forecast_temperature = select_forecast_temperature(
            forecast_items, next_event, utc_now
        )
        if forecast_temperature is not None and next_event is not None:
            forecast_temperature = round(
                forecast_temperature
                + self._forecast_correction(outdoor_temperature, next_event),
                1,
            )
        quick = self._quick_target(
            comfort_temperature,
            eco_temperature,
            frost_value,
            off_temperature,
            away_temperature,
            max_temperature,
        )
        maintenance_temperature: float | None = None
        if quick is not None and quick[0] == "quick_maintenance":
            maintenance_temperature = quick[2]
        max_preheat = int(
            self.config.get(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)
        )
        preheat_limit = self._preheat_limit(max_preheat, next_event)
        # The weather at the next comfort start; the sun is not counted on.
        event_view = (
            None
            if view is None
            else view.with_weather(outdoor=forecast_temperature, solar_kw=0.0)
        )
        setback_floor: float | None = None
        if (
            event_view is not None
            and trusted is not None
            and self.config.get(CONF_RECOVERY_LIMIT, DEFAULT_RECOVERY_LIMIT)
            and self._absence != "house_empty"
            and not self._heating_limit_reached
        ):
            setback_floor = self._recovery_floor(
                event_view, comfort_temperature, room_temperature, max_preheat * 60
            )
            previous = self._setback_floor
            if (
                previous is not None
                and abs(setback_floor - previous) < SETBACK_FLOOR_STEP - 1e-9
            ):
                setback_floor = previous
        self._setback_floor = setback_floor
        decision = decide_heating_target(
            now=utc_now,
            schedule_active=schedule_active,
            next_event=next_event,
            room_temperature=room_temperature,
            outdoor_temperature=outdoor_temperature,
            comfort_temperature=comfort_temperature,
            eco_temperature=eco_temperature,
            heating_rate_c_per_hour=self.effective_heating_rate,
            cooling_rate_c_per_hour=self.effective_cooling_rate,
            forecast_condition=forecast_condition,
            forecast_temperature=forecast_temperature,
            max_preheat_minutes=preheat_limit,
            lead_bias_minutes=self._lead_bias(),
            window_open=window_open,
            present=present,
            preheat_started=self._preheat_event is not None,
            away_temperature=away_temperature,
            heating_limit_reached=self._heating_limit_reached,
            window_temperature=None if window_value is None else float(window_value),
            frost_protection_temperature=(
                None if frost_value is None else float(frost_value)
            ),
            heating_season=heating_season,
            outdoor_warmer=self._outdoor_warmer,
            off_temperature=off_temperature,
            boost_temperature=boost_temperature,
            maintenance_temperature=maintenance_temperature,
            reduced_comfort=reduced_comfort,
            long_absence_temperature=long_absence_temperature,
            overshoot=self.overshoot,
            room_model=event_view,
            setback_floor=setback_floor,
            household_present=(
                self._household_present
                and bool(
                    self.config.get(CONF_PREHEAT_WHEN_HOME, DEFAULT_PREHEAT_WHEN_HOME)
                )
            ),
            quick_mode=self._learn_run(room_temperature, max_temperature)
            or (None if maintenance_temperature is not None else quick)
            or self._force_target(comfort_temperature, eco_temperature)
            or self._house_target(
                comfort_temperature=comfort_temperature,
                eco_temperature=eco_temperature,
                away_temperature=away_temperature,
                frost_value=frost_value,
                room_temperature=room_temperature,
                outdoor_temperature=outdoor_temperature,
            ),
        )
        if decision.mode == "window" and window_drop and not self._window_open:
            end = dt_util.as_local(self._drop_until).strftime("%H:%M")
            decision = replace(
                decision,
                status=f"Temperatursturz – Fenster vermutlich offen (bis {end} Uhr)",
            )
        if decision.mode == "maintenance" and quick is not None:
            decision = replace(decision, status=quick[1])
        if decision.mode == "boost":
            end = dt_util.as_local(self.boost_until).strftime("%H:%M")
            decision = replace(decision, status=f"Boost bis {end} Uhr")
        if decision.mode == "heating_limit" and limit_source in ("forecast", "history"):
            span = "nächste 2 Tage" if limit_source == "forecast" else "letzte 2 Tage"
            value = f"{limit_basis:.1f}".replace(".", ",")
            decision = replace(
                decision,
                status=f"Heizgrenze erreicht (Ø {span} {value} °C) – abgesenkt",
            )
        decision = self._early_stop(
            decision,
            room_temperature=room_temperature,
            comfort_temperature=comfort_temperature,
            eco_temperature=eco_temperature,
            next_event=next_event,
            schedule_active=schedule_active,
            view=trusted,
        )
        decision = self._sun_pause(
            decision, room_temperature, eco_temperature, trusted
        )
        reachable = (
            None if trusted is None else round(trusted.reachable(room_temperature), 1)
        )
        trend = temperature_trend(self._trend_samples, TREND_MIN_SPAN_SECONDS)
        if (
            reachable is not None
            and trusted is not None
            and trend is not None
            and trend > trusted.rate(room_temperature, 1.0) + REACH_TREND_MARGIN
        ):
            # The room warms faster than the model allows (a new room whose
            # model was learned under other control): no forecast from it.
            reachable = None
        if (
            reachable is not None
            and decision.target_temperature is not None
            and decision.mode in _REACH_MODES
            and decision.target_temperature > reachable + 0.2
        ):
            decision = replace(
                decision,
                status=f"{decision.status} – heute erreichbar ca. "
                + f"{reachable:.1f}".replace(".", ",")
                + " °C",
            )
        decision = self._supply_wait(
            decision,
            comfort_temperature=comfort_temperature,
            eco_temperature=eco_temperature,
            schedule_active=schedule_active,
        )
        if decision.mode == "preheat":
            self._preheat_event = next_event
        if (
            self.room_offset
            and decision.target_temperature is not None
            and decision.mode not in _NO_OFFSET_MODES
        ):
            decision = replace(
                decision,
                target_temperature=decision.target_temperature + self.room_offset,
            )

        if not self._room_fallback:
            self._update_pending_forecast(
                now=dt_util.utcnow(),
                next_event=next_event,
                projected_temperature=decision.projected_temperature,
                schedule_active=schedule_active,
                present=present,
                window_open=window_open,
            )

        target_temperature = self._fit_to_thermostat(
            decision.target_temperature, climate_state
        )

        result: dict[str, Any] = {
            "status": decision.status,
            "mode": decision.mode,
            "target_temperature": target_temperature,
            "current_setpoint": self._climate_setpoint(climate_state),
            "room_temperature": room_temperature,
            "room_temperature_source": (
                "thermostats" if self._room_fallback else "sensor"
            ),
            "outdoor_temperature": outdoor_temperature,
            "heating_rate": self.effective_heating_rate,
            "cooling_rate": self.effective_cooling_rate,
            "preheat_minutes": decision.preheat_minutes,
            "projected_temperature": decision.projected_temperature,
            "forecast_condition": forecast_condition,
            "forecast_temperature": forecast_temperature,
            "solar_adjustment_minutes": decision.solar_adjustment_minutes,
            "schedule_active": schedule_active,
            "active_schedule": schedule_id,
            "eco_temperature": eco_temperature,
            "schedule_eco_temperature": slot_eco,
            "absence": self._absence,
            "room_offset": self.room_offset,
            "temperature_trend": (
                None if self._room_fallback else self._track_trend(room_temperature)
            ),
            "absent_since": (
                self._absent_since.isoformat() if self._absent_since else None
            ),
            "next_event": next_event.isoformat() if next_event else None,
            "window_open": window_open,
            "window_contact_open": window_contact_open,
            "heating_season": heating_season,
            "comfort_temperature": comfort_temperature,
            "schedule_comfort_temperature": slot_comfort,
            "boost_until": (
                self.boost_until.isoformat() if self.boost_until is not None else None
            ),
            "quick_mode": self.current_quick_mode,
            "quick_until": (
                self.quick_until.isoformat() if self.quick_until is not None else None
            ),
            "heating_limit_reached": self._heating_limit_reached,
            "outdoor_warmer": self._outdoor_warmer,
            "heating_limit_basis": limit_basis,
            "heating_limit_source": limit_source,
            "paused_features": sorted(paused),
            "house_calendar": house_event,
            "overshoot": self.overshoot,
            "present": present,
            "presence_status": presence_status,
            "enabled": self.enabled,
            "decision_status": decision.status,
            "control_error": False,
            "manual_override": False,
            "proximity_status": self._proximity_status,
            "proximity_distance_m": self._proximity_distance_m,
            "proximity_direction": self._proximity_direction,
            "proximity_age_seconds": self._proximity_age_seconds,
            "reachable_temperature": reachable,
            "setback_floor": setback_floor,
            **self._learning_diagnostics(),
            **self._model_diagnostics(view),
        }

        if self._room_fallback:
            result["status"] = (
                f"{result['status']} – Raumfühler nicht verfügbar, "
                "Ersatzwert aus den Thermostaten"
            )
        result["valve_maintenance"] = None
        if decision.mode == "maintenance":
            # The valves are fully open anyway; a pending start is dropped.
            self._maintenance_requested = False
        if (
            self.enabled
            and decision.mode != "maintenance"
            and await self._run_valve_maintenance(window_open, result)
        ):
            return result
        if self.enabled and decision.target_temperature is not None:
            await self._apply_target(
                decision.mode, decision.target_temperature, room_temperature, result
            )
            # Only watch while the thermostats really got the target: not with
            # an open window, a manual override or every thermostat off.
            # Only what the radiators can reach at all is a fair target.
            watch_target = target_temperature
            if reachable is not None and watch_target is not None:
                watch_target = min(watch_target, reachable - RECOVERY_REACH_MARGIN)
            self._update_heating_watchdog(
                watch_target,
                room_temperature,
                watch=bool(result.get("thermostat_setpoints"))
                and not (window_open or result["manual_override"])
                and decision.mode not in ("maintenance", "learn_run"),
            )
        else:
            self._update_heating_watchdog(None, room_temperature, watch=False)
            self._written.clear()
            self._calibration.clear()
            self._maintenance_started = None
            self._manual_override = None
            self._skip_closed.clear()
            self._divergent_since.clear()
            self._divergence = {}
            for entity_id in sorted(self._maintenance_woken):
                await self._call(
                    "climate", "set_hvac_mode", {"entity_id": entity_id, "hvac_mode": "off"}
                )
            self._maintenance_woken.clear()

        return result
