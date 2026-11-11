"""SQLite persistence. The worker is the only writer.

Nothing in here stores wall-clock time: two runs with the same seed must
produce the same table contents.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np

from hiab.logging_setup import get_logger
from hiab.packs import BIOMES, PackSet
from hiab.sim.engine import DAYS_PER_YEAR, World
from hiab.sim.worldgen import WorldMap

log = get_logger("store")

MIGRATIONS: list[str] = [
    """
    CREATE TABLE worlds (
        id INTEGER PRIMARY KEY,
        seed INTEGER NOT NULL,
        parent_world INTEGER,
        fork_tick INTEGER,
        tick INTEGER NOT NULL,
        status TEXT NOT NULL,
        width INTEGER NOT NULL,
        height INTEGER NOT NULL,
        deposit_ids TEXT NOT NULL
    );
    CREATE TABLE world_state (
        world_id INTEGER PRIMARY KEY REFERENCES worlds(id),
        state TEXT NOT NULL
    );
    CREATE TABLE tiles (
        world_id INTEGER NOT NULL,
        y INTEGER NOT NULL,
        x INTEGER NOT NULL,
        elevation INTEGER NOT NULL,
        biome TEXT NOT NULL,
        water INTEGER NOT NULL,
        river INTEGER NOT NULL,
        temperature INTEGER NOT NULL,
        moisture INTEGER NOT NULL,
        region INTEGER NOT NULL,
        deposit TEXT,
        PRIMARY KEY (world_id, y, x)
    ) WITHOUT ROWID;
    CREATE TABLE tile_stocks (
        world_id INTEGER NOT NULL,
        resource TEXT NOT NULL,
        data BLOB NOT NULL,
        PRIMARY KEY (world_id, resource)
    ) WITHOUT ROWID;
    CREATE TABLE events (
        world_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        type TEXT NOT NULL,
        region INTEGER,
        importance INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (world_id, seq)
    ) WITHOUT ROWID;
    CREATE INDEX events_by_tick ON events (world_id, tick);
    CREATE INDEX events_by_type ON events (world_id, type, tick);
    CREATE TABLE world_log (
        world_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        rule TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_id INTEGER NOT NULL,
        factors TEXT NOT NULL,
        chance REAL,
        roll REAL NOT NULL,
        fired INTEGER,
        PRIMARY KEY (world_id, seq)
    ) WITHOUT ROWID;
    CREATE INDEX world_log_by_tick ON world_log (world_id, tick);
    CREATE TABLE metrics (
        world_id INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        key TEXT NOT NULL,
        scope_type TEXT NOT NULL,
        scope_id INTEGER NOT NULL,
        value REAL NOT NULL,
        PRIMARY KEY (world_id, key, scope_type, scope_id, tick)
    ) WITHOUT ROWID;
    CREATE TABLE pack_versions (
        world_id INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        pack TEXT NOT NULL,
        version TEXT NOT NULL,
        checksum TEXT NOT NULL,
        PRIMARY KEY (world_id, tick, pack)
    ) WITHOUT ROWID;
    CREATE TABLE settings_log (
        world_id INTEGER NOT NULL,
        seq INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        key TEXT NOT NULL,
        old TEXT,
        new TEXT,
        PRIMARY KEY (world_id, seq)
    ) WITHOUT ROWID;
    """,
]

# Tables compared by ``verify``, each with the order that makes rows comparable.
CONTENT_TABLES: dict[str, str] = {
    "worlds": "id",
    "world_state": "world_id",
    "tiles": "world_id, y, x",
    "tile_stocks": "world_id, resource",
    "events": "world_id, seq",
    "world_log": "world_id, seq",
    "metrics": "world_id, key, scope_type, scope_id, tick",
    "pack_versions": "world_id, tick, pack",
    "settings_log": "world_id, seq",
}


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def _migrate(self) -> None:
        current = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for version in range(current, len(MIGRATIONS)):
            with self.conn:
                self.conn.executescript(MIGRATIONS[version])
                self.conn.execute(f"PRAGMA user_version = {version + 1}")
            log.info("database migrated", extra={"schema_version": version + 1})

    # ---- worlds ---------------------------------------------------------

    def active_world_id(self) -> int | None:
        row = self.conn.execute(
            "SELECT id FROM worlds WHERE status = 'active' ORDER BY id LIMIT 1"
        ).fetchone()
        return None if row is None else int(row[0])

    def next_world_id(self) -> int:
        return int(self.conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM worlds").fetchone()[0])

    def insert_world(self, world: World) -> None:
        world_map = world.map
        rows = [
            (
                world.id,
                y,
                x,
                int(world_map.elevation[y, x]),
                BIOMES[int(world_map.biome[y, x])],
                int(world_map.water[y, x]),
                int(world_map.river[y, x]),
                int(world_map.temperature[y, x]),
                int(world_map.moisture[y, x]),
                int(world_map.region[y, x]),
                None
                if world_map.deposit[y, x] < 0
                else world_map.deposit_ids[int(world_map.deposit[y, x])],
            )
            for y in range(world_map.height)
            for x in range(world_map.width)
        ]
        with self.conn:
            self.conn.execute(
                "INSERT INTO worlds VALUES (?, ?, NULL, NULL, 0, 'active', ?, ?, ?)",
                (
                    world.id,
                    world.seed,
                    world_map.width,
                    world_map.height,
                    _json(world_map.deposit_ids),
                ),
            )
            self.conn.executemany("INSERT INTO tiles VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            self.conn.executemany(
                "INSERT INTO pack_versions VALUES (?, 0, ?, ?, ?)",
                [
                    (world.id, pack, world.packs.versions[pack], world.packs.checksum)
                    for pack in sorted(world.packs.versions)
                ],
            )
        self.save(world)

    def record_packs(self, world: World) -> bool:
        """Note the pack versions if they differ from the last recorded ones."""
        row = self.conn.execute(
            "SELECT checksum FROM pack_versions WHERE world_id = ? ORDER BY tick DESC LIMIT 1",
            (world.id,),
        ).fetchone()
        if row is not None and row[0] == world.packs.checksum:
            return False
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO pack_versions VALUES (?, ?, ?, ?, ?)",
                [
                    (world.id, world.tick, pack, world.packs.versions[pack], world.packs.checksum)
                    for pack in sorted(world.packs.versions)
                ],
            )
        log.info(
            "pack versions changed",
            extra={"world_id": world.id, "tick": world.tick, "versions": world.packs.versions},
        )
        return True

    def save(self, world: World, world_log_years: int = 50) -> None:
        """Write buffered rows and the full state in one transaction."""
        started = time.perf_counter()
        buffers = world.buffers
        with self.conn:
            self.conn.executemany(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
                [
                    (world.id, seq, tick, etype, region, importance, _json(data))
                    for seq, tick, etype, region, importance, data in buffers.events
                ],
            )
            self.conn.executemany(
                "INSERT INTO world_log VALUES (?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        world.id,
                        *row[:5],
                        _json(row[5]),
                        row[6],
                        row[7],
                        None if row[8] is None else int(row[8]),
                    )
                    for row in buffers.world_log
                ],
            )
            self.conn.executemany(
                "INSERT INTO metrics VALUES (?,?,?,?,?,?)",
                [
                    (world.id, tick, key, scope_type, scope_id, value)
                    for tick, key, scope_type, scope_id, value in buffers.metrics
                ],
            )
            self.conn.execute(
                "DELETE FROM world_log WHERE world_id = ? AND tick < ?",
                (world.id, world.tick - world_log_years * DAYS_PER_YEAR),
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO tile_stocks VALUES (?,?,?)",
                [
                    (world.id, resource, world.stocks[resource].astype("<i4").tobytes())
                    for resource in world.stock_ids
                ],
            )
            self.conn.execute(
                "INSERT OR REPLACE INTO world_state VALUES (?, ?)",
                (world.id, _json(world.dump_state())),
            )
            self.conn.execute("UPDATE worlds SET tick = ? WHERE id = ?", (world.tick, world.id))
        log.debug(
            "world saved",
            extra={
                "world_id": world.id,
                "tick": world.tick,
                "events": len(buffers.events),
                "decisions": len(buffers.world_log),
                "ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        buffers.clear()

    def load_world(
        self, world_id: int, packs: PackSet, world_log_level: str = "decisions"
    ) -> World:
        row = self.conn.execute(
            "SELECT seed, width, height, deposit_ids FROM worlds WHERE id = ?", (world_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"World {world_id} does not exist in {self.path}")
        seed, width, height, deposit_json = row
        deposit_ids: list[str] = json.loads(deposit_json)
        shape = (height, width)
        elevation = np.zeros(shape, dtype=np.int32)
        water = np.zeros(shape, dtype=bool)
        river = np.zeros(shape, dtype=bool)
        temperature = np.zeros(shape, dtype=np.int32)
        moisture = np.zeros(shape, dtype=np.int32)
        biome = np.zeros(shape, dtype=np.int8)
        region = np.zeros(shape, dtype=np.int16)
        deposit = np.full(shape, -1, dtype=np.int8)
        cursor = self.conn.execute(
            "SELECT y, x, elevation, biome, water, river, temperature, moisture, region, deposit "
            "FROM tiles WHERE world_id = ? ORDER BY y, x",
            (world_id,),
        )
        for y, x, elev, biome_name, is_water, is_river, temp, moist, reg, dep in cursor:
            elevation[y, x] = elev
            biome[y, x] = BIOMES.index(biome_name)
            water[y, x] = bool(is_water)
            river[y, x] = bool(is_river)
            temperature[y, x] = temp
            moisture[y, x] = moist
            region[y, x] = reg
            if dep is not None:
                deposit[y, x] = deposit_ids.index(dep)
        world_map = WorldMap(
            width,
            height,
            elevation,
            water,
            river,
            temperature,
            moisture,
            biome,
            region,
            deposit,
            deposit_ids,
        )
        world = World(world_id, seed, packs, world_map, world_log_level)
        for resource, blob in self.conn.execute(
            "SELECT resource, data FROM tile_stocks WHERE world_id = ? ORDER BY resource",
            (world_id,),
        ):
            if resource in world.stocks:
                world.stocks[resource] = (
                    np.frombuffer(blob, dtype="<i4").reshape(shape).astype(np.int32)
                )
        state = self.conn.execute(
            "SELECT state FROM world_state WHERE world_id = ?", (world_id,)
        ).fetchone()
        world.load_state(json.loads(state[0]))
        return world


def table_digests(path: Path) -> dict[str, tuple[int, str]]:
    """Row count and content hash per table, independent of the file layout."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        out: dict[str, tuple[int, str]] = {}
        for table, order in CONTENT_TABLES.items():
            digest = hashlib.sha256()
            count = 0
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order}"):
                digest.update(repr(row).encode("utf-8"))
                count += 1
            out[table] = (count, digest.hexdigest())
        return out
    finally:
        conn.close()
