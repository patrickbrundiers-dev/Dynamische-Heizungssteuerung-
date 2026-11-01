"""House-wide insights from all rooms (0.18.0).

Pure Python without Home Assistant imports, like ``model``.

- ``FlowStats``: is the boiler's heating curve too high or too low? Judged
  from how far the rooms open their valves while holding comfort, per band
  of outdoor temperature (idea from heating forums: valves that barely open
  in the cold mean a flow temperature higher than needed).
- ``balance_point``: from which daily mean outdoor temperature the house
  needs no heat (Heating Analytics "balance point").
- ``week_ahead``: heating hours, kWh and euros of the next days from the
  forecast and each room's full-load hours per degree day.
- ``CycleWatch``: how often and how long the house asks for heat, to see
  whether the boiler keeps starting for small loads.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

# --- Heating curve ------------------------------------------------------------

# Outdoor bands (upper limits, °C); the last one is open.
BANDS = ((0.0, "unter 0 °C"), (5.0, "0 bis 5 °C"), (10.0, "5 bis 10 °C"))
# A day weighs this much less each day: about the last four weeks count.
FLOW_DECAY = 0.97
# Hours of holding in a band (all rooms together) before it is judged.
FLOW_MIN_HOURS = 24.0
# Holding: comfort, within this of the target.
FLOW_HOLD_BAND = 0.5
# Mean demand while holding below this, and overshoot in at least this share
# of the comfort time: the flow is hotter than needed.
FLOW_LOW_DEMAND = 25.0
FLOW_OVERSHOOT_SHARE = 0.1
# A room at full demand and still this far below the target in at least this
# share of its comfort time: the flow is too cold for it (or its radiator too
# small).
FLOW_SHORT_GAP = 0.5
FLOW_SHORT_SHARE = 0.25
FLOW_SHORT_MIN_HOURS = 6.0

HOT = "zu_warm"
FITS = "passt"
SHORT = "zu_kalt"
UNKNOWN = "zu_wenig_daten"


def band_of(outdoor: float) -> int:
    for index, (upper, _label) in enumerate(BANDS):
        if outdoor < upper:
            return index
    return len(BANDS)


def band_label(index: int) -> str:
    return BANDS[index][1] if index < len(BANDS) else "über 10 °C"


@dataclass(slots=True)
class FlowStats:
    """Per room and outdoor band: [comfort h, hold h, demand × hold h,
    overshoot h, short h] (decaying daily)."""

    rooms: dict[str, list[list[float]]] = field(default_factory=dict)
    day: str | None = None

    def observe(
        self,
        room: str,
        today: date,
        hours: float,
        *,
        outdoor: float | None,
        mode: str | None,
        room_temperature: float | None,
        target: float | None,
        demand: float | None,
    ) -> None:
        """Add ``hours`` of one room's state."""
        if self.day != today.isoformat():
            if self.day is not None:
                self._decay()
            self.day = today.isoformat()
        if (
            hours <= 0
            or outdoor is None
            or mode != "comfort"
            or room_temperature is None
            or target is None
            or demand is None
        ):
            return
        bands = self.rooms.setdefault(room, [[0.0] * 5 for _ in range(len(BANDS) + 1)])
        item = bands[band_of(outdoor)]
        item[0] += hours
        gap = room_temperature - target
        if abs(gap) <= FLOW_HOLD_BAND:
            item[1] += hours
            item[2] += demand * hours
        if gap > FLOW_HOLD_BAND and demand <= 10:
            item[3] += hours
        if gap < -FLOW_SHORT_GAP and demand >= 95:
            item[4] += hours

    def _decay(self) -> None:
        for bands in self.rooms.values():
            for item in bands:
                for index in range(5):
                    item[index] = round(item[index] * FLOW_DECAY, 4)

    def verdict(self) -> dict:
        """The heating curve's verdict from the cold bands (below 10 °C)."""
        bands = []
        short_rooms: set[str] = set()
        judged_hot = judged_fit = 0
        for index in range(len(BANDS)):
            comfort = hold = demand = over = 0.0
            for room, items in self.rooms.items():
                item = items[index]
                comfort += item[0]
                hold += item[1]
                demand += item[2]
                over += item[3]
                if (
                    item[0] >= FLOW_SHORT_MIN_HOURS
                    and item[4] / item[0] >= FLOW_SHORT_SHARE
                ):
                    short_rooms.add(room)
            mean = demand / hold if hold > 0 else None
            share = over / comfort if comfort > 0 else None
            state = UNKNOWN
            if hold >= FLOW_MIN_HOURS and mean is not None and share is not None:
                if mean < FLOW_LOW_DEMAND and share >= FLOW_OVERSHOOT_SHARE:
                    state = HOT
                    judged_hot += 1
                else:
                    state = FITS
                    judged_fit += 1
            bands.append(
                {
                    "band": band_label(index),
                    "hold_hours": round(hold, 1),
                    "mean_demand": None if mean is None else round(mean),
                    "overshoot_share": None if share is None else round(share, 2),
                    "verdict": state,
                }
            )
        if short_rooms:
            state = SHORT
            text = (
                "Vorlauf reicht nicht überall: "
                + ", ".join(sorted(short_rooms))
                + " wird trotz ganz offenem Ventil oft nicht warm. Heizkurve nicht "
                "flacher stellen; eher Heizkörper prüfen oder die Kurve etwas anheben."
            )
        elif judged_hot and not judged_fit:
            state = HOT
            hot = [item for item in bands if item["verdict"] == HOT]
            worst = min(hot, key=lambda item: item["mean_demand"])
            text = (
                f"Bei {worst['band']} draußen sind die Ventile beim Halten im Mittel "
                f"nur zu {worst['mean_demand']} % offen, und die Räume werden oft "
                "wärmer als eingestellt. Die Heizkurve an der Therme kann "
                "wahrscheinlich eine Stufe flacher."
            )
        elif judged_fit or judged_hot:
            state = FITS
            text = "Die Heizkurve passt: Die Ventile regeln beim Halten im üblichen Bereich."
        else:
            state = UNKNOWN
            text = (
                "Noch zu wenig Daten aus kalten Tagen. Die Auswertung braucht etwa "
                "einen Tag Komfortzeit unter 10 °C draußen."
            )
        return {"state": state, "text": text, "bands": bands, "short_rooms": sorted(short_rooms)}

    def as_dict(self) -> dict:
        return {"rooms": self.rooms, "day": self.day}

    @classmethod
    def from_dict(cls, data: object) -> FlowStats:
        result = cls()
        if not isinstance(data, dict):
            return result
        rooms = data.get("rooms")
        if isinstance(rooms, dict):
            for room, bands in rooms.items():
                if (
                    isinstance(room, str)
                    and isinstance(bands, list)
                    and len(bands) == len(BANDS) + 1
                    and all(
                        isinstance(item, list)
                        and len(item) == 5
                        and all(
                            isinstance(value, (int, float)) and math.isfinite(value)
                            for value in item
                        )
                        for item in bands
                    )
                ):
                    result.rooms[room] = [[float(value) for value in item] for item in bands]
        day = data.get("day")
        result.day = day if isinstance(day, str) else None
        return result


# --- Balance point -------------------------------------------------------------

# Days with less full-load heating (all rooms) than this are no heating day.
BALANCE_MIN_HOURS = 0.5
BALANCE_MIN_DAYS = 10
BALANCE_MIN_SPREAD = 3.0
BALANCE_MIN_R2 = 0.5
BALANCE_RANGE = (8.0, 22.0)
# A learned limit this far from the set one is worth a suggestion.
BALANCE_SUGGEST_DIFFERENCE = 1.0


def balance_point(days: list[tuple[float, float]]) -> dict | None:
    """Fit (daily mean outdoor, full-load hours of all rooms) of heating days
    to a line; where it reaches zero the house needs no heat."""
    points = [(outdoor, hours) for outdoor, hours in days if hours >= BALANCE_MIN_HOURS]
    if len(points) < BALANCE_MIN_DAYS:
        return None
    temperatures = [point[0] for point in points]
    if max(temperatures) - min(temperatures) < BALANCE_MIN_SPREAD:
        return None
    count = len(points)
    mean_x = sum(temperatures) / count
    mean_y = sum(point[1] for point in points) / count
    sxx = sum((x - mean_x) ** 2 for x in temperatures)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in points)
    syy = sum((y - mean_y) ** 2 for _x, y in points)
    if sxx <= 0 or syy <= 0:
        return None
    slope = sxy / sxx
    if slope >= 0:
        return None
    intercept = mean_y - slope * mean_x
    r2 = (sxy * sxy) / (sxx * syy)
    point = -intercept / slope
    if r2 < BALANCE_MIN_R2 or not BALANCE_RANGE[0] <= point <= BALANCE_RANGE[1]:
        return None
    return {
        "balance_point": round(point * 2) / 2,
        "raw": round(point, 2),
        "hours_per_kelvin": round(-slope, 2),
        "r2": round(r2, 2),
        "days": count,
    }


# --- Week ahead -----------------------------------------------------------------

# As the heat meter: degree days count below this, against 20 °C inside.
DEGREE_LIMIT = 15.0
DEGREE_INDOOR = 20.0
# The range widens with the forecast's distance.
WEEK_SPREAD_BASE = 0.1
WEEK_SPREAD_PER_DAY = 0.04


@dataclass(frozen=True, slots=True)
class RoomRate:
    name: str
    hours_per_degree_day: float
    power_kw: float
    heating_limit: float | None


def week_ahead(
    forecast: list[tuple[date, float]], rooms: list[RoomRate], price_ct: float
) -> dict:
    """Expected heating per forecast day (mean outdoor °C)."""
    days = []
    total_hours = total_kwh = low = high = 0.0
    for offset, (day, outdoor) in enumerate(forecast):
        degree = max(0.0, DEGREE_INDOOR - outdoor) if outdoor < DEGREE_LIMIT else 0.0
        hours = kwh = 0.0
        for room in rooms:
            if room.heating_limit is not None and outdoor >= room.heating_limit:
                continue
            room_hours = room.hours_per_degree_day * degree
            hours += room_hours
            kwh += room_hours * room.power_kw
        spread = WEEK_SPREAD_BASE + WEEK_SPREAD_PER_DAY * offset
        days.append(
            {
                "date": day.isoformat(),
                "outdoor": round(outdoor, 1),
                "hours": round(hours, 1),
                "kwh": round(kwh, 1),
                "euro": round(kwh * price_ct / 100, 2),
            }
        )
        total_hours += hours
        total_kwh += kwh
        low += kwh * (1 - spread)
        high += kwh * (1 + spread)
    return {
        "days": days,
        "hours": round(total_hours, 1),
        "kwh": round(total_kwh, 1),
        "kwh_low": round(low, 1),
        "kwh_high": round(high, 1),
        "euro": round(total_kwh * price_ct / 100, 2),
        "price_ct": price_ct,
        "rooms": len(rooms),
    }


def week_ahead_text(result: dict) -> str:
    """One sentence for the report and Assist."""
    if not result["days"]:
        return "Keine Vorhersage für die nächsten Tage."
    text = (
        f"Nächste {len(result['days'])} Tage: etwa {result['kwh']:.0f} kWh Wärme "
        f"({result['kwh_low']:.0f} bis {result['kwh_high']:.0f} kWh)"
    )
    if result["price_ct"] > 0:
        text += f", ca. {result['euro']:.0f} €"
    coldest = min(result["days"], key=lambda item: item["outdoor"])
    outdoor = f"{coldest['outdoor']:.1f}".replace(".", ",").replace("-", "−")
    text += (
        f". Am meisten am {date.fromisoformat(coldest['date']):%d.%m.} "
        f"(Ø {outdoor} °C)."
    )
    return text


# --- Heating phases -------------------------------------------------------------

# The house asks for heat while any room's demand is at least this.
CYCLE_DEMAND = 20.0
CYCLE_KEEP_DAYS = 7
# Short phases and many of them per heating hour: the boiler likely cycles.
CYCLE_SHORT_MINUTES = 20.0
CYCLE_MANY_PER_HOUR = 1.5
CYCLE_MIN_PHASES = 12


@dataclass(slots=True)
class CycleWatch:
    """Heating phases of the house per local day: [phases, minutes asking]."""

    days: dict[str, list[float]] = field(default_factory=dict)
    asking: bool = False

    def observe(self, today: date, asking: bool, minutes: float) -> None:
        item = self.days.setdefault(today.isoformat(), [0.0, 0.0])
        if asking and not self.asking:
            item[0] += 1
        if asking and 0 < minutes <= 15:
            item[1] = round(item[1] + minutes, 2)
        self.asking = asking
        for key in sorted(self.days)[:-CYCLE_KEEP_DAYS]:
            del self.days[key]

    def verdict(self, today: date) -> dict:
        phases = minutes = 0.0
        for key, (count, asked) in self.days.items():
            if key < today.isoformat():
                phases += count
                minutes += asked
        mean = minutes / phases if phases else None
        per_hour = phases / (minutes / 60) if minutes >= 60 else None
        today_item = self.days.get(today.isoformat(), [0.0, 0.0])
        cycling = (
            phases >= CYCLE_MIN_PHASES
            and mean is not None
            and mean < CYCLE_SHORT_MINUTES
            and per_hour is not None
            and per_hour >= CYCLE_MANY_PER_HOUR
        )
        if phases < CYCLE_MIN_PHASES:
            text = "Noch zu wenig Heizphasen für eine Aussage."
        elif cycling:
            text = (
                f"Die Heizung läuft in vielen kurzen Phasen (im Mittel {mean:.0f} min). "
                "„Heizen bündeln“ einschalten lässt die Räume gemeinsam heizen."
            )
        else:
            text = (
                f"Heizphasen dauern im Mittel {mean:.0f} min, kein Hinweis auf "
                "ständiges An und Aus."
            )
        return {
            "today": int(today_item[0]),
            "phases": int(phases),
            "mean_minutes": None if mean is None else round(mean),
            "per_hour": None if per_hour is None else round(per_hour, 2),
            "cycling": cycling,
            "text": text,
        }

    def as_dict(self) -> dict:
        return {"days": self.days}

    @classmethod
    def from_dict(cls, data: object) -> CycleWatch:
        result = cls()
        days = data.get("days") if isinstance(data, dict) else None
        if isinstance(days, dict):
            for key, value in days.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, list)
                    and len(value) == 2
                    and all(isinstance(item, (int, float)) for item in value)
                ):
                    result.days[key] = [float(item) for item in value]
        return result
