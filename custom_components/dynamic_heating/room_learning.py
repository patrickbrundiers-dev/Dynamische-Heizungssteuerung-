"""What the room learns: heating and cooling rates, overshoot, forecasts and the room model.

Part of the room coordinator (``DynamicHeatingCoordinator``); the
methods use its state and run exactly as they did inside it.
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ROOM_MODEL,
    CONF_SOLAR_RADIATION_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DEFAULT_ROOM_MODEL,
    MODEL_HISTORY_DAYS,
    RECOVERY_REACH_MARGIN,
    MAX_OVERSHOOT,
    OVERSHOOT_DROP,
    OVERSHOOT_MAX_SECONDS,
    MODEL_ASKING_DEMAND,
    LEARN_RUN_DURATION_SECONDS,
    LEARN_RUN_RISE,
    HEAT_DEMAND_FULL_GAP,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    MAX_HEATING_SAMPLE_SECONDS,
    MAX_COOLING_SAMPLE_SECONDS,
    MAX_HEATING_SAMPLE_DELTA,
    MAX_COOLING_SAMPLE_DELTA,
    MIN_SAMPLE_DELTA,
    FORECAST_EVALUATION_GRACE_SECONDS,
    DOMAIN,
    MAX_LEARNED_COOLING_RATE,
    MAX_LEARNED_HEATING_RATE,
    MIN_COOLING_SAMPLE_SECONDS,
    MIN_LEARNED_COOLING_RATE,
    MIN_LEARNED_HEATING_RATE,
    MIN_SAMPLE_SECONDS,
)
from .model import (
    HORIZON_MIN,
    TRUSTED_HORIZON_ERROR,
    TRUSTED_SAMPLES,
    ModelView,
    RoomModel,
    seed_room_model,
    solar_to_kw,
    wind_to_ms,
)
from .radiator import (
    SUPPLY_COLD,
    SUPPLY_VERSION,
    SUPPLY_WARM,
)
from .room_util import (
    ROOM_MODEL_VERSION,
    SEED_VERSION,
    _LOGGER,
    _as_float,
    _de_number,
)


class LearningMixin:
    """What the room learns."""

    @staticmethod
    def _stored_count(value: object) -> int:
        """Read a non-negative persisted counter."""
        try:
            return max(0, int(value))
        except (TypeError, ValueError, OverflowError):
            return 0

    @staticmethod
    def _stored_float(value: object) -> float | None:
        """Read a finite persisted float or return none."""
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _stored_string(value: object) -> str | None:
        """Read a bounded string from persisted learning metadata."""
        return value[:200] if isinstance(value, str) else None

    def _learning_diagnostics(self) -> dict[str, Any]:
        """Expose compact model quality metrics for sensors and diagnostics."""
        return {
            "heating_samples": self._heating_samples,
            "cooling_samples": self._cooling_samples,
            "rejected_samples": self._rejected_samples,
            "last_observed_heating_rate": self._last_observed_heating_rate,
            "last_observed_cooling_rate": self._last_observed_cooling_rate,
            "last_learning_type": self._last_learning_type,
            "learning_status": self._last_learning_status,
            "last_learning_sample_at": self._last_learning_sample_at,
            "forecast_evaluations": self._forecast_evaluations,
            "forecast_mae_c": self._forecast_mae_c,
            "last_forecast_error_c": self._last_forecast_error_c,
            "last_forecast_predicted_temperature": (
                self._last_forecast_predicted_temperature
            ),
            "last_forecast_actual_temperature": self._last_forecast_actual_temperature,
            "last_forecast_event": self._last_forecast_event,
            "last_forecast_error_at": self._last_forecast_error_at,
            "proximity_updates_seen": self._proximity_updates_seen,
            "proximity_update_interval_count": self._proximity_update_interval_count,
            "proximity_average_update_interval_s": self._proximity_average_update_interval_s,
            "proximity_stale_events": self._proximity_stale_events,
            "proximity_invalid_events": self._proximity_invalid_events,
            "proximity_out_of_range_events": self._proximity_out_of_range_events,
            "proximity_approach_attempts": self._proximity_approach_attempts,
            "proximity_confirmed_approaches": self._proximity_confirmed_approaches,
            "proximity_last_update_at": self._proximity_last_update_at,
            "overshoot": self.overshoot,
            "overshoot_samples": self._overshoot_samples,
        }

    async def _save_learning(self) -> None:
        """Persist rates and compact quality metrics together."""
        await self._store.async_save(
            {
                "heating_rate": self.heating_rate,
                "cooling_rate": self.cooling_rate,
                "heating_samples": self._heating_samples,
                "cooling_samples": self._cooling_samples,
                "rejected_samples": self._rejected_samples,
                "last_observed_heating_rate": self._last_observed_heating_rate,
                "last_observed_cooling_rate": self._last_observed_cooling_rate,
                "last_learning_type": self._last_learning_type,
                "last_learning_status": self._last_learning_status,
                "last_learning_sample_at": self._last_learning_sample_at,
                "forecast_evaluations": self._forecast_evaluations,
                "forecast_mae_c": self._forecast_mae_c,
                "last_forecast_error_c": self._last_forecast_error_c,
                "last_forecast_predicted_temperature": (
                    self._last_forecast_predicted_temperature
                ),
                "last_forecast_actual_temperature": (
                    self._last_forecast_actual_temperature
                ),
                "last_forecast_event": self._last_forecast_event,
                "last_forecast_error_at": self._last_forecast_error_at,
                "proximity_updates_seen": self._proximity_updates_seen,
                "proximity_update_interval_count": self._proximity_update_interval_count,
                "proximity_average_update_interval_s": self._proximity_average_update_interval_s,
                "proximity_stale_events": self._proximity_stale_events,
                "proximity_invalid_events": self._proximity_invalid_events,
                "proximity_out_of_range_events": self._proximity_out_of_range_events,
                "proximity_approach_attempts": self._proximity_approach_attempts,
                "proximity_confirmed_approaches": self._proximity_confirmed_approaches,
                "proximity_last_state_update": (
                    self._proximity_last_state_update.isoformat()
                    if self._proximity_last_state_update else None
                ),
                "proximity_last_update_at": self._proximity_last_update_at,
                "valve_maintenance_last": (
                    self._maintenance_last.isoformat()
                    if self._maintenance_last else None
                ),
                "overshoot": self.overshoot,
                "overshoot_samples": self._overshoot_samples,
                "room_model": self.room_model.as_dict(),
                "room_model_seeded": self._model_seeded,
                "room_model_version": ROOM_MODEL_VERSION,
                "supply_profile": self.supply.as_list(),
                "supply_counts": self.supply.count_list(),
                "supply_version": SUPPLY_VERSION,
                "cooling_correction": self.cooling.as_dict(),
                "usage_profile": self.usage.as_list(),
                "seed_version": self._seed_version,
                "radiator_stats": {
                    entity_id: stats.as_dict()
                    for entity_id, stats in self.radiator_stats.items()
                },
                "plan_error": self.plan_error,
                "plan_checked": self.plan_checked,
                "punctuality": self.punctuality.as_dict(),
                "habits": self.habits.as_dict(),
                "showers": self.showers.as_dict(),
                "showers_seeded": self._showers_seeded,
                "homecoming": self.homecoming.as_dict(),
                "homecoming_seeded": self._homecoming_seeded,
                "batteries": self.batteries.as_dict(),
            }
        )

    async def _learn(
        self,
        room_temperature: float,
        climate_state: State | None,
        *,
        window_open: bool,
        schedule_active: bool,
        eco_temperature: float,
    ) -> None:
        """Learn from plausible temperature trends and reject outlier samples."""
        attributes = climate_state.attributes if climate_state else {}
        setpoint_value = self._stored_float(attributes.get("temperature"))
        last = self.data or {}
        if (
            self.enabled
            and last.get("target_temperature") is not None
            and not last.get("manual_override")
        ):
            # Under control the valve setpoint carries calibration and valve
            # offsets; the room target is what the room really heats towards.
            setpoint_value = float(last["target_temperature"])
        is_heating = self._is_heating(climate_state, room_temperature, setpoint_value)
        now = dt_util.utcnow()
        await self._track_overshoot(
            room_temperature, is_heating, window_open=window_open, now=now
        )
        if self._model_rates is not None:
            # The room model learns from every hour; single samples add nothing.
            self._heating_sample.reset()
            self._cooling_sample.reset()
            self._last_learning_status = "Raummodell übernimmt"
            return

        # Absence only lowers the target; the room still heats and cools
        # normally, and the night setback is the main cooling phase to learn.
        if window_open:
            self._heating_sample.reset()
            self._cooling_sample.reset()
            self._last_learning_status = "Lernen pausiert: Fenster offen"
            return

        if is_heating:
            self._cooling_sample.reset()
            if setpoint_value is None or room_temperature >= setpoint_value - 0.1:
                self._heating_sample.reset()
                self._last_learning_status = "Warte auf aktive Heizphase unter Solltemperatur"
                return

            outcome, observed_rate = self._heating_sample.observe(
                room_temperature,
                now,
                direction=1,
                min_seconds=MIN_SAMPLE_SECONDS,
                max_seconds=MAX_HEATING_SAMPLE_SECONDS,
                min_delta=MIN_SAMPLE_DELTA,
                max_delta=MAX_HEATING_SAMPLE_DELTA,
            )
            if outcome == "started":
                self._last_learning_type = "heating"
                self._last_learning_status = "Sammle Aufheizmessung"
                return
            if outcome == "collecting":
                self._last_learning_status = "Sammle weitere Aufheizdaten"
                return
            if outcome == "too_long":
                self._rejected_samples += 1
                self._last_learning_status = "Aufheizmessung verworfen: Messintervall zu lang"
                await self._save_learning()
                return
            if outcome == "implausible" or observed_rate is None:
                self._rejected_samples += 1
                self._last_learning_status = "Aufheizmessung verworfen: Temperaturänderung unplausibel"
                await self._save_learning()
                return

            self._last_observed_heating_rate = round(observed_rate, 3)
            # A room heating slower than the model's floor is real and
            # important to know (preheating has to start early): learn the
            # floor instead of throwing the measurement away.
            observed_rate = max(observed_rate, MIN_LEARNED_HEATING_RATE)
            if observed_rate > MAX_LEARNED_HEATING_RATE:
                self._rejected_samples += 1
                self._last_learning_status = "Aufheizmessung verworfen: Rate außerhalb plausibler Grenzen"
                await self._save_learning()
                return

            self.heating_rate = round(
                0.8 * self.heating_rate + 0.2 * observed_rate, 3
            )
            self._heating_samples += 1
            self._last_learning_type = "heating"
            self._last_learning_sample_at = now.isoformat()
            self._last_learning_status = "Aufheizrate aktualisiert"
            await self._save_learning()
            return

        self._heating_sample.reset()
        can_learn_cooling = (
            setpoint_value is not None
            and room_temperature > setpoint_value + 0.2
            and setpoint_value <= eco_temperature + 0.5
            and not schedule_active
        )
        if not can_learn_cooling:
            self._cooling_sample.reset()
            self._last_learning_status = "Warte auf stabile Abkühlphase im Absenkbetrieb"
            return

        outcome, observed_rate = self._cooling_sample.observe(
            room_temperature,
            now,
            direction=-1,
            min_seconds=MIN_COOLING_SAMPLE_SECONDS,
            max_seconds=MAX_COOLING_SAMPLE_SECONDS,
            min_delta=MIN_SAMPLE_DELTA,
            max_delta=MAX_COOLING_SAMPLE_DELTA,
        )
        if outcome == "started":
            self._last_learning_type = "cooling"
            self._last_learning_status = "Sammle Abkühlmessung"
            return
        if outcome == "collecting":
            self._last_learning_status = "Sammle weitere Abkühldaten"
            return
        if outcome == "too_long":
            self._rejected_samples += 1
            self._last_learning_status = "Abkühlmessung verworfen: Messintervall zu lang"
            await self._save_learning()
            return
        if outcome == "implausible" or observed_rate is None:
            self._rejected_samples += 1
            self._last_learning_status = "Abkühlmessung verworfen: Temperaturänderung unplausibel"
            await self._save_learning()
            return

        self._last_observed_cooling_rate = round(observed_rate, 3)
        if not MIN_LEARNED_COOLING_RATE <= observed_rate <= MAX_LEARNED_COOLING_RATE:
            self._rejected_samples += 1
            self._last_learning_status = "Abkühlmessung verworfen: Rate außerhalb plausibler Grenzen"
            await self._save_learning()
            return

        self.cooling_rate = round(
            0.8 * self.cooling_rate + 0.2 * observed_rate, 3
        )
        self._cooling_samples += 1
        self._last_learning_type = "cooling"
        self._last_learning_sample_at = now.isoformat()
        self._last_learning_status = "Abkühlrate aktualisiert"
        await self._save_learning()

    async def _track_overshoot(
        self,
        room_temperature: float,
        is_heating: bool,
        *,
        window_open: bool,
        now: datetime,
    ) -> None:
        """Measure how far the room keeps warming after heating stopped.

        A measurement starts when heating stops near the room's target and
        ends once the room cooled a little below its peak (or after 90
        minutes). New heating or an open window discard it.
        """
        if window_open or is_heating:
            self._overshoot_track = None
            self._was_heating = is_heating and not window_open
            return
        target = (self.data or {}).get("target_temperature")
        if (
            self._was_heating
            and target is not None
            and room_temperature >= float(target) - 0.3
        ):
            self._overshoot_track = (float(target), room_temperature, now)
        self._was_heating = False
        if self._overshoot_track is None:
            return
        target_value, peak, started = self._overshoot_track
        peak = max(peak, room_temperature)
        self._overshoot_track = (target_value, peak, started)
        if (
            room_temperature > peak - OVERSHOOT_DROP
            and (now - started).total_seconds() < OVERSHOOT_MAX_SECONDS
        ):
            return
        observed = max(0.0, min(peak - target_value, MAX_OVERSHOOT))
        self.overshoot = round(
            observed
            if self._overshoot_samples == 0
            else 0.8 * self.overshoot + 0.2 * observed,
            2,
        )
        self._overshoot_samples += 1
        self._overshoot_track = None
        await self._save_learning()

    async def _evaluate_pending_forecast(
        self,
        *,
        now: datetime,
        room_temperature: float,
        schedule_active: bool,
        present: bool,
        window_open: bool,
    ) -> None:
        """Compare a stored pre-schedule temperature projection with reality."""
        event = self._pending_forecast_event
        predicted = self._pending_forecast_temperature
        if event is None or predicted is None:
            return

        seconds_after_event = (now - event).total_seconds()
        if seconds_after_event > FORECAST_EVALUATION_GRACE_SECONDS:
            self._pending_forecast_event = None
            self._pending_forecast_temperature = None
            return
        if (
            seconds_after_event < 0
            or not schedule_active
            or not present
            or window_open
        ):
            return

        error = round(room_temperature - predicted, 3)
        absolute_error = abs(error)
        self._forecast_evaluations += 1
        if self._forecast_mae_c is None or self._forecast_evaluations == 1:
            self._forecast_mae_c = round(absolute_error, 3)
        else:
            self._forecast_mae_c = round(
                self._forecast_mae_c
                + (absolute_error - self._forecast_mae_c)
                / self._forecast_evaluations,
                3,
            )
        self._last_forecast_error_c = error
        self._last_forecast_predicted_temperature = round(predicted, 2)
        self._last_forecast_actual_temperature = round(room_temperature, 2)
        self._last_forecast_event = event.isoformat()
        self._last_forecast_error_at = now.isoformat()
        self._last_learning_status = (
            f"Vorhersage ausgewertet: Fehler {error:+.1f} °C "
            f"(MAE {self._forecast_mae_c:.1f} °C)"
        )
        self._pending_forecast_event = None
        self._pending_forecast_temperature = None
        await self._save_learning()

    def _update_pending_forecast(
        self,
        *,
        now: datetime,
        next_event: datetime | None,
        projected_temperature: float | None,
        schedule_active: bool,
        present: bool,
        window_open: bool,
    ) -> None:
        """Keep the latest forecast until its scheduled comfort transition."""
        if self._pending_forecast_event is not None and (
            now - self._pending_forecast_event
        ).total_seconds() > FORECAST_EVALUATION_GRACE_SECONDS:
            self._pending_forecast_event = None
            self._pending_forecast_temperature = None

        if (
            schedule_active
            or not present
            or window_open
            or next_event is None
            or projected_temperature is None
            or next_event <= now
        ):
            return
        self._pending_forecast_event = next_event
        self._pending_forecast_temperature = projected_temperature

    def _observe_cooling(self, result: dict[str, Any]) -> bool:
        """Compare stretches without heat with the model; True when one was."""
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        demand = result.get("heat_demand")
        target = result.get("target_temperature")
        # Only clearly above its target are the valves really closed; a
        # room held at its target still gets some heat.
        no_heat = (
            demand is not None
            and demand <= 10
            and room is not None
            and target is not None
            and float(room) - float(target) >= 0.3
        ) or SUPPLY_COLD in (
            result.get("radiator_supply"),
            result.get("house_supply"),
        )
        idle = (
            self.enabled
            and not self._room_fallback
            and room is not None
            and outdoor is not None
            and no_heat
            and not result.get("window_open")
            and result.get("mode") not in ("waiting", "maintenance", "window")
        )
        solar_kw, _wind = self._weather_inputs()
        learned = self.cooling.observe(
            dt_util.utcnow().timestamp(),
            float(room) if room is not None else 0.0,
            float(outdoor) if outdoor is not None else 0.0,
            bool(idle),
            self._model_view(
                None if outdoor is None else float(outdoor), 0.0, 0.0
            ),
            solar_kw,
        )
        result["cooling_factor"] = self.cooling.active_factor
        result["cooling_samples"] = self.cooling.samples
        return learned

    async def _observe_model(self, result: dict[str, Any]) -> bool:
        """Feed the hourly model sample; True when the model learned one."""
        room = result.get("room_temperature")
        outdoor = result.get("outdoor_temperature")
        demand = result.get("heat_demand")
        if self._shower_until is not None and dt_util.utcnow() >= self._shower_until:
            self._shower_until = None
        if (
            not self.enabled
            or self._room_fallback
            or self._shower_until is not None
            or room is None
            or outdoor is None
            or demand is None
            or result.get("mode") in ("waiting", "maintenance", "window")
            or result.get("window_open")
            or result.get("manual_override")
            or result.get("valve_maintenance")
            or not result.get("thermostat_setpoints")
        ):
            self._model_collector.reset()
            return False
        solar_kw, wind = self._weather_inputs()
        radiators = result.get("radiator_supply")
        # Heat asked for while the boiler delivers nothing (the house says so,
        # or it is the usual night pause and nothing here got warm): such an
        # hour shows the boiler, not the room.
        no_heat = radiators == SUPPLY_COLD or (
            float(demand) >= MODEL_ASKING_DEMAND
            and radiators != SUPPLY_WARM
            and (
                result.get("house_supply") == SUPPLY_COLD
                or bool(result.get("supply_usually_off"))
            )
        )
        at = dt_util.utcnow().timestamp()
        sample = self._model_collector.observe(
            at,
            float(room),
            float(demand) / 100,
            float(outdoor),
            solar_kw,
            wind,
            no_heat,
            radiators == SUPPLY_WARM,
        )
        return sample is not None and self.room_model.add(
            *sample, warm=self._model_collector.last_warm, at=at
        )

    async def async_seed_model(self) -> None:
        """Learn the room model from the recorder once, at its first start."""
        if self.room_model.ready or (
            self._model_seeded and self._seed_version >= SEED_VERSION
        ):
            return
        if "recorder" not in self.hass.config.components:
            return
        if self._model_seeded:
            # Learned from the recorder with an older rule: the recorder still
            # holds these hours, so start over instead of adding them twice.
            self.room_model = RoomModel()
        room_id = self.config.get(CONF_ROOM_TEMPERATURE_ENTITY)
        outdoor_id = self.config.get(CONF_OUTDOOR_TEMPERATURE_ENTITY)
        # A room set up only now has no recorded heat demand yet: the valves'
        # setpoints of the past days stand in for it.
        demand_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self.entry_id}_heat_demand"
        )
        if not room_id or not outdoor_id:
            return
        valves = [
            entity_id
            for entity_id in self._thermostat_ids()
            if entity_id not in self.skipped_valves
        ]
        from homeassistant.components.recorder import get_instance, history

        windows = [
            entity_id
            for _key, ids, _door, _open, _close in self._contact_groups()
            for entity_id in ids
        ]
        optional = [
            entity_id
            for entity_id in (
                self.config.get(CONF_SOLAR_RADIATION_ENTITY),
                self.config.get(CONF_WIND_SPEED_ENTITY),
            )
            if entity_id
        ]
        radiators = list(self._radiator_sensors().values())
        end = dt_util.utcnow()
        start = end - timedelta(days=MODEL_HISTORY_DAYS)
        ids = [
            entity_id
            for entity_id in (room_id, outdoor_id, demand_id, *windows, *optional, *radiators)
            if entity_id
        ]
        try:
            states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start,
                end,
                ids,
                None,
                True,
                False,
                False,
                True,
            )
            valve_states = await get_instance(self.hass).async_add_executor_job(
                history.get_significant_states,
                self.hass,
                start,
                end,
                valves,
                None,
                True,
                False,
                False,
                False,
            )
        except Exception:  # noqa: BLE001 - history is a bonus, never fatal
            _LOGGER.debug("Room model history not available", exc_info=True)
            return
        setpoints = {
            f"setpoint:{entity_id}": [
                (
                    state.last_updated.timestamp(),
                    "off" if state.state == "off" else str(
                        state.attributes.get("temperature")
                    ),
                )
                for state in valve_states.get(entity_id, [])
                if isinstance(state, State)
            ]
            for entity_id in valves
        }
        units = {
            entity_id: str(
                (self.hass.states.get(entity_id).attributes.get("unit_of_measurement"))
                if self.hass.states.get(entity_id) is not None
                else ""
            ).lower()
            for entity_id in optional
        }
        added = seed_room_model(
            self.room_model,
            {
                entity_id: [
                    (state.last_changed.timestamp(), state.state)
                    for state in states.get(entity_id, [])
                    if isinstance(state, State)
                ]
                for entity_id in ids
            }
            | setpoints,
            room_id=room_id,
            outdoor_id=outdoor_id,
            demand_id=demand_id or "",
            window_ids=windows,
            solar_id=self.config.get(CONF_SOLAR_RADIATION_ENTITY),
            wind_id=self.config.get(CONF_WIND_SPEED_ENTITY),
            units=units,
            start=start.timestamp(),
            end=end.timestamp(),
            radiator_ids=radiators,
            setpoint_ids=list(setpoints),
            full_gap=HEAT_DEMAND_FULL_GAP,
        )
        self._model_seeded = True
        self._seed_version = SEED_VERSION
        _LOGGER.debug("Room model learned %s hours from the recorder", added)
        if added:
            self._log(f"Raummodell hat {added} Stunden aus dem Verlauf gelernt")
        await self._save_learning()

    def _model_view(
        self, outdoor: float | None, solar_kw: float, wind: float
    ) -> ModelView | None:
        """The learned room equation with today's weather, once it is trusted."""
        if (
            outdoor is None
            or not self.config.get(CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL)
            or not self.room_model.ready
        ):
            return None
        return replace(
            self.room_model.view(outdoor, solar_kw, wind),
            cooling_factor=self.cooling.active_factor,
        )

    @staticmethod
    def _recovery_floor(
        view: ModelView, comfort: float, room: float, seconds: float
    ) -> float:
        """Lowest setback from which full heating gets back in ``seconds``.

        When comfort is out of reach today, the room has to get back to what
        it can reach instead.
        """
        reach = min(
            comfort, view.reachable(min(room, comfort)) - RECOVERY_REACH_MARGIN
        )
        return round(view.lowest_start(reach, seconds / 3600), 1)

    def _model_diagnostics(self, view: ModelView | None) -> dict[str, Any]:
        """What the room model learned, for sensors and the status."""
        model = self.room_model
        heat_output, loss, solar_gain, wind_loss = model.parameters()
        if not self.config.get(CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL):
            status = "Raummodell aus"
        elif not model.ready:
            status = (
                f"Lernt noch: {model.samples} Stunden, davon "
                f"{model.heating_samples} mit und {model.idle_samples} ohne Heizen"
            )
        elif view is None:
            status = "Bereit – Außentemperatur fehlt"
        elif not model.trusted:
            horizon = model.horizon_error
            if model.samples < TRUSTED_SAMPLES:
                status = (
                    f"Aktiv fürs Vorheizen – Absenkung und Sonne ab {TRUSTED_SAMPLES} "
                    f"Stunden (jetzt {model.samples} h)"
                )
            elif horizon is None:
                error = (
                    "–" if model.mean_error is None
                    else f"{model.mean_error:.2f}".replace(".", ",")
                )
                status = (
                    "Aktiv fürs Vorheizen – Absenkung und Sonne, sobald die "
                    f"Abweichung unter 0,12 °C/h liegt (jetzt {error}) oder "
                    f"{HORIZON_MIN} Drei-Stunden-Vergleiche vorliegen "
                    f"(jetzt {len(model.horizon_errors)})"
                )
            else:
                status = (
                    "Aktiv fürs Vorheizen – Absenkung und Sonne, sobald die "
                    "Vorhersage über 3 Stunden im Schnitt weniger als "
                    f"{_de_number(TRUSTED_HORIZON_ERROR)} °C daneben liegt "
                    f"(jetzt {_de_number(horizon)} °C)"
                )
        else:
            status = "Aktiv"
        ready = model.ready
        local = dt_util.now()
        return {
            "model_status": status,
            "model_ready": ready,
            "model_trusted": model.trusted,
            "model_samples": model.samples,
            "model_heating_samples": model.heating_samples,
            "model_idle_samples": model.idle_samples,
            "model_error": model.mean_error,
            "model_horizon_error": model.horizon_error,
            "heat_output": round(heat_output, 2) if ready else None,
            # °C per hour lost at 10 °C between room and outside.
            "heat_loss": round(loss * 10, 2) if ready else None,
            "solar_gain": round(solar_gain, 2) if ready else None,
            "wind_loss": round(wind_loss * 100, 3) if ready else None,
            "usage_now": self.usage.usage(local.weekday(), local.hour),
            "solar_pause": self._solar_pause,
        }

    async def async_start_learn_run(self, at: datetime | None = None) -> None:
        """Plan the calibration run for ``at``, or start it now."""
        now = dt_util.utcnow()
        if at is not None and dt_util.as_utc(at) > now:
            self.learn_run_at = dt_util.as_utc(at)
        else:
            self.learn_run_at = now
        self._pending_source = "Kalibrierlauf"
        await self.async_refresh()

    async def async_cancel_learn_run(self) -> None:
        """Drop a planned or running calibration run."""
        self.learn_run_at = None
        self.learn_run_until = None
        self._learn_run_target = None
        await self.async_refresh()

    def _learn_run(
        self, room_temperature: float, max_temperature: float | None
    ) -> tuple[str, str, float] | None:
        """(mode, status, target) while the calibration run heats fully."""
        now = dt_util.utcnow()
        if (
            self.learn_run_until is None
            and self.learn_run_at is not None
            and now >= self.learn_run_at
        ):
            self.learn_run_at = None
            self.learn_run_until = now + timedelta(seconds=LEARN_RUN_DURATION_SECONDS)
            self._learn_run_target = None
            self._log("Kalibrierlauf gestartet")
        if self.learn_run_until is None:
            return None
        if now >= self.learn_run_until:
            self.learn_run_until = None
            self._learn_run_target = None
            self._log("Kalibrierlauf beendet")
            return None
        if self._learn_run_target is None:
            top = max_temperature if max_temperature is not None else 30.0
            self._learn_run_target = min(
                top, round((room_temperature + LEARN_RUN_RISE) * 2) / 2
            )
        end = dt_util.as_local(self.learn_run_until).strftime("%H:%M")
        return (
            "learn_run",
            f"Kalibrierlauf – heizt voll bis {end} Uhr, das Raummodell lernt",
            self._learn_run_target,
        )

    def _weather_inputs(self) -> tuple[float, float]:
        """Solar radiation in kW/m² and wind speed in m/s (0 when unknown)."""
        solar = 0.0
        solar_state = self._state(CONF_SOLAR_RADIATION_ENTITY)
        value = _as_float(solar_state)
        if value is not None and value > 0:
            unit = str(solar_state.attributes.get("unit_of_measurement") or "")
            solar = solar_to_kw(value, unit.lower())
        wind = 0.0
        wind_state = self._state(CONF_WIND_SPEED_ENTITY)
        value = _as_float(wind_state)
        if value is not None and value > 0:
            unit = str(wind_state.attributes.get("unit_of_measurement") or "")
            wind = wind_to_ms(value, unit.lower())
        return min(solar, 1.5), min(wind, 40.0)
