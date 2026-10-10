"""Diagnostic sensors for the dynamic heating controller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DynamicHeatingCoordinator


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
    ),
    HeatingSensorDescription(
        key="forecast_condition",
        name="Wetterprognose",
        icon="mdi:weather-partly-cloudy",
    ),
    HeatingSensorDescription(
        key="solar_adjustment_minutes",
        name="Sonnenkorrektur Vorheizzeit",
        icon="mdi:weather-sunny",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="heating_rate",
        name="Gelernte Aufheizrate",
        icon="mdi:chart-line",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="cooling_rate",
        name="Gelernte Abkühlrate",
        icon="mdi:chart-bell-curve",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="heating_samples",
        name="Akzeptierte Aufheizmessungen",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="cooling_samples",
        name="Akzeptierte Abkühlmessungen",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="rejected_samples",
        name="Verworfene Lernmessungen",
        icon="mdi:filter-remove",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="forecast_evaluations",
        name="Ausgewertete Temperaturprognosen",
        icon="mdi:chart-bell-curve-cumulative",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="forecast_mae_c",
        name="Mittlerer Prognosefehler",
        icon="mdi:chart-line",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="last_forecast_error_c",
        name="Letzter Prognosefehler",
        icon="mdi:thermometer-alert",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="learning_status",
        name="Lernmodell Status",
        icon="mdi:brain",
    ),
    HeatingSensorDescription(
        key="last_observed_heating_rate",
        name="Letzte beobachtete Aufheizrate",
        icon="mdi:chart-line",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="last_observed_cooling_rate",
        name="Letzte beobachtete Abkühlrate",
        icon="mdi:chart-bell-curve",
        native_unit_of_measurement="°C/h",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="last_forecast_predicted_temperature",
        name="Letzte prognostizierte Temperatur",
        icon="mdi:thermometer-chevron-up",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="last_forecast_actual_temperature",
        name="Letzte tatsächliche Komforttemperatur",
        icon="mdi:thermometer-check",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="proximity_status",
        name="Geo-Fencing Status",
        icon="mdi:map-marker-check",
    ),
    HeatingSensorDescription(
        key="proximity_distance_m",
        name="Geo-Fencing Entfernung",
        icon="mdi:map-marker-distance",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="proximity_age_seconds",
        name="Alter der Standortdaten",
        icon="mdi:clock-alert-outline",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="proximity_updates_seen",
        name="Empfangene Standortupdates",
        icon="mdi:counter",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="proximity_average_update_interval_s",
        name="Mittleres Standortupdate-Intervall",
        icon="mdi:timer-sand",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
    ),
    HeatingSensorDescription(
        key="proximity_stale_events",
        name="Veraltete Standortereignisse",
        icon="mdi:map-marker-alert-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="proximity_invalid_events",
        name="Ungültige Standortereignisse",
        icon="mdi:alert-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="proximity_out_of_range_events",
        name="Außerhalb der Anfahrtsentfernung",
        icon="mdi:map-marker-off-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="proximity_approach_attempts",
        name="Erkannte Anfahrten",
        icon="mdi:car-arrow-left",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="proximity_confirmed_approaches",
        name="Bestätigte Anfahrten",
        icon="mdi:check-circle-outline",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    HeatingSensorDescription(
        key="preheat_minutes",
        name="Geschätzte Vorheizzeit",
        icon="mdi:timer-outline",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create controller sensors."""
    coordinator: DynamicHeatingCoordinator = entry.runtime_data
    async_add_entities(
        HeatingSensor(coordinator, entry, description) for description in SENSORS
    )


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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizungssteuerung",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    @property
    def native_value(self) -> str | float | int | None:
        """Return the latest controller value."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose decision context on the status sensor for easier troubleshooting."""
        if self.entity_description.key != "status" or not self.coordinator.data:
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
            "valve_maintenance",
            "heating_limit_reached",
            "present",
            "presence_status",
            "proximity_status",
            "proximity_distance_m",
            "proximity_direction",
            "proximity_age_seconds",
            "preheat_minutes",
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
        )
        return {
            key: self.coordinator.data[key]
            for key in diagnostic_keys
            if key in self.coordinator.data
        }
