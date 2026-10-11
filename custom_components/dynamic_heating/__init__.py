"""Dynamic Heating integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENTRY_TYPE,
    DOMAIN,
    ENTRY_TYPE_HOUSE,
    HOUSE_DATA_KEY,
    HOUSE_PLATFORMS,
    PLATFORMS,
)
from .coordinator import DynamicHeatingCoordinator
from .house import HouseManager


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = "/dynamic_heating/dynamic-heating-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the room card so it shows up in the card picker."""
    if hass.http is None:
        return True
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "frontend" / "dynamic-heating-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), True)]
    )
    if DATA_EXTRA_MODULE_URL in hass.data:
        version = await _manifest_version(hass)
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def _manifest_version(hass: HomeAssistant) -> str:
    from homeassistant.loader import async_get_integration

    return str((await async_get_integration(hass, DOMAIN)).version or "0")


def _is_house(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a room (without taking control until its switch is on) or the house."""
    if _is_house(entry):
        house = HouseManager(hass, entry)
        await house.async_load()
        entry.runtime_data = house
        hass.data.setdefault(DOMAIN, {})[HOUSE_DATA_KEY] = house
        await hass.config_entries.async_forward_entry_setups(entry, HOUSE_PLATFORMS)
        for room in house.rooms():
            await room.async_refresh()
        return True

    coordinator = DynamicHeatingCoordinator(
        hass, {**dict(entry.data), **dict(entry.options)}, entry.entry_id
    )
    await coordinator.async_load_learning()
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and discard runtime state."""
    if _is_house(entry):
        if not await hass.config_entries.async_unload_platforms(entry, HOUSE_PLATFORMS):
            return False
        house = entry.runtime_data
        await house.async_unload()
        hass.data.get(DOMAIN, {}).pop(HOUSE_DATA_KEY, None)
        # Without the house the rooms go back to their own control.
        for room in house.rooms():
            await room.async_refresh()
        return True
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    # Thermostats must not keep regulating on a room value nobody updates.
    await entry.runtime_data.async_release_external_temperature()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
