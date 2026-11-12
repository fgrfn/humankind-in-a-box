"""Speed control: the one thing the interface may change.

The API never writes to the database; the worker is its only writer. So the two
talk through two small files in the data directory:

- ``control.json`` is written by the API (what is wanted) and read by the worker.
- ``pace.json`` is written by the worker (what is actually happening).

Speed changes how fast the world is computed, never what happens in it, so
nothing of this belongs in the world's database.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SPEEDS = (1, 5, 25, 0)  # times the configured pace; 0 means as fast as the machine allows


@dataclass(frozen=True, slots=True)
class Control:
    paused: bool = False
    speed: int = 1
    until_year: int | None = None  # back to normal speed once the world reaches this year

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)  # readers see the old file or the new one, never half


def read_control(data_dir: Path) -> Control:
    """What is wanted. A missing or broken file means: run normally."""
    raw = _read(data_dir / "control.json")
    speed = raw.get("speed", 1)
    until = raw.get("until_year")
    return Control(
        paused=raw.get("paused") is True,
        speed=speed if speed in SPEEDS else 1,
        until_year=until if isinstance(until, int) and until > 0 else None,
    )


def write_control(data_dir: Path, control: Control) -> None:
    _write(data_dir / "control.json", control.as_dict())


def read_pace(data_dir: Path) -> dict[str, Any]:
    """What the worker last reported about itself; empty when no worker has run."""
    return _read(data_dir / "pace.json")


def write_pace(data_dir: Path, year: int, days_per_minute: float, running: bool) -> None:
    _write(
        data_dir / "pace.json",
        {"year": year, "days_per_minute": round(days_per_minute, 1), "running": running},
    )
