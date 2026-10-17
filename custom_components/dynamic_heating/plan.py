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
    # The central heating usually delivers nothing at this time.
    supply_off: bool = False
    # Share of full heat output the room takes in this step (0..1).
    demand: float = 0.0


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
    for offset in range(-1, hours // 24 + 2):
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


def blocks_switched_at(
    first: list[Block], second: list[Block], at: datetime
) -> list[Block]:
    """``first``'s blocks until ``at``, ``second``'s from then on.

    E.g. today's school day, then tomorrow's school-free schedule.
    """
    blocks = [
        Block(block.start, min(block.end, at), block.temperature)
        for block in first
        if block.start < at
    ] + [
        Block(max(block.start, at), block.end, block.temperature)
        for block in second
        if block.end > at
    ]
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
    lead_bias_minutes: int = 0,
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
                if needed is not None and needed > 0:
                    # The learned correction from late or early mornings.
                    needed = max(0.0, needed + lead_bias_minutes / 60)
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
        if off and preheat:
            # The valves wait for the central heating instead of standing
            # open in vain; preheating goes on once it delivers again.
            target, preheat = eco, False
        heating = not off and temperature < target - 0.05
        demand = 0.0
        start_temperature = temperature
        if heating:
            demand = 1.0
            temperature = min(
                weather.temperature_after(temperature, step_hours, 1.0), target
            )
        else:
            cooled = weather.temperature_after(temperature, step_hours, 0.0)
            if off or temperature > target:
                # Without heat (or above the target) the room cools, but with
                # the central heating on it never falls below the target.
                temperature = cooled if off else max(cooled, target)
                if not off and cooled < target:
                    demand = _hold_demand(weather, target) * (
                        (target - cooled) / max(start_temperature - cooled, 0.01)
                    )
            else:
                # At the target: the valves hold it if the radiators can.
                hold = weather.rate(target, 1.0) >= 0
                temperature = target if hold else cooled
                if hold:
                    demand = _hold_demand(weather, target)
        points.append(
            PlanPoint(
                at,
                round(target, 1),
                round(start_temperature, 2),
                heating,
                preheat,
                off,
                round(min(1.0, max(0.0, demand)), 3),
            )
        )
        at += step
    return points


def _hold_demand(view: ModelView, target: float) -> float:
    """Share of full output that keeps the room at ``target``."""
    if view.heat_output <= 0:
        return 0.0
    needed = view.effective_loss * (target - view.outdoor) - (
        view.solar_gain * view.solar_kw
    )
    return min(1.0, max(0.0, needed / view.heat_output))


def _clock(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def _degrees(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def _supply_resumes(points: list[PlanPoint], start: datetime) -> datetime | None:
    """When the central heating comes back before ``start`` after a pause in
    the hours just before it; None without such a pause."""
    window = [
        p for p in points if start - timedelta(hours=3) <= p.at < start
    ]
    if not any(p.supply_off for p in window):
        return None
    if window[-1].supply_off:
        return start
    resumes = None
    for earlier, later in zip(window, window[1:], strict=False):
        if earlier.supply_off and not later.supply_off:
            resumes = later.at
    return resumes


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
            resumes = _supply_resumes(points, upcoming.start)
            if resumes is not None and at_start.temperature < goal - 0.3:
                parts.append(
                    f"Zentralheizung liefert erst ab {_clock(resumes)} Uhr"
                )
                info["supply_resumes"] = resumes.isoformat()
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


# --- What-if: the same days with other temperatures or times ------------------

# Within this of the target counts as warm.
WARM_MARGIN = 0.2


def shifted_blocks(blocks: list[Block], minutes: int) -> list[Block]:
    """Blocks starting ``minutes`` later (earlier when negative), same end."""
    if not minutes:
        return list(blocks)
    shift = timedelta(minutes=minutes)
    return [
        Block(block.start + shift, block.end, block.temperature)
        for block in blocks
        if block.start + shift < block.end
    ]


def full_load_hours(points: list[PlanPoint]) -> float:
    """Heat the plan takes, in hours of full radiator output."""
    return sum(point.demand for point in points[:-1]) * STEP_MINUTES / 60


def warm_delays(
    points: list[PlanPoint], blocks: list[Block], now: datetime
) -> list[int | None]:
    """Per comfort block ahead: minutes after its start until the room is
    warm (0 = on time), None when it does not get warm within the block."""
    delays: list[int | None] = []
    end_of_plan = points[-1].at if points else now
    for block in blocks:
        if block.start <= now or block.start >= end_of_plan:
            continue
        delay: int | None = None
        for point in points:
            if point.at < block.start:
                continue
            if point.at >= block.end:
                break
            if point.temperature >= point.target - WARM_MARGIN:
                delay = round((point.at - block.start).total_seconds() / 60)
                break
        delays.append(delay)
    return delays


def compare_plans(
    base: list[PlanPoint],
    base_blocks: list[Block],
    other: list[PlanPoint],
    other_blocks: list[Block],
    now: datetime,
) -> dict:
    """Heat and punctuality of ``other`` compared with ``base``."""
    base_hours = full_load_hours(base)
    other_hours = full_load_hours(other)
    saving = (
        round(1 - other_hours / base_hours, 3) if base_hours > 0.05 else None
    )

    def punctuality(delays: list[int | None]) -> dict:
        reached = [delay for delay in delays if delay is not None]
        return {
            "blocks": len(delays),
            "missed": len(delays) - len(reached),
            "average_delay_minutes": (
                round(sum(reached) / len(reached)) if reached else None
            ),
            "late": sum(1 for delay in reached if delay > STEP_MINUTES),
        }

    return {
        "base_full_load_hours": round(base_hours, 2),
        "full_load_hours": round(other_hours, 2),
        "saving": saving,
        "base_punctuality": punctuality(warm_delays(base, base_blocks, now)),
        "punctuality": punctuality(warm_delays(other, other_blocks, now)),
    }


def _kwh(value: float) -> str:
    return f"{value:.0f}" if value >= 10 else _degrees(value)


def savings_text(answer: dict) -> str:
    """One or two sentences for the Spar-Rechner (see ``compare_plans``)."""
    changes = []
    if answer["new_eco"] != answer["eco"]:
        changes.append(
            f"Eco {_degrees(answer['new_eco'])} statt {_degrees(answer['eco'])} °C"
        )
    if answer["new_comfort"] != answer["comfort"]:
        changes.append(
            f"Komfort {_degrees(answer['new_comfort'])} statt "
            f"{_degrees(answer['comfort'])} °C"
        )
    shift = answer.get("shift_minutes") or 0
    if shift:
        changes.append(
            f"Komfort {abs(shift)} Minuten {'später' if shift > 0 else 'früher'}"
        )
    period = "in 7 Tagen" if answer.get("days", 1) >= 7 else "in 24 Stunden"
    if not changes:
        return (
            f"So wie jetzt eingestellt braucht der Raum {period} etwa "
            f"{_kwh(answer['base_kwh'])} kWh."
        )
    saving = answer.get("saving")
    if saving is None:
        effect = "kaum Heizbedarf in dieser Zeit, keine Ersparnis messbar"
    else:
        difference = abs(answer["base_kwh"] - answer["kwh"])
        if saving >= 0.005:
            effect = (
                f"ca. {round(saving * 100)} % weniger Wärme (etwa {_kwh(difference)} kWh "
                f"weniger {period})"
            )
        elif saving <= -0.005:
            effect = (
                f"ca. {round(-saving * 100)} % mehr Wärme (etwa {_kwh(difference)} kWh "
                f"mehr {period})"
            )
        else:
            effect = "kaum Unterschied beim Verbrauch"
    base = answer["base_punctuality"]
    other = answer["punctuality"]
    if other["missed"] > base["missed"]:
        warm = (
            f"An {other['missed']} von {other['blocks']} Komfortzeiten wird es "
            f"nicht ganz warm (bisher {base['missed']})."
        )
    elif (
        other["average_delay_minutes"] is not None
        and base["average_delay_minutes"] is not None
        and other["average_delay_minutes"] - base["average_delay_minutes"] >= 10
    ):
        warm = (
            f"Warm wird es im Schnitt {other['average_delay_minutes']} Minuten "
            f"nach Komfortbeginn (bisher {base['average_delay_minutes']})."
        )
    elif other["blocks"] and other["missed"] == 0 and other["late"] == 0:
        warm = "Trotzdem pünktlich warm."
    else:
        warm = "Warm wie bisher."
    return f"{', '.join(changes)}: {effect}. {warm}"
