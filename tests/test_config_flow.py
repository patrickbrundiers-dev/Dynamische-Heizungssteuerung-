"""Config flow tests using Home Assistant's isolated test instance."""

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.dynamic_heating.const import DOMAIN


def _valid_input():
    """Return a minimal valid configuration without any real devices."""
    return {
        "climate_entity": "climate.living_room",
        "room_temperature_entity": "sensor.living_room_temperature",
        "schedule_entity": "schedule.living_room_comfort",
        "comfort_temperature": 21.0,
        "eco_temperature": 18.0,
        "max_preheat_minutes": 120,
    }


@pytest.mark.asyncio
async def test_user_flow_creates_entry(hass, enable_custom_integrations):
    """A valid user configuration creates a named config entry."""
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


@pytest.mark.asyncio
async def test_user_flow_rejects_eco_temperature_at_or_above_comfort(
    hass, enable_custom_integrations
):
    """An invalid eco/comfort relationship is rejected without creating an entry."""
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
