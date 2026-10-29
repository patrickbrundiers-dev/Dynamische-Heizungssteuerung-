"""Valve features: emergency program, child lock, offsets, maintenance, radiator test and the external temperature feed.

Part of the room coordinator (``DynamicHeatingCoordinator``); the
methods use its state and run exactly as they did inside it.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_MAINTENANCE_DURATION,
    CONF_MAINTENANCE_HOUR,
    CONF_MAINTENANCE_WEEKDAY,
    EXTERNAL_TEMPERATURE_PLATEAU_CHANGE,
    EXTERNAL_TEMPERATURE_PLATEAU_SECONDS,
    EXTERNAL_TEMPERATURE_PLATEAU_TOLERANCE,
    MAINTENANCE_ANY_DAY,
    VALVE_DIVERGENCE_MIN,
    VALVE_DIVERGENCE_SECONDS,
    VALVE_OFFSET_MAX,
    VALVE_OFFSET_MIN,
    CONF_EXTERNAL_TEMPERATURE,
    EXTERNAL_TEMPERATURE_MIN_CHANGE,
    EXTERNAL_TEMPERATURE_RESEND_SECONDS,
    EXTERNAL_TEMPERATURE_RETRIES,
    EXTERNAL_TEMPERATURE_RETRY_SECONDS,
    EXTERNAL_TEMPERATURE_VERIFY_SECONDS,
    EXTERNAL_TEMPERATURE_VERIFY_TOLERANCE,
    CONF_VALVE_FALLBACK,
    CONF_VALVE_SENSOR_CALIBRATION,
    DEFAULT_VALVE_FALLBACK,
    DEFAULT_VALVE_SENSOR_CALIBRATION,
    VALVE_SENSOR_CALIBRATION_INTERVAL,
    VALVE_SENSOR_CALIBRATION_WINDOW,
    HEAT_DEMAND_KEYS,
    CONF_VALVE_MAINTENANCE,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_ECO_TEMPERATURE,
    VALVE_MAINTENANCE_HOUR,
    VALVE_MAINTENANCE_INTERVAL_DAYS,
    VALVE_MAINTENANCE_PHASE_SECONDS,
)
from .logic import (
    external_temperature_due,
    schedule_comfort_temperature,
    valve_maintenance_due,
    valve_maintenance_phase,
)
from .radiator import (
    RADIATOR_TEST_SECONDS,
    radiator_test_verdict,
    SUPPLY_PARTLY,
    SUPPLY_WARM,
)
from .routine import (
    TUYA_DAYS,
    fallback_schedule,
    tuya_week_schedule,
)
from .room_util import (
    _LOGGER,
    _as_float,
    _as_number,
)


class ValveMixin:
    """Valve features."""

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
        key = (schedule_id, comfort, eco, self._levels_key())
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
                weekly, comfort, eco, step, schedule_comfort_temperature, self._block_level
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

    async def async_set_valve_offset(self, entity_id: str, offset: float) -> None:
        """Shift the setpoint of one valve against the others."""
        self.valve_offsets[entity_id] = max(
            VALVE_OFFSET_MIN, min(float(offset), VALVE_OFFSET_MAX)
        )
        self._written.pop(entity_id, None)
        await self.async_refresh()

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

    async def async_start_radiator_test(self) -> None:
        """Open the valves fully for a while and judge the radiators (button)."""
        if not self.enabled:
            raise ServiceValidationError(
                "Die Regelung ist aus – Heizkörpertest nur bei aktiver Regelung."
            )
        self._radiator_test_requested = True
        await self.async_refresh()

    def _valve_own_temperatures(self) -> dict[str, float | None]:
        """Valve -> its own (radiator-side) temperature, where there is one.

        A valve with a housing sensor reads that; one without uses its own
        reading, unless it is fed the room temperature.
        """
        sensors = self._radiator_sensors()
        feeding = bool(self.config.get(CONF_EXTERNAL_TEMPERATURE))
        values: dict[str, float | None] = {}
        for entity_id in self._thermostat_ids():
            if entity_id in self.skipped_valves:
                continue
            if entity_id in sensors:
                values[entity_id] = _as_float(self.hass.states.get(sensors[entity_id]))
            elif not feeding or self._external_temperature_entities(entity_id) is None:
                state = self.hass.states.get(entity_id)
                values[entity_id] = (
                    _as_number(state.attributes.get("current_temperature"))
                    if self._valid(state)
                    else None
                )
        return values

    async def _run_radiator_test(
        self, window_open: bool, result: dict[str, Any]
    ) -> bool:
        """Radiator test; True while it owns the valves."""
        now = dt_util.utcnow()
        room = result.get("room_temperature")
        if self._radiator_test is None:
            if not self._radiator_test_requested:
                return False
            self._radiator_test_requested = False
            if window_open:
                self.radiator_test_result = {
                    "at": now.isoformat(),
                    "code": "aborted",
                    "text": "Nicht gestartet: Fenster offen.",
                }
                result["radiator_test"] = self.radiator_test_result["text"]
                return False
            self._radiator_test = {
                "started": now,
                "valves": self._valve_own_temperatures(),
                "room": None if room is None else float(room),
            }
            self._log("Heizkörpertest gestartet")
        test = self._radiator_test
        elapsed = (now - test["started"]).total_seconds()
        if window_open or elapsed >= RADIATOR_TEST_SECONDS:
            await self._finish_radiator_test(now, room, aborted=window_open)
            result["radiator_test"] = self.radiator_test_result["text"]
            return False
        minutes = max(1, round((RADIATOR_TEST_SECONDS - elapsed) / 60))
        result["status"] = f"Heizkörpertest – Ventile offen, noch {minutes} min"
        result["radiator_test"] = f"Läuft, noch {minutes} min"
        for entity_id in self._thermostat_ids():
            state = self.hass.states.get(entity_id)
            if not self._valid(state) or state.state == "off":
                continue
            try:
                setpoint = float(state.attributes["max_temp"])
            except (KeyError, TypeError, ValueError):
                continue
            if not await self._write_setpoint(entity_id, state, setpoint, now):
                result["control_error"] = True
        return True

    async def _finish_radiator_test(
        self, now: datetime, room: float | None, *, aborted: bool
    ) -> None:
        test = self._radiator_test or {}
        self._radiator_test = None
        # Forget the test setpoints so they are not taken for manual changes.
        self._written.clear()
        self._skip_closed.clear()
        if aborted:
            self.radiator_test_result = {
                "at": now.isoformat(),
                "code": "aborted",
                "text": "Abgebrochen: Fenster geöffnet.",
            }
            self._log("Heizkörpertest abgebrochen")
            return
        start = test.get("valves") or {}
        end = self._valve_own_temperatures()
        rises = {
            self._friendly_name(entity_id): (
                None
                if start.get(entity_id) is None or end.get(entity_id) is None
                else round(end[entity_id] - start[entity_id], 1)
            )
            for entity_id in start
        }
        start_room = test.get("room")
        room_rise = (
            None if start_room is None or room is None else round(float(room) - start_room, 2)
        )
        house = self._house()
        others = [
            other.data.get("radiator_supply")
            for other in (house.rooms() if house is not None else [])
            if other is not self and other.data
        ]
        if SUPPLY_WARM in others or SUPPLY_PARTLY in others:
            boiler_warm: bool | None = True
        elif self.supply_profile.usually_off(dt_util.as_local(now).hour):
            boiler_warm = False
        else:
            boiler_warm = None
        code, text = radiator_test_verdict(rises, room_rise, boiler_warm)
        self.radiator_test_result = {
            "at": now.isoformat(),
            "code": code,
            "text": text,
            "valves": rises,
            "room_rise": room_rise,
        }
        self._log(f"Heizkörpertest: {text}")
        await self._push_room(f"Heizkörpertest {self.room_name}: {text}")

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
