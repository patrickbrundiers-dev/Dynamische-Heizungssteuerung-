"""One thermostat entity per room, like the one Better Thermostat provides.

It shows the room temperature and the target the controller chose. Setting a
temperature holds it for the chosen Betriebsart-Dauer, the presets are the
quick modes and "off" is the mode Aus.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HUMIDITY_ENTITY,
    QUICK_AUTO,
    QUICK_MANUAL,
    QUICK_MODES,
    QUICK_OFF,
    ROOM_MAX_TEMPERATURE,
    ROOM_MIN_TEMPERATURE,
    ROOM_TEMPERATURE_STEP,
)
from .coordinator import DynamicHeatingCoordinator
from .select import device_info

# Quick modes offered as presets. Their keys are Home Assistant's standard
# presets (comfort, home, activity, eco, sleep, away, boost), so cards and
# voice assistants know them; Automatik is "none".
_PRESETS = [mode for mode in QUICK_MODES if mode not in (QUICK_AUTO, QUICK_OFF)]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the room thermostat."""
    async_add_entities([RoomClimate(entry.runtime_data, entry)])


class RoomClimate(CoordinatorEntity[DynamicHeatingCoordinator], ClimateEntity):
    """The whole room as one thermostat for dashboards and voice assistants."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_icon = "mdi:home-thermometer"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_NONE, *_PRESETS]
    _attr_min_temp = ROOM_MIN_TEMPERATURE
    _attr_max_temp = ROOM_MAX_TEMPERATURE
    _attr_target_temperature_step = ROOM_TEMPERATURE_STEP
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_room_climate"
        self._attr_device_info = device_info(entry)

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}

    @property
    def current_temperature(self) -> float | None:
        return self._data.get("room_temperature")

    @property
    def current_humidity(self) -> float | None:
        """Room humidity from the configured sensor, as Better Thermostat shows."""
        entity_id = self.coordinator.config.get(CONF_HUMIDITY_ENTITY)
        state = self.hass.states.get(entity_id) if entity_id else None
        try:
            return float(state.state) if state is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def target_temperature(self) -> float | None:
        return self._data.get("target_temperature")

    @property
    def hvac_mode(self) -> HVACMode:
        if self.coordinator.current_quick_mode == QUICK_OFF:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction:
        if self.coordinator.current_quick_mode == QUICK_OFF:
            return HVACAction.OFF
        if self._data.get("enabled") and (self._data.get("heat_demand") or 0) > 0:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        mode = self.coordinator.current_quick_mode
        return mode if mode in _PRESETS else PRESET_NONE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Why the room heats as it does, and until when a hand-picked mode holds."""
        until = self._data.get("boost_until") or self._data.get("quick_until")
        return {
            "status": self._data.get("status"),
            "control_active": bool(self._data.get("enabled")),
            "manual": self.coordinator.current_quick_mode == QUICK_MANUAL,
            "until": until,
            "room_offset": self._data.get("room_offset"),
            "temperature_trend": self._data.get("temperature_trend"),
            "last_change_source": self._data.get("last_change_source"),
            "last_change_at": self._data.get("last_change_at"),
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Hold the temperature for the chosen Betriebsart-Dauer."""
        if kwargs.get(ATTR_HVAC_MODE) == HVACMode.OFF:
            await self.async_set_hvac_mode(HVACMode.OFF)
            return
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            if ATTR_HVAC_MODE in kwargs:
                await self.async_set_hvac_mode(kwargs[ATTR_HVAC_MODE])
            return
        await self.coordinator.async_set_manual_temperature(float(temperature))

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Off is the mode Aus; heat goes back to automatic control."""
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_set_quick_mode(QUICK_OFF, source="Raum-Thermostat")
        elif self.coordinator.current_quick_mode == QUICK_OFF:
            await self.coordinator.async_set_quick_mode(QUICK_AUTO, source="Raum-Thermostat")

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """A preset is the quick mode of the same name; none is Automatik."""
        await self.coordinator.async_set_quick_mode(
            QUICK_AUTO if preset_mode == PRESET_NONE else preset_mode,
            source="Raum-Thermostat",
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
