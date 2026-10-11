"""End of the vacation for the house-wide mode."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .house_entities import HouseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the vacation end (house entry only)."""
    async_add_entities([VacationUntil(entry.runtime_data, entry, "vacation_until")])


class VacationUntil(HouseEntity, DateTimeEntity):
    """When the vacation ends; the rooms are warm again by then."""

    _attr_name = "Urlaub bis"
    _attr_icon = "mdi:airplane-landing"

    @property
    def native_value(self) -> datetime | None:
        return self.house.vacation_until

    async def async_set_value(self, value: datetime) -> None:
        await self.house.async_set_vacation_until(value)
