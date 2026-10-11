"""Send the weekly heating report right away."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .house_entities import HouseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the report button (house entry only)."""
    async_add_entities([SendReportButton(entry.runtime_data, entry, "send_report")])


class SendReportButton(HouseEntity, ButtonEntity):
    """Sends the report of the current week now (the week keeps counting)."""

    _attr_name = "Wochenbericht senden"
    _attr_icon = "mdi:email-fast-outline"

    async def async_press(self) -> None:
        await self.house.async_send_report(reset=False)
