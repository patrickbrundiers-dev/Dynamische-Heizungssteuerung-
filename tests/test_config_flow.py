"""Config flow and editor tests using an isolated Home Assistant instance."""

import pytest
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.dynamic_heating.const import DOMAIN


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
):
    """Submit all editor pages, using current settings unless overridden."""
    values = dict(entry.data)
    values.update(dict(entry.options))
    values.update(basic or {})
    result = await hass.config_entries.options.async_init(entry.entry_id)

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
    if values.get("frost_protection_temperature") is not None:
        first["frost_protection_temperature"] = values["frost_protection_temperature"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=first
    )
    assert result["step_id"] == "presence"

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
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=presence_input
    )
    assert result["step_id"] == "geofencing"

    geo_keys = ("proximity_entity", "proximity_direction_entity")
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
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=geo_input
    )
    assert result["step_id"] == "environment"

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
    return await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=env_input
    )


@pytest.mark.asyncio
async def test_user_flow_creates_entry(hass, enable_custom_integrations):
    """A valid initial configuration creates a room."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=_valid_input()
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Dynamische Heizung – climate.living_room"
    assert result["data"]["climate_entity"] == "climate.living_room"
    # Native duration selector values are normalized to numeric seconds.
    assert result["data"]["enter_home_duration"] == 2
    assert result["data"]["leaving_home_duration"] == 2
    assert result["data"]["proximity_duration"] == 120
    assert result["data"]["proximity_max_age"] == 900
    assert result["data"]["presence_on_duration"] == 300
    assert result["data"]["presence_off_duration"] == 1200


@pytest.mark.asyncio
async def test_user_flow_rejects_eco_temperature_at_or_above_comfort(
    hass, enable_custom_integrations
):
    """Invalid temperatures are rejected without creating an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
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
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
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

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
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

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=edited
    )

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
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=edited
    )

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
            "proximity_entity": "sensor.home_distance",
            "proximity_direction_entity": "sensor.home_direction",
            "proximity_duration": _duration(120),
            "proximity_max_age": _duration(900),
            "proximity_distance": 500,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["person_entities"] == ["person.patrick", "person.jenny"]
    assert entry.options["guest_entity"] == "input_boolean.guest_mode"
    assert entry.options["presence_schedule_entity"] == "schedule.presence_active"
    assert entry.options["proximity_entity"] == "sensor.home_distance"
    assert entry.options["proximity_direction_entity"] == "sensor.home_direction"
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
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
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
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=first
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"away_temperature": 21.0}
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
