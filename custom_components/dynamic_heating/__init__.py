"""Dynamic Heating integration."""

from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
import voluptuous as vol
from homeassistant.core import (
    Event,
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_ENTRY_TYPE,
    CONF_LEAVING_HOME_DURATION,
    DEFAULT_LEAVING_HOME_DURATION,
    OLD_DEFAULT_LEAVING_HOME_DURATION,
    PROXIMITY_SENSOR_KEYS,
    DEFAULT_DEVICE_NAME,
    DOMAIN,
    ENTRY_TYPE_HOUSE,
    HOUSE_DATA_KEY,
    HOUSE_PLATFORMS,
    PLATFORMS,
    SERVICE_ESTIMATE_SAVINGS,
    SERVICE_HEAT_LOAD,
    HEAT_LOAD_OUTDOOR,
)
from .assist import async_setup_assist
from .coordinator import DynamicHeatingCoordinator
from .house import HouseManager
from .pending_push import pending_pushes


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_URL = "/dynamic_heating/dynamic-heating-card.js"


SAVINGS_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_id,
        vol.Optional("comfort_temperature"): vol.All(
            vol.Coerce(float), vol.Range(min=5, max=30)
        ),
        vol.Optional("eco_temperature"): vol.All(
            vol.Coerce(float), vol.Range(min=5, max=30)
        ),
        vol.Optional("shift_minutes", default=0): vol.All(
            vol.Coerce(int), vol.Range(min=-240, max=240)
        ),
    }
)


def _room_of(hass: HomeAssistant, entity_id: str) -> DynamicHeatingCoordinator:
    """The room an entity of the integration belongs to."""
    entry = er.async_get(hass).async_get(entity_id)
    room = (
        hass.data.get(DOMAIN, {}).get(entry.config_entry_id)
        if entry is not None and entry.config_entry_id
        else None
    )
    if not isinstance(room, DynamicHeatingCoordinator):
        raise ServiceValidationError(
            f"{entity_id} gehört zu keinem Raum der Dynamischen Heizung."
        )
    return room


async def _estimate_savings(call: ServiceCall) -> ServiceResponse:
    """Spar-Rechner: what other temperatures or times would do (changes nothing)."""
    room = _room_of(call.hass, call.data["entity_id"])
    return await room.async_estimate_savings(
        comfort=call.data.get("comfort_temperature"),
        eco=call.data.get("eco_temperature"),
        shift_minutes=call.data.get("shift_minutes", 0),
    )


HEAT_LOAD_SCHEMA = vol.Schema(
    {
        vol.Optional("outdoor_temperature", default=HEAT_LOAD_OUTDOOR): vol.All(
            vol.Coerce(float), vol.Range(min=-30, max=15)
        ),
    }
)


async def _heat_load(call: ServiceCall) -> ServiceResponse:
    """Heizlast: what the house needs on a cold day (changes nothing)."""
    house = call.hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)
    if not isinstance(house, HouseManager):
        raise ServiceValidationError(
            "Die Heizlast braucht den Haus-Eintrag der Dynamischen Heizung."
        )
    return house.heat_load(call.data["outdoor_temperature"])


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Spar-Rechner, Assist questions, and the room card for the card picker."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_ESTIMATE_SAVINGS,
        _estimate_savings,
        schema=SAVINGS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_HEAT_LOAD,
        _heat_load,
        schema=HEAT_LOAD_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    async_setup_assist(hass)
    if hass.http is None:
        return True
    from homeassistant.components.frontend import DATA_EXTRA_MODULE_URL, add_extra_js_url
    from homeassistant.components.http import StaticPathConfig

    path = Path(__file__).parent / "frontend" / "dynamic-heating-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(path), True)]
    )
    if DATA_EXTRA_MODULE_URL in hass.data:
        version = await _manifest_version(hass)
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def _manifest_version(hass: HomeAssistant) -> str:
    from homeassistant.loader import async_get_integration

    return str((await async_get_integration(hass, DOMAIN)).version or "0")


def _rename_default_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Give a room's entities the ids of its device name.

    Entities created while the device still had the default name are called
    ``*.dynamische_heizungssteuerung_*``; once the device is named (e.g.
    "Schlafzimmer Heizung") they become ``*.schlafzimmer_heizung_*``. An id
    already taken is left alone.
    """
    device = next(
        (
            device
            for device in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
            if (DOMAIN, entry.entry_id) in device.identifiers
        ),
        None,
    )
    if device is None:
        return
    default = slugify(DEFAULT_DEVICE_NAME)
    prefix = slugify(device.name_by_user or device.name or "")
    if not prefix or prefix == default:
        return
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        domain, object_id = entity.entity_id.split(".", 1)
        if object_id != default and not object_id.startswith(f"{default}_"):
            continue
        new_id = f"{domain}.{prefix}{object_id[len(default):]}"
        if registry.async_get(new_id) is None and hass.states.get(new_id) is None:
            registry.async_update_entity(entity.entity_id, new_entity_id=new_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.2 (0.10.0): leaving delay in seconds, geo-fencing sensors per room off.

    Only the minor version changes, so an older release still loads the entry.
    """
    if entry.version > 1:
        return False
    if entry.minor_version < 2:
        options = dict(entry.options)
        if not _is_house(entry):
            stored = options.get(
                CONF_LEAVING_HOME_DURATION,
                entry.data.get(CONF_LEAVING_HOME_DURATION),
            )
            if stored is not None and int(stored) == OLD_DEFAULT_LEAVING_HOME_DURATION:
                # The old default (2) was meant as minutes but read as seconds.
                options[CONF_LEAVING_HOME_DURATION] = DEFAULT_LEAVING_HOME_DURATION
            # The geo-fencing sensors are the same in every room; the house
            # device shows them once ("Geo-Fencing").
            registry = er.async_get(hass)
            for key in PROXIMITY_SENSOR_KEYS:
                entity_id = registry.async_get_entity_id(
                    "sensor", DOMAIN, f"{entry.entry_id}_{key}"
                )
                entity = registry.async_get(entity_id) if entity_id else None
                if entity is not None and entity.disabled_by is None:
                    registry.async_update_entity(
                        entity_id, disabled_by=er.RegistryEntryDisabler.INTEGRATION
                    )
        hass.config_entries.async_update_entry(
            entry, options=options, minor_version=2
        )
    return True


def _is_house(entry: ConfigEntry) -> bool:
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_HOUSE


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a room (without taking control until its switch is on) or the house."""
    if _is_house(entry):
        house = HouseManager(hass, entry)
        await house.async_load()
        entry.runtime_data = house
        hass.data.setdefault(DOMAIN, {})[HOUSE_DATA_KEY] = house
        await hass.config_entries.async_forward_entry_setups(entry, HOUSE_PLATFORMS)
        for room in house.rooms():
            await room.async_refresh()
        return True

    coordinator = DynamicHeatingCoordinator(
        hass, {**dict(entry.data), **dict(entry.options)}, entry.entry_id
    )
    await coordinator.async_load_learning()
    await coordinator.async_load_state()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    _rename_default_entity_ids(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_listen_notify_actions()
    entry.async_on_unload(coordinator.async_stop_notify_actions)
    coordinator.async_watch_foreign_control()
    entry.async_on_unload(coordinator.async_stop_foreign_control)

    stopped = False

    async def _on_stop(_event: Event) -> None:
        nonlocal stopped
        stopped = True
        await coordinator.async_arm_valve_fallback()

    remove_stop = hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _on_stop)

    def _remove_stop() -> None:
        if not stopped:
            remove_stop()

    entry.async_on_unload(_remove_stop)
    # The room model learns from the recorder once, without delaying setup.
    entry.async_create_background_task(
        hass, coordinator.async_seed_model(), "dynamic_heating_seed_model"
    )
    entry.async_create_background_task(
        hass, coordinator.async_seed_showers(), "dynamic_heating_seed_showers"
    )
    entry.async_create_background_task(
        hass, coordinator.async_seed_homecoming(), "dynamic_heating_seed_homecoming"
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms and discard runtime state."""
    if _is_house(entry):
        if not await hass.config_entries.async_unload_platforms(entry, HOUSE_PLATFORMS):
            return False
        house = entry.runtime_data
        pending_pushes(hass).discard(entry.entry_id)
        await house.async_unload()
        hass.data.get(DOMAIN, {}).pop(HOUSE_DATA_KEY, None)
        # Without the house the rooms go back to their own control.
        for room in house.rooms():
            await room.async_refresh()
        return True
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    pending_pushes(hass).discard(entry.entry_id)
    # Thermostats must not keep regulating on a room value nobody updates.
    await entry.runtime_data.async_release_external_temperature()
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True
