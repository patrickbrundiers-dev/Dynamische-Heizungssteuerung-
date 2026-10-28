"""Pick the Home Assistant test harness for CI.

``harness stable`` prints the newest pytest-homeassistant-custom-component
that pins a released Home Assistant (what Patrick installs), ``harness beta``
the newest one at all, which during a beta week pins the beta.

``requirements conversation`` prints the Python packages the installed Home
Assistant needs for that component; the test harness does not bring them.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

HARNESS = "pytest-homeassistant-custom-component"
STABLE_PIN = re.compile(r"^homeassistant==(\d+\.\d+\.\d+)$")


def _pypi(path: str) -> dict:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{path}/json", timeout=30) as reply:
        return json.load(reply)


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version))


def harness(channel: str) -> str:
    releases = sorted(_pypi(HARNESS)["releases"], key=_version_key, reverse=True)
    if channel == "beta":
        return f"{HARNESS}=={releases[0]}"
    for version in releases[:60]:
        pins = _pypi(f"{HARNESS}/{version}")["info"]["requires_dist"] or []
        if any(STABLE_PIN.match(pin.replace(" ", "")) for pin in pins):
            return f"{HARNESS}=={version}"
    raise SystemExit("No harness for a released Home Assistant found")


def requirements(component: str) -> str:
    import homeassistant.components as components

    manifest = Path(components.__path__[0]) / component / "manifest.json"
    return " ".join(json.loads(manifest.read_text())["requirements"])


if __name__ == "__main__":
    command, argument = sys.argv[1:3]
    print(harness(argument) if command == "harness" else requirements(argument))
