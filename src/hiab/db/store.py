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
from hiab.sim.people import Person
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
    """
    CREATE TABLE persons (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        name TEXT NOT NULL,
        sex INTEGER NOT NULL,
        born INTEGER NOT NULL,
        died INTEGER,
        cause TEXT,
        mother INTEGER NOT NULL,
        father INTEGER NOT NULL,
        family INTEGER NOT NULL,
        clan INTEGER NOT NULL,
        partner INTEGER NOT NULL,
        traits TEXT NOT NULL,
        children INTEGER NOT NULL,
        last_birth INTEGER NOT NULL,
        moved INTEGER NOT NULL,
        discoveries INTEGER NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    CREATE INDEX persons_living ON persons (world_id, died, clan);
    CREATE TABLE groups (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        type TEXT NOT NULL,
        name TEXT NOT NULL,
        parent_group INTEGER NOT NULL,
        founded INTEGER NOT NULL,
        dissolved INTEGER,
        y INTEGER NOT NULL,
        x INTEGER NOT NULL,
        settled INTEGER NOT NULL,
        place INTEGER NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    CREATE TABLE discoveries (
        world_id INTEGER NOT NULL,
        group_id INTEGER NOT NULL,
        technology TEXT NOT NULL,
        tick INTEGER NOT NULL,
        discoverer INTEGER NOT NULL,
        how TEXT NOT NULL,
        PRIMARY KEY (world_id, group_id, technology)
    ) WITHOUT ROWID;
    CREATE TABLE places (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        y INTEGER NOT NULL,
        x INTEGER NOT NULL,
        name TEXT NOT NULL,
        founded INTEGER NOT NULL,
        abandoned INTEGER,
        group_id INTEGER NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    CREATE TABLE tile_layers (
        world_id INTEGER NOT NULL,
        layer TEXT NOT NULL,
        data BLOB NOT NULL,
        PRIMARY KEY (world_id, layer)
    ) WITHOUT ROWID;
    """,
    """
    CREATE TABLE buildings (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        place_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        y INTEGER NOT NULL,
        x INTEGER NOT NULL,
        started INTEGER NOT NULL,
        finished INTEGER,
        state TEXT NOT NULL,
        progress INTEGER NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    CREATE INDEX buildings_by_place ON buildings (world_id, place_id);
    """,
    """
    ALTER TABLE persons ADD COLUMN activity TEXT NOT NULL DEFAULT '';
    ALTER TABLE persons ADD COLUMN target_y INTEGER NOT NULL DEFAULT -1;
    ALTER TABLE persons ADD COLUMN target_x INTEGER NOT NULL DEFAULT -1;
    ALTER TABLE persons ADD COLUMN work TEXT NOT NULL DEFAULT '{}';
    """,
    """
    ALTER TABLE discoveries ADD COLUMN lost INTEGER;
    """,
    """
    CREATE TABLE cultures (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        name TEXT NOT NULL,
        parent_culture INTEGER NOT NULL,
        founded INTEGER NOT NULL,
        ended INTEGER,
        origin_group INTEGER NOT NULL,
        sound_rules TEXT NOT NULL,
        words TEXT NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    ALTER TABLE groups ADD COLUMN culture INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE places ADD COLUMN meaning TEXT NOT NULL DEFAULT '';
    """,
    """
    CREATE TABLE trade_links (
        world_id INTEGER NOT NULL,
        group_a INTEGER NOT NULL,
        group_b INTEGER NOT NULL,
        since INTEGER NOT NULL,
        ended INTEGER,
        PRIMARY KEY (world_id, group_a, group_b, since)
    ) WITHOUT ROWID;
    """,
    """
    ALTER TABLE groups ADD COLUMN stores TEXT NOT NULL DEFAULT '{}';
    """,
    """
    CREATE INDEX persons_by_mother ON persons (world_id, mother);
    CREATE INDEX persons_by_father ON persons (world_id, father);
    """,
    """
    CREATE TABLE realms (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        name TEXT NOT NULL,
        founded INTEGER NOT NULL,
        ended INTEGER,
        seat_group INTEGER NOT NULL,
        ruler INTEGER NOT NULL,
        people INTEGER NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    ALTER TABLE groups ADD COLUMN leader INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE groups ADD COLUMN realm INTEGER NOT NULL DEFAULT 0;
    """,
    """
    CREATE TABLE wars (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        attacker INTEGER NOT NULL,
        defender INTEGER NOT NULL,
        started INTEGER NOT NULL,
        ended INTEGER,
        outcome TEXT NOT NULL,
        battles INTEGER NOT NULL,
        fallen INTEGER NOT NULL,
        winner INTEGER NOT NULL,
        field_y INTEGER NOT NULL,
        field_x INTEGER NOT NULL,
        last_battle INTEGER NOT NULL,
        last_fallen INTEGER NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    """,
    """
    ALTER TABLE cultures ADD COLUMN ways TEXT NOT NULL DEFAULT '{}';
    ALTER TABLE persons ADD COLUMN gift TEXT NOT NULL DEFAULT '';
    """,
    """
    ALTER TABLE groups ADD COLUMN sick_until INTEGER NOT NULL DEFAULT 0;
    """,
    """
    CREATE TABLE faiths (
        world_id INTEGER NOT NULL,
        id INTEGER NOT NULL,
        name TEXT NOT NULL,
        aspect TEXT NOT NULL,
        founded INTEGER NOT NULL,
        ended INTEGER,
        origin_group INTEGER NOT NULL,
        people INTEGER NOT NULL,
        PRIMARY KEY (world_id, id)
    ) WITHOUT ROWID;
    ALTER TABLE groups ADD COLUMN faith INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE realms ADD COLUMN land_since INTEGER;
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
    "persons": "world_id, id",
    "groups": "world_id, id",
    "discoveries": "world_id, group_id, technology",
    "places": "world_id, id",
    "tile_layers": "world_id, layer",
    "buildings": "world_id, id",
    "cultures": "world_id, id",
    "trade_links": "world_id, group_a, group_b, since",
    "realms": "world_id, id",
    "wars": "world_id, id",
    "faiths": "world_id, id",
}


class WorldNotFound(Exception):
    """The requested world is not in this database."""


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

    def save(self, world: World, world_log_years: int = 50, event_detail_years: int = 100) -> None:
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
            # Everyday events (births, deaths, wanderings) are kept in detail only for a
            # while. Their counts live on in the metrics, the people in the persons table.
            self.conn.execute(
                "DELETE FROM events WHERE world_id = ? AND importance = 1 AND tick < ?",
                (world.id, world.tick - event_detail_years * DAYS_PER_YEAR),
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO tile_stocks VALUES (?,?,?)",
                [
                    (world.id, resource, world.stocks[resource].astype("<i4").tobytes())
                    for resource in world.stock_ids
                ],
            )
            self._save_society(world)
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

    def _save_society(self, world: World) -> None:
        society = world.society
        if society is None:
            return
        person_rows = []
        for person_id in sorted(society.dirty_persons):
            person = society.persons.get(person_id) or society.dead[person_id]
            person_rows.append(
                (
                    world.id,
                    person.id,
                    person.name,
                    person.sex,
                    person.born,
                    person.died,
                    person.cause,
                    person.mother,
                    person.father,
                    person.family,
                    person.clan,
                    person.partner,
                    _json(person.traits),
                    person.children,
                    person.last_birth,
                    person.moved,
                    person.discoveries,
                    person.activity,
                    person.target_y,
                    person.target_x,
                    _json(dict(sorted(person.work.items()))),
                    person.gift,
                )
            )
        self.conn.executemany(
            "INSERT OR REPLACE INTO persons VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            person_rows,
        )
        clan_rows = []
        for clan_id in sorted(society.dirty_clans | set(society.retired)):
            clan = society.clans.get(clan_id) or society.retired[clan_id]
            clan_rows.append(
                (
                    world.id,
                    clan.id,
                    "settlement" if clan.settled else "clan",
                    clan.name,
                    clan.parent,
                    clan.founded,
                    clan.dissolved,
                    clan.y,
                    clan.x,
                    int(clan.settled),
                    clan.place,
                    clan.culture,
                    _json(
                        {
                            "food": clan.food,
                            "food_room": 0
                            if clan.id not in society.clans
                            else society.monthly_need(clan) * society.effects(clan)[2],
                            "room": 0 if clan.id not in society.clans else society.room(clan),
                            "goods": dict(sorted(clan.stores.items())),
                            "last_year": dict(sorted(clan.last_flows.items())),
                        }
                    ),
                    clan.leader,
                    clan.realm,
                    clan.sick_until,
                    clan.faith,
                )
            )
        self.conn.executemany(
            "INSERT OR REPLACE INTO trade_links VALUES (?,?,?,?,NULL)",
            [(world.id, *link) for link in society.new_links],
        )
        self.conn.executemany(
            "UPDATE trade_links SET ended = ? "
            "WHERE world_id = ? AND group_a = ? AND group_b = ? AND ended IS NULL AND since <= ?",
            [(tick, world.id, a, b, tick) for a, b, tick in society.ended_links],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO cultures VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    world.id,
                    culture.id,
                    culture.name,
                    culture.parent,
                    culture.founded,
                    culture.ended,
                    culture.origin,
                    _json(culture.language),
                    _json(dict(sorted(culture.words.items()))),
                    _json(dict(sorted(culture.ways.items()))),
                )
                for culture in (society.cultures[cid] for cid in sorted(society.dirty_cultures))
            ],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO groups VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", clan_rows
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO faiths VALUES (?,?,?,?,?,?,?,?)",
            [
                (world.id, f.id, f.name, f.aspect, f.founded, f.ended, f.origin, f.people)
                for f in (society.faiths[fid] for fid in sorted(society.dirty_faiths))
            ],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO wars VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    world.id,
                    war.id,
                    war.attacker,
                    war.defender,
                    war.started,
                    war.ended,
                    war.outcome,
                    war.battles,
                    war.fallen,
                    war.winner,
                    war.field_y,
                    war.field_x,
                    war.last_battle,
                    war.last_fallen,
                )
                for war in (society.wars[wid] for wid in sorted(society.dirty_wars))
            ],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO realms VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    world.id,
                    realm.id,
                    realm.name,
                    realm.founded,
                    realm.ended,
                    realm.seat,
                    realm.ruler,
                    realm.people,
                    realm.land_since,
                )
                for realm in (society.realms[rid] for rid in sorted(society.dirty_realms))
            ],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO discoveries VALUES (?,?,?,?,?,?,NULL)",
            [(world.id, *row) for row in society.new_discoveries],
        )
        # Lost knowledge stays on record. Knowledge found again after the loss
        # has a later tick and is left alone.
        self.conn.executemany(
            "UPDATE discoveries SET lost = ? "
            "WHERE world_id = ? AND group_id = ? AND technology = ? AND tick <= ?",
            [
                (tick, world.id, clan_id, tech_id, tick)
                for clan_id, tech_id, tick in society.forgotten
            ],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO places VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    world.id,
                    place["id"],
                    place["y"],
                    place["x"],
                    place["name"],
                    place["founded"],
                    place["abandoned"],
                    place["group"],
                    place.get("meaning", ""),
                )
                for place in (society.places[pid] for pid in sorted(society.dirty_places))
            ],
        )
        self.conn.executemany(
            "DELETE FROM buildings WHERE world_id = ? AND id = ?",
            [(world.id, building_id) for building_id in sorted(society.vanished)],
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO buildings VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    world.id,
                    building["id"],
                    place_id,
                    building["type"],
                    building["y"],
                    building["x"],
                    building["started"],
                    building["finished"],
                    building["state"],
                    building["progress"],
                )
                for place_id in sorted(society.dirty_places)
                for building in society.places[place_id]["buildings"]
            ],
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO tile_layers VALUES (?, 'steps', ?)",
            (world.id, society.steps.astype("<i4").tobytes()),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO tile_layers VALUES (?, 'territory', ?)",
            (world.id, society.territory.astype("<i4").tobytes()),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO tile_layers VALUES (?, 'land_people', ?)",
            (world.id, society.land_people.astype("<i4").tobytes()),
        )
        society.clear_dirty()

    def load_world(
        self, world_id: int, packs: PackSet, world_log_level: str = "decisions"
    ) -> World:
        row = self.conn.execute(
            "SELECT seed, width, height, deposit_ids FROM worlds WHERE id = ?", (world_id,)
        ).fetchone()
        if row is None:
            raise WorldNotFound(f"World {world_id} does not exist in {self.path}")
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
        loaded = json.loads(state[0])
        world.load_state(loaded)
        if world.society is not None and loaded.get("society") is not None:
            persons = [
                Person(
                    id=row[0],
                    name=row[1],
                    sex=row[2],
                    born=row[3],
                    mother=row[4],
                    father=row[5],
                    family=row[6],
                    clan=row[7],
                    partner=row[8],
                    traits=json.loads(row[9]),
                    children=row[10],
                    last_birth=row[11],
                    moved=row[12],
                    discoveries=row[13],
                    activity=row[14],
                    target_y=row[15],
                    target_x=row[16],
                    work=json.loads(row[17]),
                    gift=row[18],
                )
                for row in self.conn.execute(
                    "SELECT id, name, sex, born, mother, father, family, clan, partner, traits, "
                    "children, last_birth, moved, discoveries, activity, target_y, target_x, work, "
                    "gift "
                    "FROM persons "
                    "WHERE world_id = ? AND died IS NULL ORDER BY id",
                    (world_id,),
                )
            ]
            layer = self.conn.execute(
                "SELECT data FROM tile_layers WHERE world_id = ? AND layer = 'steps'", (world_id,)
            ).fetchone()
            steps = (
                None
                if layer is None
                else np.frombuffer(layer[0], dtype="<i4").reshape(shape).astype(np.int32)
            )
            held = self.conn.execute(
                "SELECT data FROM tile_layers WHERE world_id = ? AND layer = 'territory'",
                (world_id,),
            ).fetchone()
            territory = (
                None
                if held is None
                else np.frombuffer(held[0], dtype="<i4").reshape(shape).astype(np.int32)
            )
            peoples_held = self.conn.execute(
                "SELECT data FROM tile_layers WHERE world_id = ? AND layer = 'land_people'",
                (world_id,),
            ).fetchone()
            world.society.load_state(loaded["society"], persons, steps, territory)
            if peoples_held is not None:
                # As it stood when the land was last shared out: a clan may have
                # changed its people since, and the next sharing compares with this.
                world.society.land_people = (
                    np.frombuffer(peoples_held[0], dtype="<i4").reshape(shape).astype(np.int32)
                )
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
