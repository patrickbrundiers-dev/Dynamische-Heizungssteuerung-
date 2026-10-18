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
    QUICK_MORNING_HOUR,
    QUICK_SLEEP,
)
from .pending_push import hold_if_missing
from .radiator import (
    SUPPLY_COLD,
    SUPPLY_VERSION,
    SUPPLY_WARM,
    SupplyProfile,
    house_supply,
)
from .logic import (
    calendar_temperature,
    description_value,
    is_on_word,
    schedule_comfort_temperature,
)

_LOGGER = logging.getLogger(__name__)

# The boiler has to stay cold this long before the house says so.
SUPPLY_NOTIFY_AFTER = timedelta(minutes=60)
# No push about the boiler at night: a pause then is common and a push would
# only wake someone; still cold in the morning, it is told then.
SUPPLY_QUIET_FROM = 22
SUPPLY_QUIET_UNTIL = 7

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
        # When the central heating delivers, learned from all rooms together
        # (there is one boiler for the whole house; persisted).
        self.supply = SupplyProfile()
        self.supply_state: str | None = None
        self._supply_at: datetime | None = None
        self._cold_since: datetime | None = None
        self._cold_sent = False

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
            if stored.get("supply_version") == SUPPLY_VERSION:
                self.supply = SupplyProfile.from_list(stored.get("supply_profile"))
        self._unsubs = [
            async_track_time_interval(
                self.hass, self._async_observe_supply, timedelta(minutes=1)
            ),
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
            data = {"title": "Wochenbericht Heizung", "message": self.report_text()}
            try:
                if not hold_if_missing(self.hass, domain, name, data):
                    await self.hass.services.async_call(
                        domain, name, data, blocking=True
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

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "mode": self.mode,
                "vacation_until": (
                    self.vacation_until.isoformat() if self.vacation_until else None
                ),
                "supply_profile": self.supply.as_list(),
                "supply_version": SUPPLY_VERSION,
            }
        )

    def supply_verdict(self, overrides: dict[str, str | None] | None = None) -> str | None:
        """Does the central heating deliver right now, judged by all rooms?

        ``overrides`` holds a room's verdict of the running cycle (entry id ->
        verdict), which is newer than the room's last data.
        """
        verdicts = dict(overrides or {})
        for room in self.rooms():
            if room.entry_id not in verdicts and room.enabled and room.data:
                # Only rooms asking for heat tell about the boiler.
                verdicts[room.entry_id] = room.data.get(
                    "supply_judged", room.data.get("radiator_supply")
                )
        return house_supply(list(verdicts.values()))

    def supply_profile(self) -> SupplyProfile | None:
        """The house's learned delivery hours, once it knows any."""
        return self.supply if self.supply.known else None

    async def _async_observe_supply(self, _now: Any = None) -> None:
        """Learn the boiler's hours and tell once when it delivers nothing."""
        if not self.supply.known:
            # Start from what the rooms learned on their own.
            for room in self.rooms():
                self.supply.merge(room.supply)
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        verdict = self.supply_verdict()
        changed = verdict != self.supply_state
        self.supply_state = verdict
        seconds = 0.0 if self._supply_at is None else (now - self._supply_at).total_seconds()
        self._supply_at = now
        if self.supply.observe(local.hour, verdict, seconds):
            await self._async_save()
        await self._notify_supply(verdict, now)
        if changed:
            for listener in list(self._listeners):
                listener()

    def supply_text(self) -> str:
        """The central heating's state in a few words."""
        state = self.supply_state
        hour = dt_util.now().hour
        if state == SUPPLY_WARM:
            return "Liefert Wärme"
        if state == SUPPLY_COLD:
            text = "Liefert keine Wärme"
            if self.supply.usually_off(hour):
                next_hour = self.supply.next_on_hour(hour)
                text += (
                    f" (um diese Zeit üblich, meist ab {next_hour}:00 Uhr)"
                    if next_hour is not None
                    else " (um diese Zeit üblich)"
                )
            return text
        if state == "waiting":
            return "Heizkörper werden warm"
        if state == "idle":
            return "Kein Heizbedarf"
        return "Unbekannt"

    async def _notify_supply(self, verdict: str | None, now: datetime) -> None:
        """One push for the whole house when the boiler delivers nothing."""
        if verdict != SUPPLY_COLD:
            if self._cold_sent and verdict == SUPPLY_WARM:
                await self._push("Die Zentralheizung liefert wieder Wärme.")
            if verdict != "waiting":
                self._cold_since = None
                self._cold_sent = False
            return
        if self._cold_since is None:
            self._cold_since = now
        if self._cold_sent or (now - self._cold_since) < SUPPLY_NOTIFY_AFTER:
            return
        hour = dt_util.as_local(now).hour
        if self.supply.usually_off(hour):
            return
        if hour >= SUPPLY_QUIET_FROM or hour < SUPPLY_QUIET_UNTIL:
            return
        since = dt_util.as_local(self._cold_since).strftime("%H:%M")
        self._cold_sent = await self._push(
            "Die Zentralheizung liefert keine Wärme: in keinem Raum werden die "
            f"Heizkörper warm (seit {since} Uhr), obwohl die Ventile offen sind. "
            "Therme prüfen (aus, Absenkung oder Störung)."
        )

    async def _push(self, message: str) -> bool:
        service = (self._notify_service() or "").strip()
        if not service:
            return False
        domain, _, name = service.partition(".")
        if not name:
            domain, name = "notify", domain
        data = {"title": "Heizung Haus", "message": message}
        if hold_if_missing(self.hass, domain, name, data):
            return True
        try:
            await self.hass.services.async_call(domain, name, data, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("House notification could not be sent: %s", err)
            return False
        return True

    async def _async_changed(self) -> None:
        await self._async_save()
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

    async def async_good_night(self) -> list[str]:
        """"Gute Nacht": rooms in comfort time go to night setback now.

        Each such room sleeps until its comfort block ends; from there the
        schedule goes on as usual (eco, preheating in the morning). Rooms
        outside comfort time stay as they are, so no preheating is lost.
        Returns the names of the rooms that were lowered.
        """
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        morning = local.replace(
            hour=QUICK_MORNING_HOUR, minute=0, second=0, microsecond=0
        )
        if morning <= local:
            morning += timedelta(days=1)
        lowered = []
        for room in self.rooms():
            data = room.data or {}
            if not room.enabled or not data.get("schedule_active"):
                continue
            end = room._next_event
            room.boost_until = None
            room.quick_mode = QUICK_SLEEP
            room.quick_until = (
                end if end is not None and end > now else dt_util.as_utc(morning)
            )
            room._pending_source = "Gute Nacht"
            lowered.append(room.room_name)
        for room in self.rooms():
            if room.room_name in lowered:
                await room.async_refresh()
        return sorted(lowered)

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
