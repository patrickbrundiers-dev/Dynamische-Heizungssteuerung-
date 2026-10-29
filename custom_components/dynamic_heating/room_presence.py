"""Who is home and in the room: people, proximity, the room's own sensors, homecoming and comfort by use.

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
    CONF_LEARN_USAGE,
    CONF_ROOM_EMPTY_GRACE,
    DEFAULT_LEARN_USAGE,
    DEFAULT_ROOM_EMPTY_GRACE,
    CONF_HOMECOMING_PREHEAT,
    DEFAULT_HOMECOMING_PREHEAT,
    HOMECOMING_HOLD_MINUTES,
    HOMECOMING_HISTORY_DAYS,
    OCCUPANCY_EXTEND_MAX_SECONDS,
    OCCUPANCY_HOLD_SECONDS,
    OCCUPANCY_UNUSED_SECONDS,
    CONF_OCCUPANCY_ENTITY,
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
    DEFAULT_ENTER_HOME_DURATION,
    DEFAULT_LEAVING_HOME_DURATION,
    PREHEAT_LEAVE_GRACE_SECONDS,
    DEFAULT_PROXIMITY_DURATION,
    DEFAULT_PROXIMITY_DISTANCE,
    DEFAULT_PROXIMITY_MAX_AGE,
    DEFAULT_PRESENCE_ON_DURATION,
    DEFAULT_PRESENCE_OFF_DURATION,
)
from .logic import (
    HeatingDecision,
    calculate_lead_minutes,
    model_lead_minutes,
)
from .model import ModelView
from .radiator import SUPPLY_WARM
from .routine import homecomings_from_history
from .room_util import (
    _LOGGER,
    _INVALID_STATES,
    _as_float,
)


class PresenceMixin:
    """Who is home and in the room."""

    def _left_home_within(
        self, entity_id: str, state: State, now: datetime, delay_seconds: int
    ) -> bool:
        """True while a person left home less than ``delay_seconds`` ago."""
        if delay_seconds <= 0:
            return False
        seen = self._seen_home.get(entity_id)
        if seen is not None:
            gone = (now - seen).total_seconds()
        elif state.state == "not_home":
            # Not seen at home since the start: the state's age tells.
            gone = (now - state.last_changed).total_seconds()
        else:
            return False
        return gone < delay_seconds

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

    def _record_proximity_category(self, category: str, key: str = "") -> None:
        """Count only changes between meaningful geofence states.

        Per source: with two people in the zone their states differ, and one
        shared state counted every cycle as a change (2526 "stale" events).
        """
        if category == self._proximity_categories.get(key):
            return
        self._proximity_categories[key] = category
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
            self._record_proximity_category("invalid", key)
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
            self._record_proximity_category("stale", key)
            return (
                None,
                # No age in the text: a status that changes every minute
                # fills the history; the age has its own sensor.
                "Standortdaten veraltet – Proximity wird nicht für Anfahrt "
                "verwendet",
            )

        legacy_direction = distance_state.attributes.get("dir_of_travel")
        if distance_state.domain == "proximity" or legacy_direction is not None:
            raw_direction = legacy_direction
        elif direction_state is not None and self._valid(direction_state):
            raw_direction = direction_state.state
        elif self.config.get(CONF_PROXIMITY_DIRECTION_ENTITY):
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Richtung nicht verfügbar"
        else:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Richtung fehlt: bitte Richtungssensor auswählen"

        direction = str(raw_direction or "").strip().lower()
        self._proximity_direction = direction or None
        if direction == "unknown" or direction in _INVALID_STATES or not direction:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Richtung ist unbekannt"

        raw_distance = _as_float(distance_state)
        if raw_distance is None:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Entfernung ist kein gültiger Zahlenwert"

        distance_m = self._distance_to_meters(
            raw_distance,
            distance_state.attributes.get("unit_of_measurement"),
        )
        if distance_m is None:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, "Proximity-Einheit nicht unterstützt"
        self._proximity_distance_m = round(distance_m, 1)

        maximum_distance = max(
            0.0,
            float(self.config.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE)),
        )
        if direction == "arrived" or distance_m <= 0:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("confirmed", key)
            return True, "Proximity meldet Ankunft"
        if direction in ("away_from", "stationary"):
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("not_approaching", key)
            return False, (
                "Bewegung weg vom Zuhause" if direction == "away_from"
                else "Standort stationär – keine Anfahrt"
            )
        if direction != "towards":
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("invalid", key)
            return None, f"Unbekannte Bewegungsrichtung: {direction}"

        if distance_m > maximum_distance:
            self._proximity_approaching.pop(key, None)
            self._record_proximity_category("out_of_range", key)
            return False, "Noch außerhalb der Anfahrtsentfernung"

        if key not in self._proximity_approaching:
            self._proximity_approaching[key] = now
            self._record_proximity_category("approaching", key)
        duration = max(
            0,
            int(self.config.get(CONF_PROXIMITY_DURATION, DEFAULT_PROXIMITY_DURATION)),
        )
        elapsed = (now - self._proximity_approaching[key]).total_seconds()
        if elapsed < duration:
            return False, (
                f"Anfahrt erkannt – Wartezeit {round(duration - elapsed)} s"
            )
        self._record_proximity_category("confirmed", key)
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
        if leave_delay > 0 and (self.data or {}).get("mode") == "preheat":
            # Heat already put in is not thrown away for a short absence
            # (0 = react at once, kept as set).
            leave_delay = max(leave_delay, PREHEAT_LEAVE_GRACE_SECONDS)

        now = dt_util.utcnow()
        for entity_id in people:
            state = self.hass.states.get(entity_id)
            if not self._valid(state):
                invalid_people = True
            elif state.state == "home":
                self._seen_home[entity_id] = now
                if self._presence_is_active(state, True, enter_delay):
                    household_home = True
            elif self._left_home_within(entity_id, state, now, leave_delay):
                # Left just now, also straight into another zone ("Arbeit"):
                # still counts as home for the leaving delay.
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
        self._household_present = household_present and has_household_source
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

    def _people(self) -> list[str]:
        people = self.config.get(CONF_PERSON_ENTITIES) or []
        return [people] if isinstance(people, str) else list(people)

    def _observe_homecoming(self, result: dict[str, Any]) -> bool:
        """Learn the usual homecoming; True when one was recorded."""
        learned = False
        people = self._people()
        states = [self.hass.states.get(entity_id) for entity_id in people]
        if people and all(self._valid(state) for state in states):
            home = any(state.state == "home" for state in states)
            learned = self.homecoming.observe(dt_util.now(), home)
            if learned:
                self._log("Heimkehr gelernt")
        today = dt_util.now()
        minute = self.homecoming.usual(today.weekday(), today.date())
        result["homecoming_today"] = (
            None if minute is None else f"{minute // 60:02d}:{minute % 60:02d}"
        )
        result["homecoming_week"] = self.homecoming.week(today.date())
        result["homecoming_count"] = self.homecoming.count()
        return learned

    async def async_seed_homecoming(self) -> None:
        """Homecomings of the last weeks from the people's history, once."""
        people = self._people()
        if (
            self._homecoming_seeded
            or not people
            or "recorder" not in self.hass.config.components
        ):
            return
        from homeassistant.components.recorder import get_instance, history

        end = dt_util.utcnow()
        start = end - timedelta(days=HOMECOMING_HISTORY_DAYS)
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start,
                end,
                people,
                None,
                True,
                False,
                False,
                True,
            )
        except Exception:  # noqa: BLE001 - history is a bonus, never fatal
            _LOGGER.debug("Person history not available", exc_info=True)
            return
        changes = []
        for entity_id in people:
            for state in states.get(entity_id, []):
                if not isinstance(state, State) or state.state in _INVALID_STATES:
                    continue
                changes.append(
                    (dt_util.as_local(state.last_changed), entity_id, state.state == "home")
                )
        seeded = homecomings_from_history(changes, len(people))
        for items in seeded.arrivals.values():
            for day, minute in items:
                moment = datetime.combine(
                    date.fromisoformat(day),
                    datetime.min.time(),
                    dt_util.get_default_time_zone(),
                ) + timedelta(minutes=minute)
                self.homecoming.record(moment)
        self._homecoming_seeded = True
        if seeded.count():
            self._log(f"{seeded.count()}× Heimkehr aus dem Verlauf gelernt")
        await self._save_learning()

    def _homecoming_preheat(
        self,
        decision: HeatingDecision,
        *,
        room_temperature: float,
        outdoor_temperature: float | None,
        comfort_temperature: float,
        schedule_active: bool,
        next_event: datetime | None,
        view: ModelView | None,
        max_preheat: int,
    ) -> HeatingDecision:
        """While nobody is home, be warm again by the usual homecoming.

        Only when the schedule asks for comfort at that time. Until then the
        room keeps the away setback; it starts as late as the room needs
        (room model, else the heating rate) and stays warm for a while after
        the usual time. Coming home earlier is handled by presence as before.
        """
        if (
            not self.config.get(CONF_HOMECOMING_PREHEAT, DEFAULT_HOMECOMING_PREHEAT)
            or self._absence != "house_empty"
            or decision.mode not in ("away", "away_reduced")
        ):
            self._homecoming_day = None
            return decision
        local = dt_util.now()
        minute = self.homecoming.usual(local.weekday(), local.date())
        if minute is None:
            return decision
        arrival = local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            minutes=minute
        )
        until = arrival + timedelta(minutes=HOMECOMING_HOLD_MINUTES)
        if local >= until:
            return decision
        if schedule_active:
            comfort_then = next_event is None or dt_util.as_utc(next_event) > dt_util.as_utc(
                arrival
            )
        else:
            comfort_then = next_event is not None and dt_util.as_utc(
                next_event
            ) <= dt_util.as_utc(arrival)
        if not comfort_then:
            return decision
        goal = comfort_temperature - max(0.0, self.overshoot)
        if view is not None:
            lead = model_lead_minutes(view, room_temperature, goal, max_preheat)
        else:
            lead = calculate_lead_minutes(
                room_temperature,
                goal,
                self.effective_heating_rate,
                outdoor_temperature,
                max_preheat,
            )
        minutes = (dt_util.as_utc(arrival) - dt_util.utcnow()).total_seconds() / 60
        started = self._homecoming_day == local.date()
        last = self.data if isinstance(self.data, dict) else {}
        if (
            self.supply_profile.usually_off(local.hour)
            and SUPPLY_WARM not in (last.get("house_supply"), last.get("radiator_supply"))
        ):
            # No heat from the central heating now: open valves would not help.
            return decision
        if not started and (
            minutes > lead or room_temperature >= comfort_temperature - 0.2
        ):
            return decision
        self._homecoming_day = local.date()
        when = arrival.strftime("%H:%M")
        status = (
            f"Vorheizen zur üblichen Heimkehr ({when} Uhr)"
            if minutes > 0
            else f"Heimkehr erwartet (meist {when} Uhr) – warm gehalten"
        )
        return HeatingDecision(
            status, "homecoming", comfort_temperature, max(0, lead)
        )

    def _occupancy(self, now: datetime, schedule_active: bool) -> str | None:
        """Comfort by use of a motion sensor (e.g. the bathroom).

        "extend": the comfort block ended, but there was motion within the
        last minutes. "unused": the block runs for a while without any
        motion since it started. None otherwise.
        """
        entity_id = self.config.get(CONF_OCCUPANCY_ENTITY)
        if not entity_id:
            self._last_motion = None
            return None
        state = self.hass.states.get(entity_id)
        if not self._valid(state):
            return None
        # Short pulses are enough: "on" is motion now, "off" since when.
        moment = now if state.state == "on" else state.last_changed
        if self._last_motion is None or moment > self._last_motion:
            self._last_motion = moment
        last = self._last_motion
        if not schedule_active:
            ended = self._comfort_ended_at
            if (
                ended is not None
                and (now - ended).total_seconds() <= OCCUPANCY_EXTEND_MAX_SECONDS
                and last >= ended - timedelta(seconds=OCCUPANCY_HOLD_SECONDS)
                and (now - last).total_seconds() <= OCCUPANCY_HOLD_SECONDS
            ):
                return "extend"
            return None
        started = self._comfort_started_at
        if (
            started is not None
            and (now - started).total_seconds() >= OCCUPANCY_UNUSED_SECONDS
            and last < started
        ):
            return "unused"
        return None

    def _hold_comfort(self, now: datetime) -> str | None:
        """Why an empty room keeps comfort for now, or None."""
        if not self.config.get(CONF_PRESENCE_ENTITY):
            return None
        grace = int(
            self.config.get(CONF_ROOM_EMPTY_GRACE, DEFAULT_ROOM_EMPTY_GRACE) or 0
        )
        if (
            grace > 0
            and self._comfort_started_at is not None
            and (now - self._comfort_started_at).total_seconds() < grace
        ):
            end = dt_util.as_local(
                self._comfort_started_at + timedelta(seconds=grace)
            ).strftime("%H:%M")
            return f"Komfortbeginn – Raum noch leer, Komfort bis {end} Uhr gehalten"
        if self.config.get(CONF_LEARN_USAGE, DEFAULT_LEARN_USAGE):
            local = dt_util.as_local(now)
            if self.usage.usually_used(local.weekday(), local.hour):
                return "Raum um diese Zeit meist genutzt – Komfort gehalten"
        return None

    def _observe_usage(self, present: bool) -> bool:
        """Learn when the room is used; True when an hour was finished."""
        if not self.config.get(CONF_PRESENCE_ENTITY) or not self.config.get(
            CONF_LEARN_USAGE, DEFAULT_LEARN_USAGE
        ):
            return False
        now = dt_util.utcnow()
        seconds = (
            0.0 if self._usage_at is None else (now - self._usage_at).total_seconds()
        )
        self._usage_at = now
        if not self._household_present:
            # Nobody home: an empty room says nothing about its use.
            self.usage.pause()
            return False
        local = dt_util.as_local(now)
        return self.usage.observe(local.weekday(), local.hour, present, seconds)
