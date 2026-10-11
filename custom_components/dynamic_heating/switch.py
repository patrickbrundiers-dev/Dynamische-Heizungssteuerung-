"""Control switch for the dynamic heating integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
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
    entities = [DynamicHeatingSwitch(coordinator, entry), BoostSwitch(coordinator, entry)]
    if coordinator.child_lock_switches():
        entities.append(ChildLockSwitch(coordinator, entry))
    thermostats = coordinator._thermostat_ids()
    if len(thermostats) > 1:
        entities.extend(
            SkipValveSwitch(coordinator, entry, entity_id) for entity_id in thermostats
        )
    async_add_entities(entities)


class DynamicHeatingSwitch(
    CoordinatorEntity[DynamicHeatingCoordinator], SwitchEntity, RestoreEntity
):
    """Enable or disable writing target temperatures to the configured thermostat.

    The last state survives restarts and option changes: once the integration
    is the only thing driving the valves, an unnoticed "off" would leave them
    stuck at whatever setpoint was written last.
    """

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

    async def async_added_to_hass(self) -> None:
        """Restore the last switch state before the first controlled refresh."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == "on":
            self.coordinator.enabled = True
            await self.coordinator.async_request_refresh()

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
        """Disable control; it stays disabled after Home Assistant restarts."""
        self.coordinator.enabled = False
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class BoostSwitch(CoordinatorEntity[DynamicHeatingCoordinator], SwitchEntity):
    """Heat to the boost temperature for a limited time; turns itself off."""

    _attr_icon = "mdi:fire"
    _attr_name = "Boost"

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_boost"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizungssteuerung",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    @property
    def is_on(self) -> bool:
        """Return whether a boost is running."""
        return self.coordinator.boost_until is not None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        """When the running boost ends."""
        until = self.coordinator.boost_until
        return {"until": until.isoformat() if until is not None else None}

    async def async_turn_on(self, **kwargs) -> None:
        """Start (or restart) the boost."""
        await self.coordinator.async_start_boost()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """End the boost early."""
        await self.coordinator.async_stop_boost()
        self.async_write_ha_state()


class ChildLockSwitch(CoordinatorEntity[DynamicHeatingCoordinator], SwitchEntity):
    """Lock the buttons of every thermostat of the room (Better Thermostat)."""

    _attr_icon = "mdi:lock"
    _attr_name = "Kindersicherung"

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_child_lock"
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizungssteuerung",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    @property
    def is_on(self) -> bool:
        """On while every thermostat of the room is locked."""
        states = [
            self.hass.states.get(switch_id)
            for switch_id in self.coordinator.child_lock_switches()
        ]
        return bool(states) and all(
            state is not None and state.state == "on" for state in states
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_child_lock(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_child_lock(False)
        self.async_write_ha_state()


class SkipValveSwitch(CoordinatorEntity[DynamicHeatingCoordinator], SwitchEntity):
    """Leave one valve out (Climate Group Helper's member isolation).

    The valve is closed once and then left alone; it no longer counts for
    the heat demand and is not set back by "Ventile sperren". Can be switched
    by an automation, e.g. from a sensor that sees a curtain or furniture in
    front of the radiator. At least one valve of the room always stays in.
    """

    _attr_icon = "mdi:radiator-off"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DynamicHeatingCoordinator,
        entry: ConfigEntry,
        thermostat_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._thermostat_id = thermostat_id
        self._attr_unique_id = f"{entry.entry_id}_skip_{thermostat_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Dynamische Heizungssteuerung",
            manufacturer="Community",
            model="Adaptive Heating Controller",
        )

    @property
    def name(self) -> str:
        # Read live: right after a restart the valve may not have a state yet.
        return f"Auslassen {self.coordinator._friendly_name(self._thermostat_id)}"

    @property
    def is_on(self) -> bool:
        return self._thermostat_id in self.coordinator.skipped_valves

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_set_valve_skipped(self._thermostat_id, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_set_valve_skipped(self._thermostat_id, False)
        self.async_write_ha_state()
