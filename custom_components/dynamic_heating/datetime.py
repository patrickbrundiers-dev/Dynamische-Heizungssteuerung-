"""End of the vacation (house) and the planned calibration run (room)."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ENTRY_TYPE, ENTRY_TYPE_HOUSE
from .coordinator import DynamicHeatingCoordinator
from .house_entities import HouseEntity
from .select import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the vacation end (house) or the calibration time (room)."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE:
        async_add_entities([VacationUntil(entry.runtime_data, entry, "vacation_until")])
        return
    async_add_entities([LearnRunAt(entry.runtime_data, entry)])


class VacationUntil(HouseEntity, DateTimeEntity):
    """When the vacation ends; the rooms are warm again by then."""

    _attr_name = "Urlaub bis"
    _attr_icon = "mdi:airplane-landing"

    @property
    def native_value(self) -> datetime | None:
        return self.house.vacation_until

    async def async_set_value(self, value: datetime) -> None:
        await self.house.async_set_vacation_until(value)


class LearnRunAt(CoordinatorEntity[DynamicHeatingCoordinator], DateTimeEntity):
    """When the calibration run starts (e.g. when nobody is in the room)."""

    _attr_has_entity_name = True
    _attr_name = "Kalibrierlauf um"
    _attr_icon = "mdi:calendar-clock"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_learn_run_at"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.learn_run_at

    async def async_set_value(self, value: datetime) -> None:
        await self.coordinator.async_start_learn_run(value)
