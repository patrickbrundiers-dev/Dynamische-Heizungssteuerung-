"""Constants for the dynamic heating integration."""

from typing import Final

DOMAIN: Final = "dynamic_heating"
PLATFORMS: Final = [
    "binary_sensor", "button", "climate", "datetime", "number", "select", "sensor",
    "switch",
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
# Judge the heating limit by the average of the next two days' forecast (else
# of the outdoor readings of the last two days) instead of the current value,
# as Better Thermostat does, so one warm afternoon does not stop heating.
CONF_HEATING_LIMIT_AVERAGE: Final = "heating_limit_average"
DEFAULT_HEATING_LIMIT_AVERAGE: Final = True
HEATING_LIMIT_AVERAGE_HOURS: Final = 48
# Forecast points needed for an average, else the outdoor history is used.
HEATING_LIMIT_MIN_FORECAST_POINTS: Final = 12
# Outdoor history: one reading per interval, used once it spans this long.
OUTDOOR_HISTORY_INTERVAL_SECONDS: Final = 600
OUTDOOR_HISTORY_MIN_SPAN_SECONDS: Final = 21600
# Without any outdoor temperature: keep heating (default) or treat the
# heating limit as reached (AHC "heating limit fallback").
CONF_HEATING_LIMIT_FALLBACK_OFF: Final = "heating_limit_fallback_off"
# The heating limit is released only this far below the limit.
HEATING_LIMIT_HYSTERESIS: Final = 1.0
# In the heating season: no heating while it is at least as warm outside as
# in the room (minus the margin); heating resumes this far below again.
CONF_OUTDOOR_WARMER_STOP: Final = "outdoor_warmer_stop"
DEFAULT_OUTDOOR_WARMER_STOP: Final = True
CONF_OUTDOOR_WARMER_MARGIN: Final = "outdoor_warmer_margin"
DEFAULT_OUTDOOR_WARMER_MARGIN: Final = 0.0
OUTDOOR_WARMER_HYSTERESIS: Final = 0.5
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
# Seconds: a short handover (one leaves, the other comes home a few minutes
# later) is not "nobody home". Until 0.9.13 this was 2 (seconds, meant as
# minutes); entries with that old value are moved to this one.
DEFAULT_LEAVING_HOME_DURATION: Final = 600
OLD_DEFAULT_LEAVING_HOME_DURATION: Final = 2
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
# A valve's own setpoint jump after its mode was switched is not manual.
MODE_SWITCH_GRACE_SECONDS: Final = 120

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
# Weekday (0 = Monday, "any" = 7 days after the last run), hour and length of
# each phase, as in Advanced Heating Control's liming protection.
CONF_MAINTENANCE_WEEKDAY: Final = "maintenance_weekday"
CONF_MAINTENANCE_HOUR: Final = "maintenance_hour"
CONF_MAINTENANCE_DURATION: Final = "maintenance_duration"
MAINTENANCE_ANY_DAY: Final = "any"

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
# A change of at least this much is sent at once (as Better Thermostat); a
# smaller one only once it held for the plateau time, so a sensor flickering
# between two readings does not wake the valves over Zigbee every cycle.
# The room sensor reports in 0.01 °C steps and wobbles by a few hundredths;
# every value sent makes the valve recalculate and often move its motor, so
# only real changes are sent, rounded to 0.1 °C.
EXTERNAL_TEMPERATURE_MIN_CHANGE: Final = 0.2
EXTERNAL_TEMPERATURE_PLATEAU_CHANGE: Final = 0.1
EXTERNAL_TEMPERATURE_PLATEAU_TOLERANCE: Final = 0.05
EXTERNAL_TEMPERATURE_PLATEAU_SECONDS: Final = 600
# The valve keeps the value; the regular resend only covers a lost message,
# the check below catches a valve that did not take it.
EXTERNAL_TEMPERATURE_RESEND_SECONDS: Final = 7200
# A valve that still shows another temperature this long after a send did not
# take the value (e.g. it was sent while the valve was still switching to its
# external input): send it again, at most once per retry interval.
EXTERNAL_TEMPERATURE_VERIFY_SECONDS: Final = 120
EXTERNAL_TEMPERATURE_VERIFY_TOLERANCE: Final = 0.3
EXTERNAL_TEMPERATURE_RETRY_SECONDS: Final = 300
EXTERNAL_TEMPERATURE_RETRIES: Final = 3

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

# Heating watchdog: the room stays at least this far below its target and warms
# by less than the given amount in this time (valve stuck, boiler off, flow
# temperature too low, ...). 0.5 °C in two hours is 0.25 °C/h, barely above
# the slowest heating rate the preheat model knows.
HEATING_WATCHDOG_GAP: Final = 1.0
HEATING_WATCHDOG_SECONDS: Final = 7200
HEATING_WATCHDOG_MIN_RISE: Final = 0.5

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

# Room readings outside this range are dropped as sensor errors (Better
# Thermostat's plausibility check), reported under Repairs, and the room
# falls back to the thermostats' readings.
ROOM_TEMPERATURE_PLAUSIBLE_MIN: Final = -5.0
ROOM_TEMPERATURE_PLAUSIBLE_MAX: Final = 45.0

# What happens to a setpoint turned while a window is open (Climate Group
# Helper): kept and applied once the window is closed, or discarded.
CONF_WINDOW_CHANGE: Final = "window_change"
WINDOW_CHANGE_KEEP: Final = "keep"
WINDOW_CHANGE_DISCARD: Final = "discard"
WINDOW_CHANGE_OPTIONS: Final = (WINDOW_CHANGE_KEEP, WINDOW_CHANGE_DISCARD)

# Door contacts and contacts shared by several rooms (e.g. a patio door) with
# their own delays (Better Thermostat's door delays, Climate Group Helper's
# zone sensor).
CONF_DOOR_ENTITIES: Final = "door_entities"
CONF_DOOR_OPEN_DELAY: Final = "door_open_delay"
CONF_DOOR_CLOSE_DELAY: Final = "door_close_delay"
DEFAULT_DOOR_OPEN_DELAY: Final = 600
DEFAULT_DOOR_CLOSE_DELAY: Final = 0
CONF_ZONE_WINDOW_ENTITIES: Final = "zone_window_entities"
CONF_ZONE_WINDOW_OPEN_DELAY: Final = "zone_window_open_delay"
CONF_ZONE_WINDOW_CLOSE_DELAY: Final = "zone_window_close_delay"
DEFAULT_ZONE_WINDOW_OPEN_DELAY: Final = 300
DEFAULT_ZONE_WINDOW_CLOSE_DELAY: Final = 0

# Pause between commands to the valves (Climate Group Helper's member delay),
# so a burst of commands does not get lost on the Zigbee network.
CONF_COMMAND_DELAY: Final = "command_delay"
DEFAULT_COMMAND_DELAY: Final = 0.0

# House calendar: while one of its events runs, every room uses the comfort
# schedule its title or ``zeitplan: <name>`` names (e.g. "Ferien"; AHC's
# automatic schedule choice). An event with ``komfort: an`` or
# ``temperature: 21`` is comfort time in every room on top of its own
# schedule (Climate Group Helper's bypass schedule).
CONF_HOUSE_CALENDAR: Final = "house_calendar"
CONF_FOLLOW_HOUSE_CALENDAR: Final = "follow_house_calendar"
DEFAULT_FOLLOW_HOUSE_CALENDAR: Final = True
HOUSE_CALENDAR_SCHEDULE_KEYS: Final = ("zeitplan", "schedule")
HOUSE_CALENDAR_COMFORT_KEYS: Final = ("komfort", "comfort")

# A valve whose setpoint differs from what was written this long is reported.
VALVE_DIVERGENCE_SECONDS: Final = 900
VALVE_DIVERGENCE_MIN: Final = 0.5

# Entities that force comfort or eco while on (AHC party / force eco), e.g.
# an input_boolean, a timer or a sensor. A number at the end of the name
# ("Party 23") is the temperature.
CONF_FORCE_COMFORT_ENTITIES: Final = "force_comfort_entities"
CONF_FORCE_ECO_ENTITIES: Final = "force_eco_entities"

# Keys in a schedule block's data or a calendar event's description that pause
# a feature while the block runs (Climate Group Helper's slot meta data).
BLOCK_WINDOW_KEYS: Final = ("fenster", "window")
BLOCK_PRESENCE_KEYS: Final = ("anwesenheit", "presence")

# Fired for device triggers; carries the room's device_id and a type.
EVENT_DEVICE_TRIGGER: Final = "dynamic_heating_event"
TRIGGER_HEATING_STARTED: Final = "heating_started"
TRIGGER_HEATING_STOPPED: Final = "heating_stopped"
TRIGGER_TARGET_REACHED: Final = "target_reached"
TRIGGER_WINDOW_OPENED: Final = "window_opened"
TRIGGER_WINDOW_CLOSED: Final = "window_closed"
TRIGGER_HUMIDITY_HIGH: Final = "humidity_high"
TRIGGER_TYPES: Final = (
    TRIGGER_HEATING_STARTED,
    TRIGGER_HEATING_STOPPED,
    TRIGGER_TARGET_REACHED,
    TRIGGER_WINDOW_OPENED,
    TRIGGER_WINDOW_CLOSED,
    TRIGGER_HUMIDITY_HIGH,
)
HUMIDITY_HIGH_PERCENT: Final = 60.0
HUMIDITY_HYSTERESIS: Final = 5.0
TARGET_REACHED_MARGIN: Final = 0.2

# Overshoot after heating stops (Better Thermostat's peak tracking): the room
# keeps warming for a while; preheating ends that much earlier.
MAX_OVERSHOOT: Final = 1.5
OVERSHOOT_MAX_SECONDS: Final = 5400
OVERSHOOT_DROP: Final = 0.1

# Groups of settings that can be copied from one room to others (house
# editor "Einstellungen übertragen", Climate Group Helper's apply_config).
# Devices of a room (thermostats, sensors, schedules, contacts) never are.
SETTINGS_GROUPS: Final = {
    "temperatures": (
        CONF_COMFORT_TEMPERATURE,
        CONF_ECO_TEMPERATURE,
        CONF_AWAY_TEMPERATURE,
        CONF_FROST_PROTECTION_TEMPERATURE,
        CONF_WINDOW_TEMPERATURE,
        CONF_BOOST_TEMPERATURE,
        CONF_BOOST_DURATION,
        CONF_HOME_TEMPERATURE,
        CONF_ACTIVITY_TEMPERATURE,
        CONF_SLEEP_TEMPERATURE,
        CONF_MAX_PREHEAT_MINUTES,
    ),
    "windows": (
        CONF_WINDOW_OPEN_DELAY,
        CONF_WINDOW_CLOSE_DELAY,
        CONF_DOOR_OPEN_DELAY,
        CONF_DOOR_CLOSE_DELAY,
        CONF_ZONE_WINDOW_ENTITIES,
        CONF_ZONE_WINDOW_OPEN_DELAY,
        CONF_ZONE_WINDOW_CLOSE_DELAY,
        CONF_WINDOW_DROP_DETECTION,
        CONF_DISABLE_TRV_WINDOW_DETECTION,
        CONF_WINDOW_CHANGE,
    ),
    "presence": (
        CONF_PERSON_ENTITIES,
        CONF_GUEST_ENTITY,
        CONF_ENTER_HOME_DURATION,
        CONF_LEAVING_HOME_DURATION,
        CONF_PROXIMITY_ZONE,
        CONF_PROXIMITY_DISTANCE,
        CONF_PROXIMITY_DURATION,
        CONF_PROXIMITY_MAX_AGE,
        CONF_AWAY_OFFSET,
        CONF_AWAY_SCHEDULE_MODE,
        CONF_FROST_AFTER_ABSENCE,
        CONF_FORCE_COMFORT_ENTITIES,
        CONF_FORCE_ECO_ENTITIES,
        CONF_FOLLOW_HOUSE_CALENDAR,
    ),
    "valves": (
        CONF_CALIBRATION,
        CONF_EXTERNAL_TEMPERATURE,
        CONF_HYSTERESIS,
        CONF_SYNC_MANUAL_CHANGE,
        CONF_LOCK_VALVES,
        CONF_AGGRESSIVE_RANGE,
        CONF_AGGRESSIVE_OFFSET,
        CONF_COMMAND_DELAY,
        CONF_VALVE_MAINTENANCE,
        CONF_MAINTENANCE_WEEKDAY,
        CONF_MAINTENANCE_HOUR,
        CONF_MAINTENANCE_DURATION,
    ),
    "outdoor": (
        CONF_OUTDOOR_TEMPERATURE_ENTITY,
        CONF_WEATHER_ENTITY,
        CONF_HEATING_SEASON_ENTITY,
        CONF_HEATING_LIMIT_TEMPERATURE,
        CONF_HEATING_LIMIT_AVERAGE,
        CONF_HEATING_LIMIT_FALLBACK_OFF,
        CONF_OUTDOOR_WARMER_STOP,
        CONF_OUTDOOR_WARMER_MARGIN,
        CONF_NOTIFY_SERVICE,
    ),
}

# Intelligent control (0.9.0): a learned room equation (heat output, heat
# loss, sun, wind) replaces the fixed heating rate once it has enough data.
CONF_ROOM_MODEL: Final = "room_model"
DEFAULT_ROOM_MODEL: Final = True
CONF_SOLAR_RADIATION_ENTITY: Final = "solar_radiation_entity"
CONF_WIND_SPEED_ENTITY: Final = "wind_speed_entity"
# Set back only as far as the room can recover: outside comfort time within
# the maximum preheat time, in an empty room within this time.
CONF_RECOVERY_LIMIT: Final = "recovery_limit"
DEFAULT_RECOVERY_LIMIT: Final = True
CONF_ROOM_EMPTY_RECOVERY: Final = "room_empty_recovery"
DEFAULT_ROOM_EMPTY_RECOVERY: Final = 3600
# The target the room has to get back to stays this far below what full
# heating can reach at all.
RECOVERY_REACH_MARGIN: Final = 0.3
# Preheat while somebody is home, even if this room is empty; at the start of
# a comfort block an empty room keeps comfort this long before it drops.
CONF_PREHEAT_WHEN_HOME: Final = "preheat_when_home"
DEFAULT_PREHEAT_WHEN_HOME: Final = True
CONF_ROOM_EMPTY_GRACE: Final = "room_empty_grace"
DEFAULT_ROOM_EMPTY_GRACE: Final = 1800
# Learn when the room is usually used (per weekday and hour) and keep comfort
# then even if the presence sensor sees nobody.
CONF_LEARN_USAGE: Final = "learn_usage"
DEFAULT_LEARN_USAGE: Final = True
# Optimum stop: end heating this long before the comfort block ends when the
# room loses at most EARLY_STOP_DROP until then.
CONF_EARLY_STOP: Final = "early_stop"
DEFAULT_EARLY_STOP: Final = 1800
EARLY_STOP_DROP: Final = 0.5
# Sun pause: the sun (solar gain of the model) keeps the room warm, so the
# valves close while it lasts.
SOLAR_PAUSE_MIN_GAIN: Final = 0.1
# Days of recorder history the room model learns from at its first start.
MODEL_HISTORY_DAYS: Final = 7

# "Kurz wärmer" (button, e.g. for Alexa): raise by this much for this long.
CONF_WARM_UP_STEP: Final = "warm_up_step"
CONF_WARM_UP_DURATION: Final = "warm_up_duration"
DEFAULT_WARM_UP_STEP: Final = 1.0
DEFAULT_WARM_UP_DURATION: Final = 3600

# Calibration run (0.9.7): full heat for this long so a new room model learns
# heat output in one go; the valves get the room temperature plus this.
LEARN_RUN_DURATION_SECONDS: Final = 7200
LEARN_RUN_RISE: Final = 4.0
# Warm on time (0.9.7): learn a preheat correction from late or early
# mornings, and allow preheating this much longer than the maximum when the
# central heating is not known to be off then.
CONF_PUNCTUALITY: Final = "punctuality"
DEFAULT_PUNCTUALITY: Final = True
CONF_PREHEAT_EXTENSION: Final = "preheat_extension"
DEFAULT_PREHEAT_EXTENSION: Final = 3600
# Push "nobody home" (with "Stimmt nicht, ich bin da") after this long.
CONF_NOTIFY_AWAY: Final = "notify_away"
DEFAULT_NOTIFY_AWAY: Final = True
NOTIFY_AWAY_SECONDS: Final = 900
# "In 15 Minuten erinnern" on the window push.
NOTIFY_SNOOZE_SECONDS: Final = 900
# Prefix of the actions on mobile app notifications.
NOTIFY_ACTION_PREFIX: Final = "DYNHEAT"
# Fallback schedule in the valves (0.9.7): written and switched on when Home
# Assistant shuts down, switched off again after the start.
CONF_VALVE_FALLBACK: Final = "valve_fallback"
DEFAULT_VALVE_FALLBACK: Final = False
# Device name of a room without area.
DEFAULT_DEVICE_NAME: Final = "Dynamische Heizungssteuerung"
# Runde 9 (0.9.9): keep comfort in the evening until the central heating's
# usual night pause starts (off by default: costs some heat).
CONF_HOLD_BEFORE_PAUSE: Final = "hold_before_supply_pause"
DEFAULT_HOLD_BEFORE_PAUSE: Final = False
# Push in the morning when the room was not warm at the start of comfort.
CONF_MORNING_REPORT: Final = "morning_report"
DEFAULT_MORNING_REPORT: Final = True
MORNING_REPORT_HOUR: Final = 7
MORNING_REPORT_SHORTFALL: Final = 0.5
# Set the valve's own sensor calibration so it reads the room temperature
# (valves without an external temperature input, e.g. Tuya).
CONF_VALVE_SENSOR_CALIBRATION: Final = "valve_sensor_calibration"
DEFAULT_VALVE_SENSOR_CALIBRATION: Final = False
VALVE_SENSOR_CALIBRATION_INTERVAL: Final = 3 * 3600
VALVE_SENSOR_CALIBRATION_WINDOW: Final = 3 * 3600
# After a start, a missing outdoor sensor is waited for this long before the
# weather entity stands in (its value can differ by degrees).
OUTDOOR_FALLBACK_GRACE_SECONDS: Final = 600
# Same for the room sensor before the valves' readings stand in for it.
ROOM_FALLBACK_GRACE_SECONDS: Final = 600

# Runde 10 (0.10.0)
# While preheating, a household that just left keeps counting as home this
# long: a short absence does not throw away the heat already put in.
PREHEAT_LEAVE_GRACE_SECONDS: Final = 900
# Cap for temperatures turned by hand (valve, app, room thermostat) and for
# how long they hold; None/0 = no cap (default).
CONF_MANUAL_MAX_TEMPERATURE: Final = "manual_max_temperature"
CONF_MANUAL_MAX_DURATION: Final = "manual_max_duration"
# School-free days: on these the room uses its school-free schedule. The
# entity says whether today is free; a workday sensor (workday integration)
# and a holiday calendar tell the day plan whether tomorrow is free too.
CONF_SCHOOL_FREE_ENTITY: Final = "school_free_entity"
CONF_SCHOOL_FREE_SCHEDULE: Final = "school_free_schedule"
CONF_WORKDAY_ENTITY: Final = "workday_entity"
CONF_SCHOOL_HOLIDAY_CALENDAR: Final = "school_holiday_calendar"
SCHOOL_HOLIDAY_WORDS: Final = ("ferien",)
# Learn shower times from the room's humidity (bathrooms): a rise of this
# many points within the window is a shower; the room model does not learn
# from the hour after it (the shower warms the room, not the radiator).
CONF_SHOWER_LEARNING: Final = "shower_learning"
DEFAULT_SHOWER_LEARNING: Final = False
SHOWER_RISE_PERCENT: Final = 6.0
SHOWER_RISE_WINDOW_SECONDS: Final = 20 * 60
SHOWER_COOLDOWN_SECONDS: Final = 2 * 3600
SHOWER_MODEL_PAUSE_SECONDS: Final = 3600
SHOWER_HISTORY_DAYS: Final = 10
# Comfort this long before the usual shower time in a suggestion.
SHOWER_LEAD_MINUTES: Final = 30
# An automation or script that sets a room's valves is reported once a day.
FOREIGN_CONTROL_NOTIFY_SECONDS: Final = 24 * 3600
# The geo-fencing sensors of a room (same in every room): shown once on the
# house device, off in the rooms by default.
PROXIMITY_SENSOR_KEYS: Final = (
    "proximity_status",
    "proximity_distance_m",
    "proximity_age_seconds",
    "proximity_updates_seen",
    "proximity_average_update_interval_s",
    "proximity_stale_events",
    "proximity_invalid_events",
    "proximity_out_of_range_events",
    "proximity_approach_attempts",
    "proximity_confirmed_approaches",
)

# The room model drops an hour in which heat was asked for (from this heat
# demand in %) while the boiler delivered nothing.
MODEL_ASKING_DEMAND: Final = 50
# The lowest setback that still gets the room warm in time changes only by
# at least this much, so the status does not flicker between 19,2 and 19,3.
SETBACK_FLOOR_STEP: Final = 0.2
# A thermostat counts as unreachable only after this long: around a restart
# every valve is unavailable for a moment.
THERMOSTAT_UNREACHABLE_GRACE_SECONDS: Final = 180
