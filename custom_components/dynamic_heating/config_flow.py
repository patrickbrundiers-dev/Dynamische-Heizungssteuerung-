"""Config flow and editable options for dynamic heating."""

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers import selector

from . import const
from .const import (
    CONF_WARM_UP_DURATION,
    CONF_WARM_UP_STEP,
    DEFAULT_WARM_UP_DURATION,
    DEFAULT_WARM_UP_STEP,
    CONF_EARLY_STOP,
    CONF_LEARN_USAGE,
    CONF_PREHEAT_WHEN_HOME,
    CONF_RECOVERY_LIMIT,
    CONF_ROOM_EMPTY_GRACE,
    CONF_ROOM_EMPTY_RECOVERY,
    CONF_ROOM_MODEL,
    CONF_SOLAR_RADIATION_ENTITY,
    CONF_WIND_SPEED_ENTITY,
    DEFAULT_EARLY_STOP,
    DEFAULT_LEARN_USAGE,
    DEFAULT_PREHEAT_WHEN_HOME,
    DEFAULT_RECOVERY_LIMIT,
    DEFAULT_ROOM_EMPTY_GRACE,
    DEFAULT_ROOM_EMPTY_RECOVERY,
    DEFAULT_ROOM_MODEL,
    CONF_COMMAND_DELAY,
    CONF_DOOR_CLOSE_DELAY,
    CONF_DOOR_ENTITIES,
    CONF_DOOR_OPEN_DELAY,
    CONF_FOLLOW_HOUSE_CALENDAR,
    CONF_FORCE_COMFORT_ENTITIES,
    CONF_FORCE_ECO_ENTITIES,
    CONF_HEATING_LIMIT_AVERAGE,
    CONF_HEATING_LIMIT_FALLBACK_OFF,
    CONF_HOUSE_CALENDAR,
    CONF_MAINTENANCE_DURATION,
    CONF_MAINTENANCE_HOUR,
    CONF_MAINTENANCE_WEEKDAY,
    CONF_WINDOW_CHANGE,
    CONF_ZONE_WINDOW_CLOSE_DELAY,
    CONF_ZONE_WINDOW_ENTITIES,
    CONF_ZONE_WINDOW_OPEN_DELAY,
    DEFAULT_COMMAND_DELAY,
    DEFAULT_DOOR_CLOSE_DELAY,
    DEFAULT_DOOR_OPEN_DELAY,
    DEFAULT_FOLLOW_HOUSE_CALENDAR,
    DEFAULT_HEATING_LIMIT_AVERAGE,
    DEFAULT_ZONE_WINDOW_CLOSE_DELAY,
    DEFAULT_ZONE_WINDOW_OPEN_DELAY,
    MAINTENANCE_ANY_DAY,
    SETTINGS_GROUPS,
    VALVE_MAINTENANCE_HOUR,
    VALVE_MAINTENANCE_PHASE_SECONDS,
    WINDOW_CHANGE_DISCARD,
    WINDOW_CHANGE_KEEP,
    CONF_ADDITIONAL_WINDOW_ENTITIES,
    CONF_HUMIDITY_ENTITY,
    CONF_LOCK_VALVES,
    CONF_ADDITIONAL_SCHEDULE_ENTITIES,
    CONF_AGGRESSIVE_OFFSET,
    CONF_AGGRESSIVE_RANGE,
    CONF_AWAY_OFFSET,
    CONF_AWAY_SCHEDULE_MODE,
    CONF_DISABLE_TRV_WINDOW_DETECTION,
    CONF_ECO_SCHEDULE_ENTITY,
    CONF_FROST_AFTER_ABSENCE,
    CONF_SYNC_MANUAL_CHANGE,
    DEFAULT_AGGRESSIVE_OFFSET,
    DEFAULT_FROST_AFTER_ABSENCE,
    DEFAULT_SYNC_MANUAL_CHANGE,
    CONF_ADDITIONAL_CLIMATE_ENTITIES,
    CONF_AWAY_TEMPERATURE,
    CONF_BOOST_DURATION,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_AWAY,
    CONF_PREHEAT_EXTENSION,
    CONF_PUNCTUALITY,
    CONF_VALVE_FALLBACK,
    CONF_VALVE_SENSOR_CALIBRATION,
    CONF_HOLD_BEFORE_PAUSE,
    CONF_MORNING_REPORT,
    DEFAULT_NOTIFY_AWAY,
    DEFAULT_PREHEAT_EXTENSION,
    DEFAULT_PUNCTUALITY,
    DEFAULT_VALVE_FALLBACK,
    DEFAULT_VALVE_SENSOR_CALIBRATION,
    DEFAULT_HOLD_BEFORE_PAUSE,
    DEFAULT_MORNING_REPORT,
    CONF_BOOST_TEMPERATURE,
    CONF_CALIBRATION,
    CONF_ENTRY_TYPE,
    CONF_EXTERNAL_TEMPERATURE,
    ENTRY_TYPE_HOUSE,
    CONF_HYSTERESIS,
    CONF_ACTIVITY_TEMPERATURE,
    CONF_HOME_TEMPERATURE,
    CONF_SLEEP_TEMPERATURE,
    DEFAULT_ACTIVITY_TEMPERATURE,
    DEFAULT_BOOST_DURATION,
    DEFAULT_BOOST_TEMPERATURE,
    DEFAULT_HOME_TEMPERATURE,
    DEFAULT_SLEEP_TEMPERATURE,
    DEFAULT_HYSTERESIS,
    CONF_VALVE_MAINTENANCE,
    CONF_CLIMATE_ENTITY,
    CONF_COMFORT_TEMPERATURE,
    CONF_ECO_TEMPERATURE,
    CONF_FROST_PROTECTION_TEMPERATURE,
    CONF_HEATING_LIMIT_TEMPERATURE,
    CONF_HEATING_SEASON_ENTITY,
    CONF_MAX_PREHEAT_MINUTES,
    CONF_OUTDOOR_TEMPERATURE_ENTITY,
    CONF_PRESENCE_ENTITY,
    CONF_PERSON_ENTITIES,
    CONF_GUEST_ENTITY,
    CONF_ENTER_HOME_DURATION,
    CONF_LEAVING_HOME_DURATION,
    CONF_PROXIMITY_ENTITY,
    CONF_PROXIMITY_ZONE,
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
    CONF_WINDOW_CLOSE_DELAY,
    CONF_WINDOW_DROP_DETECTION,
    CONF_WINDOW_ENTITY,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_TEMPERATURE,
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
    DEFAULT_WINDOW_CLOSE_DELAY,
    DEFAULT_WINDOW_OPEN_DELAY,
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
    CONF_ROOM_EMPTY_RECOVERY,
    CONF_ROOM_EMPTY_GRACE,
    CONF_EARLY_STOP,
    CONF_ENTER_HOME_DURATION,
    CONF_LEAVING_HOME_DURATION,
    CONF_PROXIMITY_DURATION,
    CONF_PRESENCE_ON_DURATION,
    CONF_PRESENCE_OFF_DURATION,
    CONF_PROXIMITY_MAX_AGE,
    CONF_WINDOW_OPEN_DELAY,
    CONF_WINDOW_CLOSE_DELAY,
    CONF_BOOST_DURATION,
    CONF_FROST_AFTER_ABSENCE,
    CONF_DOOR_OPEN_DELAY,
    CONF_DOOR_CLOSE_DELAY,
    CONF_ZONE_WINDOW_OPEN_DELAY,
    CONF_ZONE_WINDOW_CLOSE_DELAY,
    CONF_MAINTENANCE_DURATION,
    CONF_WARM_UP_DURATION,
    CONF_PREHEAT_EXTENSION,
)

_WEEKDAYS = (
    "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"
)


def _weekday_selector() -> selector.SelectSelector:
    """Weekday of the valve maintenance, or every 7 days."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=MAINTENANCE_ANY_DAY, label="Alle 7 Tage"
                ),
                *(
                    selector.SelectOptionDict(value=str(index), label=name)
                    for index, name in enumerate(_WEEKDAYS)
                ),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _window_change_selector() -> selector.SelectSelector:
    """What happens to a setpoint changed while a window is open."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=WINDOW_CHANGE_KEEP, label="Merken und nach dem Schließen anwenden"
                ),
                selector.SelectOptionDict(value=WINDOW_CHANGE_DISCARD, label="Verwerfen"),
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _force_selector() -> selector.EntitySelector:
    """Switches, sensors or timers that force comfort or eco while on."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(
            domain=["input_boolean", "binary_sensor", "switch", "timer"],
            multiple=True,
        )
    )


def _degrees_selector(maximum: float, step: float) -> selector.NumberSelector:
    """A small temperature difference in Celsius."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=maximum, step=step, mode="slider", unit_of_measurement="°C"
        )
    )


def _temperature_selector(minimum: float, maximum: float) -> selector.NumberSelector:
    """Create a temperature slider in Celsius."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=0.5, mode="slider"
        )
    )


def _hysteresis_selector() -> selector.NumberSelector:
    """Deadband in Celsius for re-adjusting the valves."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0, max=2, step=0.1, mode="slider", unit_of_measurement="°C"
        )
    )


def _zone_selector() -> selector.ConfigEntrySelector:
    """Pick a proximity zone; its sensors are found automatically."""
    return selector.ConfigEntrySelector(
        selector.ConfigEntrySelectorConfig(integration="proximity")
    )


def _notify_selector(hass) -> selector.SelectSelector:
    """Notify services of this Home Assistant, or a typed-in one."""
    services = sorted(
        f"notify.{name}"
        for name in hass.services.async_services().get("notify", {})
        if name not in ("send_message", "persistent_notification")
    )
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=services,
            custom_value=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _house_schema(hass) -> vol.Schema:
    return vol.Schema({
        vol.Optional(CONF_NOTIFY_SERVICE): _notify_selector(hass),
        vol.Optional(CONF_HOUSE_CALENDAR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["calendar", "schedule"])
        ),
    })


def _away_below_comfort(values: dict, comfort: float) -> bool:
    """An optional away temperature must stay below the comfort target."""
    away = values.get(CONF_AWAY_TEMPERATURE)
    return away is None or float(away) < comfort


def _setback_error(values: dict, comfort: float) -> str | None:
    """Optional window and frost temperatures must stay below comfort."""
    for key, error in (
        (CONF_WINDOW_TEMPERATURE, "window_must_be_below_comfort"),
        (CONF_FROST_PROTECTION_TEMPERATURE, "frost_must_be_below_comfort"),
    ):
        value = values.get(key)
        if value is not None and float(value) >= comfort:
            return error
    return None


def _user_schema() -> vol.Schema:
    """Build the initial entity and tuning form."""
    return vol.Schema(
        {
            vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(CONF_ADDITIONAL_CLIMATE_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            vol.Optional(CONF_CALIBRATION, default=False): selector.BooleanSelector(),
            vol.Optional(
                CONF_EXTERNAL_TEMPERATURE, default=False
            ): selector.BooleanSelector(),
            vol.Optional(CONF_VALVE_MAINTENANCE, default=False): selector.BooleanSelector(),
            vol.Optional(
                CONF_HYSTERESIS, default=DEFAULT_HYSTERESIS
            ): _hysteresis_selector(),
            vol.Required(CONF_ROOM_TEMPERATURE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(CONF_SCHEDULE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["schedule", "calendar"])
            ),
            vol.Optional(CONF_WINDOW_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(
                CONF_WINDOW_OPEN_DELAY,
                default=_seconds_to_duration(DEFAULT_WINDOW_OPEN_DELAY),
            ): _duration_selector(),
            vol.Optional(
                CONF_WINDOW_CLOSE_DELAY,
                default=_seconds_to_duration(DEFAULT_WINDOW_CLOSE_DELAY),
            ): _duration_selector(),
            vol.Optional(CONF_WINDOW_TEMPERATURE): _temperature_selector(5, 21),
            vol.Optional(
                CONF_WINDOW_DROP_DETECTION, default=False
            ): selector.BooleanSelector(),
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
            vol.Optional(CONF_PROXIMITY_ZONE): _zone_selector(),
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
            vol.Optional(CONF_HEATING_LIMIT_TEMPERATURE): _temperature_selector(10, 25),
            vol.Optional(CONF_HEATING_SEASON_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
            ),
            vol.Required(
                CONF_COMFORT_TEMPERATURE, default=DEFAULT_COMFORT_TEMPERATURE
            ): _temperature_selector(16, 25),
            vol.Required(
                CONF_ECO_TEMPERATURE, default=DEFAULT_ECO_TEMPERATURE
            ): _temperature_selector(7, 21),
            vol.Optional(CONF_AWAY_TEMPERATURE): _temperature_selector(5, 21),
            vol.Optional(CONF_FROST_PROTECTION_TEMPERATURE): _temperature_selector(5, 15),
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
        """Return the editor for an existing room or the house settings."""
        if config_entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE:
            return HouseOptionsFlow()
        return DynamicHeatingOptionsFlow()

    def _rooms(self) -> list[ConfigEntry]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_HOUSE
        ]

    async def async_step_user(self, user_input=None):
        """Choose between a new room, a copy of a room and the house settings."""
        options = ["room"]
        if self._rooms():
            options.append("copy")
        if not any(
            entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        ):
            options.append("house")
        return self.async_show_menu(step_id="user", menu_options=options)

    async def async_step_house(self, user_input=None):
        """Create the house-wide settings (house mode, vacation, overview)."""
        await self.async_set_unique_id(ENTRY_TYPE_HOUSE)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(
                title="Haus",
                data={CONF_ENTRY_TYPE: ENTRY_TYPE_HOUSE},
                options={
                    CONF_NOTIFY_SERVICE: user_input.get(CONF_NOTIFY_SERVICE) or None,
                    CONF_HOUSE_CALENDAR: user_input.get(CONF_HOUSE_CALENDAR) or None,
                },
            )
        return self.async_show_form(
            step_id="house", data_schema=_house_schema(self.hass)
        )

    async def async_step_copy(self, user_input=None):
        """Pick the room whose settings the new room takes over."""
        if user_input is not None:
            self._copy_source = user_input["source"]
            return await self.async_step_copy_room()
        return self.async_show_form(
            step_id="copy",
            data_schema=vol.Schema({
                vol.Required("source"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value=entry.entry_id, label=entry.title)
                            for entry in self._rooms()
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }),
        )

    async def async_step_copy_room(self, user_input=None):
        """The new room's own devices; everything else comes from the source."""
        source = self.hass.config_entries.async_get_entry(self._copy_source)
        if source is None:
            return self.async_abort(reason="source_missing")
        values = {**dict(source.data), **dict(source.options)}
        if user_input is not None:
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            await self.async_set_unique_id(climate_entity)
            self._abort_if_unique_id_configured()
            data = {key: value for key, value in values.items() if value is not None}
            for key in (
                CONF_ADDITIONAL_CLIMATE_ENTITIES,
                CONF_WINDOW_ENTITY,
                CONF_ADDITIONAL_WINDOW_ENTITIES,
                CONF_DOOR_ENTITIES,
                CONF_PRESENCE_ENTITY,
            ):
                data.pop(key, None)
            data.update(
                {key: value for key, value in user_input.items() if value}
            )
            return self.async_create_entry(
                title=f"Dynamische Heizung – {climate_entity}", data=data
            )
        schema = vol.Schema({
            vol.Required(CONF_CLIMATE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate")
            ),
            vol.Optional(CONF_ADDITIONAL_CLIMATE_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            vol.Required(CONF_ROOM_TEMPERATURE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            vol.Required(
                CONF_SCHEDULE_ENTITY, default=values.get(CONF_SCHEDULE_ENTITY)
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["schedule", "calendar"])
            ),
            vol.Optional(CONF_WINDOW_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="binary_sensor")
            ),
            vol.Optional(CONF_PRESENCE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["binary_sensor", "input_boolean"])
            ),
        })
        return self.async_show_form(
            step_id="copy_room",
            data_schema=schema,
            description_placeholders={"source": source.title},
        )

    async def async_step_room(self, user_input=None):
        """Handle the form for a new room."""
        errors: dict[str, str] = {}
        if user_input is not None:
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            await self.async_set_unique_id(climate_entity)
            self._abort_if_unique_id_configured()
            comfort = float(user_input[CONF_COMFORT_TEMPERATURE])
            eco = float(user_input[CONF_ECO_TEMPERATURE])
            if eco >= comfort:
                errors["base"] = "eco_must_be_below_comfort"
            elif not _away_below_comfort(user_input, comfort):
                errors["base"] = "away_must_be_below_comfort"
            elif error := _setback_error(user_input, comfort):
                errors["base"] = error
            else:
                title = f"Dynamische Heizung – {climate_entity}"
                data = dict(user_input)
                for key in _DURATION_OPTIONS:
                    if key in data:
                        data[key] = _duration_to_seconds(data[key])
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id="room", data_schema=_user_schema(), errors=errors
        )


# Pages of the room editor; "save" stores the changes of all pages.
OPTIONS_MENU = [
    "basics",
    "valves",
    "modes",
    "presence",
    "geofencing",
    "environment",
    "intelligence",
    "save",
]
# Every setting this version knows (the CONF_* values of const).
_KNOWN_KEYS = frozenset(
    value
    for name, value in vars(const).items()
    if name.startswith("CONF_") and isinstance(value, str)
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
        values.setdefault(CONF_WINDOW_OPEN_DELAY, DEFAULT_WINDOW_OPEN_DELAY)
        values.setdefault(CONF_WINDOW_CLOSE_DELAY, DEFAULT_WINDOW_CLOSE_DELAY)
        values.setdefault(CONF_DOOR_OPEN_DELAY, DEFAULT_DOOR_OPEN_DELAY)
        values.setdefault(CONF_DOOR_CLOSE_DELAY, DEFAULT_DOOR_CLOSE_DELAY)
        values.setdefault(CONF_ZONE_WINDOW_OPEN_DELAY, DEFAULT_ZONE_WINDOW_OPEN_DELAY)
        values.setdefault(CONF_ZONE_WINDOW_CLOSE_DELAY, DEFAULT_ZONE_WINDOW_CLOSE_DELAY)
        values.setdefault(CONF_MAINTENANCE_DURATION, VALVE_MAINTENANCE_PHASE_SECONDS)
        return values

    def _values(self) -> dict:
        """Keep pending edits across all editor steps."""
        if not hasattr(self, "_working_values"):
            self._working_values = self._current_values()
        return self._working_values

    @staticmethod
    def _entity_field(key: str, domain: str | list[str], current: dict, *, multiple=False):
        """Create an optional selector.

        Saved values are shown as suggested values, not as a schema default:
        a default would refill a field the user cleared, so it could never be
        removed again.
        """
        return (
            vol.Optional(key),
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
        """The essentials: valves, room sensor, schedule and temperatures."""
        return vol.Schema({
            vol.Required(
                CONF_CLIMATE_ENTITY, default=current[CONF_CLIMATE_ENTITY]
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
            vol.Optional(CONF_ADDITIONAL_CLIMATE_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="climate", multiple=True)
            ),
            vol.Required(
                CONF_ROOM_TEMPERATURE_ENTITY,
                default=current[CONF_ROOM_TEMPERATURE_ENTITY],
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor")),
            vol.Required(
                CONF_SCHEDULE_ENTITY, default=current[CONF_SCHEDULE_ENTITY]
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["schedule", "calendar"])
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
                selector.NumberSelectorConfig(min=15, max=240, step=5, mode="slider")
            ),
            vol.Optional(CONF_FROST_PROTECTION_TEMPERATURE): _temperature_selector(5, 15),
        })

    def _valves_schema(self, current: dict) -> vol.Schema:
        """How the valves are driven: feed, calibration, maintenance, timing."""
        return vol.Schema({
            vol.Optional(
                CONF_CALIBRATION, default=bool(current.get(CONF_CALIBRATION, False))
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_EXTERNAL_TEMPERATURE,
                default=bool(current.get(CONF_EXTERNAL_TEMPERATURE, False)),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_VALVE_MAINTENANCE,
                default=bool(current.get(CONF_VALVE_MAINTENANCE, False)),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_MAINTENANCE_WEEKDAY,
                default=str(current.get(CONF_MAINTENANCE_WEEKDAY) or MAINTENANCE_ANY_DAY),
            ): _weekday_selector(),
            vol.Optional(
                CONF_MAINTENANCE_HOUR,
                default=int(current.get(CONF_MAINTENANCE_HOUR, VALVE_MAINTENANCE_HOUR)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0, max=23, step=1, mode="box")
            ),
            self._duration_field(
                CONF_MAINTENANCE_DURATION, current, VALVE_MAINTENANCE_PHASE_SECONDS
            )[0]: _duration_selector(),
            vol.Optional(
                CONF_HYSTERESIS,
                default=float(current.get(CONF_HYSTERESIS, DEFAULT_HYSTERESIS)),
            ): _hysteresis_selector(),
            vol.Optional(
                CONF_COMMAND_DELAY,
                default=float(current.get(CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY)),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0, max=5, step=0.1, mode="slider", unit_of_measurement="s"
                )
            ),
            vol.Optional(
                CONF_SYNC_MANUAL_CHANGE,
                default=bool(
                    current.get(CONF_SYNC_MANUAL_CHANGE, DEFAULT_SYNC_MANUAL_CHANGE)
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_LOCK_VALVES, default=bool(current.get(CONF_LOCK_VALVES, False))
            ): selector.BooleanSelector(),
            vol.Optional(CONF_AGGRESSIVE_RANGE): _degrees_selector(2, 0.1),
            vol.Optional(
                CONF_AGGRESSIVE_OFFSET,
                default=float(
                    current.get(CONF_AGGRESSIVE_OFFSET, DEFAULT_AGGRESSIVE_OFFSET)
                ),
            ): _degrees_selector(5, 0.5),
            vol.Optional(
                CONF_VALVE_FALLBACK,
                default=bool(current.get(CONF_VALVE_FALLBACK, DEFAULT_VALVE_FALLBACK)),
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_VALVE_SENSOR_CALIBRATION,
                default=bool(
                    current.get(
                        CONF_VALVE_SENSOR_CALIBRATION, DEFAULT_VALVE_SENSOR_CALIBRATION
                    )
                ),
            ): selector.BooleanSelector(),
        })

    def _modes_schema(self, current: dict) -> vol.Schema:
        """More schedules, eco times, boost, quick modes and Kurz wärmer."""
        return vol.Schema({
            vol.Optional(CONF_ADDITIONAL_SCHEDULE_ENTITIES): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["schedule", "calendar"], multiple=True
                )
            ),
            vol.Optional(CONF_ECO_SCHEDULE_ENTITY): selector.EntitySelector(
                selector.EntitySelectorConfig(domain=["schedule", "calendar"])
            ),
            vol.Optional(
                CONF_BOOST_TEMPERATURE,
                default=float(
                    current.get(CONF_BOOST_TEMPERATURE, DEFAULT_BOOST_TEMPERATURE)
                ),
            ): _temperature_selector(16, 30),
            self._duration_field(
                CONF_BOOST_DURATION, current, DEFAULT_BOOST_DURATION
            )[0]: _duration_selector(),
            **{
                vol.Optional(key, default=float(current.get(key, default))):
                    _temperature_selector(5, 30)
                for key, default in (
                    (CONF_HOME_TEMPERATURE, DEFAULT_HOME_TEMPERATURE),
                    (CONF_ACTIVITY_TEMPERATURE, DEFAULT_ACTIVITY_TEMPERATURE),
                    (CONF_SLEEP_TEMPERATURE, DEFAULT_SLEEP_TEMPERATURE),
                )
            },
            vol.Optional(
                CONF_WARM_UP_STEP,
                default=float(current.get(CONF_WARM_UP_STEP, DEFAULT_WARM_UP_STEP)),
            ): _degrees_selector(3, 0.5),
            self._duration_field(
                CONF_WARM_UP_DURATION, current, DEFAULT_WARM_UP_DURATION
            )[0]: _duration_selector(),
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
        schema[vol.Optional(CONF_AWAY_TEMPERATURE)] = _temperature_selector(5, 21)
        schema[vol.Optional(CONF_AWAY_OFFSET)] = _degrees_selector(6, 0.5)
        schema[vol.Optional(
            CONF_AWAY_SCHEDULE_MODE,
            default=bool(current.get(CONF_AWAY_SCHEDULE_MODE, False)),
        )] = selector.BooleanSelector()
        item = self._duration_field(
            CONF_FROST_AFTER_ABSENCE, current, DEFAULT_FROST_AFTER_ABSENCE
        )
        schema[item[0]] = item[1]
        schema[vol.Optional(CONF_FORCE_COMFORT_ENTITIES)] = _force_selector()
        schema[vol.Optional(CONF_FORCE_ECO_ENTITIES)] = _force_selector()
        schema[vol.Optional(
            CONF_FOLLOW_HOUSE_CALENDAR,
            default=bool(
                current.get(CONF_FOLLOW_HOUSE_CALENDAR, DEFAULT_FOLLOW_HOUSE_CALENDAR)
            ),
        )] = selector.BooleanSelector()
        return vol.Schema(schema)

    def _proximity_schema(self, current: dict) -> vol.Schema:
        """Geo-fencing sensors, distance limit and data freshness."""
        schema = {vol.Optional(CONF_PROXIMITY_ZONE): _zone_selector()}
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
            self._entity_field(
                CONF_ADDITIONAL_WINDOW_ENTITIES, "binary_sensor", current, multiple=True
            ),
            self._duration_field(CONF_WINDOW_OPEN_DELAY, current, DEFAULT_WINDOW_OPEN_DELAY),
            self._duration_field(CONF_WINDOW_CLOSE_DELAY, current, DEFAULT_WINDOW_CLOSE_DELAY),
            self._entity_field(CONF_DOOR_ENTITIES, "binary_sensor", current, multiple=True),
            self._duration_field(CONF_DOOR_OPEN_DELAY, current, DEFAULT_DOOR_OPEN_DELAY),
            self._duration_field(CONF_DOOR_CLOSE_DELAY, current, DEFAULT_DOOR_CLOSE_DELAY),
            self._entity_field(
                CONF_ZONE_WINDOW_ENTITIES, "binary_sensor", current, multiple=True
            ),
            self._duration_field(
                CONF_ZONE_WINDOW_OPEN_DELAY, current, DEFAULT_ZONE_WINDOW_OPEN_DELAY
            ),
            self._duration_field(
                CONF_ZONE_WINDOW_CLOSE_DELAY, current, DEFAULT_ZONE_WINDOW_CLOSE_DELAY
            ),
        ):
            schema[item[0]] = item[1]
        schema[vol.Optional(
            CONF_WINDOW_CHANGE,
            default=current.get(CONF_WINDOW_CHANGE) or WINDOW_CHANGE_KEEP,
        )] = _window_change_selector()
        schema[vol.Optional(CONF_WINDOW_TEMPERATURE)] = _temperature_selector(5, 21)
        schema[vol.Optional(
            CONF_WINDOW_DROP_DETECTION,
            default=bool(current.get(CONF_WINDOW_DROP_DETECTION, False)),
        )] = selector.BooleanSelector()
        schema[vol.Optional(
            CONF_DISABLE_TRV_WINDOW_DETECTION,
            default=bool(current.get(CONF_DISABLE_TRV_WINDOW_DETECTION, False)),
        )] = selector.BooleanSelector()
        for item in (
            self._entity_field(CONF_OUTDOOR_TEMPERATURE_ENTITY, "sensor", current),
            self._entity_field(CONF_WEATHER_ENTITY, "weather", current),
            self._entity_field(CONF_HUMIDITY_ENTITY, "sensor", current),
            self._entity_field(
                CONF_HEATING_SEASON_ENTITY, ["binary_sensor", "input_boolean"], current
            ),
        ):
            schema[item[0]] = item[1]
        schema[vol.Optional(CONF_HEATING_LIMIT_TEMPERATURE)] = _temperature_selector(10, 25)
        schema[vol.Optional(
            CONF_HEATING_LIMIT_AVERAGE,
            default=bool(
                current.get(CONF_HEATING_LIMIT_AVERAGE, DEFAULT_HEATING_LIMIT_AVERAGE)
            ),
        )] = selector.BooleanSelector()
        schema[vol.Optional(
            CONF_HEATING_LIMIT_FALLBACK_OFF,
            default=bool(current.get(CONF_HEATING_LIMIT_FALLBACK_OFF, False)),
        )] = selector.BooleanSelector()
        schema[vol.Optional(CONF_NOTIFY_SERVICE)] = _notify_selector(self.hass)
        schema[
            vol.Optional(
                CONF_NOTIFY_AWAY,
                default=bool(current.get(CONF_NOTIFY_AWAY, DEFAULT_NOTIFY_AWAY)),
            )
        ] = selector.BooleanSelector()
        return vol.Schema(schema)

    def _intelligence_schema(self, current: dict) -> vol.Schema:
        """Room model, setback limit, presence learning and optimum stop."""
        schema = {}
        for key, default in (
            (CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL),
            (CONF_RECOVERY_LIMIT, DEFAULT_RECOVERY_LIMIT),
        ):
            schema[vol.Optional(key, default=bool(current.get(key, default)))] = (
                selector.BooleanSelector()
            )
        item = self._duration_field(
            CONF_ROOM_EMPTY_RECOVERY, current, DEFAULT_ROOM_EMPTY_RECOVERY
        )
        schema[item[0]] = item[1]
        for key, default in (
            (CONF_PREHEAT_WHEN_HOME, DEFAULT_PREHEAT_WHEN_HOME),
            (CONF_LEARN_USAGE, DEFAULT_LEARN_USAGE),
        ):
            schema[vol.Optional(key, default=bool(current.get(key, default)))] = (
                selector.BooleanSelector()
            )
        for item in (
            self._duration_field(CONF_ROOM_EMPTY_GRACE, current, DEFAULT_ROOM_EMPTY_GRACE),
            self._duration_field(CONF_EARLY_STOP, current, DEFAULT_EARLY_STOP),
            self._entity_field(CONF_SOLAR_RADIATION_ENTITY, "sensor", current),
            self._entity_field(CONF_WIND_SPEED_ENTITY, "sensor", current),
        ):
            schema[item[0]] = item[1]
        for key, default in (
            (CONF_PUNCTUALITY, DEFAULT_PUNCTUALITY),
            (CONF_MORNING_REPORT, DEFAULT_MORNING_REPORT),
            (CONF_HOLD_BEFORE_PAUSE, DEFAULT_HOLD_BEFORE_PAUSE),
        ):
            schema[vol.Optional(key, default=bool(current.get(key, default)))] = (
                selector.BooleanSelector()
            )
        item = self._duration_field(
            CONF_PREHEAT_EXTENSION, current, DEFAULT_PREHEAT_EXTENSION
        )
        schema[item[0]] = item[1]
        return vol.Schema(schema)

    def _show_step(
        self,
        step_id: str,
        schema: vol.Schema,
        current: dict,
        errors: dict[str, str] | None = None,
    ):
        """Render one editor page while preserving and formatting saved values."""
        suggested = dict(current)
        # Native duration selectors require a structured duration, not seconds.
        for key in _DURATION_OPTIONS:
            if key in suggested and not isinstance(suggested[key], dict):
                suggested[key] = _seconds_to_duration(suggested[key])
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors or {},
        )

    async def async_step_init(self, user_input=None):
        """Menu: the essentials first, everything else on its own page."""
        self._values()
        return self.async_show_menu(step_id="init", menu_options=OPTIONS_MENU)

    async def async_step_basics(self, user_input=None):
        """Valves, room sensor, schedule and the temperatures."""
        current = self._values()
        errors: dict[str, str] = {}
        if user_input is not None:
            comfort = float(user_input[CONF_COMFORT_TEMPERATURE])
            eco = float(user_input[CONF_ECO_TEMPERATURE])
            climate_entity = user_input[CONF_CLIMATE_ENTITY]
            if eco >= comfort:
                errors["base"] = "eco_must_be_below_comfort"
            elif error := _setback_error(
                {
                    CONF_FROST_PROTECTION_TEMPERATURE: user_input.get(
                        CONF_FROST_PROTECTION_TEMPERATURE
                    ),
                    CONF_WINDOW_TEMPERATURE: current.get(CONF_WINDOW_TEMPERATURE),
                },
                comfort,
            ):
                errors["base"] = error
            elif any(
                entry.entry_id != self.config_entry.entry_id
                and entry.unique_id == climate_entity
                for entry in self.hass.config_entries.async_entries(DOMAIN)
            ):
                return self.async_abort(reason="already_configured")
            else:
                current.update(user_input)
                # A cleared field must override a value saved earlier.
                current[CONF_ADDITIONAL_CLIMATE_ENTITIES] = [
                    entity_id
                    for entity_id in user_input.get(CONF_ADDITIONAL_CLIMATE_ENTITIES) or []
                    if entity_id != climate_entity
                ]
                current[CONF_FROST_PROTECTION_TEMPERATURE] = user_input.get(
                    CONF_FROST_PROTECTION_TEMPERATURE
                )
                current[CONF_ADDITIONAL_SCHEDULE_ENTITIES] = [
                    entity_id
                    for entity_id in current.get(CONF_ADDITIONAL_SCHEDULE_ENTITIES) or []
                    if entity_id != user_input[CONF_SCHEDULE_ENTITY]
                ]
                return await self.async_step_init()

        suggested = dict(current)
        suggested.update(user_input or {})
        # Keep the user's attempted values visible when validation fails.
        return self.async_show_form(
            step_id="basics",
            data_schema=self.add_suggested_values_to_schema(
                self._basic_schema(current), suggested
            ),
            errors=errors,
        )

    async def async_step_valves(self, user_input=None):
        """External temperature, calibration, maintenance and timing."""
        current = self._values()
        if user_input is not None:
            current.update(user_input)
            # An empty range turns aggressive mode off.
            current[CONF_AGGRESSIVE_RANGE] = user_input.get(CONF_AGGRESSIVE_RANGE)
            current[CONF_MAINTENANCE_DURATION] = _duration_to_seconds(
                user_input.get(
                    CONF_MAINTENANCE_DURATION,
                    current.get(
                        CONF_MAINTENANCE_DURATION, VALVE_MAINTENANCE_PHASE_SECONDS
                    ),
                )
            ) or VALVE_MAINTENANCE_PHASE_SECONDS
            if CONF_MAINTENANCE_HOUR in user_input:
                current[CONF_MAINTENANCE_HOUR] = int(user_input[CONF_MAINTENANCE_HOUR])
            current[CONF_VALVE_FALLBACK] = bool(
                user_input.get(CONF_VALVE_FALLBACK, DEFAULT_VALVE_FALLBACK)
            )
            current[CONF_VALVE_SENSOR_CALIBRATION] = bool(
                user_input.get(
                    CONF_VALVE_SENSOR_CALIBRATION, DEFAULT_VALVE_SENSOR_CALIBRATION
                )
            )
            return await self.async_step_init()
        return self._show_step("valves", self._valves_schema(current), current)

    async def async_step_modes(self, user_input=None):
        """More schedules, eco times, boost, quick modes and Kurz wärmer."""
        current = self._values()
        if user_input is not None:
            current.update(user_input)
            current[CONF_ADDITIONAL_SCHEDULE_ENTITIES] = [
                entity_id
                for entity_id in user_input.get(CONF_ADDITIONAL_SCHEDULE_ENTITIES) or []
                if entity_id != current[CONF_SCHEDULE_ENTITY]
            ]
            current[CONF_ECO_SCHEDULE_ENTITY] = (
                user_input.get(CONF_ECO_SCHEDULE_ENTITY) or None
            )
            for key, default in (
                (CONF_BOOST_DURATION, DEFAULT_BOOST_DURATION),
                (CONF_WARM_UP_DURATION, DEFAULT_WARM_UP_DURATION),
            ):
                current[key] = _duration_to_seconds(
                    user_input.get(key, current.get(key, default))
                ) or default
            return await self.async_step_init()
        return self._show_step("modes", self._modes_schema(current), current)

    async def async_step_save(self, user_input=None):
        """Store every page's changes at once."""
        current = self._values()
        climate_entity = current[CONF_CLIMATE_ENTITY]
        # Keys no version reads any more (left over from old releases) go.
        options = {key: value for key, value in current.items() if key in _KNOWN_KEYS}
        if climate_entity != self.config_entry.unique_id:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                unique_id=climate_entity,
                title=f"Dynamische Heizung – {climate_entity}",
            )
        return self.async_create_entry(title="", data=options)

    async def async_step_presence(self, user_input=None):
        """Step 2: occupancy, people and guest mode."""
        current = self._values()
        if user_input is not None and not _away_below_comfort(
            user_input, float(current[CONF_COMFORT_TEMPERATURE])
        ):
            return self._show_step(
                "presence",
                self._presence_schema(current),
                {**current, **user_input},
                {"base": "away_must_be_below_comfort"},
            )
        if user_input is not None:
            current.update(user_input)
            # A cleared field must override a value saved earlier.
            current[CONF_AWAY_TEMPERATURE] = user_input.get(CONF_AWAY_TEMPERATURE)
            current[CONF_AWAY_OFFSET] = user_input.get(CONF_AWAY_OFFSET) or None
            current[CONF_AWAY_SCHEDULE_MODE] = bool(
                user_input.get(CONF_AWAY_SCHEDULE_MODE, False)
            )
            for key in (CONF_PERSON_ENTITIES, CONF_GUEST_ENTITY, CONF_PRESENCE_ENTITY,
                        CONF_PRESENCE_SCHEDULE_ENTITY, CONF_FORCE_COMFORT_ENTITIES,
                        CONF_FORCE_ECO_ENTITIES):
                current[key] = user_input.get(key) or None
            current[CONF_FOLLOW_HOUSE_CALENDAR] = bool(
                user_input.get(CONF_FOLLOW_HOUSE_CALENDAR, DEFAULT_FOLLOW_HOUSE_CALENDAR)
            )
            for key in (CONF_ENTER_HOME_DURATION, CONF_LEAVING_HOME_DURATION,
                        CONF_PRESENCE_ON_DURATION, CONF_PRESENCE_OFF_DURATION,
                        CONF_FROST_AFTER_ABSENCE):
                current[key] = _duration_to_seconds(user_input.get(key, current.get(key, 0)))
            return await self.async_step_init()

        return self._show_step("presence", self._presence_schema(current), current)

    async def async_step_geofencing(self, user_input=None):
        """Step 3: proximity source, arrival radius and location freshness."""
        current = self._values()
        if user_input is not None:
            current.update(user_input)
            current[CONF_PROXIMITY_ZONE] = user_input.get(CONF_PROXIMITY_ZONE) or None
            # The zone replaces the separate distance and direction sensors.
            for key in (CONF_PROXIMITY_ENTITY, CONF_PROXIMITY_DIRECTION_ENTITY):
                current[key] = None
            current[CONF_PROXIMITY_DISTANCE] = max(
                0, int(user_input.get(CONF_PROXIMITY_DISTANCE, DEFAULT_PROXIMITY_DISTANCE))
            )
            for key in (CONF_PROXIMITY_DURATION, CONF_PROXIMITY_MAX_AGE):
                current[key] = _duration_to_seconds(user_input.get(key, current.get(key, 0)))
            return await self.async_step_init()

        return self._show_step(
            "geofencing", self._proximity_schema(current), current
        )

    async def async_step_environment(self, user_input=None):
        """Step 4: optional window, outdoor temperature and weather sensors."""
        current = self._values()
        error = None if user_input is None else _setback_error(
            user_input, float(current[CONF_COMFORT_TEMPERATURE])
        )
        if error:
            return self._show_step(
                "environment",
                self._environment_schema(current),
                {**current, **user_input},
                {"base": error},
            )
        if user_input is not None:
            current.update(user_input)
            for key in (CONF_WINDOW_ENTITY, CONF_OUTDOOR_TEMPERATURE_ENTITY, CONF_WEATHER_ENTITY,
                        CONF_HEATING_SEASON_ENTITY, CONF_HUMIDITY_ENTITY):
                current[key] = user_input.get(key) or None
            current[CONF_ADDITIONAL_WINDOW_ENTITIES] = [
                entity_id
                for entity_id in user_input.get(CONF_ADDITIONAL_WINDOW_ENTITIES) or []
                if entity_id != current[CONF_WINDOW_ENTITY]
            ]
            for key in (CONF_DOOR_ENTITIES, CONF_ZONE_WINDOW_ENTITIES):
                current[key] = list(user_input.get(key) or [])
            for key in (CONF_WINDOW_OPEN_DELAY, CONF_WINDOW_CLOSE_DELAY,
                        CONF_DOOR_OPEN_DELAY, CONF_DOOR_CLOSE_DELAY,
                        CONF_ZONE_WINDOW_OPEN_DELAY, CONF_ZONE_WINDOW_CLOSE_DELAY):
                current[key] = _duration_to_seconds(user_input.get(key, current.get(key, 0)))
            current[CONF_WINDOW_CHANGE] = (
                user_input.get(CONF_WINDOW_CHANGE) or WINDOW_CHANGE_KEEP
            )
            for key, default in (
                (CONF_HEATING_LIMIT_AVERAGE, DEFAULT_HEATING_LIMIT_AVERAGE),
                (CONF_HEATING_LIMIT_FALLBACK_OFF, False),
            ):
                current[key] = bool(user_input.get(key, default))
            current[CONF_WINDOW_TEMPERATURE] = user_input.get(CONF_WINDOW_TEMPERATURE)
            current[CONF_WINDOW_DROP_DETECTION] = bool(
                user_input.get(CONF_WINDOW_DROP_DETECTION, False)
            )
            current[CONF_DISABLE_TRV_WINDOW_DETECTION] = bool(
                user_input.get(CONF_DISABLE_TRV_WINDOW_DETECTION, False)
            )
            # A cleared field must override a value saved earlier.
            current[CONF_HEATING_LIMIT_TEMPERATURE] = user_input.get(
                CONF_HEATING_LIMIT_TEMPERATURE
            )
            current[CONF_NOTIFY_SERVICE] = user_input.get(CONF_NOTIFY_SERVICE) or None
            current[CONF_NOTIFY_AWAY] = bool(
                user_input.get(CONF_NOTIFY_AWAY, DEFAULT_NOTIFY_AWAY)
            )

            return await self.async_step_init()

        return self._show_step(
            "environment", self._environment_schema(current), current
        )

    async def async_step_intelligence(self, user_input=None):
        """Step 5: room model, setback limit, presence learning, sun and wind."""
        current = self._values()
        if user_input is not None:
            current.update(user_input)
            for key, default in (
                (CONF_ROOM_MODEL, DEFAULT_ROOM_MODEL),
                (CONF_RECOVERY_LIMIT, DEFAULT_RECOVERY_LIMIT),
                (CONF_PREHEAT_WHEN_HOME, DEFAULT_PREHEAT_WHEN_HOME),
                (CONF_LEARN_USAGE, DEFAULT_LEARN_USAGE),
                (CONF_PUNCTUALITY, DEFAULT_PUNCTUALITY),
                (CONF_MORNING_REPORT, DEFAULT_MORNING_REPORT),
                (CONF_HOLD_BEFORE_PAUSE, DEFAULT_HOLD_BEFORE_PAUSE),
            ):
                current[key] = bool(user_input.get(key, default))
            for key in (CONF_ROOM_EMPTY_RECOVERY, CONF_ROOM_EMPTY_GRACE, CONF_EARLY_STOP,
                        CONF_PREHEAT_EXTENSION):
                current[key] = _duration_to_seconds(user_input.get(key, current.get(key, 0)))
            for key in (CONF_SOLAR_RADIATION_ENTITY, CONF_WIND_SPEED_ENTITY):
                current[key] = user_input.get(key) or None
            return await self.async_step_init()

        return self._show_step(
            "intelligence", self._intelligence_schema(current), current
        )


class HouseOptionsFlow(config_entries.OptionsFlowWithReload):
    """Settings of the house entry, and copying settings between rooms."""

    async def async_step_init(self, user_input=None):
        return await self.async_step_house_menu()

    async def async_step_house_menu(self, user_input=None):
        return self.async_show_menu(
            step_id="house_menu", menu_options=["house_settings", "copy_settings"]
        )

    async def async_step_house_settings(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_NOTIFY_SERVICE: user_input.get(CONF_NOTIFY_SERVICE) or None,
                    CONF_HOUSE_CALENDAR: user_input.get(CONF_HOUSE_CALENDAR) or None,
                },
            )
        return self.async_show_form(
            step_id="house_settings",
            data_schema=self.add_suggested_values_to_schema(
                _house_schema(self.hass), dict(self.config_entry.options)
            ),
        )

    def _rooms(self) -> list[ConfigEntry]:
        return [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_ENTRY_TYPE) != ENTRY_TYPE_HOUSE
        ]

    async def async_step_copy_settings(self, user_input=None):
        """Write chosen groups of settings from one room to other rooms."""
        rooms = self._rooms()
        errors: dict[str, str] = {}
        if user_input is not None:
            source = self.hass.config_entries.async_get_entry(user_input["source"])
            targets = [
                entry
                for entry in rooms
                if entry.entry_id in (user_input.get("targets") or [])
                and source is not None
                and entry.entry_id != source.entry_id
            ]
            groups = user_input.get("groups") or []
            if source is None or not targets or not groups:
                errors["base"] = "copy_nothing_selected"
            else:
                values = {**dict(source.data), **dict(source.options)}
                keys = [key for group in groups for key in SETTINGS_GROUPS.get(group, ())]
                for target in targets:
                    options = {**dict(target.data), **dict(target.options)}
                    for key in keys:
                        if key in values:
                            options[key] = values[key]
                        else:
                            options.pop(key, None)
                    self.hass.config_entries.async_update_entry(target, options=options)
                    self.hass.config_entries.async_schedule_reload(target.entry_id)
                return self.async_create_entry(
                    title="", data=dict(self.config_entry.options)
                )
        room_options = [
            selector.SelectOptionDict(value=entry.entry_id, label=entry.title)
            for entry in rooms
        ]
        schema = vol.Schema({
            vol.Required("source"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options, mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required("targets"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=room_options,
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            vol.Required("groups"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=list(SETTINGS_GROUPS),
                    multiple=True,
                    mode=selector.SelectSelectorMode.LIST,
                    translation_key="settings_groups",
                )
            ),
        })
        return self.async_show_form(
            step_id="copy_settings", data_schema=schema, errors=errors
        )
