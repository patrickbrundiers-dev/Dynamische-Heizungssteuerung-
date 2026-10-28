"""Questions to the heating via Assist ("Warum ist es im Bad kalt?").

The sentences are registered as sentence triggers of Home Assistant's own
conversation agent, like an automation's "Satz" trigger; the answer is one or
two sentences from what the room's controller knows right now. Nothing is
changed. Alexa (via Nabu Casa) only switches and cannot ask these.
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, HOUSE_DATA_KEY
from .radiator import SUPPLY_COLD

if TYPE_CHECKING:
    from .coordinator import DynamicHeatingCoordinator

_LOGGER = logging.getLogger(__name__)

# {raum} is a wildcard: whatever is said there names the room.
_IN = "(im|in der|in dem|in|bei)"
SENTENCES: dict[str, list[str]] = {
    "why_cold": [
        f"warum ist es {_IN} {{raum}} [so] kalt",
        f"warum ist es {_IN} {{raum}} nicht warm",
        "warum (heizt|wird) [das|der|die] {raum} nicht [warm]",
        f"warum heizt es {_IN} {{raum}} nicht",
    ],
    "when_warm": [
        f"wann ist es {_IN} {{raum}} warm",
        "wann (ist|wird) [das|der|die] {raum} warm",
    ],
    "room_energy": [
        "wie viel (wärme|energie) (hat|braucht) [das|der|die] {raum} [heute] [verbraucht]",
        f"wie viel (wärme|energie) [wurde] {_IN} {{raum}} [heute] verbraucht",
    ],
    "house_energy": [
        "wie viel (wärme|energie) hat die heizung [heute] verbraucht",
        "wie viel hat die heizung [heute] verbraucht",
    ],
    "overview": [
        "wie läuft die heizung",
        "was macht die heizung [gerade]",
    ],
}

_FILLER = (
    "im ", "in der ", "in dem ", "in ", "bei ", "beim ", "das ", "der ", "die ",
    "dem ", "den ",
)

_TRAILING = ("so", "heute", "verbraucht", "gerade", "eigentlich", "denn", "noch")


def _degrees(value: object) -> str:
    try:
        return f"{float(value):.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return "?"


def _kwh(value: float) -> str:
    return f"{value:.0f}" if value >= 10 else f"{value:.1f}".replace(".", ",")


def _clock(moment) -> str:
    return dt_util.as_local(moment).strftime("%H:%M")


def _normalize(text: str) -> str:
    text = text.lower().strip().replace("ß", "ss")
    changed = True
    while changed:
        changed = False
        for word in _FILLER:
            if text.startswith(word):
                text = text[len(word):].strip()
                changed = True
    # A wildcard may take along words said after the room.
    words = text.split()
    while words and words[-1] in _TRAILING:
        words.pop()
    text = " ".join(words)
    # "Leonies Zimmer", "Zimmer von Leonie"
    text = text.replace("zimmer von ", "")
    if text.endswith("s zimmer"):
        text = text[: -len("s zimmer")]
    return text.removesuffix(" zimmer").strip()


def find_room(
    rooms: list[DynamicHeatingCoordinator], spoken: str
) -> DynamicHeatingCoordinator | None:
    """The room whose name fits what was said best."""
    query = _normalize(spoken)
    if not query:
        return None
    best: tuple[float, DynamicHeatingCoordinator] | None = None
    for room in rooms:
        name = _normalize(room.room_name)
        names = {name, *name.split()}
        if "badezimmer" in name or name.endswith("bad"):
            names.add("bad")
        score = 0.0
        for candidate in names:
            if not candidate:
                continue
            if query == candidate:
                value = 1.0
            elif candidate in query or query in candidate:
                value = 0.85 if candidate == name else 0.7
            else:
                value = difflib.SequenceMatcher(None, query, candidate).ratio() * 0.8
            score = max(score, value)
        if best is None or score > best[0]:
            best = (score, room)
    return best[1] if best is not None and best[0] >= 0.6 else None


def _warm_at(room: DynamicHeatingCoordinator, target: float) -> str | None:
    """When the day plan sees the room at ``target`` (local clock)."""
    now = dt_util.utcnow()
    for point in room.plan_points:
        if point.at < now:
            continue
        if point.temperature >= target - 0.2:
            return _clock(point.at)
    return None


def answer_why_cold(room: DynamicHeatingCoordinator) -> str:
    data = room.data or {}
    name = room.room_name
    current = data.get("room_temperature")
    target = data.get("target_temperature")
    if current is None:
        return f"Für {name} kenne ich gerade keine Raumtemperatur."
    text = f"{name}: {_degrees(current)} °C"
    if target is not None:
        text += f", Ziel {_degrees(target)} °C."
    else:
        text += "."
    if not room.enabled:
        return f"{text} Die Regelung ist ausgeschaltet."
    if data.get("window_open"):
        return f"{text} Das Fenster ist offen, deshalb ist die Heizung abgesenkt."
    if data.get("heating_season") is False or data.get("heating_limit_reached"):
        return f"{text} Draußen ist es warm genug, die Heizung pausiert."
    if data.get("outdoor_warmer"):
        return f"{text} Draußen ist es wärmer als drinnen, die Heizung pausiert."
    status = str(data.get("status") or "")
    if target is None or float(current) >= float(target) - 0.2:
        reason = f"Gerade gilt: {status}." if status else ""
        plan = data.get("day_plan")
        if plan:
            reason += f" {plan}."
        return f"{text} Das Ziel ist erreicht. {reason}".strip()
    if SUPPLY_COLD in (data.get("radiator_supply"), data.get("house_supply")):
        reason = "Die Zentralheizung liefert gerade keine Wärme"
        resume = room.supply_profile.next_on_hour(dt_util.now().hour)
        if data.get("supply_usually_off") and resume is not None:
            reason += f", meist wieder ab {resume}:00 Uhr"
        return f"{text} {reason}."
    if room.heating_problem:
        detail = room.heating_problem_detail or "der Raum wird nicht warm"
        return f"{text} Es gibt ein Heizproblem: {detail}."
    demand = data.get("heat_demand")
    reason = "Die Heizung läuft"
    if demand is not None:
        reason += f", Ventile {int(demand)} % offen"
    warm = _warm_at(room, float(target))
    if warm is not None:
        reason += f". Warm voraussichtlich gegen {warm} Uhr"
    return f"{text} {reason}."


def _preheat_reason(parts: object) -> str | None:
    """The main reason behind the preheat time, as one short sentence."""
    if not isinstance(parts, dict):
        return None
    if parts.get("supply_wait_until"):
        return f" Die Zentralheizung liefert erst ab {parts['supply_wait_until']} Uhr."
    if parts.get("limited"):
        return f" Das Vorheizen ist auf {parts.get('limit_minutes')} Minuten begrenzt."
    bias = int(parts.get("punctuality_minutes") or 0)
    if bias >= 10:
        return (
            f" Es startet {bias} Minuten früher, weil es an ähnlichen Morgen"
            " zu spät warm war."
        )
    if bias <= -10:
        return (
            f" Es startet {-bias} Minuten später, weil es an ähnlichen Morgen"
            " zu früh warm war."
        )
    if int(parts.get("sun_minutes") or 0) <= -5:
        return " Die Sonne hilft mit, darum startet es etwas später."
    return None


def answer_when_warm(room: DynamicHeatingCoordinator) -> str:
    text = _answer_when_warm(room)
    reason = _preheat_reason((room.data or {}).get("preheat_parts"))
    return text + reason if reason else text


def _answer_when_warm(room: DynamicHeatingCoordinator) -> str:
    data = room.data or {}
    name = room.room_name
    current = data.get("room_temperature")
    target = data.get("target_temperature")
    comfort = data.get("comfort_temperature")
    if (
        current is not None
        and target is not None
        and comfort is not None
        and float(target) >= float(comfort) - 0.05
    ):
        if float(current) >= float(target) - 0.2:
            return f"{name} ist schon warm: {_degrees(current)} °C."
        warm = _warm_at(room, float(target))
        if warm is not None:
            return (
                f"{name} heizt gerade auf {_degrees(target)} °C, "
                f"voraussichtlich gegen {warm} Uhr warm."
            )
    info = room.plan_info or {}
    start = info.get("comfort_start")
    if start:
        moment = dt_util.parse_datetime(start)
        if moment is not None:
            day = (
                "morgen "
                if dt_util.as_local(moment).date()
                == (dt_util.now() + timedelta(days=1)).date()
                else ""
            )
            text = f"{name}: Komfort beginnt {day}um {_clock(moment)} Uhr"
            expected = info.get("expected_at_start")
            goal = info.get("comfort_target")
            if expected is not None and goal is not None:
                text += f", dann sind es ca. {_degrees(expected)} °C (Ziel {_degrees(goal)} °C)"
            return f"{text}."
    plan = data.get("day_plan")
    return f"{name}: {plan}." if plan else f"Für {name} gibt es gerade keinen Tagesplan."


def answer_room_energy(room: DynamicHeatingCoordinator) -> str:
    data = room.data or {}
    today = data.get("heat_energy_today")
    week = data.get("heat_energy_7_days")
    if today is None:
        return f"Für {room.room_name} gibt es noch keinen Wärmezähler."
    return (
        f"{room.room_name} hat heute etwa {_kwh(float(today))} kWh Wärme gebraucht, "
        f"in den letzten 7 Tagen etwa {_kwh(float(week or 0))} kWh. Das ist geschätzt."
    )


def answer_house_energy(rooms: list[DynamicHeatingCoordinator]) -> str:
    values = {
        room.room_name: (room.data or {}).get("heat_energy_today")
        for room in rooms
    }
    values = {name: float(value) for name, value in values.items() if value is not None}
    if not values:
        return "Der Wärmezähler hat noch keine Werte."
    total = sum(values.values())
    top = max(values, key=values.get)
    text = f"Heute bisher etwa {_kwh(total)} kWh Wärme im ganzen Haus"
    if values[top] >= 0.1:
        text += f", am meisten {top} mit {_kwh(values[top])} kWh"
    return f"{text}. Das ist geschätzt."


def answer_overview(hass: HomeAssistant, rooms: list[DynamicHeatingCoordinator]) -> str:
    heating = []
    problems = []
    for room in sorted(rooms, key=lambda room: room.room_name):
        data = room.data or {}
        current, target = data.get("room_temperature"), data.get("target_temperature")
        if room.heating_problem:
            problems.append(room.room_name)
        if (
            room.enabled
            and current is not None
            and target is not None
            and float(target) > float(current) + 0.2
        ):
            heating.append(room.room_name)
    parts = []
    house = hass.data.get(DOMAIN, {}).get(HOUSE_DATA_KEY)
    if house is not None:
        parts.append(f"Zentralheizung: {house.supply_text()}")
    parts.append(
        "Es heizt gerade: " + ", ".join(heating) if heating else "Kein Raum heizt gerade"
    )
    if problems:
        parts.append("Problem in: " + ", ".join(problems))
    return ". ".join(parts) + "."


def _rooms(hass: HomeAssistant) -> list[DynamicHeatingCoordinator]:
    from .coordinator import DynamicHeatingCoordinator

    return [
        value
        for value in hass.data.get(DOMAIN, {}).values()
        if isinstance(value, DynamicHeatingCoordinator)
    ]


def _room_answer(
    hass: HomeAssistant, spoken: str, answer: Callable[[Any], str]
) -> str:
    rooms = _rooms(hass)
    room = find_room(rooms, spoken)
    if room is None:
        names = ", ".join(sorted(room.room_name for room in rooms))
        return f"Den Raum „{spoken}“ kenne ich nicht. Es gibt: {names}."
    return answer(room)


@callback
def async_setup_assist(hass: HomeAssistant) -> CALLBACK_TYPE | None:
    """Register the questions with the conversation agent; None without it."""
    try:
        from homeassistant.components.conversation.agent_manager import (
            get_agent_manager,
        )
    except ImportError:  # pragma: no cover - conversation is part of core
        _LOGGER.warning("Fragen über Assist nicht verfügbar: Konversation fehlt")
        return None
    try:  # up to HA 2026.x: one TriggerDetails argument
        from homeassistant.components.conversation.trigger import TriggerDetails
    except ImportError:  # newer HA: sentences and callback as keywords
        TriggerDetails = None

    def handler(kind: str):
        async def handle(_user_input: Any, result: Any) -> str:
            try:
                slot = result.entities.get("raum")
                spoken = str(slot.text if slot is not None else "").strip()
                if kind == "why_cold":
                    return _room_answer(hass, spoken, answer_why_cold)
                if kind == "when_warm":
                    return _room_answer(hass, spoken, answer_when_warm)
                if kind == "room_energy":
                    return _room_answer(hass, spoken, answer_room_energy)
                if kind == "house_energy":
                    return answer_house_energy(_rooms(hass))
                return answer_overview(hass, _rooms(hass))
            except Exception:  # noqa: BLE001 - always answer something
                _LOGGER.exception("Assist question %s failed", kind)
                return "Das kann ich gerade nicht beantworten."

        return handle

    try:
        manager = get_agent_manager(hass)
        removers = [
            manager.register_trigger(
                TriggerDetails(sentences=sentences, callback=handler(kind))
            )
            if TriggerDetails is not None
            else manager.register_trigger(
                sentences=sentences, trigger_callback=handler(kind)
            )
            for kind, sentences in SENTENCES.items()
        ]
    except Exception:  # noqa: BLE001 - an internal API; never block setup
        _LOGGER.warning(
            "Fragen über Assist nicht verfügbar (Konversations-API geändert?)",
            exc_info=True,
        )
        return None

    @callback
    def remove() -> None:
        for remover in removers:
            remover()

    return remove
