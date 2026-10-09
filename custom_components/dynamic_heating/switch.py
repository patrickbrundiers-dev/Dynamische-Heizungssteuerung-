"""Control switch for the dynamic heating integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    """Set up the opt-in control switch."""
    coordinator: DynamicHeatingCoordinator = entry.runtime_data
    async_add_entities([DynamicHeatingSwitch(coordinator, entry)])


class DynamicHeatingSwitch(CoordinatorEntity[DynamicHeatingCoordinator], SwitchEntity):
    """Enable or disable writing target temperatures to the configured thermostat."""

    _attr_icon = "mdi:heat-wave"
    _attr_name = "Regelung aktiv"

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_enabled"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizungssteuerung",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    @property
    def is_on(self) -> bool:
        """Return whether the controller may apply its calculated target."""
        return self.coordinator.enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Enable control and immediately evaluate the current conditions."""
        self.coordinator.enabled = True
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable control; it will remain disabled after Home Assistant restarts."""
        self.coordinator.enabled = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
