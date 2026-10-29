"""Window and door contacts, the temperature-drop detection and the valves' own window detection.

Part of the room coordinator (``DynamicHeatingCoordinator``); the
methods use its state and run exactly as they did inside it.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DOOR_CLOSE_DELAY,
    CONF_DOOR_ENTITIES,
    CONF_DOOR_OPEN_DELAY,
    CONF_ZONE_WINDOW_CLOSE_DELAY,
    CONF_ZONE_WINDOW_ENTITIES,
    CONF_ZONE_WINDOW_OPEN_DELAY,
    DEFAULT_DOOR_CLOSE_DELAY,
    DEFAULT_DOOR_OPEN_DELAY,
    DEFAULT_ZONE_WINDOW_CLOSE_DELAY,
    DEFAULT_ZONE_WINDOW_OPEN_DELAY,
    CONF_ADDITIONAL_WINDOW_ENTITIES,
    CONF_DISABLE_TRV_WINDOW_DETECTION,
    TRV_WINDOW_DETECTION_SUFFIX,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_DROP_DETECTION,
    CONF_WINDOW_ENTITY,
    WINDOW_DROP_DEGREES,
    WINDOW_DROP_HOLD_SECONDS,
    WINDOW_DROP_SECONDS,
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
)
from .logic import (
    evaluate_window_open,
    detect_temperature_drop,
)
from .room_util import _LOGGER


class WindowMixin:
    """Window and door contacts, the temperature-drop detection and the valves' own window detection."""

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
