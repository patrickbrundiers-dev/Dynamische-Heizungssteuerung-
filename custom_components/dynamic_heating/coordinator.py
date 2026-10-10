"""State collection, learning and guarded thermostat control."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AWAY_TEMPERATURE,
    CALIBRATION_INTERVAL_SECONDS,
    CONF_ADDITIONAL_CLIMATE_ENTITIES,
    CONF_CALIBRATION,
    CONF_EXTERNAL_TEMPERATURE,
    CONF_HYSTERESIS,
    EXTERNAL_TEMPERATURE_MIN_CHANGE,
    EXTERNAL_TEMPERATURE_RESEND_SECONDS,
    LOW_BATTERY_PERCENT,
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
    CONF_PROXIMITY_DIRECTION_ENTITY,
    CONF_PROXIMITY_MAX_AGE,
    CONF_PROXIMITY_DURATION,
    CONF_PROXIMITY_DISTANCE,
    CONF_PRESENCE_SCHEDULE_ENTITY,
    CONF_PRESENCE_ON_DURATION,
    CONF_PRESENCE_OFF_DURATION,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WINDOW_ENTITY,
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
    apply_hysteresis,
    calibration_offset,
    fallback_room_temperature,
    decide_heating_target,
    evaluate_heating_limit,
    evaluate_window_open,
    select_forecast_condition,
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


def _as_float(state: State | None) -> float | None:
    """Read a numeric state without raising on unavailable or malformed input."""
    if state is None or state.state in _INVALID_STATES:
        return None
    try:
        value = float(state.state)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class DynamicHeatingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate learning, schedule prediction and optional thermostat control."""

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
        self._proximity_approaching_since: datetime | None = None
        self._proximity_distance_m: float | None = None
        self._proximity_direction: str | None = None
        self._proximity_age_seconds: float | None = None
        self._proximity_status = "Proximity nicht konfiguriert"
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
            }
        )

    async def _learn(
        self,
        room_temperature: float,
        climate_state: State | None,
        *,
        window_open: bool,
        present: bool,
        schedule_active: bool,
        eco_temperature: float,
    ) -> None:
        """Learn from plausible temperature trends and reject outlier samples."""
        attributes = climate_state.attributes if climate_state else {}
        setpoint_value = self._stored_float(attributes.get("temperature"))
        is_heating = self._is_heating(climate_state, room_temperature, setpoint_value)
        now = dt_util.utcnow()

        if window_open or not present:
            self._heating_sample.reset()
            self._cooling_sample.reset()
            self._last_learning_status = (
                "Lernen pausiert: Fenster offen" if window_open
                else "Lernen pausiert: keine Anwesenheit"
            )
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
            if not MIN_LEARNED_HEATING_RATE <= observed_rate <= MAX_LEARNED_HEATING_RATE:
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
    ) -> tuple[bool | None, str]:
        """Validate freshness, unit, direction and distance before inferring arrival."""
        self._proximity_distance_m = None
        self._proximity_direction = None
        self._proximity_age_seconds = None

        if not self._valid(distance_state):
            self._proximity_approaching_since = None
            self._record_proximity_category("invalid")
            return None, "Proximity-Entfernung nicht verfügbar"

        self._observe_proximity_update(distance_state)

        now = dt_util.utcnow()
        age = (now - dt_util.as_utc(distance_state.last_updated)).total_seconds()
        self._proximity_age_seconds = round(max(age, 0), 1)
        max_age = max(
            0,
            int(self.config.get(CONF_PROXIMITY_MAX_AGE, DEFAULT_PROXIMITY_MAX_AGE)),
        )
        if age < -60 or age > max_age:
            self._proximity_approaching_since = None
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
            self._proximity_approaching_since = None
            self._record_proximity_category("invalid")
            return None, "Proximity-Richtung nicht verfügbar"
        else:
            self._proximity_approaching_since = None
            self._record_proximity_category("invalid")
            return None, "Proximity-Richtung fehlt: bitte Richtungssensor auswählen"

        direction = str(raw_direction or "").strip().lower()
        self._proximity_direction = direction or None
        if direction == "unknown" or direction in _INVALID_STATES or not direction:
            self._proximity_approaching_since = None
            self._record_proximity_category("invalid")
            return None, "Proximity-Richtung ist unbekannt"

        raw_distance = _as_float(distance_state)
        if raw_distance is None:
            self._proximity_approaching_since = None
            self._record_proximity_category("invalid")
            return None, "Proximity-Entfernung ist kein gültiger Zahlenwert"

        distance_m = self._distance_to_meters(
            raw_distance,
            distance_state.attributes.get("unit_of_measurement"),
        )
        if distance_m is None:
            self._proximity_approaching_since = None
            self._record_proximity_category("invalid")
            return None, "Proximity-Einheit nicht unterstützt"
        self._proximity_distance_m = round(distance_m, 1)

        maximum_distance = max(
            0.0,
            float(self.config.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE)),
        )
        if direction == "arrived" or distance_m <= 0:
            self._proximity_approaching_since = None
            self._record_proximity_category("confirmed")
            return True, "Proximity meldet Ankunft"
        if direction in ("away_from", "stationary"):
            self._proximity_approaching_since = None
            self._record_proximity_category("not_approaching")
            return False, (
                "Bewegung weg vom Zuhause" if direction == "away_from"
                else "Standort stationär – keine Anfahrt"
            )
        if direction != "towards":
            self._proximity_approaching_since = None
            self._record_proximity_category("invalid")
            return None, f"Unbekannte Bewegungsrichtung: {direction}"

        if distance_m > maximum_distance:
            self._proximity_approaching_since = None
            self._record_proximity_category("out_of_range")
            return False, "Noch außerhalb der Anfahrtsentfernung"

        if self._proximity_approaching_since is None:
            self._proximity_approaching_since = now
            self._record_proximity_category("approaching")
        duration = max(
            0,
            int(self.config.get(CONF_PROXIMITY_DURATION, DEFAULT_PROXIMITY_DURATION)),
        )
        elapsed = (now - self._proximity_approaching_since).total_seconds()
        if elapsed < duration:
            return False, (
                f"Anfahrt erkannt – Wartezeit {round(duration - elapsed)} s"
            )
        self._record_proximity_category("confirmed")
        return True, "Anfahrt bestätigt"

    def _evaluate_presence(self) -> tuple[bool | None, str]:
        """Combine person, guest, proximity and scheduled presence signals."""
        people = self.config.get(CONF_PERSON_ENTITIES) or []
        if isinstance(people, str):
            people = [people]

        guest_id = self.config.get(CONF_GUEST_ENTITY)
        proximity_id = self.config.get(CONF_PROXIMITY_ENTITY)
        direction_id = self.config.get(CONF_PROXIMITY_DIRECTION_ENTITY)
        presence_id = self.config.get(CONF_PRESENCE_ENTITY)
        has_household_source = bool(people or guest_id or proximity_id)
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
        if proximity_id:
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
            if state.state == "on":
                sensor_present = self._presence_is_active(state, True, on_delay)
            elif state.state == "off":
                sensor_present = not self._presence_is_active(state, False, off_delay)
            else:
                return None, "Anwesenheitssensor liefert ungültigen Zustand – keine Sollwertänderung"

            present = (
                household_present and sensor_present
                if has_household_source
                else sensor_present
            )
        elif presence_id and presence_schedule_off and not has_household_source:
            present = False
        else:
            present = household_present

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
                    if device_class == "battery":
                        found.append("Batterie schwach")
                    elif device_class == "problem":
                        name = state.attributes.get("friendly_name") or state.entity_id
                        found.append(f"meldet Problem ({name})")
            if found:
                warnings[entity_id] = found
        return warnings

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
            return True
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

    async def _run_valve_maintenance(
        self, window_open: bool, result: dict[str, Any]
    ) -> bool:
        """Exercise the valves weekly; True while maintenance owns the valves."""
        now = dt_util.utcnow()
        if self._maintenance_started is None:
            if (
                not self.config.get(CONF_VALVE_MAINTENANCE)
                or window_open
                or self._manual_override is not None
                or not valve_maintenance_due(
                    self._maintenance_last,
                    now,
                    dt_util.as_local(now).hour,
                    VALVE_MAINTENANCE_INTERVAL_DAYS,
                    VALVE_MAINTENANCE_HOUR,
                )
            ):
                return False
            self._maintenance_started = now
            self._maintenance_last = now
            await self._save_learning()

        phase = valve_maintenance_phase(
            self._maintenance_started, now, VALVE_MAINTENANCE_PHASE_SECONDS
        )
        if phase is None:
            # Done: forget the maintenance setpoints so they are not taken
            # for manual changes, and write the normal target again.
            self._maintenance_started = None
            self._written.clear()
            return False

        result["valve_maintenance"] = phase
        result["status"] = (
            "Ventilwartung – Ventile öffnen"
            if phase == "open"
            else "Ventilwartung – Ventile schließen"
        )
        for entity_id in self._thermostat_ids():
            state = self.hass.states.get(entity_id)
            if not self._valid(state) or state.state == "off":
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

        if self._manual_override is None:
            for entity_id, state in available.items():
                if self._changed_manually(entity_id, state):
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
            return

        active = {
            entity_id: state
            for entity_id, state in available.items()
            if state.state != "off"
        }
        if not active:
            result["status"] = "Thermostat ausgeschaltet – keine Sollwertänderung"
            return

        now = dt_util.utcnow()
        failed = False
        # Outside the heating season the valve stays at its minimum.
        calibrate = decision_mode != "season_off"
        setpoints: dict[str, float] = {}
        for entity_id, state in active.items():
            setpoint = self._fit_to_thermostat(
                self._calibrated(entity_id, state, target, room_temperature, now)
                if calibrate
                else target,
                state,
            )
            setpoints[entity_id] = setpoint
            if not await self._write_setpoint(entity_id, state, setpoint, now):
                failed = True
        result["thermostat_setpoints"] = setpoints
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

    async def _async_update_data(self) -> dict[str, Any]:
        """Run one control cycle and attach the thermostats' health."""
        await self._sync_external_temperature()
        result = await self._async_control_cycle()
        result["thermostat_warnings"] = self._thermostat_warnings()
        result["external_temperature_thermostats"] = sorted(self._external_fed)
        return result

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

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> bool:
        """Call a service; log and return False instead of raising."""
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
        room_temperature = _as_float(self._state(CONF_ROOM_TEMPERATURE_ENTITY))
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
                last = self._external_sent.get(number_id)
                if (
                    last is None
                    or abs(last[0] - room_temperature) >= EXTERNAL_TEMPERATURE_MIN_CHANGE
                    or (now - last[1]).total_seconds() >= EXTERNAL_TEMPERATURE_RESEND_SECONDS
                ):
                    if not await self._call(
                        "number",
                        "set_value",
                        {"entity_id": number_id, "value": room_temperature},
                    ):
                        continue
                    self._external_sent[number_id] = (room_temperature, now)
                if select_state.state != "external" and not await self._call(
                    "select",
                    "select_option",
                    {"entity_id": select_id, "option": "external"},
                ):
                    continue
                fed.add(entity_id)
            else:
                self._external_sent.pop(number_id, None)
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
        room_temperature = _as_float(self._state(CONF_ROOM_TEMPERATURE_ENTITY))
        schedule_state = self._state(CONF_SCHEDULE_ENTITY)
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

        window_open = False
        window_contact_open = False
        window_id = self.config.get(CONF_WINDOW_ENTITY)
        if window_id:
            window_state = self.hass.states.get(window_id)
            if not self._valid(window_state):
                return self._waiting_result(
                    "Fensterkontakt nicht verfügbar – keine Sollwertänderung",
                    room_temperature,
                    outdoor_temperature,
                )
            window_contact_open = window_state.state == "on"
            window_open = evaluate_window_open(
                window_contact_open,
                (dt_util.utcnow() - window_state.last_changed).total_seconds(),
                self._window_open,
                int(self.config.get(CONF_WINDOW_OPEN_DELAY) or DEFAULT_WINDOW_OPEN_DELAY),
                int(self.config.get(CONF_WINDOW_CLOSE_DELAY) or DEFAULT_WINDOW_CLOSE_DELAY),
            )
        self._window_open = window_open

        present, presence_status = self._evaluate_presence()
        if self._proximity_metrics_dirty:
            self._proximity_metrics_dirty = False
            await self._save_learning()
        if present is None:
            return self._waiting_result(presence_status, room_temperature, outdoor_temperature)

        comfort_temperature = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        eco_temperature = float(
            self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE)
        )
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
        schedule_active = schedule_state.state == "on"
        limit_value = self.config.get(CONF_HEATING_LIMIT_TEMPERATURE)
        self._heating_limit_reached = evaluate_heating_limit(
            outdoor_temperature,
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
                present=present,
                schedule_active=schedule_active,
                eco_temperature=eco_temperature,
            )

        next_event = self._parse_next_event(schedule_state)
        if self._preheat_event is not None and self._preheat_event != next_event:
            self._preheat_event = None
        forecast_items = await self._async_get_forecast_items()
        forecast_condition = select_forecast_condition(
            forecast_items, next_event, dt_util.now()
        )
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
        )
        if decision.mode == "preheat":
            self._preheat_event = next_event

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
            "solar_adjustment_minutes": decision.solar_adjustment_minutes,
            "schedule_active": schedule_active,
            "next_event": next_event.isoformat() if next_event else None,
            "window_open": window_open,
            "window_contact_open": window_contact_open,
            "heating_season": heating_season,
            "heating_limit_reached": self._heating_limit_reached,
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
        if self.enabled and await self._run_valve_maintenance(window_open, result):
            return result
        if self.enabled and decision.target_temperature is not None:
            await self._apply_target(
                decision.mode, decision.target_temperature, room_temperature, result
            )
        else:
            self._written.clear()
            self._calibration.clear()
            self._maintenance_started = None
            self._manual_override = None

        return result
