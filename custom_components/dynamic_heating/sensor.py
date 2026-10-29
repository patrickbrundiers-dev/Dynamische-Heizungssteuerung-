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
    UnitOfEnergy,
    UnitOfLength,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import CONF_ENTRY_TYPE, CONF_HUMIDITY_ENTITY, DOMAIN, ENTRY_TYPE_HOUSE
from .select import device_info
from .coordinator import DynamicHeatingCoordinator
from .house_entities import HouseEntity

# Only the house overview polls; room sensors follow their coordinator.
SCAN_INTERVAL = timedelta(seconds=30)


@dataclass(frozen=True, kw_only=True)
class HeatingSensorDescription(SensorEntityDescription):
    """Describe a coordinator-backed sensor."""

    key: str
    # Published rounded: a value that moves in its last digits would write a
    # new state to the database on every update.
    round_digits: int | None = None


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
        round_digits=1,
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
        round_digits=1,
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
        key="heat_energy_total",
        name="Wärmemenge",
        icon="mdi:radiator",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=1,
    ),
    HeatingSensorDescription(
        key="battery_days_left",
        name="Batterie fällig in",
        icon="mdi:battery-clock",
        native_unit_of_measurement=UnitOfTime.DAYS,
        entity_category=EntityCategory.DIAGNOSTIC,
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
    "model_horizon_error",
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
            HouseEnergySensor(entry.runtime_data, entry, "heat_energy"),
            HouseHeatLoadSensor(entry.runtime_data, entry, "heat_load"),
            HouseHomecomingSensor(entry.runtime_data, entry, "homecoming"),
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
    entities = [
        HeatEnergySensor(coordinator, entry, description)
        if description.key == "heat_energy_total"
        else entity
        for description, entity in zip(SENSORS, entities, strict=True)
    ]
    entities.append(DayPlanSensor(coordinator, entry, DAY_PLAN))
    entities.append(PreheatSensor(coordinator, entry, PREHEAT))
    entities.append(DataQualitySensor(coordinator, entry, DATA_QUALITY))
    entities.append(RadiatorTestSensor(coordinator, entry, RADIATOR_TEST))
    if coordinator.config.get(CONF_HUMIDITY_ENTITY):
        entities.append(AiringSensor(coordinator, entry, AIRING))
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
        value = self.coordinator.data.get(self.entity_description.key)
        digits = self.entity_description.round_digits
        if digits is not None and isinstance(value, (int, float)):
            return round(value, digits)
        return value

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
                "running_correction_minutes": data.get("punctuality_running_bias"),
                "from_similar_mornings": data.get("punctuality_similar"),
                "mornings_with_weather": data.get("punctuality_mornings"),
                "mornings": data.get("punctuality_results"),
            }
        if self.entity_description.key == "heat_energy_total":
            data = self.coordinator.data
            return {
                "today_kwh": data.get("heat_energy_today"),
                "yesterday_kwh": data.get("heat_energy_yesterday"),
                "last_7_days_kwh": data.get("heat_energy_7_days"),
                "radiator_power_w": data.get("radiator_power_w"),
                "estimated": True,
            }
        if self.entity_description.key == "battery_days_left":
            return {"batteries": self.coordinator.data.get("batteries")}
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
            "outdoor_warmer",
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
            ],
            # Levels a block can name instead of a temperature ("stufe: abend").
            "levels": self.coordinator.level_options(),
        }


class HeatEnergySensor(HeatingSensor, RestoreEntity):
    """The room's heat meter; never shows less than before a restart.

    The room's total is saved every 15 minutes, so after a restart it can be
    a little behind the last shown value; a falling meter would count as a
    new one in the statistics.
    """

    _floor = 0.0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        try:
            self._floor = float(last.state) if last is not None else 0.0
        except ValueError:
            self._floor = 0.0

    @property
    def native_value(self) -> float | None:
        value = super().native_value
        if value is None:
            return None
        self._floor = max(self._floor, float(value))
        return round(self._floor, 2)


DAY_PLAN = HeatingSensorDescription(
    key="day_plan",
    name="Tagesplan",
    icon="mdi:calendar-clock",
)


class DayPlanSensor(HeatingSensor):
    """What the room will do in the next 24 hours; the curve in the attributes."""

    # The curve changes every 15 minutes and is only useful live.
    _unrecorded_attributes = frozenset({"forecast", "calculated_at", "segments"})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.plan_attributes()


PREHEAT = HeatingSensorDescription(
    key="preheat_minutes",
    name="Geschätzte Vorheizzeit",
    icon="mdi:timer-outline",
    native_unit_of_measurement="min",
    state_class=SensorStateClass.MEASUREMENT,
)


class PreheatSensor(HeatingSensor):
    """Minutes of preheating; how they came about in the attributes."""

    # The parts move with the room temperature and are only useful live.
    _unrecorded_attributes = frozenset({"parts", "breakdown"})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        data = self.coordinator.data
        return {
            "breakdown": data.get("preheat_breakdown"),
            "parts": data.get("preheat_parts"),
        }


AIRING = HeatingSensorDescription(
    key="airing",
    name="Lüften",
    icon="mdi:window-open-variant",
)


class AiringSensor(HeatingSensor):
    """Is airing worth it for the humidity? Display only."""

    _unrecorded_attributes = frozenset(
        {
            "relative_humidity",
            "absolute_humidity",
            "dew_point",
            "outdoor_absolute_humidity",
            "humidity_after_airing",
        }
    )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        details = self.coordinator.data.get("airing_details") or {}
        return {key: value for key, value in details.items() if key != "text"}


DATA_QUALITY = HeatingSensorDescription(
    key="data_quality",
    name="Datenqualität",
    icon="mdi:database-check-outline",
    entity_category=EntityCategory.DIAGNOSTIC,
)


class DataQualitySensor(HeatingSensor):
    """Do all sources of the room still report? Which ones do not?"""

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        data = self.coordinator.data
        return {
            "problems": data.get("data_quality_problems") or [],
            "sources": data.get("data_quality_sources") or {},
        }


RADIATOR_TEST = HeatingSensorDescription(
    key="radiator_test",
    name="Heizkörpertest",
    icon="mdi:radiator",
    entity_category=EntityCategory.DIAGNOSTIC,
)


class RadiatorTestSensor(HeatingSensor):
    """Result of the last radiator test (button "Heizkörpertest starten")."""

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        result = self.coordinator.radiator_test_result
        if not result:
            return None
        return {
            "tested_at": result.get("at"),
            "result": result.get("code"),
            "valve_rise": result.get("valves"),
            "room_rise": result.get("room_rise"),
        }


class HouseHomecomingSensor(HouseEntity, SensorEntity):
    """When somebody usually comes home today; every weekday in the attributes."""

    _attr_name = "Übliche Heimkehr"
    _attr_icon = "mdi:home-import-outline"
    _attr_should_poll = True

    @property
    def native_value(self) -> str | None:
        return self.house.homecoming()["today"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.house.homecoming()
        return {
            "weekdays": info["week"],
            "homecomings_seen": info["count"],
            "learned_in": info["room"],
        }


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


class HouseHeatLoadSensor(HouseEntity, SensorEntity):
    """What the house needs at -10 °C, from the rooms' learned models."""

    _attr_name = "Heizlast"
    _attr_icon = "mdi:home-thermometer"
    _attr_should_poll = True
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> float | None:
        load = self.house.heat_load()
        return load["total_kw"] if load["rooms"] else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        load = self.house.heat_load()
        return {
            "outdoor_temperature": load["outdoor_temperature"],
            "rooms": load["rooms"],
            "text": load["text"],
            "estimated": True,
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


class HouseEnergySensor(HouseEntity, SensorEntity, RestoreEntity):
    """Estimated heat of all rooms, e.g. as gas source of the energy dashboard.

    Each room's last total is kept (also over restarts): a room still starting
    or reloading would otherwise make the sum drop, which the statistics take
    for a new meter and count twice.
    """

    _attr_name = "Wärmemenge"
    _attr_icon = "mdi:radiator"
    _attr_should_poll = True
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 1

    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self._totals: dict[str, float] = {}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        stored = last.attributes.get("room_totals") if last is not None else None
        if isinstance(stored, dict):
            for entry_id, value in stored.items():
                if isinstance(value, (int, float)) and value >= 0:
                    self._totals[str(entry_id)] = float(value)

    def _rooms(self) -> dict[str, dict[str, Any]]:
        rooms = {}
        for room in self.house.rooms():
            data = room.data
            if data and data.get("heat_energy_total") is not None:
                rooms[room.room_name] = data
                # A room's own total can restart a little behind (it is saved
                # every 15 minutes); the house total must not fall with it.
                self._totals[room.entry_id] = max(
                    self._totals.get(room.entry_id, 0.0),
                    float(data["heat_energy_total"]),
                )
        return rooms

    @property
    def native_value(self) -> float | None:
        self._rooms()
        if not self._totals:
            return None
        return round(sum(self._totals.values()), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rooms = self._rooms()

        def total(key: str) -> float:
            return round(sum(data.get(key) or 0.0 for data in rooms.values()), 2)

        return {
            "today_kwh": total("heat_energy_today"),
            "yesterday_kwh": total("heat_energy_yesterday"),
            "last_7_days_kwh": total("heat_energy_7_days"),
            "rooms_last_7_days_kwh": {
                name: data.get("heat_energy_7_days") for name, data in rooms.items()
            },
            "room_totals": dict(self._totals),
            "estimated": True,
        }
