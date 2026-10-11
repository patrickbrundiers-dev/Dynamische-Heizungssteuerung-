"""Entities of the house-wide settings entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN
from .house import HouseManager


class HouseEntity(Entity):
    """Base for entities that follow the house manager."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, house: HouseManager, entry: ConfigEntry, key: str) -> None:
        self.house = house
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizung Haus",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.house.async_add_listener(self.async_write_ha_state))
