"""The core promise: one seed, one history."""

from __future__ import annotations

from pathlib import Path

import pytest

from hiab.config import Settings
from hiab.db.store import table_digests
from hiab.worker import simulate


def run(path: Path, settings: Settings, years: int, seed: int) -> dict[str, tuple[int, str]]:
    simulate(path, settings, years, seed)
    return table_digests(path)


def test_same_seed_same_world(tmp_path: Path, settings: Settings) -> None:
    first = run(tmp_path / "a.sqlite", settings, 40, 7)
    second = run(tmp_path / "b.sqlite", settings, 40, 7)
    assert first == second


def test_other_seed_other_world(tmp_path: Path, settings: Settings) -> None:
    first = run(tmp_path / "a.sqlite", settings, 40, 7)
    second = run(tmp_path / "b.sqlite", settings, 40, 8)
    assert first["tiles"] != second["tiles"]
    assert first["events"] != second["events"]


def test_save_load_continue_equals_straight_run(tmp_path: Path, settings: Settings) -> None:
    straight = run(tmp_path / "straight.sqlite", settings, 60, 11)
    resumed_path = tmp_path / "resumed.sqlite"
    # Stops in the middle of a rule year and of the log retention window on purpose.
    for years in (13, 30, 17):
        simulate(resumed_path, settings, years, 11)
    assert table_digests(resumed_path) == straight


def test_a_run_fills_chronicle_log_and_metrics(tmp_path: Path, settings: Settings) -> None:
    digests = run(tmp_path / "a.sqlite", settings, 30, 3)
    for table in ("events", "world_log", "metrics", "tiles", "tile_stocks", "pack_versions"):
        assert digests[table][0] > 0, table


@pytest.mark.slow
def test_500_years_twice(tmp_path: Path, settings: Settings) -> None:
    assert run(tmp_path / "a.sqlite", settings, 500, 42) == run(
        tmp_path / "b.sqlite", settings, 500, 42
    )
