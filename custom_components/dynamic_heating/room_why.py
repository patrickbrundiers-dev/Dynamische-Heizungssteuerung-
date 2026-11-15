"""Why the room heats (or not) and the log of its decisions (0.21.0).

Ideas from Raumklima: a check page that lists every precondition of heating
with its value, and a list of the room's decisions with the reason and the
measured values. Part of the room coordinator (``DynamicHeatingCoordinator``).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import DECISIONS_DAYS, DECISIONS_KEEP, QUICK_AUTO, QUICK_LABELS

# Area of a decision by its mode; quick_* modes are "Bedienung".
_AREAS: dict[str, str] = {
    "window": "Fenster",
    "away": "Anwesenheit",
    "away_reduced": "Anwesenheit",
    "long_absence": "Anwesenheit",
    "homecoming": "Anwesenheit",
    "departure_stop": "Anwesenheit",
    "comfort": "Zeitplan",
    "eco": "Zeitplan",
    "preheat": "Zeitplan",
    "early_stop": "Zeitplan",
    "force_comfort": "Zeitplan",
    "force_eco": "Zeitplan",
    "heating_limit": "Wetter",
    "outdoor_warm": "Wetter",
    "season_off": "Wetter",
    "solar": "Wetter",
    "solar_ahead": "Wetter",
    "frost": "Wetter",
    "supply_wait": "Therme",
    "maintenance": "Ventile",
    "learn_run": "Ventile",
    "boost": "Bedienung",
    "waiting": "Störung",
}
AREAS: tuple[str, ...] = (
    "Zeitplan", "Anwesenheit", "Fenster", "Wetter", "Therme", "Ventile",
    "Bedienung", "Hinweis", "Störung",
)


def decision_area(mode: str | None) -> str:
    """The area a decision belongs to (for the filter)."""
    if not mode:
        return "Hinweis"
    if mode.startswith("quick_"):
        return "Bedienung"
    return _AREAS.get(mode, "Zeitplan")


def _number(value: Any, digits: int = 1) -> str:
    try:
        return f"{float(value):.{digits}f}".replace(".", ",").replace("-", "−")
    except (TypeError, ValueError):
        return "?"


def _time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = dt_util.parse_datetime(value)
    return None if parsed is None else dt_util.as_local(parsed).strftime("%H:%M")


def why_checks(data: dict[str, Any], enabled: bool) -> dict[str, Any]:
    """Every precondition of heating with its value, from a cycle's result.

    Each check has ``ok``: True (does not stop heating), False (stops or
    lowers it) or None (information). The verdict names the first check that
    stops heating, else says why the room heats or holds.
    """
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    room = data.get("room_temperature")
    target = data.get("target_temperature")
    mode = data.get("mode")
    add("Regelung", enabled, "eingeschaltet" if enabled else "ausgeschaltet – Ventile werden nicht gestellt")
    if room is None:
        add("Raumfühler", False, "liefert keine Werte")
    elif data.get("room_temperature_source") == "thermostats":
        add("Raumfühler", False, f"ausgefallen – Ersatzwert {_number(room)} °C aus den Ventilen")
    else:
        add("Raumfühler", True, f"{_number(room)} °C")
    if mode == "waiting":
        add("Daten", False, str(data.get("status") or "es fehlt ein Wert"))
    next_event = _time(data.get("next_event"))
    if data.get("schedule_active"):
        add(
            "Zeitplan",
            True,
            f"Komfortzeit {_number(data.get('comfort_temperature'))} °C"
            + (f" bis {next_event} Uhr" if next_event else ""),
        )
    else:
        add(
            "Zeitplan",
            None,
            f"Absenkzeit {_number(data.get('eco_temperature'))} °C"
            + (f", Komfort ab {next_event} Uhr" if next_event else ""),
        )
    contacts = data.get("contact_problems") or {}
    if data.get("window_open"):
        add("Fenster", False, "offen – Heizung pausiert")
    elif data.get("window_contact_open"):
        add("Fenster", None, "gerade geöffnet – Pause beginnt nach der Verzögerung")
    else:
        add("Fenster", True, "zu")
    if contacts:
        add("Fensterkontakte", None, "; ".join(f"{k}: {v}" for k, v in contacts.items()))
    present = data.get("present")
    presence = str(data.get("presence_status") or "")
    if present is False:
        add("Anwesenheit", False, presence or "niemand da – abgesenkt")
    else:
        add("Anwesenheit", True, presence or "jemand da")
    quick = data.get("quick_mode")
    if quick and quick != QUICK_AUTO:
        until = _time(data.get("quick_until"))
        label = QUICK_LABELS.get(quick, quick)
        add("Betriebsart", None, f"{label}" + (f" bis {until} Uhr" if until else ""))
    else:
        add("Betriebsart", True, "Automatik")
    if data.get("manual_override"):
        add("Handbetrieb", False, "am Ventil verstellt – Regelung pausiert")
    if not data.get("heating_season", True):
        add("Heizsaison", False, "außerhalb der Heizsaison")
    lifted = data.get("heating_limit_lifted")
    basis = data.get("heating_limit_basis")
    if data.get("heating_limit_reached") and not lifted:
        add(
            "Heizgrenze",
            False,
            "erreicht" + (f" (Ø {_number(basis)} °C)" if basis is not None else ""),
        )
    elif lifted == "heat_today":
        add("Heizgrenze", True, "aufgehoben – „Heute heizen“ ist an")
    elif lifted == "cold_snap":
        add(
            "Heizgrenze",
            True,
            f"aufgehoben – Kälteeinbruch (Ø 6 h {_number(data.get('cold_snap_mean'))} °C)",
        )
    else:
        add(
            "Heizgrenze",
            True,
            "nicht erreicht" + (f" (Ø {_number(basis)} °C)" if basis is not None else ""),
        )
    outdoor = data.get("outdoor_temperature")
    if data.get("outdoor_warmer"):
        add("Außentemperatur", False, f"draußen {_number(outdoor)} °C – wärmer als drinnen")
    elif outdoor is not None:
        add("Außentemperatur", True, f"{_number(outdoor)} °C")
    if data.get("frost_night") is not None:
        add("Frostnacht", None, f"{_number(data['frost_night'], 0)} °C erwartet – nur halb abgesenkt")
    if data.get("facade"):
        sun = data.get("sun_on_facade")
        add(
            "Sonne",
            None,
            f"Fassade {data['facade']}: "
            + ("Sonne scheint auf die Wand" if sun else "keine Sonne auf der Wand"),
        )
    if mode == "supply_wait" or data.get("supply_usually_off"):
        add(
            "Zentralheizung",
            False if mode == "supply_wait" else None,
            str(data.get("radiator_status") or "liefert gerade meist keine Wärme (Nachtpause)"),
        )
    elif data.get("radiator_supply") == "cold" and (data.get("heat_demand") or 0) > 0:
        add("Zentralheizung", False, str(data.get("radiator_status") or "Heizkörper bleiben kalt"))
    elif data.get("radiator_status"):
        add("Zentralheizung", True, str(data["radiator_status"]))
    foreign = data.get("foreign_control") or []
    if foreign:
        add(
            "Fremde Automation",
            False,
            ", ".join(str(item.get("name") or item.get("source")) for item in foreign)
            + " stellt die Ventile",
        )
    setpoints = data.get("thermostat_setpoints") or {}
    problems: list[str] = []
    for text in (data.get("valve_divergence") or {}).values():
        problems.append(f"übernimmt den Sollwert nicht ({text})")
    for text in (data.get("valve_own_state") or {}).values():
        problems.append(text)
    if data.get("unavailable_thermostats"):
        problems.append(f"{len(data['unavailable_thermostats'])} nicht erreichbar")
    if problems:
        add("Ventile", False, "; ".join(problems))
    elif setpoints:
        values = sorted({_number(value) for value in setpoints.values()})
        add(
            "Ventile",
            True,
            f"{len(setpoints)} auf {', '.join(values)} °C"
            + (" – ganz offen" if data.get("full_open") else ""),
        )
    elif enabled:
        add("Ventile", None, "keine Sollwerte gesendet")
    demand = data.get("heat_demand")
    if demand is not None:
        add("Wärmebedarf", None, f"{_number(demand, 0)} %")

    blocking = next((check for check in checks if check["ok"] is False), None)
    if room is not None and target is not None:
        gap = float(target) - float(room)
        if gap > 0.2 and blocking is None:
            verdict = (
                f"Heizt: Soll {_number(target)} °C, im Raum {_number(room)} °C – "
                + str(data.get("status") or "")
            ).rstrip(" –")
            heating = True
        elif blocking is not None:
            verdict = f"Heizt nicht: {blocking['name']} – {blocking['detail']}"
            heating = False
        else:
            verdict = (
                f"Heizt gerade nicht: das Soll {_number(target)} °C ist erreicht "
                f"(im Raum {_number(room)} °C)"
            )
            heating = False
    else:
        verdict = (
            f"Heizt nicht: {blocking['name']} – {blocking['detail']}"
            if blocking
            else str(data.get("status") or "Noch keine Entscheidung")
        )
        heating = False
    return {
        "heating": heating,
        "verdict": verdict,
        "status": data.get("status"),
        "checks": checks,
    }


class WhyMixin:
    """The "Warum heizt der Raum (nicht)?" checks and the decision log."""

    def why(self) -> dict[str, Any]:
        return why_checks(self.data or {}, self.enabled)

    def _note_decision(self, entry: dict[str, Any]) -> None:
        now = dt_util.utcnow()
        cutoff = now - timedelta(days=DECISIONS_DAYS)
        kept = [
            item for item in self.decision_log
            if (parsed := dt_util.parse_datetime(item.get("at", ""))) is not None
            and parsed >= cutoff
        ]
        kept.append({"at": now.isoformat(), **entry})
        self.decision_log = kept[-DECISIONS_KEEP:]

    def _record_decision(self, result: dict[str, Any]) -> None:
        """A new entry when the mode, the target or what set it changed."""
        key = (
            result.get("mode"),
            result.get("target_temperature"),
            result.get("last_change_source"),
            bool(result.get("window_open")),
            result.get("present"),
        )
        if key == self._decision_key:
            return
        self._decision_key = key
        self._note_decision(
            {
                "area": decision_area(result.get("mode")),
                "mode": result.get("mode"),
                "text": str(result.get("status") or ""),
                "target": result.get("target_temperature"),
                "room": result.get("room_temperature"),
                "outdoor": result.get("outdoor_temperature"),
                "source": result.get("last_change_source"),
                "valves": dict(result.get("thermostat_setpoints") or {}),
            }
        )

    def _note_message(self, message: str) -> None:
        """Logbook lines (valve fixes, contacts, …) go into the log as hints."""
        area = "Hinweis"
        lowered = message.lower()
        if "fenster" in lowered:
            area = "Fenster"
        elif "ventil" in lowered or "sollwert" in lowered or "thermostat" in lowered:
            area = "Ventile"
        self._note_decision({"area": area, "mode": None, "text": message})

    def decisions(
        self, days: float | None = None, area: str | None = None
    ) -> list[dict[str, Any]]:
        """The room's decisions, newest first, filtered by age and area."""
        now = dt_util.utcnow()
        cutoff = now - timedelta(days=days or DECISIONS_DAYS)
        items: list[dict[str, Any]] = []
        for item in reversed(self.decision_log):
            parsed: datetime | None = dt_util.parse_datetime(item.get("at", ""))
            if parsed is None or parsed < cutoff:
                continue
            if area and item.get("area") != area:
                continue
            items.append(item)
        return items
