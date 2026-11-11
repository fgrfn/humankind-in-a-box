from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np

from hiab.config import Settings
from hiab.packs import load_packs
from hiab.sim.engine import DAYS_PER_YEAR, World
from hiab.sim.rng import RandomStreams
from hiab.worker import simulate


def test_streams_are_independent_and_restorable() -> None:
    streams = RandomStreams(5)
    first = [int(streams.get("a").integers(0, 1000)) for _ in range(5)]
    other = RandomStreams(5)
    other.get("b").integers(0, 1000, size=100)  # using another stream must not shift "a"
    assert [int(other.get("a").integers(0, 1000)) for _ in range(5)] == first

    saved = json.loads(json.dumps(streams.dump()))
    expected = [int(streams.get("a").integers(0, 1000)) for _ in range(5)]
    restored = RandomStreams(5)
    restored.load(saved)
    assert [int(restored.get("a").integers(0, 1000)) for _ in range(5)] == expected


def test_world_generation_respects_land_share() -> None:
    packs = load_packs(["base"])
    world = World.create(1, 99, packs, 64, 64, 45)
    land = 100 * int((~world.map.water).sum()) / world.map.water.size
    assert 40 <= land <= 50
    assert world.map.river.any()
    assert (world.map.deposit >= 0).any()
    assert not (world.map.deposit[world.map.water] >= 0).any()


def test_stocks_stay_within_capacity() -> None:
    packs = load_packs(["base"])
    world = World.create(1, 4, packs, 48, 48, 45)
    for _ in range(30 * DAYS_PER_YEAR):
        world.step()
    for resource in world.stock_ids:
        assert (world.stocks[resource] >= 0).all()
        assert (world.stocks[resource] <= world.capacity[resource]).all()
    assert any(not np.array_equal(world.stocks[r], world.capacity[r]) for r in world.stock_ids), (
        "natural events should move stocks away from their capacity"
    )


def test_every_fired_rule_has_a_logged_decision(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    simulate(path, settings, 20, 21)
    conn = sqlite3.connect(path)
    try:
        events = conn.execute(
            "SELECT tick, region, data FROM events WHERE region IS NOT NULL"
        ).fetchall()
        assert events
        for tick, region, data in events:
            rule = json.loads(data)["rule"]
            row = conn.execute(
                "SELECT chance, roll, fired FROM world_log "
                "WHERE tick = ? AND rule = ? AND scope_id = ?",
                (tick, rule, region),
            ).fetchone()
            assert row is not None
            chance, roll, fired = row
            assert fired == 1 and roll < chance
        checked, fired_count = conn.execute(
            "SELECT SUM(CASE WHEN key LIKE 'rule.%.checked' THEN value END), "
            "SUM(CASE WHEN key LIKE 'rule.%.fired' THEN value END) FROM metrics"
        ).fetchone()
        assert checked > fired_count > 0
    finally:
        conn.close()
