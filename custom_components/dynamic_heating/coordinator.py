"""State collection, learning and guarded thermostat control."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
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
    DEFAULT_ZONE_WINDOW_CLOSE_DELAY,
    DEFAULT_ZONE_WINDOW_OPEN_DELAY,
    EVENT_DEVICE_TRIGGER,
    EXTERNAL_TEMPERATURE_PLATEAU_CHANGE,
    EXTERNAL_TEMPERATURE_PLATEAU_SECONDS,
    EXTERNAL_TEMPERATURE_PLATEAU_TOLERANCE,
    HEATING_LIMIT_AVERAGE_HOURS,
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
    HEATING_WATCHDOG_GAP,
    HEATING_WATCHDOG_MIN_RISE,
    HEATING_WATCHDOG_SECONDS,
    IGNORED_PROBLEM_ENTITY_SUFFIXES,
    LOW_BATTERY_PERCENT,
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
)
from .logic import (
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
    evaluate_window_open,
    detect_temperature_drop,
    select_forecast_condition,
    select_forecast_temperature,
    valve_maintenance_due,
    valve_maintenance_phase,
)

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
_NO_OFFSET_MODES = frozenset(
    {
        "season_off",
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
        self._store = Store(hass, 1, f"{DOMAIN}_{entry_id}_learning")
        self._heating_sample = TrendSample()
        self._cooling_sample = TrendSample()
        # Comfort event for which preheating already started (see logic).
        self._preheat_event: datetime | None = None
        # Kept between updates so the heating limit releases with hysteresis.
        self._heating_limit_reached = False
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
        self._proximity_status_category = "unconfigured"
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
            data = {**state, "week": dict(self._week)}
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
        window = bool(result.get("window_open")) and result.get("heating_season", True)
        if window and not self._week_window:
            self._week["window_events"] += 1
        self._week_window = window

    def week_summary(self) -> str:
        """One line for the weekly report."""
        week = self._week
        hours = week["heating_s"] / 3600
        parts = [f"{hours:.0f} h geheizt".replace(".", ",")]
        if week["temperature_s"]:
            average = week["temperature_sum"] / week["temperature_s"]
            parts.append(f"Ø {average:.1f} °C".replace(".", ","))
        if week["window_events"]:
            parts.append(f"{week['window_events']}× Fenster offen beim Heizen")
        if week["alerts"]:
            parts.append(
                f"{week['alerts']} Meldung" + ("en" if week["alerts"] > 1 else "")
            )
        if self._heating_samples == 0:
            parts.append("Lernmodell sammelt noch Aufheizmessungen")
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

    def _record_proximity_category(self, category: str) -> None:
        """Count only changes between meaningful geofence states."""
        if category == self._proximity_status_category:
            return
        self._proximity_status_category = category
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
            self._record_proximity_category("invalid")
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
            self._record_proximity_category("stale")
            return (
                None,
                f"Standortdaten veraltet ({round(max(age, 0) / 60)} min) – "
                "Proximity wird nicht für Anfahrt verwendet",
            )

        legacy_direction = distance_state.attributes.get("dir_of_travel")
        if distance_state.domain == "proximity" or legacy_direction is not None:
            raw_direction = legacy_direction
        elif direction_state is not None and self._valid(direction_state):
            raw_direction = direction_state.state
        elif self.config.get(CONF_PROXIMITY_DIRECTION_ENTITY):
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid")
            return None, "Proximity-Richtung nicht verfügbar"
        else:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid")
            return None, "Proximity-Richtung fehlt: bitte Richtungssensor auswählen"

        direction = str(raw_direction or "").strip().lower()
        self._proximity_direction = direction or None
        if direction == "unknown" or direction in _INVALID_STATES or not direction:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid")
            return None, "Proximity-Richtung ist unbekannt"

        raw_distance = _as_float(distance_state)
        if raw_distance is None:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid")
            return None, "Proximity-Entfernung ist kein gültiger Zahlenwert"

        distance_m = self._distance_to_meters(
            raw_distance,
            distance_state.attributes.get("unit_of_measurement"),
        )
        if distance_m is None:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid")
            return None, "Proximity-Einheit nicht unterstützt"
        self._proximity_distance_m = round(distance_m, 1)

        maximum_distance = max(
            0.0,
            float(self.config.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE)),
        )
        if direction == "arrived" or distance_m <= 0:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("confirmed")
            return True, "Proximity meldet Ankunft"
        if direction in ("away_from", "stationary"):
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("not_approaching")
            return False, (
                "Bewegung weg vom Zuhause" if direction == "away_from"
                else "Standort stationär – keine Anfahrt"
            )
        if direction != "towards":
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid")
            return None, f"Unbekannte Bewegungsrichtung: {direction}"

        if distance_m > maximum_distance:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("out_of_range")
            return False, "Noch außerhalb der Anfahrtsentfernung"

        if key not in self._proximity_approaching:
            self._proximity_approaching[key] = now
            self._record_proximity_category("approaching")
        duration = max(
            0,
            int(self.config.get(CONF_PROXIMITY_DURATION, DEFAULT_PROXIMITY_DURATION)),
        )
        elapsed = (now - self._proximity_approaching[key]).total_seconds()
        if elapsed < duration:
            return False, (
                f"Anfahrt erkannt – Wartezeit {round(duration - elapsed)} s"
            )
        self._record_proximity_category("confirmed")
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

        for entity_id in people:
            state = self.hass.states.get(entity_id)
            if not self._valid(state):
                invalid_people = True
            elif state.state == "home" and self._presence_is_active(
                state, True, enter_delay
            ):
                household_home = True
            elif state.state == "not_home" and not self._presence_is_active(
                state, False, leave_delay
            ):
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
                found.append("nicht erreichbar")
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
        return written.confirmed

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
        if not self.config.get(CONF_CALIBRATION) or entity_id in self._external_fed:
            # A thermostat fed with the room temperature needs no offset.
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
        calibrate = decision_mode not in ("season_off", "maintenance")
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
        if (
            not watch
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
        self.quick_temperature = float(temperature)
        self.quick_until = self._quick_end()
        # A temperature set directly is meant as is (as in Climate Group Helper).
        self.room_offset = 0.0
        await self.async_refresh()

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
        ids += [entity_id for entity_id in extra if entity_id not in ids]
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
        temperature = round(setpoint * 2) / 2
        self.boost_until = None
        self.quick_mode = QUICK_MANUAL
        self.quick_temperature = temperature
        self.quick_until = self._quick_end()
        return temperature

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
                self.heating_rate,
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Run one control cycle and attach the thermostats' health."""
        await self._sync_external_temperature()
        await self._sync_trv_window_detection()
        result = await self._async_control_cycle()
        self._update_repair_issue()
        self._announce_mode(result)
        self._pending_source = None
        result["last_change_source"] = self.last_change_source
        result["last_change_at"] = (
            self.last_change_at.isoformat() if self.last_change_at else None
        )
        result["thermostat_warnings"] = self._thermostat_warnings()
        result["heating_problem"] = self.heating_problem
        result["heating_problem_detail"] = self.heating_problem_detail
        await self._send_notifications(result)
        result["external_temperature_thermostats"] = sorted(self._external_fed)
        result["quick_duration"] = self.quick_duration
        result["heat_demand"], result["heat_demand_source"] = self._heat_demand(
            result.get("target_temperature"), result.get("room_temperature")
        )
        self._fire_triggers(result)
        self._track_week(result)
        self._save_runtime_state()
        return result

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
        if result.get("heating_problem"):
            detail = result.get("heating_problem_detail")
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
                if sent:
                    await self._call(
                        domain,
                        name,
                        {"title": title, "message": "Wieder in Ordnung: " + {
                            "thermostat": "die Thermostate melden kein Problem mehr.",
                            "heating": "kein Heizproblem mehr.",
                            "sensor": "der Raumfühler liefert wieder Werte.",
                            "blocked": "die Regelung arbeitet wieder.",
                            "frost": "keine Frostgefahr mehr.",
                            "window": "das Fenster ist wieder geschlossen.",
                        }.get(key, key)},
                    )
        for key, (delay, message) in conditions.items():
            since, sent = self._alerts.get(key, (now, False))
            if not sent and (now - since).total_seconds() >= delay:
                sent = await self._call(
                    domain, name, {"title": title, "message": message}
                )
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
                due, pending = external_temperature_due(
                    None if switched else self._external_sent.get(number_id),
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
                if due:
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

    async def _async_control_cycle(self) -> dict[str, Any]:
        """Read Home Assistant states, calculate a target and optionally apply it."""
        room_temperature = self._room_temperature()
        schedule_id = self.active_schedule
        schedule_state = self.hass.states.get(schedule_id) if schedule_id else None
        climate_state = self._state(CONF_CLIMATE_ENTITY)
        outdoor_temperature = self._outdoor_temperature()

        self._room_fallback = room_temperature is None
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

        present, presence_status = self._evaluate_presence()
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
            reduced_comfort = (
                (
                    f"Raum leer – Komfort minus {value} °C"
                    if self._absence == "room_empty"
                    else f"Niemand zuhause – Komfort minus {value} °C"
                ),
                reduced,
            )
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
        forecast_condition = select_forecast_condition(
            forecast_items, next_event, dt_util.now()
        )
        forecast_temperature = select_forecast_temperature(
            forecast_items, next_event, dt_util.now()
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
        decision = decide_heating_target(
            now=dt_util.now(),
            schedule_active=schedule_active,
            next_event=next_event,
            room_temperature=room_temperature,
            outdoor_temperature=outdoor_temperature,
            comfort_temperature=comfort_temperature,
            eco_temperature=eco_temperature,
            heating_rate_c_per_hour=self.heating_rate,
            cooling_rate_c_per_hour=self.cooling_rate,
            forecast_condition=forecast_condition,
            forecast_temperature=forecast_temperature,
            max_preheat_minutes=int(
                self.config.get(
                    CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES
                )
            ),
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
            off_temperature=off_temperature,
            boost_temperature=boost_temperature,
            maintenance_temperature=maintenance_temperature,
            reduced_comfort=reduced_comfort,
            long_absence_temperature=long_absence_temperature,
            overshoot=self.overshoot,
            quick_mode=(None if maintenance_temperature is not None else quick)
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
            "heating_rate": self.heating_rate,
            "cooling_rate": self.cooling_rate,
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
            **self._learning_diagnostics(),
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
            self._update_heating_watchdog(
                target_temperature,
                room_temperature,
                watch=bool(result.get("thermostat_setpoints"))
                and not (window_open or result["manual_override"])
                and decision.mode != "maintenance",
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
