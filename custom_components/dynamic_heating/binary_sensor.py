"""Problem sensor for the thermostats of a dynamically heated room."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DynamicHeatingCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the thermostat problem sensor."""
    coordinator: DynamicHeatingCoordinator = entry.runtime_data
    async_add_entities([ThermostatProblemSensor(coordinator, entry)])


class ThermostatProblemSensor(
    CoordinatorEntity[DynamicHeatingCoordinator], BinarySensorEntity
):
    """On while a thermostat is unreachable, low on battery or reports a fault."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_name = "Thermostat-Problem"
    _attr_icon = "mdi:radiator-off"

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_thermostat_problem"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizungssteuerung",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether any thermostat of the room has a problem."""
        if not self.coordinator.data:
            return None
        return bool(self.coordinator.data.get("thermostat_warnings"))

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """List the problems per thermostat."""
        if not self.coordinator.data:
            return None
        return {"warnings": self.coordinator.data.get("thermostat_warnings") or {}}
