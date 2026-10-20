"""Config flow and editor tests using an isolated Home Assistant instance."""

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_heating.const import DOMAIN


async def _start_room_flow(hass):
    """Open the setup menu and pick a new room."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "room"}
    )


def _valid_input():
    """Return a minimal valid configuration without real devices."""
    return {
        "climate_entity": "climate.living_room",
        "room_temperature_entity": "sensor.living_room_temperature",
        "schedule_entity": "schedule.living_room_comfort",
        "comfort_temperature": 21.0,
        "eco_temperature": 18.0,
        "max_preheat_minutes": 120,
    }


def _mock_room(hass, *, options=None):
    """Register a pre-existing room to exercise its editor."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Dynamische Heizung – climate.living_room",
        unique_id="climate.living_room",
        data=_valid_input(),
        options=options or {},
    )
    entry.add_to_hass(hass)
    return entry

def _duration(seconds: int) -> dict[str, int]:
    """Build a Home Assistant duration selector value."""
    return {
        "hours": seconds // 3600,
        "minutes": (seconds % 3600) // 60,
        "seconds": seconds % 60,
    }


async def _finish_editor_flow(
    hass,
    entry,
    *,
    basic=None,
    presence=None,
    geofencing=None,
    environment=None,
    intelligence=None,
):
    """Submit all editor pages, using current settings unless overridden."""
    values = dict(entry.data)
    values.update(dict(entry.options))
    values.update(basic or {})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    flow_id = result["flow_id"]

    first = {
        key: values[key]
        for key in (
            "climate_entity",
            "room_temperature_entity",
            "schedule_entity",
            "comfort_temperature",
            "eco_temperature",
            "max_preheat_minutes",
        )
    }
    if values.get("additional_climate_entities"):
        first["additional_climate_entities"] = values["additional_climate_entities"]
    if values.get("frost_protection_temperature") is not None:
        first["frost_protection_temperature"] = values["frost_protection_temperature"]
    result = await _submit_page(hass, flow_id, "basics", first)
    if result["type"] is not FlowResultType.MENU:
        return result

    valves = {
        key: values[key] for key in ("calibration", "hysteresis") if key in values
    }
    result = await _submit_page(hass, flow_id, "valves", valves)
    assert result["type"] is FlowResultType.MENU

    modes = {key: values[key] for key in ("boost_temperature",) if key in values}
    if isinstance(values.get("boost_duration"), int):
        modes["boost_duration"] = _duration(values["boost_duration"])
    elif isinstance(values.get("boost_duration"), dict):
        modes["boost_duration"] = values["boost_duration"]
    result = await _submit_page(hass, flow_id, "modes", modes)
    assert result["type"] is FlowResultType.MENU

    presence_keys = (
        "person_entities", "guest_entity", "presence_entity",
        "presence_schedule_entity",
    )
    presence_input = {
        key: values[key] for key in presence_keys if values.get(key)
    }
    presence_input.update({
        "enter_home_duration": _duration(values.get("enter_home_duration", 2)),
        "leaving_home_duration": _duration(values.get("leaving_home_duration", 2)),
        "presence_on_duration": _duration(values.get("presence_on_duration", 300)),
        "presence_off_duration": _duration(values.get("presence_off_duration", 1200)),
    })
    for key, value in (presence or {}).items():
        if value is None:
            presence_input.pop(key, None)
        else:
            presence_input[key] = value
    result = await _submit_page(hass, flow_id, "presence", presence_input)
    if result["type"] is not FlowResultType.MENU:
        return result

    geo_keys = ("proximity_zone",)
    geo_input = {key: values[key] for key in geo_keys if values.get(key)}
    geo_input.update({
        "proximity_distance": values.get("proximity_distance", 500),
        "proximity_duration": _duration(values.get("proximity_duration", 120)),
        "proximity_max_age": _duration(values.get("proximity_max_age", 900)),
    })
    for key, value in (geofencing or {}).items():
        if value is None:
            geo_input.pop(key, None)
        else:
            geo_input[key] = value
    result = await _submit_page(hass, flow_id, "geofencing", geo_input)
    assert result["type"] is FlowResultType.MENU

    env_keys = (
        "window_entity", "outdoor_temperature_entity", "weather_entity",
        "heating_limit_temperature", "window_temperature", "heating_season_entity",
    )
    env_input = {key: values[key] for key in env_keys if values.get(key)}
    for key, value in (environment or {}).items():
        if value is None:
            env_input.pop(key, None)
        else:
            env_input[key] = value
    result = await _submit_page(hass, flow_id, "environment", env_input)
    if result["type"] is not FlowResultType.MENU:
        return result
    smart_input = {
        key: values[key]
        for key in ("solar_radiation_entity", "wind_speed_entity")
        if values.get(key)
    }
    for key, value in (intelligence or {}).items():
        if value is None:
            smart_input.pop(key, None)
        else:
            smart_input[key] = value
    result = await _submit_page(hass, flow_id, "intelligence", smart_input)
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": "save"}
    )


async def _submit_page(hass, flow_id, page, user_input):
    """Open one page from the editor menu and submit it."""
    result = await hass.config_entries.options.async_configure(
        flow_id, {"next_step_id": page}
    )
    assert result["step_id"] == page
    return await hass.config_entries.options.async_configure(
        flow_id, user_input=user_input
    )


@pytest.mark.asyncio
async def test_user_flow_creates_entry(hass, enable_custom_integrations):
    """A valid initial configuration creates a room."""
    result = await _start_room_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "room"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_input()
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dynamische Heizung – climate.living_room"
    assert result["data"]["climate_entity"] == "climate.living_room"
    # Native duration selector values are normalized to numeric seconds.
    assert result["data"]["enter_home_duration"] == 2
    assert result["data"]["leaving_home_duration"] == 600
    assert result["data"]["proximity_duration"] == 120
    assert result["data"]["proximity_max_age"] == 900
    assert result["data"]["presence_on_duration"] == 300
    assert result["data"]["presence_off_duration"] == 1200


@pytest.mark.asyncio
async def test_user_flow_rejects_eco_temperature_at_or_above_comfort(
    hass, enable_custom_integrations
):
    """Invalid temperatures are rejected without creating an entry."""
    result = await _start_room_flow(hass)
    user_input = _valid_input()
    user_input["eco_temperature"] = 21.0

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "eco_must_be_below_comfort"}
    assert not hass.config_entries.async_entries(DOMAIN)


@pytest.mark.asyncio
async def test_user_flow_accepts_optional_weather_forecast_entity(
    hass, enable_custom_integrations
):
    """Weather can be supplied during setup, but is not required."""
    result = await _start_room_flow(hass)
    user_input = _valid_input()
    user_input["weather_entity"] = "weather.home_forecast"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["weather_entity"] == "weather.home_forecast"


@pytest.mark.asyncio
async def test_editor_opens_for_an_existing_room(hass, enable_custom_integrations):
    """The editor should open after the room has already been created."""
    entry = _mock_room(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "init"
    assert result["menu_options"][0] == "basics"
    assert result["menu_options"][-1] == "save"
    assert result["flow_id"]


@pytest.mark.asyncio
async def test_editor_saves_room_temperature_and_schedule_changes(
    hass, enable_custom_integrations
):
    """An existing room's sensor, schedule and target temperatures can be edited."""
    entry = _mock_room(hass)
    edited = {
        **_valid_input(),
        "room_temperature_entity": "sensor.bedroom_temperature",
        "schedule_entity": "schedule.bedroom_comfort",
        "comfort_temperature": 22.0,
        "eco_temperature": 17.0,
    }
    result = await _finish_editor_flow(hass, entry, basic=edited)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["room_temperature_entity"] == "sensor.bedroom_temperature"
    assert entry.options["schedule_entity"] == "schedule.bedroom_comfort"
    assert entry.options["comfort_temperature"] == 22.0
    assert entry.options["eco_temperature"] == 17.0


@pytest.mark.asyncio
async def test_editor_rejects_invalid_comfort_and_eco_values(
    hass, enable_custom_integrations
):
    """The editor retains the form and reports invalid setback relationships."""
    _mock_room(hass)
    result = await hass.config_entries.options.async_init(
        hass.config_entries.async_entries(DOMAIN)[0].entry_id
    )
    edited = {
        **_valid_input(),
        "comfort_temperature": 18.0,
        "eco_temperature": 20.0,
    }

    result = await _submit_page(hass, result["flow_id"], "basics", edited)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "eco_must_be_below_comfort"}


@pytest.mark.asyncio
async def test_editor_allows_changing_thermostat_when_not_already_used(
    hass, enable_custom_integrations
):
    """Editing the target thermostat updates the config entry's unique ID."""
    entry = _mock_room(hass)
    edited = {**_valid_input(), "climate_entity": "climate.bedroom"}
    result = await _finish_editor_flow(hass, entry, basic=edited)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.unique_id == "climate.bedroom"
    assert entry.title == "Dynamische Heizung – climate.bedroom"


@pytest.mark.asyncio
async def test_editor_rejects_thermostat_already_used_by_another_room(
    hass, enable_custom_integrations
):
    """Two rooms are prevented from controlling the same thermostat."""
    first = _mock_room(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Dynamische Heizung – climate.kitchen",
        unique_id="climate.kitchen",
        data={
            **_valid_input(),
            "climate_entity": "climate.kitchen",
        },
    )
    second.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(second.entry_id)
    edited = {**_valid_input(), "climate_entity": "climate.living_room"}
    result = await _submit_page(hass, result["flow_id"], "basics", edited)

    assert result["type"] is FlowResultType.ABORT
    assert second.unique_id == "climate.kitchen"
    assert first.unique_id == "climate.living_room"



@pytest.mark.asyncio
async def test_editor_saves_presence_and_proximity_settings(
    hass, enable_custom_integrations
):
    """Each grouped editor page saves its entity settings and durations."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass,
        entry,
        presence={
            "person_entities": ["person.patrick", "person.jenny"],
            "guest_entity": "input_boolean.guest_mode",
            "enter_home_duration": _duration(120),
            "leaving_home_duration": _duration(180),
            "presence_schedule_entity": "schedule.presence_active",
            "presence_on_duration": _duration(300),
            "presence_off_duration": _duration(1200),
        },
        geofencing={
            "proximity_zone": "zone_entry_home",
            "proximity_duration": _duration(120),
            "proximity_max_age": _duration(900),
            "proximity_distance": 500,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["person_entities"] == ["person.patrick", "person.jenny"]
    assert entry.options["guest_entity"] == "input_boolean.guest_mode"
    assert entry.options["presence_schedule_entity"] == "schedule.presence_active"
    assert entry.options["proximity_zone"] == "zone_entry_home"
    # The zone replaces the separately picked sensors.
    assert entry.options["proximity_entity"] is None
    assert entry.options["proximity_direction_entity"] is None
    assert entry.options["proximity_max_age"] == 900
    assert entry.options["enter_home_duration"] == 120
    assert entry.options["leaving_home_duration"] == 180
    assert entry.options["proximity_duration"] == 120
    assert entry.options["presence_on_duration"] == 300
    assert entry.options["presence_off_duration"] == 1200


@pytest.mark.asyncio
async def test_user_flow_validates_optional_away_temperature(
    hass, enable_custom_integrations
):
    """An away temperature is optional but must stay below comfort."""
    result = await _start_room_flow(hass)
    user_input = _valid_input() | {"away_temperature": 21.0}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "away_must_be_below_comfort"}

    user_input["away_temperature"] = 16.0
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["away_temperature"] == 16.0


@pytest.mark.asyncio
async def test_editor_saves_rejects_and_clears_away_temperature(
    hass, enable_custom_integrations
):
    """The presence page edits the away temperature; clearing it is kept."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass, entry, presence={"away_temperature": 16.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["away_temperature"] == 16.0

    result = await hass.config_entries.options.async_init(entry.entry_id)
    first = {
        key: entry.data[key]
        for key in (
            "climate_entity",
            "room_temperature_entity",
            "schedule_entity",
            "comfort_temperature",
            "eco_temperature",
            "max_preheat_minutes",
        )
    }
    result = await _submit_page(hass, result["flow_id"], "basics", first)
    result = await _submit_page(
        hass, result["flow_id"], "presence", {"away_temperature": 21.0}
    )
    assert result["step_id"] == "presence"
    assert result["errors"] == {"base": "away_must_be_below_comfort"}

    result = await _finish_editor_flow(
        hass, entry, presence={"away_temperature": None}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["away_temperature"] is None


@pytest.mark.asyncio
async def test_editor_saves_and_clears_heating_limit(
    hass, enable_custom_integrations
):
    """The environment page edits the heating limit; clearing it is kept."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass, entry, environment={"heating_limit_temperature": 16.0}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["heating_limit_temperature"] == 16.0

    result = await _finish_editor_flow(
        hass, entry, environment={"heating_limit_temperature": None}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["heating_limit_temperature"] is None


@pytest.mark.asyncio
async def test_editor_saves_window_and_frost_settings(
    hass, enable_custom_integrations
):
    """Window delays, window temperature and frost protection are editable."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass,
        entry,
        basic={"frost_protection_temperature": 12.0},
        environment={
            "window_open_delay": {"hours": 0, "minutes": 5, "seconds": 0},
            "window_close_delay": {"hours": 0, "minutes": 10, "seconds": 0},
            "window_temperature": 15.0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["window_open_delay"] == 300
    assert entry.options["window_close_delay"] == 600
    assert entry.options["window_temperature"] == 15.0
    assert entry.options["frost_protection_temperature"] == 12.0

    result = await _finish_editor_flow(
        hass, entry, environment={"window_temperature": None}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["window_temperature"] is None
    assert entry.options["window_open_delay"] == 300


@pytest.mark.asyncio
async def test_editor_rejects_window_temperature_above_comfort(
    hass, enable_custom_integrations
):
    """The open-window temperature must stay below comfort."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass, entry, environment={"window_temperature": 21.0}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "window_must_be_below_comfort"}


@pytest.mark.asyncio
async def test_editor_saves_and_clears_heating_season_entity(
    hass, enable_custom_integrations
):
    """The winter-mode entity is optional and can be removed again."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass, entry, environment={"heating_season_entity": "binary_sensor.wintermodus"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["heating_season_entity"] == "binary_sensor.wintermodus"

    result = await _finish_editor_flow(
        hass, entry, environment={"heating_season_entity": None}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["heating_season_entity"] is None


@pytest.mark.asyncio
async def test_editor_saves_additional_thermostats_without_primary(
    hass, enable_custom_integrations
):
    """Additional thermostats are saved; the primary is not duplicated."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass,
        entry,
        basic={
            "additional_climate_entities": [
                "climate.living_room",
                "climate.living_room_2",
            ]
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["additional_climate_entities"] == ["climate.living_room_2"]


@pytest.mark.asyncio
async def test_editor_saves_calibration_flag(hass, enable_custom_integrations):
    """Calibration can be switched on in the room editor."""
    entry = _mock_room(hass)
    result = await _finish_editor_flow(hass, entry, basic={"calibration": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["calibration"] is True


@pytest.mark.asyncio
async def test_editor_saves_boost_settings_in_seconds(
    hass, enable_custom_integrations
):
    """Boost temperature and duration are stored; the duration as seconds."""
    _mock_room(hass)
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await _finish_editor_flow(
        hass,
        entry,
        basic={
            "boost_temperature": 23.0,
            "boost_duration": {"hours": 0, "minutes": 45, "seconds": 0},
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["boost_temperature"] == 23.0
    assert entry.options["boost_duration"] == 2700


@pytest.mark.asyncio
async def test_new_room_copies_the_settings_of_another_room(
    hass, enable_custom_integrations
):
    """Only the new room's devices are asked for; the rest is copied."""
    source = _mock_room(
        hass,
        options={
            "comfort_temperature": 22.0,
            "person_entities": ["person.patrick"],
            "proximity_zone": "zone_home",
            "window_entity": "binary_sensor.living_room_window",
            "presence_entity": "binary_sensor.living_room_presence",
            "notify_service": "notify.phone",
        },
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert set(result["menu_options"]) == {"room", "copy", "house"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "copy"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"source": source.entry_id}
    )
    assert result["step_id"] == "copy_room"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "climate_entity": "climate.bathroom",
            "room_temperature_entity": "sensor.bathroom_temperature",
            "schedule_entity": "schedule.living_room_comfort",
            "window_entity": "binary_sensor.bathroom_window",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data["climate_entity"] == "climate.bathroom"
    assert data["room_temperature_entity"] == "sensor.bathroom_temperature"
    assert data["window_entity"] == "binary_sensor.bathroom_window"
    assert "presence_entity" not in data
    assert data["comfort_temperature"] == 22.0
    assert data["person_entities"] == ["person.patrick"]
    assert data["proximity_zone"] == "zone_home"
    assert data["notify_service"] == "notify.phone"


@pytest.mark.asyncio
async def test_house_settings_are_created_once(hass, enable_custom_integrations):
    """The house entry is offered until it exists."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["menu_options"] == ["room", "house"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "house"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"notify_service": "notify.phone"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"entry_type": "house"}
    assert result["options"] == {
        "notify_service": "notify.phone", "house_calendar": None
    }
    await hass.async_block_till_done()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["menu_options"] == ["room"]


@pytest.mark.asyncio
async def test_house_editor_copies_settings_to_other_rooms(
    hass, enable_custom_integrations
):
    """Chosen groups go from one room to others; devices stay as they are."""
    source = _mock_room(
        hass,
        options={
            "comfort_temperature": 22.5,
            "eco_temperature": 17.0,
            "window_open_delay": 120,
            "window_entity": "binary_sensor.living_room_window",
        },
    )
    target = MockConfigEntry(
        domain=DOMAIN,
        title="Dynamische Heizung – climate.bathroom",
        unique_id="climate.bathroom",
        data={
            **_valid_input(),
            "climate_entity": "climate.bathroom",
            "window_entity": "binary_sensor.bathroom_window",
        },
        options={"window_open_delay": 600, "door_open_delay": 900},
    )
    target.add_to_hass(hass)
    house = MockConfigEntry(
        domain=DOMAIN, title="Haus", unique_id="house", data={"entry_type": "house"}
    )
    house.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(house.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "copy_settings"}
    )
    assert result["step_id"] == "copy_settings"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"source": source.entry_id, "targets": [target.entry_id], "groups": ["temperatures"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert target.options["comfort_temperature"] == 22.5
    assert target.options["eco_temperature"] == 17.0
    # Not in the chosen group: untouched.
    assert target.options["window_open_delay"] == 600
    assert target.options["window_entity"] == "binary_sensor.bathroom_window"

    result = await hass.config_entries.options.async_init(house.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "copy_settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"source": source.entry_id, "targets": [target.entry_id], "groups": ["windows"]},
    )
    assert target.options["window_open_delay"] == 120
    # Not set in the source: the target goes back to the default.
    assert "door_open_delay" not in target.options
    # Let the reloads the copy started finish before Home Assistant stops.
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_copy_settings_needs_a_target(hass, enable_custom_integrations):
    source = _mock_room(hass)
    house = MockConfigEntry(
        domain=DOMAIN, title="Haus", unique_id="house", data={"entry_type": "house"}
    )
    house.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(house.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "copy_settings"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"source": source.entry_id, "targets": [source.entry_id], "groups": ["valves"]},
    )
    assert result["errors"] == {"base": "copy_nothing_selected"}


@pytest.mark.asyncio
async def test_editor_saves_new_window_door_and_limit_settings(
    hass, enable_custom_integrations
):
    entry = _mock_room(hass)
    result = await _finish_editor_flow(
        hass,
        entry,
        environment={
            "door_entities": ["binary_sensor.door"],
            "door_open_delay": _duration(900),
            "zone_window_entities": ["binary_sensor.patio"],
            "window_change": "discard",
            "heating_limit_average": False,
            "heating_limit_fallback_off": True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["door_entities"] == ["binary_sensor.door"]
    assert entry.options["door_open_delay"] == 900
    assert entry.options["zone_window_entities"] == ["binary_sensor.patio"]
    assert entry.options["zone_window_open_delay"] == 300
    assert entry.options["window_change"] == "discard"
    assert entry.options["heating_limit_average"] is False
    assert entry.options["heating_limit_fallback_off"] is True
    assert entry.options["maintenance_duration"] == 300
