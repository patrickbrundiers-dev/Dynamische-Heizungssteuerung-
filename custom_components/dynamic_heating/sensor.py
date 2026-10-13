"""Diagnostic sensors for the dynamic heating controller."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfLength,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, DOMAIN, ENTRY_TYPE_HOUSE
from .select import device_info
from .coordinator import DynamicHeatingCoordinator
from .house_entities import HouseEntity

# Only the house overview polls; room sensors follow their coordinator.
SCAN_INTERVAL = timedelta(seconds=30)


@dataclass(frozen=True, kw_only=True)
class HeatingSensorDescription(SensorEntityDescription):
    """Describe a coordinator-backed sensor."""

    key: str


SENSORS = (
    HeatingSensorDescription(
        key="status",
        name="Status",
        icon="mdi:home-thermometer",
    ),
    HeatingSensorDescription(
        key="room_temperature",
        name="Raumtemperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="temperature_trend",
        name="Temperaturtrend",
        icon="mdi:chart-line-variant",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="outdoor_temperature",
        name="Außentemperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="target_temperature",
        name="Berechnete Solltemperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="current_setpoint",
        name="Aktueller Thermostat-Sollwert",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="projected_temperature",
        name="Prognostizierte Raumtemperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="forecast_condition",
        name="Wetterprognose",
        icon="mdi:weather-partly-cloudy",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="solar_adjustment_minutes",
        name="Sonnenkorrektur Vorheizzeit",
        icon="mdi:weather-sunny",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="heating_rate",
        name="Aufheizrate",
        icon="mdi:chart-line",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="cooling_rate",
        name="Abkühlrate",
        icon="mdi:chart-bell-curve",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="proximity_status",
        name="Geo-Fencing Status",
        icon="mdi:map-marker-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_distance_m",
        name="Geo-Fencing Entfernung",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_age_seconds",
        name="Alter der Standortdaten",
        icon="mdi:clock-alert-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_updates_seen",
        name="Empfangene Standortupdates",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_average_update_interval_s",
        name="Mittleres Standortupdate-Intervall",
        icon="mdi:timer-sand",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_stale_events",
        name="Veraltete Standortereignisse",
        icon="mdi:map-marker-alert-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_invalid_events",
        name="Ungültige Standortereignisse",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_out_of_range_events",
        name="Außerhalb der Anfahrtsentfernung",
        icon="mdi:map-marker-off-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_approach_attempts",
        name="Erkannte Anfahrten",
        icon="mdi:car-arrow-left",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="proximity_confirmed_approaches",
        name="Bestätigte Anfahrten",
        icon="mdi:check-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    HeatingSensorDescription(
        key="preheat_minutes",
        name="Geschätzte Vorheizzeit",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="heat_demand",
        name="Wärmebedarf",
        icon="mdi:fire",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="overshoot",
        name="Gelerntes Überschwingen",
        icon="mdi:chart-bell-curve",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="heating_limit_basis",
        name="Außentemperatur für die Heizgrenze",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="forecast_temperature",
        name="Vorhergesagte Außentemperatur zum Komfortbeginn",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="model_status",
        name="Raummodell",
        icon="mdi:home-analytics",
    ),
    HeatingSensorDescription(
        key="radiator_status",
        name="Heizkörper",
        icon="mdi:radiator",
    ),
    HeatingSensorDescription(
        key="radiator_balance",
        name="Heizkörper-Abgleich",
        icon="mdi:scale-balance",
    ),
    HeatingSensorDescription(
        key="selftest",
        name="Selbsttest",
        icon="mdi:clipboard-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="reachable_temperature",
        name="Erreichbare Temperatur",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="heat_output",
        name="Heizleistung",
        icon="mdi:radiator",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="heat_loss",
        name="Wärmeverlust je 10 °C Unterschied",
        icon="mdi:home-thermometer-outline",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    HeatingSensorDescription(
        key="punctuality",
        name="Pünktlichkeit",
        icon="mdi:clock-check-outline",
    ),
    HeatingSensorDescription(
        key="schedule_suggestion",
        name="Zeitplan-Vorschlag",
        icon="mdi:calendar-edit",
    ),
    HeatingSensorDescription(
        key="heating_hours_total",
        name="Heizstunden",
        icon="mdi:radiator",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    HeatingSensorDescription(
        key="degree_days_total",
        name="Heizgradtage",
        icon="mdi:thermometer-low",
        native_unit_of_measurement="Kd",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    HeatingSensorDescription(
        key="hours_per_degree_day",
        name="Heizstunden je Gradtag",
        icon="mdi:chart-line",
        native_unit_of_measurement="h/Kd",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    HeatingSensorDescription(
        key="solar_gain",
        name="Sonnengewinn je kW/m²",
        icon="mdi:white-balance-sunny",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)

# Sensors of the old sample learner and its forecast check, replaced by the
# room model in 0.9.2; their values stay in the status sensor's attributes.
REMOVED_SENSORS = (
    "heating_samples",
    "cooling_samples",
    "rejected_samples",
    "forecast_evaluations",
    "forecast_mae_c",
    "last_forecast_error_c",
    "learning_status",
    "last_observed_heating_rate",
    "last_observed_cooling_rate",
    "last_forecast_predicted_temperature",
    "last_forecast_actual_temperature",
)

# Extra attributes of the room model sensor.
_MODEL_KEYS = (
    "model_ready",
    "model_trusted",
    "model_samples",
    "model_heating_samples",
    "model_idle_samples",
    "model_error",
    "wind_loss",
    "setback_floor",
    "usage_now",
    "solar_pause",
)

# Extra attributes of the radiator sensor.
_RADIATOR_KEYS = (
    "radiators",
    "radiator_supply",
    "supply_usually_off",
    "supply_off_hours",
    "supply_today",
    "supply_source",
    "house_supply",
)

# Extra attributes of the radiator balance sensor.
_BALANCE_KEYS = ("radiator_stats", "radiator_balance_weak")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create controller sensors, or the overview for the house entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE:
        async_add_entities([
            HouseOverviewSensor(entry.runtime_data, entry, "overview"),
            HouseHeatDemandSensor(entry.runtime_data, entry, "heat_demand"),
            HouseSupplySensor(entry.runtime_data, entry, "central_heating"),
            HouseGeofenceSensor(entry.runtime_data, entry, "geofencing"),
        ])
        return
    coordinator: DynamicHeatingCoordinator = entry.runtime_data
    registry = er.async_get(hass)
    for key in REMOVED_SENSORS:
        if entity_id := registry.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_{key}"
        ):
            registry.async_remove(entity_id)
    entities: list[SensorEntity] = [
        HeatingSensor(coordinator, entry, description) for description in SENSORS
    ]
    entities.append(DayPlanSensor(coordinator, entry, DAY_PLAN))
    async_add_entities(entities)


class HeatingSensor(CoordinatorEntity[DynamicHeatingCoordinator], SensorEntity):
    """Present a value calculated by the coordinator."""

    entity_description: HeatingSensorDescription

    def __init__(
        self,
        coordinator: DynamicHeatingCoordinator,
        entry: ConfigEntry,
        description: HeatingSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> str | float | int | None:
        """Return the latest controller value."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose decision context on the status sensor for easier troubleshooting."""
        if not self.coordinator.data:
            return None
        if self.entity_description.key == "model_status":
            data = self.coordinator.data
            # Today's learned room use per hour (0 = never, 1 = always).
            return {key: data[key] for key in _MODEL_KEYS if key in data} | {
                "usage_today": self.coordinator.usage.as_list()[
                    dt_util.now().weekday()
                ]
            }
        if self.entity_description.key == "radiator_status":
            data = self.coordinator.data
            return {key: data[key] for key in _RADIATOR_KEYS if key in data}
        if self.entity_description.key == "radiator_balance":
            data = self.coordinator.data
            return {key: data[key] for key in _BALANCE_KEYS if key in data}
        if self.entity_description.key == "punctuality":
            data = self.coordinator.data
            return {
                "preheat_correction_minutes": data.get("punctuality_bias"),
                "mornings": data.get("punctuality_results"),
            }
        if self.entity_description.key == "schedule_suggestion":
            return {"suggestions": self.coordinator.data.get("schedule_suggestions")}
        if self.entity_description.key == "selftest":
            selftest = self.coordinator.selftest
            if selftest is None:
                return None
            return {
                "last_run": selftest["at"],
                "problems": selftest["problems"],
                "checks": {
                    check["name"]: (
                        "ok" if check["ok"] else
                        "info" if check["ok"] is None else "Problem"
                    )
                    + f" – {check['detail']}"
                    for check in selftest["checks"]
                },
            }
        if self.entity_description.key != "status":
            return None

        diagnostic_keys = (
            "mode",
            "enabled",
            "schedule_active",
            "next_event",
            "window_open",
            "window_contact_open",
            "heating_season",
            "thermostat_setpoints",
            "unavailable_thermostats",
            "room_temperature_source",
            "thermostat_warnings",
            "external_temperature_thermostats",
            "comfort_temperature",
            "schedule_comfort_temperature",
            "eco_temperature",
            "active_schedule",
            "boost_until",
            "valve_maintenance",
            "heating_limit_reached",
            "heating_limit_basis",
            "heating_limit_source",
            "paused_features",
            "house_calendar",
            "skipped_valves",
            "valve_divergence",
            "window_change",
            "last_change_source",
            "last_change_at",
            "overshoot",
            "overshoot_samples",
            "present",
            "presence_status",
            "proximity_status",
            "proximity_distance_m",
            "proximity_direction",
            "proximity_age_seconds",
            "preheat_minutes",
            "forecast_temperature",
            "heat_demand",
            "heat_demand_source",
            "heating_rate",
            "cooling_rate",
            "projected_temperature",
            "target_temperature",
            "current_setpoint",
            "forecast_condition",
            "solar_adjustment_minutes",
            "decision_status",
            "control_error",
            "manual_override",
            "heating_samples",
            "cooling_samples",
            "rejected_samples",
            "last_observed_heating_rate",
            "last_observed_cooling_rate",
            "last_learning_type",
            "learning_status",
            "last_learning_sample_at",
            "forecast_evaluations",
            "forecast_mae_c",
            "last_forecast_error_c",
            "last_forecast_predicted_temperature",
            "last_forecast_actual_temperature",
            "last_forecast_event",
            "last_forecast_error_at",
            "proximity_updates_seen",
            "proximity_update_interval_count",
            "proximity_average_update_interval_s",
            "proximity_stale_events",
            "proximity_invalid_events",
            "proximity_out_of_range_events",
            "proximity_approach_attempts",
            "proximity_confirmed_approaches",
            "proximity_last_update_at",
            "reachable_temperature",
            "setback_floor",
            "model_status",
            "solar_pause",
            "radiator_supply",
            "aggressive_setpoint",
        )
        return {
            key: self.coordinator.data[key]
            for key in diagnostic_keys
            if key in self.coordinator.data
        } | {
            # The room card's schedule editor offers these to edit.
            "schedules": [
                {"entity_id": entity_id, "name": name}
                for entity_id, name in self.coordinator.schedule_options()
            ]
        }


DAY_PLAN = HeatingSensorDescription(
    key="day_plan",
    name="Tagesplan",
    icon="mdi:calendar-clock",
)


class DayPlanSensor(HeatingSensor):
    """What the room will do in the next 24 hours; the curve in the attributes."""

    # The curve changes every 15 minutes and is only useful live.
    _unrecorded_attributes = frozenset({"forecast", "calculated_at"})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.plan_attributes()


class HouseSupplySensor(HouseEntity, SensorEntity):
    """Does the central heating deliver? Judged by the radiators of all rooms."""

    _attr_name = "Zentralheizung"
    _attr_icon = "mdi:water-boiler"
    _attr_should_poll = True

    @property
    def native_value(self) -> str:
        return self.house.supply_text()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "delivers": self.house.supply_state,
            "off_hours": self.house.supply.off_hours(),
            "profile": self.house.supply.as_list(),
            "rooms": {
                room.room_name: (room.data or {}).get("radiator_supply")
                for room in self.house.rooms()
            },
        }


class HouseGeofenceSensor(HouseEntity, SensorEntity):
    """Geo-fencing once for the house: the rooms share people and zone."""

    _attr_name = "Geo-Fencing"
    _attr_icon = "mdi:map-marker-check"
    _attr_should_poll = True

    def _room(self):
        rooms = [
            room
            for room in sorted(self.house.rooms(), key=lambda room: room.room_name)
            if room.data
            and room.data.get("proximity_status") not in (None, "Proximity nicht konfiguriert")
        ]
        return rooms[0] if rooms else None

    @property
    def native_value(self) -> str | None:
        room = self._room()
        return None if room is None else room.data.get("proximity_status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        room = self._room()
        if room is None:
            return {}
        data = room.data
        return {
            "room": room.room_name,
            "distance_m": data.get("proximity_distance_m"),
            "direction": data.get("proximity_direction"),
            "age_seconds": data.get("proximity_age_seconds"),
            **{
                key.removeprefix("proximity_"): data.get(key)
                for key in (
                    "proximity_updates_seen",
                    "proximity_average_update_interval_s",
                    "proximity_stale_events",
                    "proximity_invalid_events",
                    "proximity_out_of_range_events",
                    "proximity_approach_attempts",
                    "proximity_confirmed_approaches",
                )
            },
        }


class HouseHeatDemandSensor(HouseEntity, SensorEntity):
    """Highest heat demand of all rooms, e.g. for a boiler or flow temperature."""

    _attr_name = "Wärmebedarf"
    _attr_icon = "mdi:fire"
    _attr_should_poll = True
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def _demands(self) -> dict[str, int]:
        return {
            room.room_name: room.data.get("heat_demand")
            for room in self.house.rooms()
            if room.data and room.data.get("heat_demand") is not None
        }

    @property
    def native_value(self) -> int:
        return max(self._demands().values(), default=0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        demands = self._demands()
        return {
            "average": round(sum(demands.values()) / len(demands)) if demands else 0,
            "rooms": demands,
        }


class HouseOverviewSensor(HouseEntity, SensorEntity):
    """Number of rooms heating right now; every room in the attributes."""

    _attr_name = "Räume heizen"
    _attr_icon = "mdi:home-thermometer-outline"
    _attr_should_poll = True
    _attr_native_unit_of_measurement = "Räume"

    @property
    def native_value(self) -> int:
        return sum(
            1
            for room in self.house.rooms_overview()
            if room["room_temperature"] is not None
            and room["target_temperature"] is not None
            and room["target_temperature"] > room["room_temperature"]
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rooms = self.house.rooms_overview()
        return {
            "house_mode": self.house.mode,
            "vacation_until": (
                self.house.vacation_until.isoformat()
                if self.house.vacation_until
                else None
            ),
            "rooms": rooms,
            "problems": [room["room"] for room in rooms if room["problem"]],
        }
