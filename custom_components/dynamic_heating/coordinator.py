"""State collection, learning and guarded thermostat control."""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, State
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
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WINDOW_ENTITY,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_ECO_TEMPERATURE,
    DEFAULT_HEATING_RATE,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DOMAIN,
    MAX_LEARNED_HEATING_RATE,
    MIN_LEARNED_HEATING_RATE,
    MIN_SAMPLE_SECONDS,
)
from .logic import decide_heating_target

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
            update_interval=timedelta(minutes=1),
        )
        self.hass = hass
        self.config = config
        self.entry_id = entry_id
        self.enabled = False
        self.heating_rate = DEFAULT_HEATING_RATE
        self._store = Store(hass, 1, f"{DOMAIN}_{entry_id}_learning")
        self._sample_temperature: float | None = None
        self._sample_time: datetime | None = None

    async def async_load_learning(self) -> None:
        """Restore the learned heating rate after a Home Assistant restart."""
        stored = await self._store.async_load()
        if not isinstance(stored, dict):
            return
        try:
            rate = float(stored.get("heating_rate", DEFAULT_HEATING_RATE))
        except (TypeError, ValueError):
            return
        self.heating_rate = max(
            MIN_LEARNED_HEATING_RATE, min(rate, MAX_LEARNED_HEATING_RATE)
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

    async def _learn(self, room_temperature: float, climate_state: State | None) -> None:
        """Update the heating-rate estimate only during an observed heating phase."""
        attributes = climate_state.attributes if climate_state else {}
        setpoint = attributes.get("temperature")
        is_heating = attributes.get("hvac_action") == "heating"
        try:
            setpoint_value = float(setpoint)
        except (TypeError, ValueError):
            setpoint_value = None

        if (
            not is_heating
            or setpoint_value is None
            or room_temperature >= setpoint_value - 0.1
        ):
            self._sample_temperature = None
            self._sample_time = None
            return

        now = dt_util.utcnow()
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
            await self._store.async_save({"heating_rate": self.heating_rate})

        self._sample_temperature = room_temperature
        self._sample_time = now

    async def _async_update_data(self) -> dict[str, Any]:
        """Read Home Assistant states, calculate a target and optionally apply it."""
        room_state = self._state(CONF_ROOM_TEMPERATURE_ENTITY)
        room_temperature = _as_float(room_state)
        schedule_state = self._state(CONF_SCHEDULE_ENTITY)
        climate_state = self._state(CONF_CLIMATE_ENTITY)
        outdoor_temperature = _as_float(self._state(CONF_OUTDOOR_TEMPERATURE_ENTITY))

        if room_temperature is None:
            return {
                "status": "Temperatursensor nicht verfügbar",
                "mode": "waiting",
                "target_temperature": None,
                "room_temperature": None,
                "outdoor_temperature": outdoor_temperature,
                "heating_rate": self.heating_rate,
                "preheat_minutes": 0,
                "enabled": self.enabled,
            }

        if not self._valid(schedule_state):
            return {
                "status": "Zeitplan nicht verfügbar – keine Sollwertänderung",
                "mode": "waiting",
                "target_temperature": None,
                "room_temperature": room_temperature,
                "outdoor_temperature": outdoor_temperature,
                "heating_rate": self.heating_rate,
                "preheat_minutes": 0,
                "enabled": self.enabled,
            }

        window_open = False
        window_id = self.config.get(CONF_WINDOW_ENTITY)
        if window_id:
            window_state = self.hass.states.get(window_id)
            if not self._valid(window_state):
                return {
                    "status": "Fensterkontakt nicht verfügbar – keine Sollwertänderung",
                    "mode": "waiting",
                    "target_temperature": None,
                    "room_temperature": room_temperature,
                    "outdoor_temperature": outdoor_temperature,
                    "heating_rate": self.heating_rate,
                    "preheat_minutes": 0,
                    "enabled": self.enabled,
                }
            window_open = window_state.state == "on"

        present = True
        presence_id = self.config.get(CONF_PRESENCE_ENTITY)
        if presence_id:
            presence_state = self.hass.states.get(presence_id)
            if not self._valid(presence_state):
                return {
                    "status": "Anwesenheitssensor nicht verfügbar – keine Sollwertänderung",
                    "mode": "waiting",
                    "target_temperature": None,
                    "room_temperature": room_temperature,
                    "outdoor_temperature": outdoor_temperature,
                    "heating_rate": self.heating_rate,
                    "preheat_minutes": 0,
                    "enabled": self.enabled,
                }
            present = presence_state.state == "on"

        await self._learn(room_temperature, climate_state)

        next_event = self._parse_next_event(schedule_state)
        now = dt_util.now()
        decision = decide_heating_target(
            now=now,
            schedule_active=schedule_state.state == "on",
            next_event=next_event,
            room_temperature=room_temperature,
            outdoor_temperature=outdoor_temperature,
            comfort_temperature=float(
                self.config.get(
                    CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE
                )
            ),
            eco_temperature=float(
                self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE)
            ),
            heating_rate_c_per_hour=self.heating_rate,
            max_preheat_minutes=int(
                self.config.get(
                    CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES
                )
            ),
            window_open=window_open,
            present=present,
        )

        target_temperature = decision.target_temperature
        if target_temperature is not None and self._valid(climate_state):
            # Respect the temperature limits advertised by the thermostat.
            try:
                min_temp = float(
                    climate_state.attributes.get("min_temp", target_temperature)
                )
                max_temp = float(
                    climate_state.attributes.get("max_temp", target_temperature)
                )
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
            "room_temperature": room_temperature,
            "outdoor_temperature": outdoor_temperature,
            "heating_rate": self.heating_rate,
            "preheat_minutes": decision.preheat_minutes,
            "schedule_active": schedule_state.state == "on",
            "next_event": next_event.isoformat() if next_event else None,
            "window_open": window_open,
            "present": present,
            "enabled": self.enabled,
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
                await self.hass.services.async_call(
                    "climate",
                    "set_temperature",
                    {
                        "entity_id": self.config[CONF_CLIMATE_ENTITY],
                        "temperature": round(target_temperature, 1),
                    },
                    blocking=True,
                )

        return result
