"""Telling people: pushes, morning report, alerts, actions on notifications, foreign control, device triggers and the self-test.

Part of the room coordinator (``DynamicHeatingCoordinator``); the
methods use its state and run exactly as they did inside it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HUMIDITY_ENTITY,
    EVENT_DEVICE_TRIGGER,
    HUMIDITY_HIGH_PERCENT,
    HUMIDITY_HYSTERESIS,
    TARGET_REACHED_MARGIN,
    TRIGGER_HEATING_STARTED,
    TRIGGER_HEATING_STOPPED,
    TRIGGER_HUMIDITY_HIGH,
    TRIGGER_PREHEAT_STARTED,
    TRIGGER_TARGET_REACHED,
    TRIGGER_WINDOW_CLOSED,
    TRIGGER_WINDOW_OPENED,
    EVENT_MODE_CHANGED,
    CONF_EXTERNAL_TEMPERATURE,
    THERMOSTAT_UNREACHABLE_GRACE_SECONDS,
    IGNORED_PROBLEM_ENTITY_SUFFIXES,
    LOW_BATTERY_PERCENT,
    CONF_NOTIFY_AWAY,
    CONF_MORNING_REPORT,
    DEFAULT_NOTIFY_AWAY,
    DEFAULT_MORNING_REPORT,
    MORNING_REPORT_HOUR,
    MORNING_REPORT_SHORTFALL,
    NOTIFY_ACTION_PREFIX,
    NOTIFY_AWAY_SECONDS,
    NOTIFY_SNOOZE_SECONDS,
    CONF_NOTIFY_SERVICE,
    NOTIFY_FROST_FALLBACK_TEMPERATURE,
    NOTIFY_FROST_MARGIN,
    NOTIFY_PROBLEM_DELAY_SECONDS,
    NOTIFY_WINDOW_SECONDS,
    QUICK_HOME,
    CONF_FROST_PROTECTION_TEMPERATURE,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
    FOREIGN_CONTROL_NOTIFY_SECONDS,
)
from .logic import data_quality
from .radiator import (
    SUPPLY_COLD,
    SUPPLY_PARTLY,
    SUPPLY_WARM,
)
from .room_util import (
    SELFTEST_RETRY,
    SELFTEST_VALVE_TOLERANCE,
    _LOGGER,
    _PREHEAT_MODES,
    _as_float,
    foreign_source,
    _foreign_issue_id,
)


class NotifyMixin:
    """Telling people."""

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
        from .coordinator import DynamicHeatingCoordinator

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
        from .coordinator import DynamicHeatingCoordinator

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
            "preheat": (
                result.get("mode") in _PREHEAT_MODES if self.enabled else None
            ),
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
            "preheat": (TRIGGER_PREHEAT_STARTED, None),
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
        quality = data_quality(self._data_sources())
        if quality["state"] is not None:
            add(
                "Datenqualität",
                not quality["problems"],
                "; ".join(quality["problems"]) or "alle Quellen melden",
            )
        add(
            "Raummodell",
            None,
            "bereit" if self.room_model.ready else
            f"lernt noch ({self.room_model.samples} Stunden)",
        )
        return checks

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
