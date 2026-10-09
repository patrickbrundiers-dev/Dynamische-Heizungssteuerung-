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
    CONF_PERSON_ENTITIES,
    CONF_GUEST_ENTITY,
    CONF_ENTER_HOME_DURATION,
    CONF_LEAVING_HOME_DURATION,
    CONF_PROXIMITY_ENTITY,
    CONF_PROXIMITY_DIRECTION_ENTITY,
    CONF_PROXIMITY_MAX_AGE,
    CONF_PROXIMITY_DURATION,
    CONF_PROXIMITY_DISTANCE,
    CONF_PRESENCE_SCHEDULE_ENTITY,
    CONF_PRESENCE_ON_DURATION,
    CONF_PRESENCE_OFF_DURATION,
    CONF_ROOM_TEMPERATURE_ENTITY,
    CONF_SCHEDULE_ENTITY,
    CONF_WEATHER_ENTITY,
    CONF_WINDOW_ENTITY,
    DEFAULT_COMFORT_TEMPERATURE,
    DEFAULT_ECO_TEMPERATURE,
    DEFAULT_MAX_PREHEAT_MINUTES,
    DEFAULT_ENTER_HOME_DURATION,
    DEFAULT_LEAVING_HOME_DURATION,
    DEFAULT_PROXIMITY_DURATION,
    DEFAULT_PROXIMITY_DISTANCE,
    DEFAULT_PROXIMITY_MAX_AGE,
    DEFAULT_PRESENCE_ON_DURATION,
    DEFAULT_PRESENCE_OFF_DURATION,
    DOMAIN,
)


def _duration_selector() -> selector.DurationSelector:
    """Use Home Assistant's hours/minutes/seconds duration input.

    Seconds are enabled by default in Home Assistant's DurationSelector. Do not
    pass optional selector configuration here to remain compatible with Core
    releases whose selector config schema differs.
    """
    return selector.DurationSelector()


def _duration_to_seconds(value: object) -> int:
    """Convert duration-selector output or a stored number to seconds."""
    if isinstance(value, dict):
        return (
            int(value.get("days", 0) or 0) * 86400
            + int(value.get("hours", 0) or 0) * 3600
            + int(value.get("minutes", 0) or 0) * 60
            + int(value.get("seconds", 0) or 0)
        )
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _seconds_to_duration(value: object) -> dict[str, int]:
    """Build a default value for the duration selector from stored seconds."""
    seconds = _duration_to_seconds(value)
    return {
        "hours": seconds // 3600,
        "minutes": (seconds % 3600) // 60,
        "seconds": seconds % 60,
    }


_DURATION_OPTIONS = (
    CONF_ENTER_HOME_DURATION,
    CONF_LEAVING_HOME_DURATION,
    CONF_PROXIMITY_DURATION,
    CONF_PRESENCE_ON_DURATION,
    CONF_PRESENCE_OFF_DURATION,
    CONF_PROXIMITY_MAX_AGE,
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
            vol.Optional(CONF_PERSON_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["person", "device_tracker"], multiple=True
                )
            ),
            vol.Optional(
                CONF_ENTER_HOME_DURATION,
                default=_seconds_to_duration(DEFAULT_ENTER_HOME_DURATION),
            ): _duration_selector(),
            vol.Optional(
                CONF_LEAVING_HOME_DURATION,
                default=_seconds_to_duration(DEFAULT_LEAVING_HOME_DURATION),
            ): _duration_selector(),
            vol.Optional(CONF_GUEST_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
            ),
            vol.Optional(CONF_PROXIMITY_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["sensor", "proximity"])
            ),
            vol.Optional(CONF_PROXIMITY_DIRECTION_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Optional(
                CONF_PROXIMITY_DISTANCE, default=DEFAULT_PROXIMITY_DISTANCE
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=100000, step=50, mode="box"
                )
            ),
            vol.Optional(
                CONF_PROXIMITY_DURATION,
                default=_seconds_to_duration(DEFAULT_PROXIMITY_DURATION),
            ): _duration_selector(),
            vol.Optional(
                CONF_PROXIMITY_MAX_AGE,
                default=_seconds_to_duration(DEFAULT_PROXIMITY_MAX_AGE),
            ): _duration_selector(),
            vol.Optional(CONF_PRESENCE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
            ),
            vol.Optional(CONF_PRESENCE_SCHEDULE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="schedule")
            ),
            vol.Optional(
                CONF_PRESENCE_ON_DURATION,
                default=_seconds_to_duration(DEFAULT_PRESENCE_ON_DURATION),
            ): _duration_selector(),
            vol.Optional(
                CONF_PRESENCE_OFF_DURATION,
                default=_seconds_to_duration(DEFAULT_PRESENCE_OFF_DURATION),
            ): _duration_selector(),
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
                data = dict(user_input)
                for key in _DURATION_OPTIONS:
                    if key in data:
                        data[key] = _duration_to_seconds(data[key])
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="user", data_schema=_user_schema(), errors=errors
        )


class DynamicHeatingOptionsFlow(config_entries.OptionsFlowWithReload):
    """Editable, multi-step room editor with clear functional groups."""

    def _current_values(self) -> dict:
        """Return effective values, with saved options taking precedence."""
        values = dict(self.config_entry.data)
        values.update(dict(self.config_entry.options))
        values.setdefault(CONF_COMFORT_TEMPERATURE, DEFAULT_COMFORT_TEMPERATURE)
        values.setdefault(CONF_ECO_TEMPERATURE, DEFAULT_ECO_TEMPERATURE)
        values.setdefault(CONF_MAX_PREHEAT_MINUTES, DEFAULT_MAX_PREHEAT_MINUTES)
        values.setdefault(CONF_ENTER_HOME_DURATION, DEFAULT_ENTER_HOME_DURATION)
        values.setdefault(CONF_LEAVING_HOME_DURATION, DEFAULT_LEAVING_HOME_DURATION)
        values.setdefault(CONF_PROXIMITY_DURATION, DEFAULT_PROXIMITY_DURATION)
        values.setdefault(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE)
        values.setdefault(CONF_PROXIMITY_MAX_AGE, DEFAULT_PROXIMITY_MAX_AGE)
        values.setdefault(CONF_PRESENCE_ON_DURATION, DEFAULT_PRESENCE_ON_DURATION)
        values.setdefault(CONF_PRESENCE_OFF_DURATION, DEFAULT_PRESENCE_OFF_DURATION)
        return values

    def _values(self) -> dict:
        """Keep pending edits across all editor steps."""
        if not hasattr(self, "_working_values"):
            self._working_values = self._current_values()
        return self._working_values

    @staticmethod
    def _entity_field(key: str, domain: str | list[str], current: dict, *, multiple=False):
        """Create an optional selector with a readable saved-value default."""
        if current.get(key):
            field = vol.Optional(key, default=current[key])
        else:
            field = vol.Optional(key)
        return (
            field,
            selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=domain,
                    **({"multiple": True} if multiple else {}),
                )
            ),
        )

    @staticmethod
    def _duration_field(key: str, current: dict, default: int):
        """Create a duration field shown as hours, minutes and seconds."""
        return (
            vol.Optional(
                key,
                default=_seconds_to_duration(current.get(key, default)),
            ),
            _duration_selector(),
        )

    def _basic_schema(self, current: dict) -> vol.Schema:
        """Room identity and heating target settings."""
        return vol.Schema({
            vol.Required(
                CONF_CLIMATE_ENTITY, default=current[CONF_CLIMATE_ENTITY]
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
            vol.Required(
                CONF_ROOM_TEMPERATURE_ENTITY,
                default=current[CONF_ROOM_TEMPERATURE_ENTITY],
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_SCHEDULE_ENTITY, default=current[CONF_SCHEDULE_ENTITY]
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="schedule")),
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
                selector.NumberSelectorConfig(min=15, max=240, step=5, mode="slider")
            ),
        })

    def _presence_schema(self, current: dict) -> vol.Schema:
        """Household people, guests and indoor presence settings."""
        schema = {}
        for item in (
            self._entity_field(CONF_PERSON_ENTITIES, ["person", "device_tracker"], current, multiple=True),
            self._duration_field(CONF_ENTER_HOME_DURATION, current, DEFAULT_ENTER_HOME_DURATION),
            self._duration_field(CONF_LEAVING_HOME_DURATION, current, DEFAULT_LEAVING_HOME_DURATION),
            self._entity_field(CONF_GUEST_ENTITY, ["binary_sensor", "input_boolean"], current),
            self._entity_field(CONF_PRESENCE_ENTITY, ["binary_sensor", "input_boolean"], current),
            self._entity_field(CONF_PRESENCE_SCHEDULE_ENTITY, "schedule", current),
            self._duration_field(CONF_PRESENCE_ON_DURATION, current, DEFAULT_PRESENCE_ON_DURATION),
            self._duration_field(CONF_PRESENCE_OFF_DURATION, current, DEFAULT_PRESENCE_OFF_DURATION),
        ):
            schema[item[0]] = item[1]
        return vol.Schema(schema)

    def _proximity_schema(self, current: dict) -> vol.Schema:
        """Geo-fencing sensors, distance limit and data freshness."""
        schema = {}
        for item in (
            self._entity_field(CONF_PROXIMITY_ENTITY, ["sensor", "proximity"], current),
            self._entity_field(CONF_PROXIMITY_DIRECTION_ENTITY, "sensor", current),
        ):
            schema[item[0]] = item[1]
        schema[vol.Optional(
            CONF_PROXIMITY_DISTANCE,
            default=int(current.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE)),
        )] = selector.NumberSelector(
            selector.NumberSelectorConfig(min=0, max=100000, step=50, mode="box")
        )
        for item in (
            self._duration_field(CONF_PROXIMITY_DURATION, current, DEFAULT_PROXIMITY_DURATION),
            self._duration_field(CONF_PROXIMITY_MAX_AGE, current, DEFAULT_PROXIMITY_MAX_AGE),
        ):
            schema[item[0]] = item[1]
        return vol.Schema(schema)

    def _environment_schema(self, current: dict) -> vol.Schema:
        """Window, outdoor temperature and weather options."""
        schema = {}
        for item in (
            self._entity_field(CONF_WINDOW_ENTITY, "binary_sensor", current),
            self._entity_field(CONF_OUTDOOR_TEMPERATURE_ENTITY, "sensor", current),
            self._entity_field(CONF_WEATHER_ENTITY, "weather", current),
        ):
            schema[item[0]] = item[1]
        return vol.Schema(schema)

    def _show_step(self, step_id: str, schema: vol.Schema, current: dict):
        """Render one editor page while preserving and formatting saved values."""
        suggested = dict(current)
        # Native duration selectors require a structured duration, not seconds.
        for key in _DURATION_OPTIONS:
            if key in suggested and not isinstance(suggested[key], dict):
                suggested[key] = _seconds_to_duration(suggested[key])
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
        )

    async def async_step_init(self, user_input=None):
        """Step 1: room entities and desired temperatures."""
        current = self._values()
        errors: dict[str, str] = {}
        if user_input is not None:
            comfort = float(user_input[CONF_COMFORT_TEMPERATURE])
            eco = float(user_input[CONF_ECO_TEMPERATURE])
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            if eco >= comfort:
                errors["base"] = "eco_must_be_below_comfort"
            elif any(
                entry.entry_id != self.config_entry.entry_id
                and entry.unique_id == climate_entity
                for entry in self.hass.config_entries.async_entries(DOMAIN)
            ):
                return self.async_abort(reason="already_configured")
            else:
                current.update(user_input)
                return await self.async_step_presence()

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                self._basic_schema(current), current
            ),
            errors=errors,
        )

    async def async_step_presence(self, user_input=None):
        """Step 2: occupancy, people and guest mode."""
        current = self._values()
        if user_input is not None:
            current.update(user_input)
            for key in (CONF_PERSON_ENTITIES, CONF_GUEST_ENTITY, CONF_PRESENCE_ENTITY,
                        CONF_PRESENCE_SCHEDULE_ENTITY):
                current[key] = user_input.get(key) or None
            for key in (CONF_ENTER_HOME_DURATION, CONF_LEAVING_HOME_DURATION,
                        CONF_PRESENCE_ON_DURATION, CONF_PRESENCE_OFF_DURATION):
                current[key] = _duration_to_seconds(user_input.get(key, current.get(key, 0)))
            return await self.async_step_geofencing()

        return self._show_step("presence", self._presence_schema(current), current)

    async def async_step_geofencing(self, user_input=None):
        """Step 3: proximity source, arrival radius and location freshness."""
        current = self._values()
        if user_input is not None:
            current.update(user_input)
            for key in (CONF_PROXIMITY_ENTITY, CONF_PROXIMITY_DIRECTION_ENTITY):
                current[key] = user_input.get(key) or None
            current[CONF_PROXIMITY_DISTANCE] = max(
                0, int(user_input.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE))
            )
            for key in (CONF_PROXIMITY_DURATION, CONF_PROXIMITY_MAX_AGE):
                current[key] = _duration_to_seconds(user_input.get(key, current.get(key, 0)))
            return await self.async_step_environment()

        return self._show_step(
            "geofencing", self._proximity_schema(current), current
        )

    async def async_step_environment(self, user_input=None):
        """Step 4: optional window, outdoor temperature and weather sensors."""
        current = self._values()
        if user_input is not None:
            current.update(user_input)
            for key in (CONF_WINDOW_ENTITY, CONF_OUTDOOR_TEMPERATURE_ENTITY, CONF_WEATHER_ENTITY):
                current[key] = user_input.get(key) or None

            climate_entity = current[CONF_CLIMATE_ENTITY]
            options = dict(current)
            if climate_entity != self.config_entry.unique_id:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    unique_id=climate_entity,
                    title=f"Dynamische Heizung – {climate_entity}",
                )
            return self.async_create_entry(title="", data=options)

        return self._show_step(
            "environment", self._environment_schema(current), current
        )
