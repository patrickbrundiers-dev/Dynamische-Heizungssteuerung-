"""Looking ahead: schedule blocks, day plan, savings estimate, preheat timing, early stop and the sun pause.

Part of the room coordinator (``DynamicHeatingCoordinator``); the
methods use its state and run exactly as they did inside it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_EARLY_STOP,
    CONF_SOLAR_RADIATION_ENTITY,
    DEFAULT_EARLY_STOP,
    EARLY_STOP_DROP,
    SOLAR_PAUSE_MIN_GAIN,
    CONF_HOMECOMING_PREHEAT,
    DEFAULT_HOMECOMING_PREHEAT,
    CALENDAR_TEMPERATURE_KEY,
    CONF_PREHEAT_EXTENSION,
    CONF_PUNCTUALITY,
    SAVINGS_DAYS,
    DEFAULT_PREHEAT_EXTENSION,
    DEFAULT_PUNCTUALITY,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_SCHEDULE_ENTITY,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_ECO_TEMPERATURE,
    DEFAULT_MAX_PREHEAT_MINUTES,
    CONF_SCHOOL_FREE_ENTITY,
    CONF_SCHOOL_FREE_SCHEDULE,
    CONF_WORKDAY_ENTITY,
    CONF_SCHOOL_HOLIDAY_CALENDAR,
    SCHOOL_HOLIDAY_WORDS,
)
from .logic import (
    HeatingDecision,
    calendar_temperature,
    schedule_comfort_temperature,
)
from .model import ModelView
from .plan import (
    CHECK_ALPHA,
    CHECK_HOURS,
    Block,
    blocks_from_schedule,
    blocks_switched_at,
    compare_plans,
    plan_segments,
    shifted_blocks,
    savings_text,
    simulate,
    summary as plan_summary,
    temperature_at,
)
from .room_util import (
    FORECAST_CORRECTION_HOURS,
    PLAN_INTERVAL,
    SCHEDULE_WEEK_INTERVAL,
    _PLAN_MODES,
    _LOGGER,
    _as_number,
)


class PlanMixin:
    """Looking ahead."""

    async def _schedule_blocks(self, now: datetime) -> list[Block] | None:
        """Comfort blocks of the active schedule in the next 24 hours.

        A schedule helper's week comes from ``schedule.get_schedule``, a
        calendar's events from ``calendar.get_events``; None when neither
        answers. When tomorrow is school-free (or not) and that needs another
        schedule, the blocks after midnight come from that one.
        """
        schedule_id = self.active_schedule
        tomorrow_id = await self._tomorrow_schedule(now)
        key = (
            schedule_id,
            tomorrow_id,
            self._levels_key(),
            dt_util.as_local(now).strftime("%Y-%m-%d %H"),
        )
        if (
            self._schedule_week is not None
            and self._schedule_week_key is not None
            and self._schedule_week_key[:3] == key[:3]
            and self._schedule_week_at is not None
            and now - self._schedule_week_at < SCHEDULE_WEEK_INTERVAL
        ):
            return [block for block in self._schedule_week if block.end > now]
        if not schedule_id:
            return None
        local = dt_util.as_local(now)
        blocks = await self._fetch_blocks(schedule_id, local)
        self._tomorrow_note = None
        if blocks is not None and tomorrow_id is not None and tomorrow_id != schedule_id:
            later = await self._fetch_blocks(tomorrow_id, local)
            if later is not None:
                midnight = (local + timedelta(days=1)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                blocks = blocks_switched_at(blocks, later, midnight)
                self._tomorrow_note = (
                    "morgen schulfrei"
                    if tomorrow_id == self.config.get(CONF_SCHOOL_FREE_SCHEDULE)
                    else "morgen Schultag"
                )
        self._schedule_week = blocks
        self._schedule_week_key = key
        self._schedule_week_at = now
        return blocks

    async def _fetch_blocks(self, schedule_id: str, local: datetime) -> list[Block] | None:
        """The next 24 hours of one schedule helper or calendar."""
        blocks: list[Block] | None = None
        try:
            if schedule_id.startswith("schedule."):
                response = await self.hass.services.async_call(
                    "schedule",
                    "get_schedule",
                    {"entity_id": schedule_id},
                    blocking=True,
                    return_response=True,
                )
                weekly = response.get(schedule_id) if isinstance(response, dict) else None
                if isinstance(weekly, dict):
                    self._schedule_weekly[schedule_id] = weekly
                blocks = blocks_from_schedule(
                    weekly, local, schedule_comfort_temperature, level_of=self._block_level
                )
            elif schedule_id.startswith("calendar."):
                response = await self.hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": schedule_id,
                        "start_date_time": local.isoformat(),
                        "end_date_time": (local + timedelta(days=1)).isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
                events = (
                    (response.get(schedule_id) or {}).get("events")
                    if isinstance(response, dict)
                    else None
                )
                blocks = []
                for event in events or []:
                    start = self._parse_local_time(event.get("start"))
                    end = self._parse_local_time(event.get("end"))
                    if start is None or end is None or end <= start:
                        continue
                    blocks.append(
                        Block(
                            dt_util.as_local(start),
                            dt_util.as_local(end),
                            calendar_temperature(
                                event.get("description"), CALENDAR_TEMPERATURE_KEY
                            ),
                        )
                    )
                blocks.sort(key=lambda block: block.start)
        except (HomeAssistantError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.debug("Schedule of %s not readable for the day plan: %s", schedule_id, err)
            blocks = None
        return blocks

    def _follow_school_free(self) -> None:
        """Pick the school-free schedule on free days, the normal one else.

        Like the automation it replaces: on a change of the entity (and once
        after the start). Picking another schedule by hand holds until the
        next change.
        """
        entity_id = self.config.get(CONF_SCHOOL_FREE_ENTITY)
        free_schedule = self.config.get(CONF_SCHOOL_FREE_SCHEDULE)
        if not entity_id or not free_schedule:
            return
        state = self.hass.states.get(entity_id)
        if not self._valid(state):
            return
        free = state.state == "on"
        if free == self._school_free:
            return
        self._school_free = free
        choice = free_schedule if free else self.config.get(CONF_SCHEDULE_ENTITY)
        if choice and self.schedule_choice != choice:
            self.schedule_choice = choice
            self._preheat_event = None
            self._pending_source = "Schulfrei"
            self._log(
                f"Zeitplan {self._friendly_name(choice)} "
                + ("(schulfrei)" if free else "(Schultag)")
            )

    async def _tomorrow_schedule(self, now: datetime) -> str | None:
        """The schedule tomorrow needs when school-free days are set up.

        None when that is not known (no workday sensor or holiday calendar).
        """
        free_schedule = self.config.get(CONF_SCHOOL_FREE_SCHEDULE)
        if not self.config.get(CONF_SCHOOL_FREE_ENTITY) or not free_schedule:
            return None
        free = await self._free_tomorrow(now)
        if free is None:
            return None
        return free_schedule if free else self.config.get(CONF_SCHEDULE_ENTITY)

    async def _free_tomorrow(self, now: datetime) -> bool | None:
        """Is tomorrow school-free? Asked once a day (workday, holidays)."""
        day = (dt_util.as_local(now) + timedelta(days=1)).date()
        if self._free_tomorrow_cache is not None and self._free_tomorrow_cache[0] == day:
            return self._free_tomorrow_cache[1]
        workday_id = self.config.get(CONF_WORKDAY_ENTITY)
        calendar_id = self.config.get(CONF_SCHOOL_HOLIDAY_CALENDAR)
        if not workday_id and not calendar_id:
            return None
        free: bool | None = None
        try:
            if workday_id:
                response = await self.hass.services.async_call(
                    "workday",
                    "check_date",
                    {"entity_id": workday_id, "check_date": day},
                    blocking=True,
                    return_response=True,
                )
                value = (
                    (response.get(workday_id) or {}).get("workday")
                    if isinstance(response, dict)
                    else None
                )
                if isinstance(value, bool):
                    free = not value
            if calendar_id and not free:
                start = datetime.combine(day, datetime.min.time(), dt_util.get_default_time_zone())
                response = await self.hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": calendar_id,
                        "start_date_time": (start + timedelta(hours=8)).isoformat(),
                        "end_date_time": (start + timedelta(hours=16)).isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
                events = (
                    (response.get(calendar_id) or {}).get("events")
                    if isinstance(response, dict)
                    else None
                )
                if events is not None:
                    holiday = any(
                        word in str(event.get("summary") or "").casefold()
                        for event in events
                        for word in SCHOOL_HOLIDAY_WORDS
                    )
                    free = bool(free) or holiday
        except (HomeAssistantError, TypeError, ValueError, AttributeError) as err:
            _LOGGER.debug("Could not tell whether tomorrow is school-free: %s", err)
            return None
        if free is not None:
            self._free_tomorrow_cache = (day, free)
        return free

    def _forecast_points(self) -> list[tuple[datetime, float]]:
        forecast: list[tuple[datetime, float]] = []
        for item in self._forecast_items:
            raw = item.get("datetime")
            moment = dt_util.parse_datetime(raw) if isinstance(raw, str) else None
            value = _as_number(item.get("temperature"))
            if moment is not None and value is not None:
                forecast.append((dt_util.as_utc(moment), value))
        forecast.sort()
        return forecast

    def _forecast_correction(
        self, outdoor: float | None, at: datetime, now: datetime | None = None
    ) -> float:
        """What to add to the forecast for ``at``: the forecast's error now.

        The weather service's hourly value can be degrees off the own outdoor
        sensor (13.10.: 10.9 °C forecast, 8.4 °C measured). The error seen
        now is carried into the next hours, fading out over half a day.
        """
        if outdoor is None:
            return 0.0
        now = dt_util.utcnow() if now is None else dt_util.as_utc(now)
        forecast_now = None
        for start, temperature in self._forecast_points():
            if start > now:
                if forecast_now is None and start - now <= timedelta(hours=1):
                    forecast_now = temperature
                break
            forecast_now = temperature
        if forecast_now is None:
            return 0.0
        hours = max(0.0, (dt_util.as_utc(at) - now).total_seconds() / 3600)
        fade = max(0.0, 1 - hours / FORECAST_CORRECTION_HOURS)
        return (float(outdoor) - forecast_now) * fade

    def _outdoor_at(self, fallback: float) -> Any:
        """A function giving the forecast outdoor temperature for a time."""
        forecast = self._forecast_points()

        def outdoor_at(at: datetime) -> float:
            value = fallback
            moment = dt_util.as_utc(at)
            found = False
            for start, temperature in forecast:
                if start > moment:
                    break
                value = temperature
                found = True
            if found:
                value += self._forecast_correction(fallback, at)
            return value

        return outdoor_at

    async def _update_plan(self, result: dict[str, Any]) -> None:
        """Recalculate the day plan now and then and check it against the room."""
        now = dt_util.utcnow()
        room = result.get("room_temperature")
        self._check_plan(result, now)
        # Also at once when control is switched on (after a restart it comes
        # on a moment after the first cycle), room and outdoor temperature
        # arrive, the model gets ready or the schedule changes.
        key = (
            self.enabled,
            room is not None and result.get("outdoor_temperature") is not None,
            self.room_model.ready,
            self.active_schedule,
        )
        if (
            self._plan_at is None
            or now - self._plan_at >= PLAN_INTERVAL
            or key != self._plan_key
        ):
            self._plan_at = now
            self._plan_key = key
            self.plan_points, self.plan_info = await self._calculate_plan(result, now)
        result["day_plan"] = self.plan_info.get("text")
        result["plan_error"] = self.plan_error
        result["plan_checked"] = self.plan_checked
        local_hour = dt_util.as_local(now).hour
        if (
            self.plan_points
            and room is not None
            and local_hour != self._plan_check_hour
            and result.get("mode") in _PLAN_MODES
        ):
            self._plan_check_hour = local_hour
            at = now + timedelta(hours=CHECK_HOURS)
            predicted = temperature_at(self.plan_points, dt_util.as_local(at))
            if predicted is not None:
                self._plan_checks[at] = predicted

    def _check_plan(self, result: dict[str, Any], now: datetime) -> None:
        """Compare what the plan said a few hours ago with the room now."""
        room = result.get("room_temperature")
        for at in sorted(self._plan_checks):
            if at > now:
                break
            predicted = self._plan_checks.pop(at)
            if (
                room is None
                or now - at > PLAN_INTERVAL
                or result.get("mode") not in _PLAN_MODES
                or result.get("room_temperature_source") != "sensor"
            ):
                continue
            error = abs(float(room) - predicted)
            self.plan_error = round(
                error
                if self.plan_error is None
                else (1 - CHECK_ALPHA) * self.plan_error + CHECK_ALPHA * error,
                2,
            )
            self.plan_checked += 1

    async def _calculate_plan(
        self, result: dict[str, Any], now: datetime
    ) -> tuple[list, dict[str, Any]]:
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        if not self.enabled:
            return [], {"text": "Regelung aus – kein Tagesplan"}
        if room is None or outdoor is None:
            return [], {"text": "Raum- oder Außentemperatur fehlt – kein Tagesplan"}
        view = self._model_view(float(outdoor), 0.0, 0.0)
        if view is None:
            return [], {"text": "Raummodell lernt noch – Tagesplan folgt"}
        blocks = await self._schedule_blocks(now)
        if blocks is None:
            return [], {"text": "Zeitplan nicht lesbar – kein Tagesplan"}
        profile = self.supply_profile
        local = dt_util.as_local(now)
        comfort = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        eco = float(result.get("eco_temperature") or self.config.get(
            CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE
        ))
        points = simulate(
            view,
            now=local,
            room=float(room),
            comfort=comfort,
            eco=eco,
            blocks=blocks,
            outdoor_at=self._outdoor_at(float(outdoor)),
            supply_off=lambda at: profile.usually_off(dt_util.as_local(at).hour),
            max_preheat_minutes=int(
                self.config.get(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)
            )
            + self._preheat_extension_minutes(),
            lead_bias_minutes=self._lead_bias(),
        )
        info = plan_summary(points, blocks, local)
        info["segments"] = plan_segments(points, eco)
        if self.config.get(CONF_HOMECOMING_PREHEAT, DEFAULT_HOMECOMING_PREHEAT):
            minute = self.homecoming.usual(local.weekday(), local.date())
            if minute is not None:
                info["homecoming"] = f"{minute // 60:02d}:{minute % 60:02d}"
                info["text"] = (
                    f"{info['text']} · Heimkehr meist {info['homecoming']} Uhr"
                )
        if self._tomorrow_note:
            info["text"] = f"{info['text']} ({self._tomorrow_note})"
        if self.plan_error is not None and self.plan_checked >= 3:
            info["text"] = (
                f"{info['text']} (Abweichung bisher ±"
                + f"{self.plan_error:.1f}".replace(".", ",")
                + " °C)"
            )
        info["text"] = str(info.get("text") or "")[:250]
        return points, info

    async def async_estimate_savings(
        self,
        *,
        comfort: float | None = None,
        eco: float | None = None,
        shift_minutes: int = 0,
    ) -> dict[str, Any]:
        """Spar-Rechner: the next days with other temperatures or times.

        Both variants are replayed on the learned room model like the day
        plan (schedule, central heating's pauses, weather forecast); presence,
        windows and the sun are left out. Nothing is changed.
        """
        result = self.data or {}
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        base_comfort = float(
            self.config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        )
        base_eco = float(self.config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE))
        new_comfort = base_comfort if comfort is None else float(comfort)
        new_eco = base_eco if eco is None else float(eco)
        answer: dict[str, Any] = {
            "room": self.room_name,
            "comfort": base_comfort,
            "eco": base_eco,
            "new_comfort": new_comfort,
            "new_eco": new_eco,
            "shift_minutes": int(shift_minutes),
        }
        if new_eco >= new_comfort:
            answer["text"] = "Eco muss unter der Komforttemperatur liegen."
            return answer
        view = self._model_view(None if outdoor is None else float(outdoor), 0.0, 0.0)
        if room is None or outdoor is None:
            answer["text"] = "Raum- oder Außentemperatur fehlt – keine Rechnung möglich."
            return answer
        if view is None:
            answer["text"] = "Das Raummodell lernt noch – der Spar-Rechner folgt."
            return answer
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        days = SAVINGS_DAYS
        schedule_id = self.active_schedule or ""
        blocks = await self._schedule_blocks(now)
        weekly = self._schedule_weekly.get(schedule_id)
        if schedule_id.startswith("schedule.") and isinstance(weekly, dict):
            blocks = blocks_from_schedule(
                weekly,
                local,
                schedule_comfort_temperature,
                hours=days * 24,
                level_of=self._block_level,
            )
        else:
            days = 1
        if blocks is None:
            answer["text"] = "Zeitplan nicht lesbar – keine Rechnung möglich."
            return answer
        delta = new_comfort - base_comfort
        new_blocks = shifted_blocks(
            [
                Block(
                    block.start,
                    block.end,
                    None if block.temperature is None else block.temperature + delta,
                )
                for block in blocks
            ],
            int(shift_minutes),
        )
        profile = self.supply_profile
        settings = {
            "view": view,
            "now": local,
            "room": float(room),
            "outdoor_at": self._outdoor_at(float(outdoor)),
            "supply_off": lambda at: profile.usually_off(dt_util.as_local(at).hour),
            "max_preheat_minutes": int(
                self.config.get(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)
            )
            + self._preheat_extension_minutes(),
            "hours": days * 24,
            "lead_bias_minutes": self._lead_bias(),
        }
        base = simulate(comfort=base_comfort, eco=base_eco, blocks=blocks, **settings)
        other = simulate(
            comfort=new_comfort, eco=new_eco, blocks=new_blocks, **settings
        )
        comparison = compare_plans(base, blocks, other, new_blocks, local)
        power_kw = self.radiator_power_w / 1000
        answer.update(comparison)
        answer["days"] = days
        answer["base_kwh"] = round(comparison["base_full_load_hours"] * power_kw, 1)
        answer["kwh"] = round(comparison["full_load_hours"] * power_kw, 1)
        answer["text"] = savings_text(answer)
        return answer

    def plan_attributes(self) -> dict[str, Any]:
        """The day plan for dashboards: times, target and expected temperature."""
        return {
            **{key: value for key, value in self.plan_info.items() if key != "text"},
            "plan_error": self.plan_error,
            "plan_checked": self.plan_checked,
            "calculated_at": self._plan_at.isoformat() if self._plan_at else None,
            "forecast": [
                {
                    "time": point.at.isoformat(),
                    "temperature": point.temperature,
                    "target": point.target,
                }
                for point in self.plan_points[::2]
            ],
        }

    def _punctual(self) -> bool:
        return bool(self.config.get(CONF_PUNCTUALITY, DEFAULT_PUNCTUALITY))

    def _lead_bias(self) -> int:
        """The learned preheat correction in minutes (0 when switched off).

        Taken from earlier mornings like the next one (outdoor temperature at
        the comfort start, degrees to warm up), see ``Punctuality.bias_for``.
        """
        if not self._punctual():
            return 0
        outdoor, gap = self._bias_context
        return round(
            self.punctuality.bias_for(outdoor, gap, dt_util.as_local(dt_util.utcnow()).date())
        )

    def _preheat_extension_minutes(self) -> int:
        if not self._punctual():
            return 0
        value = self.config.get(CONF_PREHEAT_EXTENSION, DEFAULT_PREHEAT_EXTENSION)
        try:
            return max(0, int(float(value or 0) // 60))
        except (TypeError, ValueError):
            return 0

    def _preheat_limit(self, max_preheat: int, next_event: datetime | None) -> int:
        """Maximum preheat time, extended while the central heating delivers.

        The extra time is only allowed when none of its hours is one in which
        the central heating is usually off: heating then would be in vain.
        """
        extension = self._preheat_extension_minutes()
        if not extension or next_event is None:
            return max_preheat
        profile = self.supply_profile
        start = dt_util.as_local(next_event) - timedelta(minutes=max_preheat + extension)
        end = dt_util.as_local(next_event) - timedelta(minutes=max_preheat)
        at = start
        while at < end:
            if profile.usually_off(at.hour):
                return max_preheat
            at += timedelta(minutes=30)
        return max_preheat + extension

    def _early_stop(
        self,
        decision: HeatingDecision,
        *,
        room_temperature: float,
        comfort_temperature: float,
        eco_temperature: float,
        next_event: datetime | None,
        schedule_active: bool,
        view: ModelView | None,
    ) -> HeatingDecision:
        """End heating before the comfort block ends if the room holds."""
        if self._early_stop_event is not None and self._early_stop_event != next_event:
            self._early_stop_event = None
        seconds = int(self.config.get(CONF_EARLY_STOP, DEFAULT_EARLY_STOP) or 0)
        if (
            seconds <= 0
            or not schedule_active
            or next_event is None
            or decision.mode != "comfort"
        ):
            return decision
        minutes_left = (next_event - dt_util.utcnow()).total_seconds() / 60
        if minutes_left <= 0 or minutes_left > seconds / 60:
            return decision
        lowest = comfort_temperature - EARLY_STOP_DROP
        if self._early_stop_event == next_event:
            if room_temperature < lowest:
                # Cooled faster than expected: heat again until the end.
                self._early_stop_event = None
                return decision
        else:
            hours = minutes_left / 60
            if view is not None:
                predicted = view.temperature_after(room_temperature, hours, 0.0)
            elif self._cooling_samples:
                predicted = room_temperature - self.cooling_rate * hours
            else:
                return decision
            if room_temperature < comfort_temperature - 0.2 or predicted < lowest:
                return decision
            self._early_stop_event = next_event
        end = dt_util.as_local(next_event).strftime("%H:%M")
        return replace(
            decision,
            status=f"Komfort endet um {end} Uhr – Heizung schon aus, "
            "der Raum hält die Wärme",
            mode="early_stop",
            target_temperature=min(eco_temperature, comfort_temperature),
            preheat_minutes=0,
        )

    def _sun_pause(
        self,
        decision: HeatingDecision,
        room_temperature: float,
        eco_temperature: float,
        view: ModelView | None,
    ) -> HeatingDecision:
        """Close the valves while the sun alone keeps the room at its target."""
        target = decision.target_temperature
        if (
            view is None
            or not self.config.get(CONF_SOLAR_RADIATION_ENTITY)
            or decision.mode not in ("comfort", "preheat", "away_reduced")
            or target is None
        ):
            self._solar_pause = False
            return decision
        gain = view.solar_gain * view.solar_kw
        predicted = view.temperature_after(room_temperature, 1.0, 0.0)
        if self._solar_pause:
            pause = (
                gain >= SOLAR_PAUSE_MIN_GAIN / 2
                and room_temperature >= target - 0.5
                and predicted >= target - 0.3
            )
        else:
            pause = (
                gain >= SOLAR_PAUSE_MIN_GAIN
                and room_temperature >= target - 0.3
                and predicted >= target
            )
        self._solar_pause = pause
        if not pause:
            return decision
        return replace(
            decision,
            status="Sonne wärmt den Raum – Heizung pausiert",
            mode="solar",
            target_temperature=min(eco_temperature, target),
            preheat_minutes=0,
        )
