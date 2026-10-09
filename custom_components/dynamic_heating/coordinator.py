"""State collection, learning and guarded thermostat control."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_PERSON_ENTITIES,
    CONF_GUEST_ENTITY,
    CONF_ENTER_HOME_DURATION,
    CONF_LEAVING_HOME_DURATION,
    CONF_PROXIMITY_ENTITY,
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
from .logic import decide_heating_target, select_forecast_condition

_LOGGER = logging.getLogger(__name__)
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
        self.heating_rate = DEFAULT_HEATING_RATE
        self.cooling_rate = DEFAULT_COOLING_RATE
        self._store = Store(hass, 1, f"{DOMAIN}_{entry_id}_learning")
        self._sample_temperature: float | None = None
        self._sample_time: datetime | None = None
        self._cooling_sample_temperature: float | None = None
        self._cooling_sample_time: datetime | None = None
        self._forecast_items: list[dict[str, Any]] = []
        self._forecast_fetched_at: datetime | None = None
        self._proximity_approaching_since: datetime | None = None

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

    async def _save_learning(self) -> None:
        """Persist both bounded learning estimates together."""
        await self._store.async_save(
            {
                "heating_rate": self.heating_rate,
                "cooling_rate": self.cooling_rate,
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
        """Learn only from bounded, stable heating or setback observations."""
        attributes = climate_state.attributes if climate_state else {}
        setpoint = attributes.get("temperature")
        is_heating = attributes.get("hvac_action") == "heating"
        try:
            setpoint_value = float(setpoint)
        except (TypeError, ValueError):
            setpoint_value = None
        if setpoint_value is not None and not math.isfinite(setpoint_value):
            setpoint_value = None

        now = dt_util.utcnow()

        # Do not learn during open-window or away periods, as those observations
        # are not representative of normal room behaviour.
        if window_open or not present:
            self._sample_temperature = None
            self._sample_time = None
            self._cooling_sample_temperature = None
            self._cooling_sample_time = None
            return

        if is_heating:
            self._cooling_sample_temperature = None
            self._cooling_sample_time = None
            if setpoint_value is None or room_temperature >= setpoint_value - 0.1:
                self._sample_temperature = None
                self._sample_time = None
                return

            if self._sample_temperature is None or self._sample_time is None:
                self._sample_temperature = room_temperature
                self._sample_time = now
                return

            elapsed = (now - self._sample_time).total_seconds()
            if elapsed < MIN_SAMPLE_SECONDS:
                return

            delta = room_temperature - self._sample_temperature
            if 0.05 <= delta <= 2.5:
                observed_rate = delta / (elapsed / 3600)
                observed_rate = max(
                    MIN_LEARNED_HEATING_RATE,
                    min(observed_rate, MAX_LEARNED_HEATING_RATE),
                )
                self.heating_rate = round(
                    0.8 * self.heating_rate + 0.2 * observed_rate, 3
                )
                await self._save_learning()

            self._sample_temperature = room_temperature
            self._sample_time = now
            return

        self._sample_temperature = None
        self._sample_time = None
        can_learn_cooling = (
            setpoint_value is not None
            and room_temperature > setpoint_value + 0.2
            and setpoint_value <= eco_temperature + 0.5
            and not schedule_active
        )
        if not can_learn_cooling:
            self._cooling_sample_temperature = None
            self._cooling_sample_time = None
            return

        if (
            self._cooling_sample_temperature is None
            or self._cooling_sample_time is None
        ):
            self._cooling_sample_temperature = room_temperature
            self._cooling_sample_time = now
            return

        elapsed = (now - self._cooling_sample_time).total_seconds()
        if elapsed < MIN_COOLING_SAMPLE_SECONDS:
            return

        delta = room_temperature - self._cooling_sample_temperature
        if -2.0 <= delta <= -0.05:
            observed_rate = -delta / (elapsed / 3600)
            observed_rate = max(
                MIN_LEARNED_COOLING_RATE,
                min(observed_rate, MAX_LEARNED_COOLING_RATE),
            )
            self.cooling_rate = round(0.8 * self.cooling_rate + 0.2 * observed_rate, 3)
            await self._save_learning()

        self._cooling_sample_temperature = room_temperature
        self._cooling_sample_time = now



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

    def _proximity_is_active(self, state: State) -> bool:
        """Count continuous approach time independently of changing distance state."""
        direction = str(state.attributes.get("dir_of_travel", "")).lower()
        distance = _as_float(state)

        if state.state == "home" or direction == "arrived" or distance == 0:
            self._proximity_approaching_since = None
            return True

        within_range = (
            distance is not None
            and distance <= float(
                self.config.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE)
            )
        )
        approaching = direction == "towards" and within_range
        if not approaching:
            self._proximity_approaching_since = None
            return False

        now = dt_util.utcnow()
        if self._proximity_approaching_since is None:
            self._proximity_approaching_since = now
        delay = max(
            0,
            int(self.config.get(CONF_PROXIMITY_DURATION, DEFAULT_PROXIMITY_DURATION)),
        )
        return (now - self._proximity_approaching_since).total_seconds() >= delay

    def _evaluate_presence(self) -> tuple[bool | None, str]:
        """Combine household, guest, proximity and scheduled presence signals."""
        people = self.config.get(CONF_PERSON_ENTITIES) or []
        if isinstance(people, str):
            people = [people]

        guest_id = self.config.get(CONF_GUEST_ENTITY)
        proximity_id = self.config.get(CONF_PROXIMITY_ENTITY)
        presence_id = self.config.get(CONF_PRESENCE_ENTITY)
        has_household_source = bool(people or guest_id or proximity_id)
        has_any_source = has_household_source or bool(presence_id)

        # Preserve old behavior only when no presence source has been configured.
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
                # Keep the former home state during the configured leave grace.
                household_home = True

        if guest_id:
            guest = self.hass.states.get(guest_id)
            if not self._valid(guest):
                return None, "Gastmodus-Entität nicht verfügbar – keine Sollwertänderung"
            household_home = household_home or guest.state == "on"

        proximity_home = False
        if proximity_id:
            proximity = self.hass.states.get(proximity_id)
            if not self._valid(proximity):
                return None, "Proximity-Entität nicht verfügbar – keine Sollwertänderung"
            proximity_home = self._proximity_is_active(proximity)

        household_present = household_home or proximity_home
        if invalid_people and not household_present:
            return None, "Personen-/Geräte-Tracker nicht verfügbar – keine Sollwertänderung"

        use_presence = bool(presence_id)
        schedule_id = self.config.get(CONF_PRESENCE_SCHEDULE_ENTITY)
        presence_schedule_off = False
        if schedule_id:
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
                # Keep presence true for the configured off-delay after motion stops.
                sensor_present = not self._presence_is_active(state, False, off_delay)
            else:
                return None, "Anwesenheitssensor liefert ungültigen Zustand – keine Sollwertänderung"

            present = (
                household_present and sensor_present
                if has_household_source
                else sensor_present
            )
        elif presence_id and presence_schedule_off and not has_household_source:
            # With no other source, a disabled presence schedule intentionally means eco.
            present = False
        else:
            present = household_present

        return present, (
            "Anwesenheit erkannt" if present else "Keine Anwesenheit – abgesenkt"
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Read Home Assistant states, calculate a target and optionally apply it."""
        room_temperature = _as_float(self._state(CONF_ROOM_TEMPERATURE_ENTITY))
        schedule_state = self._state(CONF_SCHEDULE_ENTITY)
        climate_state = self._state(CONF_CLIMATE_ENTITY)
        outdoor_temperature = _as_float(self._state(CONF_OUTDOOR_TEMPERATURE_ENTITY))

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
        window_id = self.config.get(CONF_WINDOW_ENTITY)
        if window_id:
            window_state = self.hass.states.get(window_id)
            if not self._valid(window_state):
                return self._waiting_result(
                    "Fensterkontakt nicht verfügbar – keine Sollwertänderung",
                    room_temperature,
                    outdoor_temperature,
                )
            window_open = window_state.state == "on"

        present, presence_status = self._evaluate_presence()
        if present is None:
            return self._waiting_result(presence_status, room_temperature, outdoor_temperature)

        comfort_temperature = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        eco_temperature = float(
            self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE)
        )
        schedule_active = schedule_state.state == "on"

        await self._learn(
            room_temperature,
            climate_state,
            window_open=window_open,
            present=present,
            schedule_active=schedule_active,
            eco_temperature=eco_temperature,
        )

        next_event = self._parse_next_event(schedule_state)
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
        )

        target_temperature = decision.target_temperature
        # Respect the temperature limits advertised by the thermostat.
        try:
            min_temp = float(climate_state.attributes.get("min_temp", target_temperature))
            max_temp = float(climate_state.attributes.get("max_temp", target_temperature))
            if min_temp <= max_temp:
                target_temperature = max(
                    min_temp, min(target_temperature, max_temp)
                )
        except (TypeError, ValueError):
            pass

        result: dict[str, Any] = {
            "status": decision.status,
            "mode": decision.mode,
            "target_temperature": target_temperature,
            "current_setpoint": self._climate_setpoint(climate_state),
            "room_temperature": room_temperature,
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
            "present": present,
            "presence_status": presence_status,
            "enabled": self.enabled,
            "decision_status": decision.status,
            "control_error": False,
        }

        if (
            self.enabled
            and target_temperature is not None
            and self._valid(climate_state)
        ):
            current_setpoint = climate_state.attributes.get("temperature")
            try:
                current_setpoint_value = float(current_setpoint)
            except (TypeError, ValueError):
                current_setpoint_value = None
            if (
                current_setpoint_value is None
                or abs(current_setpoint_value - target_temperature) >= 0.2
            ):
                try:
                    await self.hass.services.async_call(
                        "climate",
                        "set_temperature",
                        {
                            "entity_id": self.config[CONF_CLIMATE_ENTITY],
                            "temperature": round(target_temperature, 1),
                        },
                        blocking=True,
                    )
                except HomeAssistantError as err:
                    # Keep the coordinator healthy and retry on the next update.
                    _LOGGER.warning(
                        "Could not set target temperature %.1f for %s: %s",
                        target_temperature,
                        self.config[CONF_CLIMATE_ENTITY],
                        err,
                    )
                    result["control_error"] = True
                    result["status"] = (
                        "Thermostat konnte Sollwert nicht übernehmen – "
                        "erneuter Versuch beim nächsten Update"
                    )

        return result
