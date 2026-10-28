"""Room settings as sliders, like Better Thermostat's preset temperatures.

Temperatures are saved to the room's options without reloading it. The room
offset (Climate Group Helper's group offset) and the per-valve offsets
(its member offsets) are kept with the room's runtime state.
"""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTRY_TYPE,
    ENTRY_TYPE_HOUSE,
    LEVELS,
    CONF_ACTIVITY_TEMPERATURE,
    CONF_BOOST_TEMPERATURE,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_HOME_TEMPERATURE,
    CONF_SLEEP_TEMPERATURE,
    DEFAULT_ACTIVITY_TEMPERATURE,
    DEFAULT_BOOST_TEMPERATURE,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_ECO_TEMPERATURE,
    DEFAULT_HOME_TEMPERATURE,
    DEFAULT_SLEEP_TEMPERATURE,
    ROOM_OFFSET_MAX,
    ROOM_OFFSET_MIN,
    VALVE_OFFSET_MAX,
    VALVE_OFFSET_MIN,
)
from .coordinator import DynamicHeatingCoordinator
from .house import HouseManager
from .house_entities import HouseEntity
from .select import device_info

# key, name, icon, minimum, maximum, default
_TEMPERATURES = (
    (CONF_COMFORT_TEMPERATURE, "Komforttemperatur", "mdi:sofa", 16.0, 25.0,
     DEFAULT_COMFORT_TEMPERATURE),
    (CONF_ECO_TEMPERATURE, "Eco-Temperatur", "mdi:leaf", 7.0, 21.0,
     DEFAULT_ECO_TEMPERATURE),
    (CONF_HOME_TEMPERATURE, "Zuhause-Temperatur", "mdi:home", 5.0, 30.0,
     DEFAULT_HOME_TEMPERATURE),
    (CONF_ACTIVITY_TEMPERATURE, "Aktivität-Temperatur", "mdi:run", 5.0, 30.0,
     DEFAULT_ACTIVITY_TEMPERATURE),
    (CONF_SLEEP_TEMPERATURE, "Schlafen-Temperatur", "mdi:bed", 5.0, 30.0,
     DEFAULT_SLEEP_TEMPERATURE),
    (CONF_BOOST_TEMPERATURE, "Boost-Temperatur", "mdi:fire", 16.0, 30.0,
     DEFAULT_BOOST_TEMPERATURE),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the room's sliders, or the house's temperature levels."""
    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE:
        async_add_entities(
            [HouseLevel(entry.runtime_data, entry, key) for key in LEVELS]
        )
        return
    coordinator: DynamicHeatingCoordinator = entry.runtime_data
    entities: list[NumberEntity] = [
        TemperatureSetting(coordinator, entry, *item) for item in _TEMPERATURES
    ]
    entities.append(RoomOffset(coordinator, entry))
    thermostats = coordinator._thermostat_ids()
    if len(thermostats) > 1:
        entities.extend(
            ValveOffset(coordinator, entry, entity_id) for entity_id in thermostats
        )
    async_add_entities(entities)


class _RoomNumber(CoordinatorEntity[DynamicHeatingCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = device_info(entry)


class TemperatureSetting(_RoomNumber):
    """One temperature of the room, saved to its options."""

    def __init__(
        self,
        coordinator: DynamicHeatingCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
        minimum: float,
        maximum: float,
        default: float,
    ) -> None:
        super().__init__(coordinator, entry)
        self._key = key
        self._default = default
        self._attr_name = name
        self._attr_icon = icon
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        self._attr_unique_id = f"{entry.entry_id}_{key}"

    @property
    def native_value(self) -> float:
        value = self.coordinator.config.get(self._key)
        return float(value) if value is not None else self._default

    async def async_set_native_value(self, value: float) -> None:
        config = self.coordinator.config
        comfort = float(config.get(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE))
        eco = float(config.get(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE))
        if self._key == CONF_ECO_TEMPERATURE and value >= comfort:
            raise ServiceValidationError(
                "Die Eco-Temperatur muss unter der Komforttemperatur liegen."
            )
        if self._key == CONF_COMFORT_TEMPERATURE and value <= eco:
            raise ServiceValidationError(
                "Die Komforttemperatur muss über der Eco-Temperatur liegen."
            )
        self.hass.config_entries.async_update_entry(
            self._entry, options={**self._entry.options, self._key: float(value)}
        )
        await self.coordinator.async_set_option(self._key, float(value))


class RoomOffset(_RoomNumber):
    """Shift every target of the room up or down."""

    _attr_name = "Raum-Versatz"
    _attr_icon = "mdi:plus-minus-variant"
    _attr_native_min_value = ROOM_OFFSET_MIN
    _attr_native_max_value = ROOM_OFFSET_MAX

    def __init__(
        self, coordinator: DynamicHeatingCoordinator, entry: ConfigEntry
    ) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_room_offset"

    @property
    def native_value(self) -> float:
        return self.coordinator.room_offset

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_room_offset(value)


class ValveOffset(_RoomNumber):
    """Shift one valve against the others of the room."""

    _attr_icon = "mdi:radiator"
    _attr_native_min_value = VALVE_OFFSET_MIN
    _attr_native_max_value = VALVE_OFFSET_MAX

    def __init__(
        self,
        coordinator: DynamicHeatingCoordinator,
        entry: ConfigEntry,
        thermostat_id: str,
    ) -> None:
        super().__init__(coordinator, entry)
        self._thermostat_id = thermostat_id
        self._attr_unique_id = f"{entry.entry_id}_valve_offset_{thermostat_id}"

    @property
    def name(self) -> str:
        # Read live: right after a restart the valve may not have a state yet.
        return f"Versatz {self.coordinator._friendly_name(self._thermostat_id)}"

    @property
    def native_value(self) -> float:
        return self.coordinator.valve_offsets.get(self._thermostat_id, 0.0)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_set_valve_offset(self._thermostat_id, value)


class HouseLevel(HouseEntity, NumberEntity):
    """A temperature level that schedule blocks name, e.g. ``stufe: abend``."""

    _attr_mode = NumberMode.SLIDER
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_step = 0.5
    _attr_native_min_value = 5.0
    _attr_native_max_value = 30.0
    _attr_icon = "mdi:stairs"

    def __init__(self, house: HouseManager, entry: ConfigEntry, key: str) -> None:
        super().__init__(house, entry, f"level_{key}")
        self._key = key
        self._attr_name = LEVELS[key][0]

    @property
    def native_value(self) -> float | None:
        return self.house.level(self._key)

    async def async_set_native_value(self, value: float) -> None:
        await self.house.async_set_level(self._key, value)
