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

    env_keys = ("window_entity", "outdoor_temperature_entity", "weather_entity")
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
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    edited = {
        **_valid_input(),
        "room_temperature_entity": "sensor.bedroom_temperature",
        "schedule_entity": "schedule.bedroom_comfort",
        "comfort_temperature": 22.0,
        "eco_temperature": 17.0,
        # Empty optional selectors are omitted by Home Assistant's form.
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=edited
    )

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
    result = await hass.config_entries.options.async_init(entry.entry_id)
    edited = {**_valid_input(), "climate_entity": "climate.bedroom"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=edited
    )

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
    """The room editor exposes person, guest, proximity and debounce fields."""
    entry = _mock_room(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    edited = {
        **_valid_input(),
        "person_entities": ["person.patrick", "person.jenny"],
        "guest_entity": "input_boolean.guest_mode",
        "enter_home_duration": {"hours": 0, "minutes": 0, "seconds": 2},
        "leaving_home_duration": {"hours": 0, "minutes": 0, "seconds": 2},
        "proximity_entity": "sensor.home_distance",
        "proximity_direction_entity": "sensor.home_direction",
        "proximity_duration": {"hours": 0, "minutes": 2, "seconds": 0},
        "proximity_max_age": {"hours": 0, "minutes": 15, "seconds": 0},
        "proximity_distance": 500,
        "presence_schedule_entity": "schedule.presence_active",
        "presence_on_duration": {"hours": 0, "minutes": 5, "seconds": 0},
        "presence_off_duration": {"hours": 0, "minutes": 20, "seconds": 0},
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=edited
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["person_entities"] == ["person.patrick", "person.jenny"]
    assert entry.options["guest_entity"] == "input_boolean.guest_mode"
    assert entry.options["proximity_entity"] == "sensor.home_distance"
    assert entry.options["proximity_direction_entity"] == "sensor.home_direction"
    assert entry.options["proximity_max_age"] == 900
    assert entry.options["presence_schedule_entity"] == "schedule.presence_active"
    assert entry.options["enter_home_duration"] == 2
    assert entry.options["leaving_home_duration"] == 2
    assert entry.options["proximity_duration"] == 120
    assert entry.options["presence_on_duration"] == 300
    assert entry.options["presence_off_duration"] == 1200
