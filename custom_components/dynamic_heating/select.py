"""Quick selection of the heating mode of a dynamically heated room."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    QUICK_AUTO,
    QUICK_BOOST,
    QUICK_COMFORT,
    QUICK_ECO,
    QUICK_MODES,
    QUICK_OFF,
)
from .coordinator import DynamicHeatingCoordinator

_LABELS = {
    QUICK_AUTO: "Automatik",
    QUICK_COMFORT: "Komfort",
    QUICK_ECO: "Eco",
    QUICK_BOOST: "Boost",
    QUICK_OFF: "Aus",
}
_MODES = {label: mode for mode, label in _LABELS.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the quick mode selection."""
    coordinator: DynamicHeatingCoordinator = entry.runtime_data
    async_add_entities([QuickModeSelect(coordinator, entry)])


class QuickModeSelect(CoordinatorEntity[DynamicHeatingCoordinator], SelectEntity):
    """Automatik, or a mode picked by hand until the next schedule switch."""

    _attr_name = "Betriebsart"
    _attr_icon = "mdi:radiator"
    _attr_options = [_LABELS[mode] for mode in QUICK_MODES]

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_quick_mode"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizungssteuerung",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    @property
    def current_option(self) -> str:
        """Return the active quick mode."""
        return _LABELS[self.coordinator.current_quick_mode]

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """When a hand-picked mode or a boost ends."""
        until = (
            self.coordinator.boost_until
            if self.coordinator.boost_until is not None
            else self.coordinator.quick_until
        )
        return {"until": until.isoformat() if until is not None else None}

    async def async_select_option(self, option: str) -> None:
        """Switch to the picked mode."""
        await self.coordinator.async_set_quick_mode(_MODES[option])
