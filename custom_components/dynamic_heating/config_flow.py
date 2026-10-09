"""Config flow for the dynamic heating integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WINDOW_ENTITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_ECO_TEMPERATURE,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DOMAIN,
)


def _user_schema() -> vol.Schema:
    """Build the entity and tuning form."""
    return vol.Schema(
        {
            vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Required(CONF_ROOM_TEMPERATURE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_SCHEDULE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="schedule")
            ),
            vol.Optional(CONF_WINDOW_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(CONF_PRESENCE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(CONF_OUTDOOR_TEMPERATURE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(CONF_WEATHER_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            vol.Required(
                CONF_COMFORT_TEMPERATURE, default=DEFAULT_COMFORT_TEMPERATURE
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=16, max=25, step=0.5, mode="slider")
            ),
            vol.Required(CONF_ECO_TEMPERATURE, default=DEFAULT_ECO_TEMPERATURE): (
                selector.NumberSelector(
                    selector.NumberSelectorConfig(min=7, max=21, step=0.5, mode="slider")
                )
            ),
            vol.Required(
                CONF_MAX_PREHEAT_MINUTES, default=DEFAULT_MAX_PREHEAT_MINUTES
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=15, max=240, step=5, mode="slider")
            ),
        }
    )


class DynamicHeatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one controller per thermostat."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Allow existing entries to configure an optional weather entity."""
        return DynamicHeatingOptionsFlow()

    async def async_step_user(self, user_input=None):
        """Handle the initial setup form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            await self.async_set_unique_id(climate_entity)
            self._abort_if_unique_id_configured()
            comfort = float(user_input[CONF_COMFORT_TEMPERATURE])
            eco = float(user_input[CONF_ECO_TEMPERATURE])
            if eco >= comfort:
                errors["base"] = "eco_must_be_below_comfort"
            else:
                title = f"Dynamische Heizung – {climate_entity}"
                return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(), errors=errors
        )



class DynamicHeatingOptionsFlow(config_entries.OptionsFlowWithReload):
    """Configure an optional weather forecast without recreating the entry."""

    async def async_step_init(self, user_input=None):
        """Manage the optional weather entity."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_WEATHER_ENTITY: user_input.get(CONF_WEATHER_ENTITY, "")},
            )

        current_weather = self.config_entry.options.get(
            CONF_WEATHER_ENTITY,
            self.config_entry.data.get(CONF_WEATHER_ENTITY),
        )
        weather_field = (
            vol.Optional(CONF_WEATHER_ENTITY, default=current_weather)
            if current_weather
            else vol.Optional(CONF_WEATHER_ENTITY)
        )
        schema = vol.Schema({
            weather_field: selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            )
        })
        return self.async_show_form(step_id="init", data_schema=schema)
