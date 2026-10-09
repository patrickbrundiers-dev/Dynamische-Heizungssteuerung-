"""Config flow and editable options for dynamic heating."""

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
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_ENTITY,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_ECO_TEMPERATURE,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DOMAIN,
)


def _temperature_selector(minimum: float, maximum: float) -> selector.NumberSelector:
    """Create a temperature slider in Celsius."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=0.5, mode="slider"
        )
    )


def _user_schema() -> vol.Schema:
    """Build the initial entity and tuning form."""
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
            ): _temperature_selector(16, 25),
            vol.Required(
                CONF_ECO_TEMPERATURE, default=DEFAULT_ECO_TEMPERATURE
            ): _temperature_selector(7, 21),
            vol.Required(
                CONF_MAX_PREHEAT_MINUTES, default=DEFAULT_MAX_PREHEAT_MINUTES
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=15, max=240, step=5, mode="slider"
                )
            ),
        }
    )


class DynamicHeatingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one controller per thermostat."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Return the editor for an existing room."""
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
    """Allow an existing room's configuration to be edited and saved."""

    def _current_values(self) -> dict:
        """Return effective values, with saved options taking precedence."""
        values = dict(self.config_entry.data)
        values.update(dict(self.config_entry.options))
        values.setdefault(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        values.setdefault(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE)
        values.setdefault(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)
        return values

    def _options_schema(self, current: dict) -> vol.Schema:
        """Build the editor with the saved room configuration as defaults."""
        schema: dict = {
            vol.Required(
                CONF_CLIMATE_ENTITY, default=current[CONF_CLIMATE_ENTITY]
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Required(
                CONF_ROOM_TEMPERATURE_ENTITY,
                default=current[CONF_ROOM_TEMPERATURE_ENTITY],
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_SCHEDULE_ENTITY, default=current[CONF_SCHEDULE_ENTITY]
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="schedule")
            ),
            vol.Required(
                CONF_COMFORT_TEMPERATURE,
                default=float(current[CONF_COMFORT_TEMPERATURE]),
            ): _temperature_selector(16, 25),
            vol.Required(
                CONF_ECO_TEMPERATURE,
                default=float(current[CONF_ECO_TEMPERATURE]),
            ): _temperature_selector(7, 21),
            vol.Required(
                CONF_MAX_PREHEAT_MINUTES,
                default=int(current[CONF_MAX_PREHEAT_MINUTES]),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=15, max=240, step=5, mode="slider"
                )
            ),
        }

        optional_entities = (
            (CONF_WINDOW_ENTITY, "binary_sensor"),
            (CONF_PRESENCE_ENTITY, "binary_sensor"),
            (CONF_OUTDOOR_TEMPERATURE_ENTITY, "sensor"),
            (CONF_WEATHER_ENTITY, "weather"),
        )
        for key, entity_domain in optional_entities:
            if current.get(key):
                field = vol.Optional(key, default=current[key])
            else:
                field = vol.Optional(key)
            schema[field] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=entity_domain)
            )
        return vol.Schema(schema)

    async def async_step_init(self, user_input=None):
        """Manage room settings after the room was created."""
        current = self._current_values()
        errors: dict[str, str] = {}

        if user_input is not None:
            comfort = float(user_input[CONF_COMFORT_TEMPERATURE])
            eco = float(user_input[CONF_ECO_TEMPERATURE])
            if eco >= comfort:
                errors["base"] = "eco_must_be_below_comfort"
            else:
                climate_entity = user_input[CONF_CLIMATE_ENTITY]
                if any(
                    entry.entry_id != self.config_entry.entry_id
                    and entry.unique_id == climate_entity
                    for entry in self.hass.config_entries.async_entries(DOMAIN)
                ):
                    return self.async_abort(reason="already_configured")

                # Save all editable values as options. Empty optional entity IDs
                # intentionally override old values so a sensor can be removed.
                options = dict(user_input)
                for key in (
                    CONF_WINDOW_ENTITY,
                    CONF_PRESENCE_ENTITY,
                    CONF_OUTDOOR_TEMPERATURE_ENTITY,
                    CONF_WEATHER_ENTITY,
                ):
                    options[key] = user_input.get(key) or None

                if climate_entity != self.config_entry.unique_id:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        unique_id=climate_entity,
                        title=f"Dynamische Heizung – {climate_entity}",
                    )
                return self.async_create_entry(title="", data=options)

        # Use values already entered on a failed submission as suggested values.
        schema = self._options_schema(current)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or current
            ),
            errors=errors,
        )
