"""0.9.2: the room model replaces the old sample learner, fewer entities."""

import pytest
from homeassistant.const import EntityCategory
from homeassistant.helpers import entity_registry as er
from test_home_assistant_sandbox import (
    _capture_climate_calls,
    _set_up_test_entities,
    _setup_integration,
)
from test_smart_090 import _trained_model

from custom_components.dynamic_heating.const import DOMAIN


@pytest.mark.asyncio
async def test_room_model_rates_replace_the_sample_learner(
    hass, enable_custom_integrations
):
    """With a ready model the shown rates are the model's; samples stop."""
    _set_up_test_entities(hass, room_temperature="19.0")
    entry, coordinator = await _setup_integration(hass)
    assert coordinator.data["heating_rate"] == coordinator.heating_rate

    coordinator.room_model = _trained_model(heat_output=0.35, loss=0.02)
    with _capture_climate_calls(hass):
        coordinator.enabled = True
        await coordinator.async_refresh()

    view = coordinator.room_model.view(3.0, 0.0, 0.0)
    assert coordinator.data["heating_rate"] == pytest.approx(view.rate(19.0, 1.0), abs=0.01)
    assert coordinator.data["cooling_rate"] == pytest.approx(-view.rate(19.0, 0.0), abs=0.01)
    assert coordinator.data["learning_status"] == "Raummodell übernimmt"


@pytest.mark.asyncio
async def test_old_learner_sensors_are_removed_and_counters_hidden(
    hass, enable_custom_integrations
):
    """Entities of the old learner disappear, diagnostics move aside."""
    _set_up_test_entities(hass)
    registry = er.async_get(hass)
    entry, coordinator = await _setup_integration(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_learning_status",
        config_entry=entry,
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(old.entity_id) is None

    def entity(key):
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{key}")
        return registry.async_get(entity_id)

    assert entity("heating_rate").entity_category is EntityCategory.DIAGNOSTIC
    assert entity("proximity_updates_seen").disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert entity("status").entity_category is None
    assert entity("model_status").entity_category is None
