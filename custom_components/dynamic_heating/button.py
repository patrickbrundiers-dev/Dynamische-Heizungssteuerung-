"""Buttons: one per quick mode in a room, the weekly report for the house."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_HOUSE,
    QUICK_ICONS,
    QUICK_LABELS,
    QUICK_MODES,
)
from .coordinator import DynamicHeatingCoordinator
from .house_entities import HouseEntity
from .select import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the report button (house) or the mode buttons (room)."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE:
        async_add_entities([SendReportButton(entry.runtime_data, entry, "send_report")])
        return
    async_add_entities(
        QuickModeButton(entry.runtime_data, entry, mode) for mode in QUICK_MODES
    )


class QuickModeButton(CoordinatorEntity[DynamicHeatingCoordinator], ButtonEntity):
    """Switches the room to one mode, like a Better Thermostat preset."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry, mode: str
    ) -> None:
        super().__init__(coordinator)
        self._mode = mode
        self._attr_name = QUICK_LABELS[mode]
        self._attr_icon = QUICK_ICONS[mode]
        self._attr_unique_id = f"{entry.entry_id}_quick_button_{mode}"
        self._attr_device_info = device_info(entry)

    @property
    def extra_state_attributes(self) -> dict[str, bool]:
        """Whether this mode is the active one (for dashboards)."""
        return {"active": self.coordinator.current_quick_mode == self._mode}

    async def async_press(self) -> None:
        """Pick this mode; it holds for the chosen Betriebsart-Dauer."""
        await self.coordinator.async_set_quick_mode(self._mode)


class SendReportButton(HouseEntity, ButtonEntity):
    """Sends the report of the current week now (the week keeps counting)."""

    _attr_name = "Wochenbericht senden"
    _attr_icon = "mdi:email-fast-outline"

    async def async_press(self) -> None:
        await self.house.async_send_report(reset=False)
