"""State collection, learning and guarded thermostat control."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_WARM_UP_DURATION,
    CONF_WARM_UP_STEP,
    DEFAULT_WARM_UP_DURATION,
    DEFAULT_WARM_UP_STEP,
    CONF_PREHEAT_WHEN_HOME,
    CONF_RECOVERY_LIMIT,
    CONF_ROOM_EMPTY_RECOVERY,
    DEFAULT_PREHEAT_WHEN_HOME,
    DEFAULT_RECOVERY_LIMIT,
    DEFAULT_ROOM_EMPTY_RECOVERY,
    RECOVERY_REACH_MARGIN,
    BLOCK_PRESENCE_KEYS,
    BLOCK_WINDOW_KEYS,
    CONF_COMMAND_DELAY,
    CONF_FOLLOW_HOUSE_CALENDAR,
    CONF_FORCE_COMFORT_ENTITIES,
    CONF_FORCE_ECO_ENTITIES,
    CONF_HEATING_LIMIT_AVERAGE,
    CONF_HEATING_LIMIT_FALLBACK_OFF,
    CONF_OUTDOOR_WARMER_MARGIN,
    CONF_OUTDOOR_WARMER_STOP,
    CONF_WINDOW_CHANGE,
    DEFAULT_COMMAND_DELAY,
    DEFAULT_FOLLOW_HOUSE_CALENDAR,
    DEFAULT_HEATING_LIMIT_AVERAGE,
    DEFAULT_OUTDOOR_WARMER_MARGIN,
    DEFAULT_OUTDOOR_WARMER_STOP,
    HEATING_LIMIT_AVERAGE_HOURS,
    OUTDOOR_WARMER_HYSTERESIS,
    HEATING_LIMIT_MIN_FORECAST_POINTS,
    MAX_OVERSHOOT,
    OUTDOOR_HISTORY_INTERVAL_SECONDS,
    OUTDOOR_HISTORY_MIN_SPAN_SECONDS,
    ROOM_TEMPERATURE_PLAUSIBLE_MAX,
    ROOM_TEMPERATURE_PLAUSIBLE_MIN,
    CONF_COLD_COMFORT_BOOST,
    DEFAULT_COLD_COMFORT_BOOST,
    COLD_COMFORT_MAX,
    COLD_COMFORT_FROM,
    COLD_COMFORT_FULL,
    LEVEL_KEYS,
    LEVELS,
    WINDOW_CHANGE_DISCARD,
    CALENDAR_TEMPERATURE_KEY,
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
    CONF_ECO_SCHEDULE_ENTITY,
    CONF_FROST_AFTER_ABSENCE,
    CONF_SYNC_MANUAL_CHANGE,
    DEFAULT_AGGRESSIVE_OFFSET,
    DEFAULT_FROST_AFTER_ABSENCE,
    DEFAULT_SYNC_MANUAL_CHANGE,
    QUICK_MAINTENANCE,
    QUICK_LABELS,
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
    HEATING_WATCHDOG_GAP,
    SETBACK_FLOOR_STEP,
    HEATING_WATCHDOG_MIN_RISE,
    HEATING_WATCHDOG_SECONDS,
    CONF_RADIATOR_POWER,
    RADIATOR_POWER_PER_THERMOSTAT_W,
    DEFAULT_DEVICE_NAME,
    MODE_SWITCH_GRACE_SECONDS,
    OUTDOOR_FALLBACK_GRACE_SECONDS,
    HEAT_DEMAND_FULL_GAP,
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
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_FROST_PROTECTION_TEMPERATURE,
    CONF_HEATING_LIMIT_TEMPERATURE,
    CONF_HEATING_SEASON_ENTITY,
    CONF_WINDOW_TEMPERATURE,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_COOLING_RATE,
    DEFAULT_ECO_TEMPERATURE,
    INFERRED_HEATING_MARGIN,
    HEATING_LIMIT_HYSTERESIS,
    MAX_CALIBRATION_OFFSET,
    SETPOINT_RESEND_SECONDS,
    DEFAULT_HEATING_RATE,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DOMAIN,
    MAX_LEARNED_COOLING_RATE,
    MAX_LEARNED_HEATING_RATE,
    MIN_LEARNED_COOLING_RATE,
    MIN_LEARNED_HEATING_RATE,
    CONF_MANUAL_MAX_TEMPERATURE,
    CONF_MANUAL_MAX_DURATION,
    CONF_SCHOOL_FREE_SCHEDULE,
    SHOWER_RISE_PERCENT,
    SHOWER_RISE_WINDOW_SECONDS,
    SHOWER_COOLDOWN_SECONDS,
)
from .logic import (
    TrendSample,
    match_schedule,
    mean_forecast_temperature,
    mean_history_temperature,
    name_temperature,
    paused_features,
    plausible_temperature,
    calendar_temperature,
    description_value,
    temperature_trend,
    aggressive_setpoint,
    select_schedule,
    apply_hysteresis,
    calibration_offset,
    fallback_room_temperature,
    calculate_lead_minutes,
    preheat_parts_text,
    schedule_comfort_temperature,
    decide_heating_target,
    evaluate_heating_limit,
    evaluate_outdoor_warmer,
    select_forecast_condition,
    select_forecast_temperature,
)
from .model import (
    HOLDS_DOWN_TO_FLOOR,
    CoolingCorrection,
    RoomModel,
    SampleCollector,
    UsageProfile,
    heat_load,
)
from .radiator import (
    SUPPLY_COLD,
    SUPPLY_VERSION,
    SUPPLY_WARM,
    RadiatorStats,
    RadiatorTracker,
    RoomResponse,
    SupplyProfile,
)
from .battery import BatteryWatch
from .routine import (
    Habits,
    Homecoming,
    ShowerWatch,
    HeatStats,
    Punctuality,
)
from .pending_push import hold_if_missing
from .plan import Block
from .room_util import (
    ROOM_MODEL_VERSION,
    REACH_TREND_MARGIN,
    SELFTEST_DELAY,
    _LOGGER,
    _WrittenSetpoint,
    _INVALID_STATES,
    _REACH_MODES,
    _NO_OFFSET_MODES,
    _as_float,
    _as_number,
)
from .room_presence import PresenceMixin
from .room_windows import WindowMixin
from .room_valves import ValveMixin
from .room_supply import SupplyMixin
from .room_learning import LearningMixin
from .room_plan import PlanMixin
from .room_notify import NotifyMixin
from .room_insights import InsightsMixin


class DynamicHeatingCoordinator(
    PresenceMixin,
    WindowMixin,
    ValveMixin,
    SupplyMixin,
    LearningMixin,
    PlanMixin,
    NotifyMixin,
    InsightsMixin,
    DataUpdateCoordinator[dict[str, Any]],
):
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
        # Radiator test (button): the running one and the last result.
        self._radiator_test: dict[str, Any] | None = None
        self._radiator_test_requested = False
        self.radiator_test_result: dict[str, Any] | None = None
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
        self._schedule_week_key: tuple | None = None
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
        # Latest motion of the occupancy sensor (runtime only).
        self._last_motion: datetime | None = None
        # Comfort block that already ended heating early, and the sun pause.
        self._early_stop_event: datetime | None = None
        self._solar_pause = False
        # Calibration run of the room model: planned start and running end.
        self.learn_run_at: datetime | None = None
        self.learn_run_until: datetime | None = None
        self._learn_run_target: float | None = None
        # Warm on time, modes picked by hand, long-term figures (persisted).
        self.punctuality = Punctuality()
        # (outdoor at the next comfort start, degrees to warm up) for the
        # correction from similar mornings; set every cycle.
        self._bias_context: tuple[float | None, float | None] = (None, None)
        self.habits = Habits()
        # Showers seen in the room's humidity (bathrooms, runde 10).
        self.showers = Habits()
        self.batteries = BatteryWatch()
        self._battery_seed_at: datetime | None = None
        self._showers_seeded = False
        # Usual homecoming per weekday (persisted), seeded once from the
        # recorder; the day preheating for it began (runtime).
        self.homecoming = Homecoming()
        self._airing_state: str | None = None
        self._homecoming_seeded = False
        self._homecoming_day: date | None = None
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
            SupplyProfile.from_list(
                stored.get("supply_profile"), stored.get("supply_counts")
            )
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
        self.homecoming = Homecoming.from_dict(stored.get("homecoming"))
        self._homecoming_seeded = bool(stored.get("homecoming_seeded"))
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
            if active and temperature is None:
                name = description_value(state.attributes.get("description"), LEVEL_KEYS)
                temperature = self._level_temperature(name)
            return active, next_event, temperature
        temperature = (
            schedule_comfort_temperature(
                state.attributes.get(SCHEDULE_TEMPERATURE_ATTRIBUTE)
            )
            if active
            else None
        )
        if active and temperature is None:
            temperature = self._block_level(state.attributes)
        return active, self._parse_next_event(state), temperature

    def _level_temperature(self, name: object) -> float | None:
        """Temperature of a level such as "abend", kept by the house."""
        if not isinstance(name, str) or not name.strip():
            return None
        key = name.strip().casefold()
        house = self._house()
        if house is not None:
            return house.level(key)
        item = LEVELS.get(key)
        return None if item is None else item[1]

    def _levels_key(self) -> tuple[float | None, ...]:
        """The current level temperatures, so caches notice a change."""
        return tuple(self._level_temperature(key) for key in LEVELS)

    def level_options(self) -> list[dict[str, Any]]:
        """The temperature levels for the schedule editor."""
        return [
            {"key": key, "name": name, "temperature": self._level_temperature(key)}
            for key, (name, _default) in LEVELS.items()
        ]

    def _block_level(self, data: object) -> float | None:
        """Temperature of the level a schedule block names (``stufe: abend``)."""
        if not hasattr(data, "get"):
            return None
        for key in LEVEL_KEYS:
            value = data.get(key)
            if value is not None:
                return self._level_temperature(str(value))
        return None


    def _track_trend(self, room_temperature: float) -> float | None:
        """Keep the last half hour of room readings; return the trend."""
        now = dt_util.utcnow()
        self._trend_samples.append((now, room_temperature))
        cutoff = now - timedelta(seconds=TREND_WINDOW_SECONDS)
        self._trend_samples = [
            sample for sample in self._trend_samples if sample[0] >= cutoff
        ]
        return temperature_trend(self._trend_samples, TREND_MIN_SPAN_SECONDS)


    async def async_set_room_offset(self, offset: float) -> None:
        """Shift every target of the room by ``offset``."""
        self.room_offset = max(ROOM_OFFSET_MIN, min(float(offset), ROOM_OFFSET_MAX))
        await self.async_refresh()


    async def async_set_option(self, key: str, value: Any) -> None:
        """Change one setting from an entity, without reloading the room."""
        self.config[key] = value
        await self.async_refresh()


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


    def _thermostat_ids(self) -> list[str]:
        """Primary thermostat first, then additional ones of the same room."""
        ids = [self.config[CONF_CLIMATE_ENTITY]]
        for entity_id in self.config.get(CONF_ADDITIONAL_CLIMATE_ENTITIES) or []:
            if entity_id not in ids:
                ids.append(entity_id)
        return ids


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


    def _cold_comfort_raise(self, outdoor: float | None) -> float:
        """How much comfort rises in the cold (walls feel colder), 0 = off.

        Nothing above ``COLD_COMFORT_FROM`` outdoors, the full set raise at
        ``COLD_COMFORT_FULL`` and below, evenly in between (0.1 °C steps).
        """
        try:
            raise_by = float(
                self.config.get(CONF_COLD_COMFORT_BOOST, DEFAULT_COLD_COMFORT_BOOST) or 0
            )
        except (TypeError, ValueError):
            return 0.0
        raise_by = max(0.0, min(COLD_COMFORT_MAX, raise_by))
        if not raise_by or outdoor is None:
            return 0.0
        share = (COLD_COMFORT_FROM - float(outdoor)) / (COLD_COMFORT_FROM - COLD_COMFORT_FULL)
        return round(raise_by * max(0.0, min(1.0, share)), 1)


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
            # A tiny learned loss puts this at −300 °C: no real meaning.
            "holds_comfort_down_to": round(max(load.holds_down_to, HOLDS_DOWN_TO_FLOOR), 1),
            "verdict": load.verdict if self.room_model.trusted else "noch ungenau",
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
        routine_learned = self._observe_homecoming(result) or routine_learned
        await self._morning_report(result)
        shower_seen = self._observe_shower(result)
        self._update_airing(result)
        self._update_data_quality(result)
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
                outdoor=self._bias_context[0],
                bias=self._lead_bias(),
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
        result["punctuality_running_bias"] = round(self.punctuality.bias_minutes)
        result["punctuality_similar"] = self.punctuality.similar_ready()
        result["punctuality_mornings"] = len(self.punctuality.history)
        result["punctuality_results"] = [
            {"date": day, "minutes_late": late}
            for day, late in self.punctuality.results
        ]
        return judged


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


    def _friendly_name(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        name = state.attributes.get("friendly_name") if state is not None else None
        return str(name).strip(" -") if name else entity_id


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
        cold_raise = self._cold_comfort_raise(outdoor_temperature)
        comfort_temperature += cold_raise
        now_utc = dt_util.utcnow()
        if not schedule_active:
            self._comfort_started_at = None
            if self._schedule_was_active:
                self._comfort_ended_at = now_utc
        elif self._schedule_was_active is False:
            self._comfort_started_at = now_utc
        self._schedule_was_active = schedule_active
        occupancy = self._occupancy(now_utc, schedule_active)
        if occupancy == "extend":
            # Still in use after the block ended: comfort without an end, so
            # nothing stops it early.
            schedule_active, next_event = True, None
            presence_status = "Raum wird noch genutzt – Komfort gehalten"
        elif occupancy == "unused" and self._absence == "none" and "presence" not in paused:
            present = False
            presence_status = "Seit Komfortbeginn keine Bewegung – abgesenkt bis zur ersten Bewegung"
            self._absence = "room_empty"
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
        self._bias_context = (
            forecast_temperature
            if forecast_temperature is not None
            else outdoor_temperature,
            max(0.0, comfort_temperature - room_temperature),
        )
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
        if cold_raise and decision.mode in ("comfort", "preheat", "homecoming"):
            decision = replace(
                decision,
                status=f"{decision.status} (+"
                + f"{cold_raise:.1f}".replace(".", ",")
                + " °C wegen Kälte)",
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
        decision = self._homecoming_preheat(
            decision,
            room_temperature=room_temperature,
            outdoor_temperature=outdoor_temperature,
            comfort_temperature=comfort_temperature,
            schedule_active=schedule_active,
            next_event=next_event,
            view=event_view,
            max_preheat=preheat_limit,
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
            "preheat_parts": decision.preheat_parts,
            "cold_comfort_raise": cold_raise,
            "preheat_breakdown": (
                preheat_parts_text(decision.preheat_parts)
                if decision.preheat_parts
                else None
            ),
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
        result["radiator_test"] = (
            self.radiator_test_result["text"] if self.radiator_test_result else None
        )
        if decision.mode == "maintenance":
            # The valves are fully open anyway; a pending start is dropped.
            self._maintenance_requested = False
        if (
            self.enabled
            and decision.mode != "maintenance"
            and await self._run_valve_maintenance(window_open, result)
        ):
            return result
        if self.enabled and await self._run_radiator_test(window_open, result):
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
            self._radiator_test = None
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
