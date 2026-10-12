"""Day plan: what the room will do in the next 24 hours.

Pure Python without Home Assistant imports, like ``logic`` and ``model``.

The plan replays the control rules on the learned room equation: comfort
during the schedule's blocks, eco in between, preheating as early as the
model says the room needs (at most the maximum preheat time), no heat in the
hours in which the central heating usually delivers none. Presence, windows
and hand-picked modes are not foreseeable and are left out; the sun is not
counted on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from .model import ModelView

STEP_MINUTES = 15
PLAN_HOURS = 24
# The plan is checked against the room this many hours later.
CHECK_HOURS = 3
CHECK_ALPHA = 0.2
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True, slots=True)
class Block:
    """A comfort block; ``temperature`` None means the room's comfort."""

    start: datetime
    end: datetime
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class PlanPoint:
    at: datetime
    target: float
    temperature: float
    heating: bool
    preheat: bool


def _parse_time(raw: object) -> time | None:
    """'06:30:00' (or '24:00:00' for the end of the day) as a time."""
    if isinstance(raw, time):
        return raw
    if not isinstance(raw, str):
        return None
    parts = raw.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        second = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return None
    if hour == 24 and minute == 0 and second == 0:
        return time.max
    try:
        return time(hour, minute, second)
    except ValueError:
        return None


def blocks_from_schedule(
    weekly: object,
    now: datetime,
    temperature_of: Callable[[object], float | None],
    hours: int = PLAN_HOURS,
) -> list[Block]:
    """Comfort blocks from a schedule helper's week (``schedule.get_schedule``).

    ``now`` is local and aware; ``temperature_of`` reads a block's data.
    """
    if not isinstance(weekly, dict):
        return []
    end_of_plan = now + timedelta(hours=hours)
    blocks: list[Block] = []
    for offset in (-1, 0, 1):
        day = (now + timedelta(days=offset)).date()
        items = weekly.get(_WEEKDAYS[day.weekday()]) or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            begin, finish = _parse_time(item.get("from")), _parse_time(item.get("to"))
            if begin is None or finish is None:
                continue
            start = datetime.combine(day, begin, now.tzinfo)
            end = (
                datetime.combine(day + timedelta(days=1), time.min, now.tzinfo)
                if finish == time.max
                else datetime.combine(day, finish, now.tzinfo)
            )
            if end <= now or start >= end_of_plan or end <= start:
                continue
            data = item.get("data")
            temperature = (
                temperature_of(data.get("temperature")) if isinstance(data, dict) else None
            )
            blocks.append(Block(start, end, temperature))
    return sorted(blocks, key=lambda block: block.start)


def _block_at(blocks: list[Block], at: datetime) -> Block | None:
    for block in blocks:
        if block.start <= at < block.end:
            return block
    return None


def _next_block(blocks: list[Block], at: datetime) -> Block | None:
    for block in blocks:
        if block.start > at:
            return block
    return None


def simulate(
    view: ModelView,
    *,
    now: datetime,
    room: float,
    comfort: float,
    eco: float,
    blocks: list[Block],
    outdoor_at: Callable[[datetime], float],
    supply_off: Callable[[datetime], bool],
    max_preheat_minutes: int,
    hours: int = PLAN_HOURS,
) -> list[PlanPoint]:
    """Step through the next ``hours`` and return one point per step."""
    step = timedelta(minutes=STEP_MINUTES)
    step_hours = STEP_MINUTES / 60
    points: list[PlanPoint] = []
    temperature = room
    at = now
    # Once preheating for a block started it goes on until the block starts,
    # like the controller (the remaining lead shrinks while the room warms).
    preheating_for: Block | None = None
    for _ in range(int(hours * 60 / STEP_MINUTES) + 1):
        weather = view.with_weather(outdoor=outdoor_at(at), solar_kw=0.0)
        block = _block_at(blocks, at)
        preheat = False
        if block is not None:
            target = comfort if block.temperature is None else block.temperature
        else:
            target = eco
            upcoming = _next_block(blocks, at)
            if upcoming is not None:
                goal = comfort if upcoming.temperature is None else upcoming.temperature
                needed = weather.hours_to_reach(temperature, goal)
                lead = (
                    max_preheat_minutes / 60
                    if needed is None
                    else min(needed, max_preheat_minutes / 60)
                )
                if preheating_for is upcoming or (
                    lead > 0 and upcoming.start - at <= timedelta(hours=lead)
                ):
                    target, preheat = goal, True
                    preheating_for = upcoming
        off = supply_off(at)
        heating = not off and temperature < target - 0.05
        points.append(
            PlanPoint(at, round(target, 1), round(temperature, 2), heating, preheat)
        )
        if heating:
            temperature = min(
                weather.temperature_after(temperature, step_hours, 1.0), target
            )
        else:
            cooled = weather.temperature_after(temperature, step_hours, 0.0)
            if off or temperature > target:
                # Without heat (or above the target) the room cools, but with
                # the central heating on it never falls below the target.
                temperature = cooled if off else max(cooled, target)
            else:
                # At the target: the valves hold it if the radiators can.
                hold = weather.rate(target, 1.0) >= 0
                temperature = target if hold else cooled
        at += step
    return points


def _clock(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _degrees(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def summary(points: list[PlanPoint], blocks: list[Block], now: datetime) -> dict:
    """Short text and key times of a plan (all times local)."""
    if not points:
        return {"text": None}
    info: dict = {}
    parts: list[str] = []
    running = _block_at(blocks, now)
    if running is not None:
        after = next((p for p in points if p.at >= running.end), None)
        text = f"Komfort bis {_clock(running.end)} Uhr"
        if after is not None and running.end < now + timedelta(hours=PLAN_HOURS):
            text += f", dann {_degrees(after.target)} °C"
        parts.append(text)
    upcoming = _next_block(blocks, now)
    if upcoming is not None:
        preheat = next(
            (p for p in points if p.preheat and p.at < upcoming.start), None
        )
        at_start = next((p for p in points if p.at >= upcoming.start), None)
        day = "morgen " if upcoming.start.date() != now.date() else ""
        if preheat is not None and preheat.at > now:
            parts.append(f"{day}Vorheizen ab {_clock(preheat.at)} Uhr".strip())
            info["preheat_start"] = preheat.at.isoformat()
        elif preheat is not None:
            parts.append("Vorheizen läuft")
            info["preheat_start"] = preheat.at.isoformat()
        if at_start is not None:
            goal = at_start.target
            parts.append(
                f"{day if preheat is None else ''}um {_clock(upcoming.start)} Uhr "
                f"ca. {_degrees(at_start.temperature)} °C (Ziel {_degrees(goal)} °C)"
            )
            info["comfort_start"] = upcoming.start.isoformat()
            info["expected_at_start"] = round(at_start.temperature, 1)
            info["comfort_target"] = goal
    if not parts:
        parts.append(
            f"Kein Komfort in den nächsten {PLAN_HOURS} Stunden – "
            f"{_degrees(points[0].target)} °C"
        )
    text = ", ".join(parts)
    info["text"] = text[0].upper() + text[1:]
    info["heating_hours"] = round(
        sum(1 for p in points[:-1] if p.heating) * STEP_MINUTES / 60, 1
    )
    return info


def temperature_at(points: list[PlanPoint], at: datetime) -> float | None:
    """The planned room temperature at ``at`` (nearest step)."""
    best = None
    for point in points:
        if best is None or abs((point.at - at).total_seconds()) < abs(
            (best.at - at).total_seconds()
        ):
            best = point
    if best is None or abs((best.at - at).total_seconds()) > STEP_MINUTES * 60:
        return None
    return best.temperature
