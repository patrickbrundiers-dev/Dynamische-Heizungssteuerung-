"""When the batteries of valves and room sensors will need changing.

Pure Python without Home Assistant imports, like ``logic`` and ``plan``.

Each battery keeps its lowest level per day. A straight line through the last
weeks says how many days are left until the level reaches the low-battery
warning. A level that jumps up means a new battery: the history starts over.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Up to this many days of history per battery.
HISTORY_DAYS = 90
# A forecast needs this many days between the first and the last reading
# and a drop of at least this many percent; coarse reports (Tuya valves
# report in big steps) need a few distinct levels too.
MIN_SPAN_DAYS = 7
MIN_DROP_PERCENT = 3.0
MIN_LEVELS = 3
# A level this much above the one before is a new battery.
NEW_BATTERY_JUMP = 15.0
# Slower than this the battery lasts beyond any useful forecast.
MIN_DRAIN_PER_DAY = 0.02
MAX_DAYS = 365


@dataclass
class BatteryWatch:
    """Daily lowest levels per battery entity and the forecast from them."""

    # entity id -> [(ISO day, lowest level that day)], oldest first.
    days: dict[str, list[tuple[str, float]]] = field(default_factory=dict)
    # Entities whose history was read from the recorder already.
    seeded: set[str] = field(default_factory=set)

    def observe(self, entity_id: str, day: date, level: float) -> bool:
        """Note a reading; True when the stored history changed."""
        history = self.days.setdefault(entity_id, [])
        key = day.isoformat()
        if history and level >= history[-1][1] + NEW_BATTERY_JUMP:
            history.clear()
        if history and history[-1][0] == key:
            if level >= history[-1][1]:
                return False
            history[-1] = (key, level)
            return True
        if history and history[-1][0] > key:
            return False
        history.append((key, level))
        cutoff = date.fromordinal(day.toordinal() - HISTORY_DAYS).isoformat()
        while history and history[0][0] < cutoff:
            history.pop(0)
        return True

    def forget_others(self, entity_ids: set[str]) -> None:
        """Drop batteries no longer part of the room."""
        for entity_id in list(self.days):
            if entity_id not in entity_ids:
                del self.days[entity_id]
        self.seeded &= entity_ids

    def days_left(self, entity_id: str, today: date, low: float) -> int | None:
        """Days until the level reaches ``low``; None without a forecast."""
        history = self.days.get(entity_id) or []
        if len(history) < 2:
            return None
        points = [(date.fromisoformat(day).toordinal(), level) for day, level in history]
        span = points[-1][0] - points[0][0]
        levels = {level for _day, level in points}
        if (
            span < MIN_SPAN_DAYS
            or len(levels) < MIN_LEVELS
            or max(levels) - points[-1][1] < MIN_DROP_PERCENT
        ):
            return None
        count = len(points)
        mean_x = sum(x for x, _ in points) / count
        mean_y = sum(y for _, y in points) / count
        spread = sum((x - mean_x) ** 2 for x, _ in points)
        slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / spread
        if slope > -MIN_DRAIN_PER_DAY:
            return None
        # From the line's value today, not the last coarse step.
        level_today = mean_y + slope * (today.toordinal() - mean_x)
        left = (level_today - low) / -slope
        return max(0, min(MAX_DAYS, round(left)))

    def as_dict(self) -> dict:
        return {
            "days": {key: [list(item) for item in value] for key, value in self.days.items()},
            "seeded": sorted(self.seeded),
        }

    @classmethod
    def from_dict(cls, raw: object) -> BatteryWatch:
        watch = cls()
        if not isinstance(raw, dict):
            return watch
        days = raw.get("days")
        if isinstance(days, dict):
            for entity_id, items in days.items():
                if not isinstance(items, list):
                    continue
                history = []
                for item in items:
                    try:
                        day, level = str(item[0]), float(item[1])
                        date.fromisoformat(day)
                    except (TypeError, ValueError, IndexError):
                        continue
                    history.append((day, level))
                watch.days[str(entity_id)] = sorted(history)
        seeded = raw.get("seeded")
        if isinstance(seeded, list):
            watch.seeded = {str(item) for item in seeded}
        return watch


def describe_days(days: int) -> str:
    """'in etwa 3 Wochen' style text for a forecast."""
    if days <= 0:
        return "jetzt"
    if days < 14:
        return f"in etwa {days} {'Tag' if days == 1 else 'Tagen'}"
    if days < 60:
        return f"in etwa {round(days / 7)} Wochen"
    return f"in etwa {round(days / 30)} Monaten"
