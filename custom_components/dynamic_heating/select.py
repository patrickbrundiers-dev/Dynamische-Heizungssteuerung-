"""Quick selection of the heating mode of a dynamically heated room."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_HOUSE,
    HOUSE_AWAY,
    HOUSE_HOME,
    HOUSE_MODES,
    HOUSE_VACATION,
    QUICK_DURATIONS,
    QUICK_LABELS,
    QUICK_MANUAL,
    QUICK_MODES,
    QUICK_UNTIL_1H,
    QUICK_UNTIL_3H,
    QUICK_UNTIL_FOREVER,
    QUICK_UNTIL_MORNING,
    QUICK_UNTIL_SCHEDULE,
)
from .coordinator import DynamicHeatingCoordinator
from .house_entities import HouseEntity

_LABELS = QUICK_LABELS
_MODES = {label: mode for mode, label in _LABELS.items()}
_DURATION_LABELS = {
    QUICK_UNTIL_SCHEDULE: "Bis Zeitplanwechsel",
    QUICK_UNTIL_1H: "1 Stunde",
    QUICK_UNTIL_3H: "3 Stunden",
    QUICK_UNTIL_MORNING: "Bis morgen früh",
    QUICK_UNTIL_FOREVER: "Dauerhaft",
}
_DURATIONS = {label: key for key, label in _DURATION_LABELS.items()}


def device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Dynamische Heizungssteuerung",
        manufacturer="Community",
        model="Adaptive Heating Controller",
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the quick mode selection, or the house mode for the house entry."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE:
        async_add_entities([HouseModeSelect(entry.runtime_data, entry, "house_mode")])
        return
    coordinator: DynamicHeatingCoordinator = entry.runtime_data
    async_add_entities(
        [
            QuickModeSelect(coordinator, entry),
            QuickDurationSelect(coordinator, entry),
            ScheduleSelect(coordinator, entry),
        ]
    )


class QuickModeSelect(CoordinatorEntity[DynamicHeatingCoordinator], SelectEntity):
    """Automatik, or a mode picked by hand until the next schedule switch."""

    _attr_name = "Betriebsart"
    _attr_icon = "mdi:radiator"
    # Manuell shows a temperature set on the room thermostat entity.
    _attr_options = [_LABELS[mode] for mode in (*QUICK_MODES, QUICK_MANUAL)]

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_quick_mode"
        self._attr_has_entity_name = True
        self._attr_device_info = device_info(entry)

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


class QuickDurationSelect(CoordinatorEntity[DynamicHeatingCoordinator], SelectEntity):
    """How long Komfort, Eco or Aus picked by hand holds."""

    _attr_name = "Betriebsart-Dauer"
    _attr_icon = "mdi:timer-outline"
    _attr_options = [_DURATION_LABELS[key] for key in QUICK_DURATIONS]

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_quick_duration"
        self._attr_has_entity_name = True
        self._attr_device_info = device_info(entry)

    @property
    def current_option(self) -> str:
        """Return the chosen duration."""
        return _DURATION_LABELS[self.coordinator.quick_duration]

    async def async_select_option(self, option: str) -> None:
        """Use the picked duration, also for a mode that is already running."""
        await self.coordinator.async_set_quick_duration(_DURATIONS[option])


class ScheduleSelect(CoordinatorEntity[DynamicHeatingCoordinator], SelectEntity):
    """Which of the room's comfort schedules is in use."""

    _attr_name = "Zeitplan"
    _attr_icon = "mdi:calendar-multiple"

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_schedule"
        self._attr_has_entity_name = True
        self._attr_device_info = device_info(entry)

    @property
    def options(self) -> list[str]:
        return [name for _, name in self.coordinator.schedule_options()]

    @property
    def current_option(self) -> str | None:
        active = self.coordinator.active_schedule
        for entity_id, name in self.coordinator.schedule_options():
            if entity_id == active:
                return name
        return None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        return {"entity_id": self.coordinator.active_schedule}

    async def async_select_option(self, option: str) -> None:
        for entity_id, name in self.coordinator.schedule_options():
            if name == option:
                await self.coordinator.async_set_schedule(entity_id)
                return


_HOUSE_LABELS = {
    HOUSE_HOME: "Zuhause",
    HOUSE_AWAY: "Abwesend",
    HOUSE_VACATION: "Urlaub",
}
_HOUSE_MODES = {label: mode for mode, label in _HOUSE_LABELS.items()}


class HouseModeSelect(HouseEntity, SelectEntity):
    """Zuhause, Abwesend or Urlaub for every room at once."""

    _attr_name = "Hausmodus"
    _attr_icon = "mdi:home-switch"
    _attr_options = [_HOUSE_LABELS[mode] for mode in HOUSE_MODES]

    @property
    def current_option(self) -> str:
        return _HOUSE_LABELS[self.house.mode]

    async def async_select_option(self, option: str) -> None:
        await self.house.async_set_mode(_HOUSE_MODES[option])
