"""Side observations: weekly report, batteries, showers, airing, data quality and habits.

Part of the room coordinator (``DynamicHeatingCoordinator``); the
methods use its state and run exactly as they did inside it.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ROOM_MODEL,
    DEFAULT_ROOM_MODEL,
    CONF_HUMIDITY_ENTITY,
    HUMIDITY_HYSTERESIS,
    AIRING_HUMIDITY_PERCENT,
    AIRING_MIN_DIFFERENCE,
    CONF_OUTDOOR_HUMIDITY_ENTITY,
    LOW_BATTERY_PERCENT,
    BATTERY_HISTORY_DAYS,
    DATA_STALE_SECONDS,
    DATA_VALVE_STALE_SECONDS,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_SHOWER_LEARNING,
    DEFAULT_SHOWER_LEARNING,
    SHOWER_RISE_PERCENT,
    SHOWER_RISE_WINDOW_SECONDS,
    SHOWER_COOLDOWN_SECONDS,
    SHOWER_MODEL_PAUSE_SECONDS,
    SHOWER_HISTORY_DAYS,
    SHOWER_LEAD_MINUTES,
)
from .logic import (
    airing_advice,
    data_quality,
    source_quality,
)
from .radiator import SUPPLY_COLD
from .routine import (
    HABIT_DAYS,
    ShowerWatch,
    schedule_covers,
    showers_from_history,
)
from .room_util import (
    _LOGGER,
    _as_float,
    _as_number,
    _de_number,
)


class InsightsMixin:
    """Side observations."""

    @staticmethod
    def _empty_week() -> dict[str, Any]:
        return {
            "since": dt_util.utcnow().isoformat(),
            "heating_s": 0.0,
            "temperature_sum": 0.0,
            "temperature_s": 0.0,
            "window_events": 0,
            "alerts": 0,
            # Radiators cold although heat was asked for.
            "no_heat_s": 0.0,
            # Room minus outdoor temperature over time, actual and as if the
            # room had been held at comfort: heat loss follows it.
            "loss_actual": 0.0,
            "loss_comfort": 0.0,
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
        if result.get("radiator_supply") == SUPPLY_COLD:
            self._week["no_heat_s"] += seconds
        outdoor = result.get("outdoor_temperature")
        comfort = result.get("comfort_temperature")
        if (
            self.enabled
            and result.get("heating_season", True)
            and room is not None
            and outdoor is not None
            and comfort is not None
            and float(comfort) > float(outdoor)
        ):
            self._week["loss_actual"] += max(0.0, float(room) - float(outdoor)) * seconds
            self._week["loss_comfort"] += (float(comfort) - float(outdoor)) * seconds
        window = bool(result.get("window_open")) and result.get("heating_season", True)
        if window and not self._week_window:
            self._week["window_events"] += 1
        self._week_window = window

    def week_summary(self) -> str:
        """One line for the weekly report."""
        week = self._week
        hours = week["heating_s"] / 3600
        parts = [f"{hours:.0f} h geheizt".replace(".", ",")]
        today = dt_util.now().date()
        energy = self.heat_stats.energy_between(today - timedelta(days=6), today)
        if energy >= 0.5:
            parts.append(f"ca. {energy:.0f} kWh Wärme (geschätzt)")
        if week["temperature_s"]:
            average = week["temperature_sum"] / week["temperature_s"]
            parts.append(f"Ø {average:.1f} °C".replace(".", ","))
        if week["loss_comfort"] > 0:
            saving = 1 - week["loss_actual"] / week["loss_comfort"]
            if saving >= 0.01:
                parts.append(f"ca. {saving:.0%} weniger Wärme als bei Dauer-Komfort")
        if week["no_heat_s"] >= 1800:
            parts.append(
                f"{week['no_heat_s'] / 3600:.0f} h Heizkörper kalt trotz Heizbedarf"
            )
        if week["window_events"]:
            parts.append(f"{week['window_events']}× Fenster offen beim Heizen")
        if week["alerts"]:
            parts.append(
                f"{week['alerts']} Meldung" + ("en" if week["alerts"] > 1 else "")
            )
        model = self.room_model
        if model.trusted and model.horizon_error is not None:
            parts.append(
                "Raummodell liegt über 3 Stunden im Schnitt "
                f"{_de_number(model.horizon_error)} °C daneben"
            )
        elif model.trusted and model.mean_error is not None:
            parts.append(
                f"Raummodell liegt im Schnitt {model.mean_error:.2f} °C/h daneben"
                .replace(".", ",")
            )
        elif self.config.get(CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL):
            parts.append(f"Raummodell lernt noch ({model.samples} h)")
        return f"{self.room_name}: " + ", ".join(parts)

    def reset_week(self) -> None:
        self._week = self._empty_week()
        self._week_saved_at = None
        self._save_runtime_state()

    def _battery_entities(self) -> dict[str, str]:
        """Battery level sensors on the devices of the room's valves and room
        sensor (entity id -> name)."""
        registry = er.async_get(self.hass)
        sources = list(self._thermostat_ids())
        if room_sensor := self.config.get(CONF_ROOM_TEMPERATURE_ENTITY):
            sources.append(room_sensor)
        found: dict[str, str] = {}
        for source in sources:
            entry = registry.async_get(source)
            if entry is None or not entry.device_id:
                continue
            for device_entry in er.async_entries_for_device(registry, entry.device_id):
                if device_entry.domain != "sensor":
                    continue
                state = self.hass.states.get(device_entry.entity_id)
                # The registry keeps the class while the sensor is unavailable.
                device_class = (
                    device_entry.device_class
                    or device_entry.original_device_class
                    or (state.attributes.get("device_class") if state else None)
                )
                if device_class != "battery":
                    continue
                found[device_entry.entity_id] = str(
                    (state.attributes.get("friendly_name") if state else None)
                    or device_entry.entity_id
                )
        return found

    def _observe_batteries(self, result: dict[str, Any]) -> bool:
        """Battery levels and when each will need changing; True when the
        stored history changed."""
        entities = self._battery_entities()
        changed = bool(set(self.batteries.days) - set(entities))
        self.batteries.forget_others(set(entities))
        today = dt_util.now().date()
        batteries = []
        for entity_id, name in sorted(entities.items()):
            level = _as_float(self.hass.states.get(entity_id))
            if level is not None and 0 <= level <= 100:
                changed = self.batteries.observe(entity_id, today, level) or changed
            batteries.append(
                {
                    "entity_id": entity_id,
                    "name": name,
                    "level": level,
                    "days_left": self.batteries.days_left(
                        entity_id, today, LOW_BATTERY_PERCENT
                    ),
                }
            )
        result["batteries"] = batteries
        if any(entity_id not in self.batteries.seeded for entity_id in entities) and (
            self._battery_seed_at is None
            or (dt_util.utcnow() - self._battery_seed_at).total_seconds() >= 3600
        ):
            # A valve that shows up after the start gets its history too.
            self._battery_seed_at = dt_util.utcnow()
            self.hass.async_create_task(self.async_seed_batteries())
        result["battery_days_left"] = min(
            (item["days_left"] for item in batteries if item["days_left"] is not None),
            default=None,
        )
        return changed

    async def async_seed_batteries(self) -> None:
        """Battery levels of the last months from the recorder, once per
        battery, so the forecast does not wait weeks."""
        self._battery_seed_at = dt_util.utcnow()
        entity_ids = [
            entity_id
            for entity_id in self._battery_entities()
            if entity_id not in self.batteries.seeded
        ]
        if not entity_ids or "recorder" not in self.hass.config.components:
            return
        from homeassistant.components.recorder import get_instance, history
        from homeassistant.components.recorder.statistics import (
            statistics_during_period,
        )

        end = dt_util.utcnow()
        start = end - timedelta(days=BATTERY_HISTORY_DAYS)
        recorder = get_instance(self.hass)
        try:
            # Long-term statistics outlive the recorder's few days of states.
            daily = await recorder.async_add_executor_job(
                statistics_during_period,
                self.hass,
                start,
                end,
                set(entity_ids),
                "day",
                None,
                {"min"},
            )
            missing = [entity_id for entity_id in entity_ids if not daily.get(entity_id)]
            states = (
                await recorder.async_add_executor_job(
                    history.get_significant_states,
                    self.hass,
                    start,
                    end,
                    missing,
                    None,
                    True,
                    False,
                    False,
                    True,
                )
                if missing
                else {}
            )
        except Exception:  # noqa: BLE001 - history is a bonus, never fatal
            _LOGGER.debug("Battery history not available", exc_info=True)
            return
        for entity_id in entity_ids:
            # What was seen live already goes on top of the recorder's days.
            live = self.batteries.days.pop(entity_id, [])
            readings: list[tuple[date, float | None]] = [
                (
                    dt_util.as_local(dt_util.utc_from_timestamp(row["start"])).date(),
                    _as_number(row.get("min")),
                )
                for row in daily.get(entity_id, [])
            ] + [
                (dt_util.as_local(state.last_changed).date(), _as_float(state))
                for state in states.get(entity_id, [])
                if isinstance(state, State)
            ]
            for day, level in readings:
                if level is not None and 0 <= level <= 100:
                    self.batteries.observe(entity_id, day, level)
            for day, level in live:
                self.batteries.observe(entity_id, date.fromisoformat(day), level)
            self.batteries.seeded.add(entity_id)
        await self._save_learning()

    def _shower_suggestions(self, now: datetime) -> list[dict]:
        """Usual shower times that the schedule does not warm the room for."""
        if not self.config.get(CONF_SHOWER_LEARNING, DEFAULT_SHOWER_LEARNING):
            return []

        profile = self.supply_profile

        def lead_start(minute: int) -> tuple[int, int | None]:
            """Comfort start for a shower at ``minute``, and the hour the
            boiler starts when it is later than the usual lead (heating
            earlier would be in vain)."""
            start = (minute - SHOWER_LEAD_MINUTES) % (24 * 60)
            if not profile.usually_off(start // 60):
                return start, None
            on_hour = profile.next_on_hour(start // 60)
            if on_hour is None or not start < on_hour * 60 <= minute:
                return start, None
            return on_hour * 60, on_hour

        def describe(when: str, clock: str, _label: str, days: int) -> str:
            hour, minute = (int(part) for part in clock.split(":"))
            start, on_hour = lead_start(hour * 60 + minute)
            text = (
                f"{when} gegen {clock} Uhr wird geduscht ({days}× in "
                f"{HABIT_DAYS // 7} Wochen) – Komfort im Bad ab "
                f"{start // 60:02d}:{start % 60:02d} Uhr in den Zeitplan?"
            )
            if on_hour is not None:
                text += f" (die Zentralheizung liefert erst ab {on_hour}:00 Uhr)"
            return text

        weekly = self._schedule_weekly.get(self.config.get(CONF_SCHEDULE_ENTITY) or "")
        return [
            item
            for item in self.showers.suggestions(now, describe)
            if not schedule_covers(
                weekly, item["weekend"], lead_start(item["minute"])[0]
            )
        ]

    def _observe_shower(self, result: dict[str, Any]) -> bool:
        """A shower in the room's humidity; True when one was seen."""
        result["shower_until"] = (
            self._shower_until.isoformat() if self._shower_until else None
        )
        if not self.config.get(CONF_SHOWER_LEARNING, DEFAULT_SHOWER_LEARNING):
            return False
        humidity = _as_float(self._state(CONF_HUMIDITY_ENTITY))
        if humidity is None:
            return False
        now = dt_util.utcnow()
        if not self._shower_watch.observe(now.timestamp(), humidity):
            return False
        self.showers.record(dt_util.now(), "shower", "Duschen")
        self._shower_until = now + timedelta(seconds=SHOWER_MODEL_PAUSE_SECONDS)
        self._habits_at = None
        result["shower_until"] = self._shower_until.isoformat()
        self._log("Duschen erkannt (Luftfeuchte steigt schnell)")
        return True

    async def async_seed_showers(self) -> None:
        """Showers of the last days from the recorder, once."""
        humidity_id = self.config.get(CONF_HUMIDITY_ENTITY)
        if (
            self._showers_seeded
            or not humidity_id
            or not self.config.get(CONF_SHOWER_LEARNING, DEFAULT_SHOWER_LEARNING)
            or "recorder" not in self.hass.config.components
        ):
            return
        from homeassistant.components.recorder import get_instance, history

        end = dt_util.utcnow()
        start = end - timedelta(days=SHOWER_HISTORY_DAYS)
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start,
                end,
                [humidity_id],
                None,
                True,
                False,
                False,
                True,
            )
        except Exception:  # noqa: BLE001 - history is a bonus, never fatal
            _LOGGER.debug("Humidity history not available", exc_info=True)
            return
        readings = []
        for state in states.get(humidity_id, []):
            if not isinstance(state, State):
                continue
            try:
                readings.append((state.last_changed.timestamp(), float(state.state)))
            except (TypeError, ValueError):
                continue
        watch = ShowerWatch(
            SHOWER_RISE_PERCENT, SHOWER_RISE_WINDOW_SECONDS, SHOWER_COOLDOWN_SECONDS
        )
        found = showers_from_history(watch, readings, end.timestamp())
        for at in found:
            self.showers.record(
                dt_util.as_local(dt_util.utc_from_timestamp(at)), "shower", "Duschen"
            )
        self._showers_seeded = True
        self._habits_at = None
        if found:
            self._log(f"{len(found)}× Duschen aus dem Verlauf erkannt")
        await self._save_learning()

    def _outdoor_humidity(self) -> float | None:
        """Outdoor humidity in %: own sensor, else the weather entity's."""
        value = _as_float(self._state(CONF_OUTDOOR_HUMIDITY_ENTITY))
        if value is None:
            weather_id = self.config.get(CONF_WEATHER_ENTITY)
            weather = self.hass.states.get(weather_id) if weather_id else None
            if self._valid(weather):
                try:
                    value = float(weather.attributes.get("humidity"))
                except (TypeError, ValueError):
                    value = None
        if value is None or not math.isfinite(value) or not 0 < value <= 100:
            return None
        return value

    def _data_sources(self) -> list[tuple[str, str, float | None]]:
        """Every source the room reads, with how fresh it is."""
        now = dt_util.utcnow()
        sources: list[tuple[str, str, float | None]] = []

        def add(name: str, entity_id: str | None, max_age: float | None) -> None:
            if not entity_id:
                return
            state = self.hass.states.get(entity_id)
            age = None
            if state is not None:
                reported = getattr(state, "last_reported", None) or state.last_updated
                age = (now - reported).total_seconds()
            sources.append(
                (name, source_quality(self._valid(state), age, max_age), age)
            )

        add("Raumfühler", self.config.get(CONF_ROOM_TEMPERATURE_ENTITY), DATA_STALE_SECONDS)
        add(
            "Außentemperatur",
            self.config.get(CONF_OUTDOOR_TEMPERATURE_ENTITY),
            DATA_STALE_SECONDS,
        )
        add("Wettervorhersage", self.config.get(CONF_WEATHER_ENTITY), DATA_STALE_SECONDS)
        add("Feuchte", self.config.get(CONF_HUMIDITY_ENTITY), DATA_STALE_SECONDS)
        add(
            "Außenfeuchte",
            self.config.get(CONF_OUTDOOR_HUMIDITY_ENTITY),
            DATA_STALE_SECONDS,
        )
        for entity_id in self._thermostat_ids():
            if entity_id not in self.skipped_valves:
                add(self._friendly_name(entity_id), entity_id, DATA_VALVE_STALE_SECONDS)
        contacts = {
            entity_id
            for _key, ids, _door, _open, _close in self._contact_groups()
            for entity_id in ids
        }
        for entity_id in sorted(contacts):
            # Contacts report only when they change: only availability counts.
            add(self._friendly_name(entity_id), entity_id, None)
        for entity_id in self._people():
            add(self._friendly_name(entity_id), entity_id, None)
        return sources

    def _update_data_quality(self, result: dict[str, Any]) -> None:
        """Datenqualität: does every source of the room still report?"""
        quality = data_quality(self._data_sources())
        result["data_quality"] = quality["state"]
        result["data_quality_problems"] = quality["problems"]
        result["data_quality_sources"] = quality["sources"]

    def _update_airing(self, result: dict[str, Any]) -> None:
        """Airing advice from indoor and outdoor humidity (display only)."""
        humidity = _as_float(self._state(CONF_HUMIDITY_ENTITY))
        room = result.get("room_temperature")
        if humidity is not None and not 0 < humidity <= 100:
            humidity = None
        # Once humid, the room counts as humid until 5 points below the limit.
        limit = AIRING_HUMIDITY_PERCENT - (
            HUMIDITY_HYSTERESIS
            if self._airing_state in ("helps", "useless", "unknown")
            else 0
        )
        advice = airing_advice(
            None if room is None or result.get("room_temperature_source") != "sensor"
            else float(room),
            humidity,
            result.get("outdoor_temperature"),
            self._outdoor_humidity(),
            humid_percent=limit,
            min_difference=AIRING_MIN_DIFFERENCE,
        )
        self._airing_state = None if advice is None else advice["state"]
        result["airing"] = None if advice is None else advice["text"]
        result["airing_details"] = advice

    def _record_habit(self, mode: str, label: str) -> None:
        """Remember a mode picked by hand, for schedule suggestions."""
        self.habits.record(dt_util.now(), mode, label)
        self._habits_at = None
        self.hass.async_create_task(self._save_learning())

    def _update_habits(self, result: dict[str, Any]) -> str | None:
        """Schedule suggestions from repeated hand picks; a new one to push."""
        now = dt_util.now()
        if self._habits_at is None or now - self._habits_at >= timedelta(hours=1):
            self._habits_at = now
            self._habit_suggestions = (
                self.habits.suggestions(now) + self._shower_suggestions(now)
            )
        suggestions = self._habit_suggestions
        result["schedule_suggestion"] = (
            suggestions[0]["text"] if suggestions else "Keine Vorschläge"
        )
        result["schedule_suggestions"] = [item["text"] for item in suggestions]
        for item in suggestions:
            if item["key"] not in self.habits.notified:
                self.habits.notified.append(item["key"])
                return str(item["text"])
        return None
