"""Constants for the dynamic heating integration."""

from typing import Final

DOMAIN: Final = "dynamic_heating"
PLATFORMS: Final = ["sensor", "switch"]

CONF_CLIMATE_ENTITY: Final = "climate_entity"
CONF_ROOM_TEMPERATURE_ENTITY: Final = "room_temperature_entity"
CONF_SCHEDULE_ENTITY: Final = "schedule_entity"
CONF_WINDOW_ENTITY: Final = "window_entity"
CONF_PRESENCE_ENTITY: Final = "presence_entity"
CONF_OUTDOOR_TEMPERATURE_ENTITY: Final = "outdoor_temperature_entity"
CONF_COMFORT_TEMPERATURE: Final = "comfort_temperature"
CONF_ECO_TEMPERATURE: Final = "eco_temperature"
CONF_MAX_PREHEAT_MINUTES: Final = "max_preheat_minutes"

DEFAULT_COMFORT_TEMPERATURE: Final = 21.0
DEFAULT_ECO_TEMPERATURE: Final = 18.0
DEFAULT_MAX_PREHEAT_MINUTES: Final = 120
DEFAULT_HEATING_RATE: Final = 1.0
MIN_LEARNED_HEATING_RATE: Final = 0.2
MAX_LEARNED_HEATING_RATE: Final = 4.0
MIN_SAMPLE_SECONDS: Final = 300

# The cooling-rate estimate is deliberately bounded and learned only during
# stable, closed-window setback periods. It is a forecasting aid, not a promise.
DEFAULT_COOLING_RATE: Final = 0.3
MIN_LEARNED_COOLING_RATE: Final = 0.05
MAX_LEARNED_COOLING_RATE: Final = 2.0
MIN_COOLING_SAMPLE_SECONDS: Final = 900
