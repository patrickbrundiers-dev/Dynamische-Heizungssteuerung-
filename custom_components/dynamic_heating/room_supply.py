"""Radiators and the central heating: are they warm, when does the boiler deliver, balance between radiators.

Part of the room coordinator (``DynamicHeatingCoordinator``); the
methods use its state and run exactly as they did inside it.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .const import (
    CONF_HOLD_BEFORE_PAUSE,
    DEFAULT_HOLD_BEFORE_PAUSE,
    HOUSE_DATA_KEY,
    DOMAIN,
)
from .logic import HeatingDecision
from .radiator import (
    COLD,
    SUPPLY_COLD,
    SUPPLY_IDLE,
    SUPPLY_PARTLY,
    SUPPLY_WAITING,
    SUPPLY_WARM,
    RadiatorStats,
    RadiatorTracker,
    SupplyProfile,
    IDLE,
    balance_verdict,
    combined_supply,
    judged_supply,
    room_supply,
)
from .room_util import _as_float


class SupplyMixin:
    """Radiators and the central heating."""

    def _device_sensor(self, entity_id: str, suffix: str) -> str | None:
        """A sensor of the thermostat's device whose id ends in ``suffix``."""
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)
        if entry is None or not entry.device_id:
            return None
        for device_entry in er.async_entries_for_device(registry, entry.device_id):
            if device_entry.domain == "sensor" and (
                device_entry.entity_id.endswith(suffix)
                or (device_entry.unique_id or "").endswith(suffix)
            ):
                return device_entry.entity_id
        return None

    def _radiator_sensors(self) -> dict[str, str]:
        """Valve -> sensor with the valve's own (radiator-side) temperature."""
        sensors = {}
        for entity_id in self._thermostat_ids():
            if entity_id in self.skipped_valves:
                continue
            sensor_id = self._device_sensor(entity_id, "device_temperature")
            if sensor_id:
                sensors[entity_id] = sensor_id
        return sensors

    def _observe_radiators(self, result: dict[str, Any]) -> bool:
        """Judge whether heat reaches the radiators; True when an hour of the
        central heating's times was learned."""
        sensors = self._radiator_sensors() if self.enabled else {}
        for entity_id in list(self._radiators):
            if entity_id not in sensors:
                self._radiators.pop(entity_id)
        room = result.get("room_temperature")
        demand = result.get("heat_demand")
        if (
            result.get("mode") in ("window", "maintenance", "season_off", "outdoor_warm")
            or result.get("window_open")
        ):
            demand = 0
        at = dt_util.utcnow().timestamp()
        states = {
            entity_id: self._radiators.setdefault(
                entity_id, RadiatorTracker()
            ).observe(
                at,
                demand,
                _as_float(self.hass.states.get(sensor_id)),
                None if room is None else float(room),
            )
            for entity_id, sensor_id in sensors.items()
        }
        target = result.get("target_temperature")
        response = self._response.observe(
            at,
            demand,
            None if room is None else float(room),
            None if target is None else float(target),
        )
        result["room_response"] = response
        supply = combined_supply(room_supply(states), response)
        asking = response != IDLE or any(
            tracker.heating_since is not None
            for entity_id, tracker in self._radiators.items()
            if entity_id in sensors
        )
        judged = judged_supply(supply, asking)
        result["supply_judged"] = judged
        now = dt_util.utcnow()
        local = dt_util.as_local(now)
        seconds = (
            0.0 if self._supply_at is None else (now - self._supply_at).total_seconds()
        )
        self._supply_at = now
        learned = self.supply.observe(local.hour, judged, seconds)
        house = self._house()
        house_verdict = (
            None if house is None else house.supply_verdict({self.entry_id: judged})
        )
        if SUPPLY_COLD not in (supply, house_verdict):
            # Without hot water in the house, cold radiators say nothing
            # about their balance.
            learned = self._learn_balance(sensors) or learned
        else:
            for tracker in self._radiators.values():
                tracker.period = None
        profile = self.supply_profile
        result["radiators"] = {
            self._friendly_name(entity_id): state for entity_id, state in states.items()
        }
        result["radiator_supply"] = supply
        result["house_supply"] = house_verdict
        result["supply_usually_off"] = profile.usually_off(local.hour)
        result["supply_off_hours"] = profile.off_hours()
        result["supply_today"] = profile.as_list()
        result["supply_source"] = "Haus" if profile is not self.supply else "Raum"
        result["radiator_status"] = self._radiator_text(
            states, supply, local.hour, house_verdict
        )
        if supply == SUPPLY_COLD and result.get("status"):
            result["status"] = f"{result['status']} – Heizkörper bleiben kalt"
        balance, weak = balance_verdict(
            {
                self._friendly_name(entity_id): self.radiator_stats.setdefault(
                    entity_id, RadiatorStats()
                )
                for entity_id in sensors
            }
        )
        result["radiator_balance"] = balance
        result["radiator_balance_weak"] = weak
        result["radiator_stats"] = {
            self._friendly_name(entity_id): self.radiator_stats[entity_id].as_dict()
            for entity_id in sensors
            if entity_id in self.radiator_stats
        }
        return learned

    def _house(self):
        """The house manager, if a house entry is set up."""
        return self.hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)

    @property
    def supply_profile(self) -> SupplyProfile:
        """When the central heating delivers: the house's view, else the room's."""
        house = self._house()
        profile = house.supply_profile() if house is not None else None
        return profile if profile is not None else self.supply

    def _learn_balance(self, sensors: dict[str, str]) -> bool:
        """Count finished heating periods per radiator; True when one was added.

        A period in which no radiator of the room got warm shows the central
        heating, not the radiators, and is skipped.
        """
        periods = {
            entity_id: tracker.period
            for entity_id, tracker in self._radiators.items()
            if entity_id in sensors and tracker.period is not None
        }
        if not periods or all(
            period.warmup_minutes is None for period in periods.values()
        ):
            return False
        for entity_id, period in periods.items():
            self.radiator_stats.setdefault(entity_id, RadiatorStats()).add(period)
        return True

    def _radiator_text(
        self,
        states: dict[str, str],
        supply: str | None,
        hour: int,
        house_verdict: str | None = None,
    ) -> str | None:
        """What the radiators say, in a few words."""
        if supply is None:
            return None
        if supply == SUPPLY_COLD and house_verdict == SUPPLY_WARM:
            return (
                "Kalt, obwohl die Zentralheizung liefert (andere Räume werden "
                "warm) – Ventile und Heizkörper prüfen"
            )
        if supply == SUPPLY_COLD:
            profile = self.supply_profile
            text = "Kalt – die Zentralheizung liefert keine Wärme"
            if profile.usually_off(hour):
                next_hour = profile.next_on_hour(hour)
                text += (
                    f" (um diese Zeit üblich, meist wieder ab {next_hour}:00 Uhr)"
                    if next_hour is not None
                    else " (um diese Zeit üblich)"
                )
            return text
        if supply == SUPPLY_PARTLY and house_verdict == SUPPLY_COLD:
            return "Kalt – die Zentralheizung liefert keine Wärme"
        if supply == SUPPLY_PARTLY:
            cold = ", ".join(
                self._friendly_name(entity_id)
                for entity_id, state in states.items()
                if state == COLD
            )
            return f"{cold} bleibt kalt – entlüften oder Ventil prüfen"
        return {
            SUPPLY_WARM: "Warm",
            SUPPLY_WAITING: "Werden warm",
            SUPPLY_IDLE: "Kein Heizbedarf",
        }.get(supply, supply)

    def _supply_wait(
        self,
        decision: HeatingDecision,
        *,
        comfort_temperature: float,
        eco_temperature: float,
        schedule_active: bool,
    ) -> HeatingDecision:
        """Fit preheating and the evening to the central heating's pauses.

        Preheating in an hour in which the central heating usually delivers
        nothing only keeps the valves open in vain: it waits until the usual
        end of the pause (unless the radiators are warm right now). With
        the option on, comfort that ended shortly before the usual night
        pause is kept until the pause starts.
        """
        profile = self.supply_profile
        local = dt_util.now()
        hour = local.hour
        last = self.data if isinstance(self.data, dict) else {}
        if (
            decision.mode == "preheat"
            and profile.usually_off(hour)
            and last.get("house_supply") != SUPPLY_WARM
            and last.get("radiator_supply") != SUPPLY_WARM
        ):
            next_hour = profile.next_on_hour(hour)
            # Timed afresh once the central heating delivers again.
            self._preheat_event = None
            parts = decision.preheat_parts
            if parts is not None and next_hour is not None:
                parts = {**parts, "supply_wait_until": f"{next_hour:02d}:00"}
            return replace(
                decision,
                preheat_parts=parts,
                status="Vorheizen wartet auf die Zentralheizung"
                + (
                    f" (liefert meist ab {next_hour}:00 Uhr)"
                    if next_hour is not None
                    else ""
                ),
                mode="eco",
                target_temperature=eco_temperature,
            )
        if (
            self.config.get(CONF_HOLD_BEFORE_PAUSE, DEFAULT_HOLD_BEFORE_PAUSE)
            and decision.mode == "eco"
            and not schedule_active
            and self._comfort_ended_at is not None
            and dt_util.utcnow() - self._comfort_ended_at <= timedelta(hours=2)
            and not profile.usually_off(hour)
            and any(profile.usually_off((hour + step) % 24) for step in (1, 2))
        ):
            return replace(
                decision,
                status="Komfort bis zur Nachtpause der Zentralheizung",
                mode="comfort",
                target_temperature=comfort_temperature,
            )
        return decision
