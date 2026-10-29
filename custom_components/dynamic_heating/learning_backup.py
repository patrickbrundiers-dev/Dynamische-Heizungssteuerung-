"""Back up and restore what the rooms and the house learned.

Weeks of learning (room model, punctuality, homecomings, boiler hours,
levels) live in Home Assistant's own storage. A weekly copy as one JSON file
under ``/config/dynamic_heating_backup`` lets a room that was deleted and set
up again start where it was, and survives a broken storage file.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    HOUSE_DATA_KEY,
    LEARNING_BACKUP_DIR,
    LEARNING_BACKUP_KEEP,
    LEARNING_BACKUP_VERSION,
)

PREFIX = "lernstand-"


def _rooms(hass: HomeAssistant) -> list[Any]:
    from .coordinator import DynamicHeatingCoordinator

    return [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, DynamicHeatingCoordinator)
    ]


def _room_store(hass: HomeAssistant, entry_id: str) -> Store:
    return Store(hass, 1, f"{DOMAIN}_{entry_id}_learning")


def _house_store(hass: HomeAssistant) -> Store:
    return Store(hass, 1, f"{DOMAIN}_house")


def backup_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(LEARNING_BACKUP_DIR))


def _write(directory: Path, name: str, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    files = sorted(directory.glob(f"{PREFIX}*.json"))
    for old in files[:-LEARNING_BACKUP_KEEP]:
        old.unlink(missing_ok=True)
    return path


def _files(directory: Path) -> list[str]:
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.glob(f"{PREFIX}*.json"))


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


async def async_export_learning(
    hass: HomeAssistant, now: datetime | None = None
) -> dict[str, Any]:
    """Write one backup file with every room and the house."""
    now = now or dt_util.now()
    rooms = {}
    for room in _rooms(hass):
        # Write what is in memory first, so the copy is current.
        await room._save_learning()
        stored = await _room_store(hass, room.entry_id).async_load()
        if isinstance(stored, dict):
            rooms[room.entry_id] = {"room": room.room_name, "learning": stored}
    house_data = None
    house = hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)
    if house is not None:
        await house._async_save()
        house_data = await _house_store(hass).async_load()
    payload = {
        "version": LEARNING_BACKUP_VERSION,
        "created": dt_util.as_local(now).isoformat(),
        "rooms": rooms,
        "house": house_data if isinstance(house_data, dict) else None,
    }
    name = f"{PREFIX}{dt_util.as_local(now).strftime('%Y-%m-%d')}.json"
    path = await hass.async_add_executor_job(_write, backup_dir(hass), name, payload)
    return {
        "file": path.name,
        "rooms": sorted(item["room"] for item in rooms.values()),
        "house": payload["house"] is not None,
    }


def match_room(backup_rooms: dict[str, Any], entry_id: str, name: str) -> dict | None:
    """The backed-up learning of a room: by its entry, else by its name.

    A room that was deleted and set up again has a new entry id but keeps
    its name.
    """
    item = backup_rooms.get(entry_id)
    if isinstance(item, dict):
        return item
    wanted = name.strip().casefold()
    for item in backup_rooms.values():
        if isinstance(item, dict) and str(item.get("room", "")).strip().casefold() == wanted:
            return item
    return None


async def async_restore_learning(
    hass: HomeAssistant,
    file: str | None = None,
    room_entry_id: str | None = None,
    include_house: bool | None = None,
) -> dict[str, Any]:
    """Put a backup back; the restored entries are reloaded."""
    directory = backup_dir(hass)
    files = await hass.async_add_executor_job(_files, directory)
    if not files:
        raise ServiceValidationError(
            f"Keine Sicherung gefunden (Ordner {LEARNING_BACKUP_DIR})."
        )
    name = file.strip() if file else files[-1]
    if name not in files:
        raise ServiceValidationError(
            f"Sicherung {name} nicht gefunden. Vorhanden: {', '.join(files)}"
        )
    try:
        payload = await hass.async_add_executor_job(_read, directory / name)
    except (OSError, ValueError) as err:
        raise ServiceValidationError(f"Sicherung {name} nicht lesbar: {err}") from err
    if not isinstance(payload, dict) or payload.get("version") != LEARNING_BACKUP_VERSION:
        raise ServiceValidationError(f"Sicherung {name} hat ein unbekanntes Format.")
    backup_rooms = payload.get("rooms") if isinstance(payload.get("rooms"), dict) else {}
    targets = [
        room for room in _rooms(hass)
        if room_entry_id is None or room.entry_id == room_entry_id
    ]
    restored, missing = [], []
    for room in targets:
        item = match_room(backup_rooms, room.entry_id, room.room_name)
        learning = item.get("learning") if item else None
        if not isinstance(learning, dict):
            missing.append(room.room_name)
            continue
        entry_id = room.entry_id
        await hass.config_entries.async_unload(entry_id)
        await _room_store(hass, entry_id).async_save(learning)
        await hass.config_entries.async_setup(entry_id)
        restored.append(room.room_name)
    house_restored = False
    if include_house is None:
        include_house = room_entry_id is None
    house = hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)
    if include_house and house is not None and isinstance(payload.get("house"), dict):
        entry_id = house.entry.entry_id
        await hass.config_entries.async_unload(entry_id)
        await _house_store(hass).async_save(payload["house"])
        await hass.config_entries.async_setup(entry_id)
        house_restored = True
    return {
        "file": name,
        "restored": sorted(restored),
        "not_in_backup": sorted(missing),
        "house": house_restored,
    }
