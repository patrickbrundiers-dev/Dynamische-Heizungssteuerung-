"""House-wide mode (Zuhause, Abwesend, Urlaub) shared by all rooms."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CALENDAR_TEMPERATURE_KEY,
    CONF_HOUSE_CALENDAR,
    HOUSE_CALENDAR_COMFORT_KEYS,
    HOUSE_CALENDAR_SCHEDULE_KEYS,
    SCHEDULE_TEMPERATURE_ATTRIBUTE,
    CONF_NOTIFY_SERVICE,
    DOMAIN,
    REPORT_HOUR,
    REPORT_WEEKDAY,
    HOUSE_AWAY,
    HOUSE_HOME,
    HOUSE_MODES,
    HOUSE_VACATION,
    QUICK_AUTO,
)
from .logic import (
    calendar_temperature,
    description_value,
    is_on_word,
    schedule_comfort_temperature,
)

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .coordinator import DynamicHeatingCoordinator


class HouseManager:
    """Holds the house mode and the end of a vacation for every room."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.mode = HOUSE_HOME
        self.vacation_until: datetime | None = None
        self._store = Store(hass, 1, f"{DOMAIN}_house")
        self._listeners: list[Callable[[], None]] = []
        self._unsubs: list[Callable[[], None]] = []

    def rooms(self) -> list[DynamicHeatingCoordinator]:
        """All rooms that are set up right now."""
        from .coordinator import DynamicHeatingCoordinator

        return [
            value
            for value in self.hass.data.get(DOMAIN, {}).values()
            if isinstance(value, DynamicHeatingCoordinator)
        ]

    async def async_load(self) -> None:
        """Restore mode and vacation end, then watch for the vacation to end."""
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            if stored.get("mode") in HOUSE_MODES:
                self.mode = stored["mode"]
            raw = stored.get("vacation_until")
            parsed = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
            self.vacation_until = dt_util.as_utc(parsed) if parsed else None
        self._unsubs = [
            async_track_time_interval(
                self.hass, self._async_check_vacation, timedelta(minutes=1)
            ),
            async_track_time_change(
                self.hass, self._async_weekly, hour=REPORT_HOUR, minute=0, second=0
            ),
        ]
        await self._async_check_vacation()

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []

    async def _async_weekly(self, now: datetime) -> None:
        if dt_util.as_local(now).weekday() == REPORT_WEEKDAY:
            await self.async_send_report(reset=True)

    def _notify_service(self) -> str | None:
        """The house's notify service, else the first room's."""
        service = self.entry.options.get(CONF_NOTIFY_SERVICE)
        if service:
            return service
        for room in self.rooms():
            if room.config.get(CONF_NOTIFY_SERVICE):
                return room.config[CONF_NOTIFY_SERVICE]
        return None

    def report_text(self) -> str:
        labels = {HOUSE_HOME: "Zuhause", HOUSE_AWAY: "Abwesend", HOUSE_VACATION: "Urlaub"}
        lines = [room.week_summary() for room in sorted(
            self.rooms(), key=lambda room: room.room_name
        )]
        lines.append(f"Hausmodus: {labels.get(self.mode, self.mode)}")
        return "\n".join(lines)

    async def async_send_report(self, *, reset: bool) -> bool:
        """Push the weekly report; afterwards a new week starts if ``reset``."""
        service = (self._notify_service() or "").strip()
        sent = False
        if service and self.rooms():
            domain, _, name = service.partition(".")
            if not name:
                domain, name = "notify", domain
            try:
                await self.hass.services.async_call(
                    domain,
                    name,
                    {"title": "Wochenbericht Heizung", "message": self.report_text()},
                    blocking=True,
                )
                sent = True
            except HomeAssistantError as err:
                _LOGGER.warning("Weekly report could not be sent: %s", err)
        if reset:
            for room in self.rooms():
                room.reset_week()
        return sent

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    async def _async_changed(self) -> None:
        await self._store.async_save(
            {
                "mode": self.mode,
                "vacation_until": (
                    self.vacation_until.isoformat() if self.vacation_until else None
                ),
            }
        )
        for listener in list(self._listeners):
            listener()
        for room in self.rooms():
            await room.async_refresh()

    async def async_set_mode(self, mode: str) -> None:
        """Switch the house mode; leaving home resets hand-picked room modes."""
        if mode not in HOUSE_MODES:
            return
        if mode != HOUSE_HOME and mode != self.mode:
            for room in self.rooms():
                room.quick_mode = QUICK_AUTO
                room.quick_until = None
                room.boost_until = None
        for room in self.rooms():
            room._pending_source = "Hausmodus"
        self.mode = mode
        await self._async_changed()

    async def async_set_vacation_until(self, value: datetime | None) -> None:
        """Set when the vacation ends (and the house returns to Zuhause)."""
        self.vacation_until = dt_util.as_utc(value) if value is not None else None
        await self._async_changed()

    async def _async_check_vacation(self, _now: Any = None) -> None:
        """At the end of the vacation the house is back to Zuhause."""
        if (
            self.mode == HOUSE_VACATION
            and self.vacation_until is not None
            and dt_util.utcnow() >= self.vacation_until
        ):
            self.mode = HOUSE_HOME
            await self._async_changed()

    def calendar_overlay(
        self,
    ) -> tuple[str | None, str | None, bool, float | None, datetime | None] | None:
        """The running event of the house calendar, if any.

        Returns (event name, schedule it names, comfort time, temperature,
        end). A calendar's event names a schedule by its title or by
        ``zeitplan: <name>`` in the description; ``komfort: an`` or
        ``temperature: 21`` make it comfort time. A schedule helper carries
        the same keys in its block data.
        """
        entity_id = self.entry.options.get(CONF_HOUSE_CALENDAR)
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.state != "on":
            return None
        attributes = state.attributes
        if state.domain == "calendar":
            name = attributes.get("message")
            description = attributes.get("description")
            schedule = description_value(description, HOUSE_CALENDAR_SCHEDULE_KEYS)
            comfort_value = description_value(description, HOUSE_CALENDAR_COMFORT_KEYS)
            temperature = calendar_temperature(description, CALENDAR_TEMPERATURE_KEY)
            raw_end = attributes.get("end_time")
        else:
            name = attributes.get("friendly_name")
            lowered = {str(key).casefold(): value for key, value in attributes.items()}
            schedule = next(
                (str(lowered[key]) for key in HOUSE_CALENDAR_SCHEDULE_KEYS if key in lowered),
                None,
            )
            comfort_value = next(
                (lowered[key] for key in HOUSE_CALENDAR_COMFORT_KEYS if key in lowered),
                None,
            )
            temperature = schedule_comfort_temperature(
                attributes.get(SCHEDULE_TEMPERATURE_ATTRIBUTE)
            )
            raw_end = attributes.get("next_event")
        end = None
        if isinstance(raw_end, datetime):
            end = raw_end
        elif isinstance(raw_end, str):
            end = dt_util.parse_datetime(raw_end)
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=dt_util.get_default_time_zone())
        comfort = temperature is not None or is_on_word(comfort_value)
        return (
            str(name) if name else None,
            schedule,
            comfort,
            temperature,
            dt_util.as_utc(end) if end is not None else None,
        )

    @property
    def away(self) -> bool:
        return self.mode == HOUSE_AWAY

    def rooms_overview(self) -> list[dict[str, Any]]:
        """Short state of every room for the overview sensor and card."""
        overview = []
        for room in self.rooms():
            data = room.data or {}
            overview.append(
                {
                    "room": room.room_name,
                    "entry_id": room.entry_id,
                    "room_temperature": data.get("room_temperature"),
                    "target_temperature": data.get("target_temperature"),
                    "status": data.get("status"),
                    "mode": data.get("mode"),
                    "quick_mode": data.get("quick_mode"),
                    "enabled": room.enabled,
                    "problem": bool(
                        data.get("heating_problem") or data.get("thermostat_warnings")
                    ),
                }
            )
        return sorted(overview, key=lambda item: item["room"])
