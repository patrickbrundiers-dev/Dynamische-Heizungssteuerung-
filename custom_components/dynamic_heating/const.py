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
CONF_WEATHER_ENTITY: Final = "weather_entity"
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
# A trend is evaluated only after the reading moved by at least two typical
# 0.1 °C sensor steps; single steps are too coarse to estimate a rate.
MIN_SAMPLE_DELTA: Final = 0.2
MAX_HEATING_SAMPLE_DELTA: Final = 2.5
MAX_COOLING_SAMPLE_DELTA: Final = 2.0

# The cooling-rate estimate is deliberately bounded and learned only during
# stable, closed-window setback periods. It is a forecasting aid, not a promise.
DEFAULT_COOLING_RATE: Final = 0.3
MIN_LEARNED_COOLING_RATE: Final = 0.05
MAX_LEARNED_COOLING_RATE: Final = 2.0
MIN_COOLING_SAMPLE_SECONDS: Final = 900

CONF_PERSON_ENTITIES: Final = "person_entities"
CONF_GUEST_ENTITY: Final = "guest_entity"
CONF_ENTER_HOME_DURATION: Final = "enter_home_duration"
CONF_LEAVING_HOME_DURATION: Final = "leaving_home_duration"
CONF_PROXIMITY_ENTITY: Final = "proximity_entity"
CONF_PROXIMITY_DURATION: Final = "proximity_duration"
CONF_PROXIMITY_DISTANCE: Final = "proximity_distance"
CONF_PRESENCE_SCHEDULE_ENTITY: Final = "presence_schedule_entity"
CONF_PRESENCE_ON_DURATION: Final = "presence_on_duration"
CONF_PRESENCE_OFF_DURATION: Final = "presence_off_duration"
DEFAULT_ENTER_HOME_DURATION: Final = 2
DEFAULT_LEAVING_HOME_DURATION: Final = 2
DEFAULT_PROXIMITY_DURATION: Final = 120
DEFAULT_PROXIMITY_DISTANCE: Final = 500
DEFAULT_PRESENCE_ON_DURATION: Final = 300
DEFAULT_PRESENCE_OFF_DURATION: Final = 1200

CONF_PROXIMITY_DIRECTION_ENTITY: Final = "proximity_direction_entity"
CONF_PROXIMITY_MAX_AGE: Final = "proximity_max_age"

# GPS-derived values older than this are never used to infer a new arrival.
DEFAULT_PROXIMITY_MAX_AGE: Final = 900

# Discard implausible sample windows instead of clipping them into plausible rates.
MAX_HEATING_SAMPLE_SECONDS: Final = 21600
MAX_COOLING_SAMPLE_SECONDS: Final = 21600
FORECAST_EVALUATION_GRACE_SECONDS: Final = 1800

# A setpoint that was written successfully is not re-sent for this long, even if
# the thermostat reports a slightly different value (rounding, slow devices).
SETPOINT_RESEND_SECONDS: Final = 300

# Thermostats without hvac_action count as heating when the setpoint is at least
# this far above the room temperature (used for learning only).
INFERRED_HEATING_MARGIN: Final = 0.5
