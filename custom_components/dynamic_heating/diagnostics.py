"""Redacted diagnostics for the dynamic heating integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADDITIONAL_CLIMATE_ENTITIES,
    CONF_CLIMATE_ENTITY,
    CONF_GUEST_ENTITY,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PERSON_ENTITIES,
    CONF_PRESENCE_ENTITY,
    CONF_PRESENCE_SCHEDULE_ENTITY,
    CONF_PROXIMITY_DIRECTION_ENTITY,
    CONF_PROXIMITY_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WINDOW_ENTITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)

TO_REDACT = {
    CONF_ADDITIONAL_CLIMATE_ENTITIES,
    CONF_CLIMATE_ENTITY,
    CONF_GUEST_ENTITY,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PERSON_ENTITIES,
    CONF_PRESENCE_ENTITY,
    CONF_PRESENCE_SCHEDULE_ENTITY,
    CONF_PROXIMITY_DIRECTION_ENTITY,
    CONF_PROXIMITY_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WINDOW_ENTITY,
    CONF_WEATHER_ENTITY,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return useful runtime diagnostics while hiding configured entity IDs."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    runtime = {
        "enabled": coordinator.enabled,
        "heating_rate": coordinator.heating_rate,
        "cooling_rate": coordinator.cooling_rate,
        "latest_decision": coordinator.data or {},
    }
    return async_redact_data(
        {
            "config": {**dict(entry.data), **dict(entry.options)},
            "runtime": runtime,
        },
        TO_REDACT,
    )
