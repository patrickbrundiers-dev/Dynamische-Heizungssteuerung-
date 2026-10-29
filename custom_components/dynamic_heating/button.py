"""Buttons: one per quick mode in a room, the weekly report for the house."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
        async_add_entities([
            SendReportButton(entry.runtime_data, entry, "send_report"),
            GoodNightButton(entry.runtime_data, entry, "good_night"),
        ])
        return
    entities: list[ButtonEntity] = [
        QuickModeButton(entry.runtime_data, entry, mode) for mode in QUICK_MODES
    ]
    entities.append(ValveMaintenanceButton(entry.runtime_data, entry))
    entities.append(WarmUpButton(entry.runtime_data, entry))
    entities.append(SelfTestButton(entry.runtime_data, entry))
    entities.append(RadiatorTestButton(entry.runtime_data, entry))
    entities.append(LearnRunButton(entry.runtime_data, entry))
    async_add_entities(entities)


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
        await self.coordinator.async_set_quick_mode(self._mode, source="Taste")


class ValveMaintenanceButton(CoordinatorEntity[DynamicHeatingCoordinator], ButtonEntity):
    """Exercises the room's valves now (open fully, then close)."""

    _attr_has_entity_name = True
    _attr_name = "Ventilwartung starten"
    _attr_icon = "mdi:valve"

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_valve_maintenance_button"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self.coordinator.async_start_valve_maintenance()


class WarmUpButton(CoordinatorEntity[DynamicHeatingCoordinator], ButtonEntity):
    """Kurz wärmer: a little warmer for a while, then back to automatic.

    Made for voice assistants ("Alexa, Wohnzimmer kurz wärmer einschalten").
    """

    _attr_has_entity_name = True
    _attr_name = "Kurz wärmer"
    _attr_icon = "mdi:thermometer-plus"

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_warm_up_button"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self.coordinator.async_warm_up()


class SelfTestButton(CoordinatorEntity[DynamicHeatingCoordinator], ButtonEntity):
    """Runs the self-test now."""

    _attr_has_entity_name = True
    _attr_name = "Selbsttest starten"
    _attr_icon = "mdi:clipboard-play-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_selftest_button"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self.coordinator.async_run_selftest()


class RadiatorTestButton(CoordinatorEntity[DynamicHeatingCoordinator], ButtonEntity):
    """Valves fully open for 20 minutes: does the radiator get warm?"""

    _attr_has_entity_name = True
    _attr_name = "Heizkörpertest starten"
    _attr_icon = "mdi:radiator"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_radiator_test_button"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self.coordinator.async_start_radiator_test()


class LearnRunButton(CoordinatorEntity[DynamicHeatingCoordinator], ButtonEntity):
    """Calibration run now: two hours of full heat teach the room model."""

    _attr_has_entity_name = True
    _attr_name = "Raummodell kalibrieren"
    _attr_icon = "mdi:chart-bell-curve-cumulative"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_learn_run_button"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        await self.coordinator.async_start_learn_run()


class SendReportButton(HouseEntity, ButtonEntity):
    """Sends the report of the current week now (the week keeps counting)."""

    _attr_name = "Wochenbericht senden"
    _attr_icon = "mdi:email-fast-outline"

    async def async_press(self) -> None:
        await self.house.async_send_report(reset=False)


class GoodNightButton(HouseEntity, ButtonEntity):
    """"Gute Nacht": every room in comfort time goes to night setback now."""

    _attr_name = "Gute Nacht"
    _attr_icon = "mdi:weather-night"

    async def async_press(self) -> None:
        await self.house.async_good_night()
