"""Constants for the dynamic heating integration."""

from typing import Final

DOMAIN: Final = "dynamic_heating"
PLATFORMS: Final = [
    "binary_sensor", "button", "climate", "number", "select", "sensor", "switch"
]

CONF_CLIMATE_ENTITY: Final = "climate_entity"
# Further thermostats of the same room; they get the same target.
CONF_ADDITIONAL_CLIMATE_ENTITIES: Final = "additional_climate_entities"
CONF_ROOM_TEMPERATURE_ENTITY: Final = "room_temperature_entity"
CONF_SCHEDULE_ENTITY: Final = "schedule_entity"
CONF_WINDOW_ENTITY: Final = "window_entity"
CONF_PRESENCE_ENTITY: Final = "presence_entity"
CONF_OUTDOOR_TEMPERATURE_ENTITY: Final = "outdoor_temperature_entity"
CONF_WEATHER_ENTITY: Final = "weather_entity"
CONF_COMFORT_TEMPERATURE: Final = "comfort_temperature"
CONF_ECO_TEMPERATURE: Final = "eco_temperature"
CONF_MAX_PREHEAT_MINUTES: Final = "max_preheat_minutes"
# Optional setpoint while nobody is home; falls back to the eco temperature.
CONF_AWAY_TEMPERATURE: Final = "away_temperature"
# Optional outdoor temperature at or above which comfort heating pauses.
CONF_HEATING_LIMIT_TEMPERATURE: Final = "heating_limit_temperature"
# The heating limit is released only this far below the limit.
HEATING_LIMIT_HYSTERESIS: Final = 1.0
# Window contact debounce (seconds) and optional own setpoint while open.
CONF_WINDOW_OPEN_DELAY: Final = "window_open_delay"
CONF_WINDOW_CLOSE_DELAY: Final = "window_close_delay"
CONF_WINDOW_TEMPERATURE: Final = "window_temperature"
DEFAULT_WINDOW_OPEN_DELAY: Final = 0
DEFAULT_WINDOW_CLOSE_DELAY: Final = 0
# Optional floor that no setpoint goes below (window, away, eco).
CONF_FROST_PROTECTION_TEMPERATURE: Final = "frost_protection_temperature"
# Optional on/off entity for the heating season (e.g. a winter-mode sensor).
# While it is off the room is not heated: the setpoint goes to the frost
# protection temperature, or the thermostat minimum without one.
CONF_HEATING_SEASON_ENTITY: Final = "heating_season_entity"

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
# Config entry id of a Home Assistant proximity zone (replaces the two
# sensor fields above).
CONF_PROXIMITY_ZONE: Final = "proximity_zone"
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

# Setpoint calibration with the room sensor (as Better Thermostat's
# target-temperature based calibration): the thermostat measures near the
# radiator, so its setpoint is shifted by (thermostat - room) temperature.
CONF_CALIBRATION: Final = "calibration"
# The offset is refreshed at most this often so the setpoint does not follow
# every small reading of the valve's own sensor.
CALIBRATION_INTERVAL_SECONDS: Final = 600
MAX_CALIBRATION_OFFSET: Final = 10.0
# A recomputed offset is only adopted when it moved at least this far, so the
# valves are not re-adjusted for every small sensor fluctuation.
CONF_HYSTERESIS: Final = "hysteresis"
DEFAULT_HYSTERESIS: Final = 0.5

# Weekly valve exercise against calcification (as in Better Thermostat):
# open fully, then close fully, each for a few minutes, at a fixed hour.
CONF_VALVE_MAINTENANCE: Final = "valve_maintenance"
VALVE_MAINTENANCE_INTERVAL_DAYS: Final = 7
VALVE_MAINTENANCE_HOUR: Final = 11
VALVE_MAINTENANCE_PHASE_SECONDS: Final = 300

# Thermostats without hvac_action count as heating when the setpoint is at least
# this far above the room temperature (used for learning only).
INFERRED_HEATING_MARGIN: Final = 0.5

# A thermostat battery at or below this level is reported as a warning.
LOW_BATTERY_PERCENT: Final = 20

# Feed the room sensor into thermostats that accept an external temperature
# (e.g. Aqara E1 via Zigbee2MQTT: a "sensor" select internal/external and an
# "external_temperature_input" number), as Better Thermostat does.
CONF_EXTERNAL_TEMPERATURE: Final = "external_temperature"
# Resend when the room temperature moved this far, or after this long anyway.
EXTERNAL_TEMPERATURE_MIN_CHANGE: Final = 0.1
EXTERNAL_TEMPERATURE_RESEND_SECONDS: Final = 1800

# Boost: heat to a higher temperature for a limited time (Better Thermostat's
# boost preset), started with the "Boost" switch.
CONF_BOOST_TEMPERATURE: Final = "boost_temperature"
CONF_BOOST_DURATION: Final = "boost_duration"
DEFAULT_BOOST_TEMPERATURE: Final = 24.0
DEFAULT_BOOST_DURATION: Final = 3600

# A schedule block may carry its own comfort temperature in its additional
# data (e.g. ``temperature: 22``); it replaces the comfort temperature while
# that block is active.
SCHEDULE_TEMPERATURE_ATTRIBUTE: Final = "temperature"

# Problem entities of a thermostat's device that are not reported. Aqara E1's
# "valve_alarm" comes from its valve detection and stays on for days while the
# valve works normally (typically with an external sensor or several valves
# per room), which would keep the problem sensor on permanently.
IGNORED_PROBLEM_ENTITY_SUFFIXES: Final = ("_valve_alarm",)

# A room sensor that has not reported for this long counts as failed, so the
# room falls back to the thermostats' readings instead of a frozen value.
ROOM_SENSOR_STALE_SECONDS: Final = 21600

# Heating watchdog: the room stays at least this far below its target for this
# long without warming by the given amount (valve stuck, boiler off, ...).
HEATING_WATCHDOG_GAP: Final = 1.0
HEATING_WATCHDOG_SECONDS: Final = 7200
HEATING_WATCHDOG_MIN_RISE: Final = 0.3

# Quick selection ("Betriebsart"): a mode picked by hand holds until the next
# switch of the comfort schedule, then the room returns to automatic control.
QUICK_AUTO: Final = "auto"
QUICK_COMFORT: Final = "comfort"
QUICK_ECO: Final = "eco"
QUICK_BOOST: Final = "boost"
QUICK_OFF: Final = "off"
# Further presets as in Better Thermostat: away uses the away temperature
# (or eco), sleep, home and activity have their own temperatures.
QUICK_AWAY: Final = "away"
QUICK_SLEEP: Final = "sleep"
QUICK_HOME: Final = "home"
QUICK_ACTIVITY: Final = "activity"
# A temperature set on the room thermostat entity; it holds like the other
# modes for the chosen duration. Not offered as a button.
QUICK_MANUAL: Final = "manual"
# Every valve fully open regardless of windows or season, e.g. for boiler
# service or the chimney sweep (AHC "force max temperature").
QUICK_MAINTENANCE: Final = "maintenance"
QUICK_MODES: Final = (
    QUICK_AUTO,
    QUICK_COMFORT,
    QUICK_HOME,
    QUICK_ACTIVITY,
    QUICK_ECO,
    QUICK_SLEEP,
    QUICK_AWAY,
    QUICK_BOOST,
    QUICK_MAINTENANCE,
    QUICK_OFF,
)
# German names of the quick modes, used by the select and the buttons.
QUICK_LABELS: Final = {
    QUICK_AUTO: "Automatik",
    QUICK_COMFORT: "Komfort",
    QUICK_HOME: "Zuhause",
    QUICK_ACTIVITY: "Aktivität",
    QUICK_ECO: "Eco",
    QUICK_SLEEP: "Schlafen",
    QUICK_AWAY: "Abwesend",
    QUICK_BOOST: "Boost",
    QUICK_MAINTENANCE: "Wartung",
    QUICK_OFF: "Aus",
    QUICK_MANUAL: "Manuell",
}
QUICK_ICONS: Final = {
    QUICK_AUTO: "mdi:calendar-clock",
    QUICK_COMFORT: "mdi:sofa",
    QUICK_HOME: "mdi:home",
    QUICK_ACTIVITY: "mdi:run",
    QUICK_ECO: "mdi:leaf",
    QUICK_SLEEP: "mdi:bed",
    QUICK_AWAY: "mdi:home-export-outline",
    QUICK_BOOST: "mdi:fire",
    QUICK_MAINTENANCE: "mdi:wrench",
    QUICK_OFF: "mdi:snowflake",
    QUICK_MANUAL: "mdi:hand-back-right",
}
# Range and step of a temperature set on the room thermostat entity.
ROOM_MIN_TEMPERATURE: Final = 5.0
ROOM_MAX_TEMPERATURE: Final = 30.0
ROOM_TEMPERATURE_STEP: Final = 0.5
CONF_SLEEP_TEMPERATURE: Final = "sleep_temperature"
CONF_HOME_TEMPERATURE: Final = "home_temperature"
CONF_ACTIVITY_TEMPERATURE: Final = "activity_temperature"
DEFAULT_SLEEP_TEMPERATURE: Final = 18.0
DEFAULT_HOME_TEMPERATURE: Final = 20.0
DEFAULT_ACTIVITY_TEMPERATURE: Final = 22.0
# How long a hand-picked Komfort/Eco/Aus holds.
QUICK_UNTIL_SCHEDULE: Final = "schedule"
QUICK_UNTIL_1H: Final = "1h"
QUICK_UNTIL_3H: Final = "3h"
QUICK_UNTIL_MORNING: Final = "morning"
QUICK_UNTIL_FOREVER: Final = "forever"
QUICK_DURATIONS: Final = (
    QUICK_UNTIL_SCHEDULE,
    QUICK_UNTIL_1H,
    QUICK_UNTIL_3H,
    QUICK_UNTIL_MORNING,
    QUICK_UNTIL_FOREVER,
)
QUICK_MORNING_HOUR: Final = 6

# Push notifications through a notify service (e.g. notify.mobile_app_phone).
CONF_NOTIFY_SERVICE: Final = "notify_service"
# A thermostat problem or a failed room sensor is only reported after this
# long, so short radio dropouts stay quiet.
NOTIFY_PROBLEM_DELAY_SECONDS: Final = 1800
# An open window is reported after this long during the heating season.
NOTIFY_WINDOW_SECONDS: Final = 3600
# Frost warning when the room falls this close to frost protection (or to the
# fallback limit below without frost protection).
NOTIFY_FROST_MARGIN: Final = 1.0
NOTIFY_FROST_FALLBACK_TEMPERATURE: Final = 10.0

# House-wide settings live in their own config entry.
CONF_ENTRY_TYPE: Final = "entry_type"
ENTRY_TYPE_HOUSE: Final = "house"
HOUSE_DATA_KEY: Final = "house"
HOUSE_PLATFORMS: Final = ["button", "datetime", "select", "sensor"]
HOUSE_HOME: Final = "home"
HOUSE_AWAY: Final = "away"
HOUSE_VACATION: Final = "vacation"
HOUSE_MODES: Final = (HOUSE_HOME, HOUSE_AWAY, HOUSE_VACATION)

# Window detection without a contact: the room cools this much this fast.
CONF_WINDOW_DROP_DETECTION: Final = "window_drop_detection"
WINDOW_DROP_DEGREES: Final = 1.0
WINDOW_DROP_SECONDS: Final = 600
# How long the room then stays lowered as with an open window.
WINDOW_DROP_HOLD_SECONDS: Final = 900

# Heat demand estimated from the gap to the target when the valves do not
# report an opening: this gap counts as full demand.
HEAT_DEMAND_FULL_GAP: Final = 2.0
HEAT_DEMAND_KEYS: Final = ("pi_heating_demand", "valve_position", "position")

# Weekly report of the house entry: Sunday evening.
REPORT_WEEKDAY: Final = 6
REPORT_HOUR: Final = 18

# Turning a valve by hand: the new setpoint goes to every thermostat of the
# room and is held as quick mode Manuell (AHC "physical change / sync").
# Without it, control only pauses until the next mode change.
CONF_SYNC_MANUAL_CHANGE: Final = "sync_manual_change"
DEFAULT_SYNC_MANUAL_CHANGE: Final = True

# Graded absence (AHC away mode): while the schedule asks for comfort but the
# room is empty although somebody is home, heat to comfort minus this offset
# instead of the setback. Optionally also while nobody is home at all.
CONF_AWAY_OFFSET: Final = "away_offset"
CONF_AWAY_SCHEDULE_MODE: Final = "away_schedule_mode"

# After this long without anybody home the room drops to frost protection
# (AHC "frost protection fallback duration"). 0 turns it off.
CONF_FROST_AFTER_ABSENCE: Final = "frost_after_absence"
DEFAULT_FROST_AFTER_ABSENCE: Final = 0

# More comfort schedules per room; the "Zeitplan" select picks the active one.
CONF_ADDITIONAL_SCHEDULE_ENTITIES: Final = "additional_schedule_entities"

# A schedule whose blocks carry a ``temperature`` in their data sets the eco
# temperature while that block is active (AHC heating plan adjustments).
CONF_ECO_SCHEDULE_ENTITY: Final = "eco_schedule_entity"

# Aggressive mode: outside +/- range around the target, send target +/- offset
# so sluggish valves open or close decisively. No range turns it off.
CONF_AGGRESSIVE_RANGE: Final = "aggressive_range"
CONF_AGGRESSIVE_OFFSET: Final = "aggressive_offset"
DEFAULT_AGGRESSIVE_OFFSET: Final = 2.0

# Turn off the thermostats' own window detection when the room has a window
# contact, so a valve does not close on its own while the room should heat.
CONF_DISABLE_TRV_WINDOW_DETECTION: Final = "disable_trv_window_detection"
TRV_WINDOW_DETECTION_SUFFIX: Final = "_window_detection"

# Fired on the event bus whenever the decided mode or target changes.
EVENT_MODE_CHANGED: Final = "dynamic_heating_mode_changed"

# More window and door contacts per room: any open one counts as open
# (Better Thermostat's window/door sensors, the room/zone sensors of
# Climate Group Helper).
CONF_ADDITIONAL_WINDOW_ENTITIES: Final = "additional_window_entities"

# Room humidity shown on the room thermostat entity (Better Thermostat).
CONF_HUMIDITY_ENTITY: Final = "humidity_entity"

# Turned valves are set back to the room's target (Better Thermostat's
# software child lock, Climate Group Helper's lock sync mode). Wins over
# syncing a turned valve to the room.
CONF_LOCK_VALVES: Final = "lock_valves"

# Room offset (Climate Group Helper's group offset): shifts every target of
# the room; a temperature set on the room thermostat resets it.
ROOM_OFFSET_MIN: Final = -3.0
ROOM_OFFSET_MAX: Final = 3.0
# Per-valve offset (Climate Group Helper's member offsets), e.g. a valve
# that sits in a colder corner of the room.
VALVE_OFFSET_MIN: Final = -3.0
VALVE_OFFSET_MAX: Final = 3.0

# Temperature trend of the room over this window, in °C per hour.
TREND_WINDOW_SECONDS: Final = 1800
TREND_MIN_SPAN_SECONDS: Final = 600

# A calendar event's description may carry ``temperature: 22`` like the
# additional data of a schedule block.
CALENDAR_TEMPERATURE_KEY: Final = "temperature"
