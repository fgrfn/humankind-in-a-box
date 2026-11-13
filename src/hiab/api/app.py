"""The HTTP API. It only reads the database: the worker is its single writer.

The one thing that can be changed from outside is how fast the world runs, and
that goes through a small file the worker reads (see hiab.control).

Everything the browser shows comes from here, and so does everything an
external consumer (a REST sensor, a script) can ask.
"""

import asyncio
import json
import secrets
import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hiab import __version__
from hiab.control import SPEEDS, Control, read_control, read_pace, write_control
from hiab.packs import BIOMES, PackSet
from hiab.render import calendar, meaning_text, render_event

Language = Literal["de", "en"]
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _rows(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def _layer(blob: bytes) -> list[int]:
    values: list[int] = np.frombuffer(blob, dtype="<i4").tolist()
    return values


class SpeedWish(BaseModel):
    """What the interface may ask of the worker. Nothing else can be changed from outside."""

    paused: bool | None = None
    speed: int | None = None
    for_years: int | None = Field(None, ge=1, le=100000)


def create_app(
    db_path: Path,
    packs: PackSet,
    default_language: Language = "de",
    data_dir: Path | None = None,
    api_token: str | None = None,
    pace: float = 120.0,
) -> FastAPI:
    app = FastAPI(
        title="Humankind in a Box",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    # The map and the list of people are long and repetitive; compressed they are small.
    app.add_middleware(GZipMiddleware, minimum_size=2000)
    api = APIRouter(prefix="/api/v1")

    def connect() -> sqlite3.Connection:
        # FastAPI may open and use a connection on different pool threads. That is
        # safe here: each request has its own read-only connection, used in sequence.
        conn = sqlite3.connect(
            f"file:{db_path.as_posix()}?mode=ro", uri=True, check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        return conn

    def database() -> Iterator[sqlite3.Connection]:
        try:
            conn = connect()
        except sqlite3.OperationalError as exc:
            raise HTTPException(503, "The world database is not available yet") from exc
        try:
            yield conn
        finally:
            conn.close()

    Db = Annotated[sqlite3.Connection, Depends(database)]
    Lang = Annotated[Language, Query(description="Language of rendered texts")]

    def world_row(conn: sqlite3.Connection, world_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM worlds WHERE id = ?", (world_id,)).fetchone()
        if row is None:
            raise HTTPException(404, f"World {world_id} does not exist")
        return row

    def active_world(conn: sqlite3.Connection) -> sqlite3.Row | None:
        row: sqlite3.Row | None = conn.execute(
            "SELECT * FROM worlds WHERE status = 'active' ORDER BY id LIMIT 1"
        ).fetchone()
        return row

    def event_out(row: sqlite3.Row, language: Language) -> dict[str, Any]:
        data = json.loads(row["data"])
        return {
            "seq": row["seq"],
            **calendar(row["tick"]),
            "type": row["type"],
            "importance": row["importance"],
            "region": row["region"],
            "text": render_event(packs, row["type"], data, language),
            "data": data,
        }

    def world_out(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "seed": row["seed"],
            "status": row["status"],
            "width": row["width"],
            "height": row["height"],
            "parent_world": row["parent_world"],
            **calendar(row["tick"]),
        }

    @api.get("/health")
    def health(conn: Db) -> dict[str, Any]:
        world = active_world(conn)
        return {
            "status": "ok",
            "version": __version__,
            "world": None if world is None else world_out(world),
        }

    @api.get("/worlds")
    def worlds(conn: Db) -> list[dict[str, Any]]:
        return [world_out(row) for row in _rows(conn, "SELECT * FROM worlds ORDER BY id")]

    @api.get("/worlds/{world_id}")
    def world(world_id: int, conn: Db) -> dict[str, Any]:
        return world_out(world_row(conn, world_id))

    @api.get("/worlds/{world_id}/stats")
    def stats(world_id: int, conn: Db, lang: Lang = default_language) -> dict[str, Any]:
        """Flat key figures, readable by a REST sensor without any post-processing."""
        row = world_row(conn, world_id)

        def one(sql: str, *args: Any) -> Any:
            return conn.execute(sql, (world_id, *args)).fetchone()[0]

        def total(key: str) -> int:
            value = one(
                "SELECT COALESCE(SUM(value), 0) FROM metrics "
                "WHERE world_id = ? AND key = ? AND scope_type = 'world'",
                key,
            )
            return int(value)

        last = conn.execute(
            "SELECT * FROM events WHERE world_id = ? AND importance >= 3 ORDER BY seq DESC LIMIT 1",
            (world_id,),
        ).fetchone()
        anomaly = conn.execute(
            "SELECT value FROM metrics WHERE world_id = ? AND key = 'climate.anomaly' "
            "ORDER BY tick DESC LIMIT 1",
            (world_id,),
        ).fetchone()
        return {
            **calendar(row["tick"]),
            "seed": row["seed"],
            "population": one("SELECT COUNT(*) FROM persons WHERE world_id = ? AND died IS NULL"),
            "ever_lived": one("SELECT COUNT(*) FROM persons WHERE world_id = ?"),
            "clans": one("SELECT COUNT(*) FROM groups WHERE world_id = ? AND dissolved IS NULL"),
            "settlements": one(
                "SELECT COUNT(*) FROM groups "
                "WHERE world_id = ? AND dissolved IS NULL AND settled = 1"
            ),
            "discoveries": one(
                "SELECT COUNT(DISTINCT technology) FROM discoveries WHERE world_id = ?"
            ),
            "discoveries_possible": len(packs.technologies),
            **{
                f"stored_{good}": amount
                for good, amount in sorted(store_totals(conn, world_id)[0].items())
            },
            "trade_partnerships": one(
                "SELECT COUNT(*) FROM trade_links WHERE world_id = ? AND ended IS NULL"
            ),
            "peoples": one(
                "SELECT COUNT(DISTINCT culture) FROM groups "
                "WHERE world_id = ? AND dissolved IS NULL"
            ),
            "realms": one("SELECT COUNT(*) FROM realms WHERE world_id = ? AND ended IS NULL"),
            "lands": one(
                "SELECT COUNT(*) FROM realms "
                "WHERE world_id = ? AND ended IS NULL AND land_since IS NOT NULL"
            ),
            "free_clans": one(
                "SELECT COUNT(*) FROM groups g WHERE g.world_id = ? AND g.dissolved IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM realms r WHERE r.world_id = g.world_id "
                "AND r.id = g.realm AND r.ended IS NULL AND r.land_since IS NOT NULL)"
            ),
            "wars_ongoing": one("SELECT COUNT(*) FROM wars WHERE world_id = ? AND ended IS NULL"),
            "faiths": one("SELECT COUNT(*) FROM faiths WHERE world_id = ? AND ended IS NULL"),
            "wars_total": one("SELECT COUNT(*) FROM wars WHERE world_id = ?"),
            "births_total": total("people.births"),
            "deaths_total": total("people.deaths"),
            "migrations_total": total("clans.migrations"),
            "events_total": one("SELECT COUNT(*) FROM events WHERE world_id = ?"),
            "climate_anomaly": None if anomaly is None else anomaly[0] / 10,
            "last_event": None if last is None else event_out(last, lang)["text"],
            "last_event_year": None if last is None else last["tick"] // 360,
        }

    @api.get("/worlds/{world_id}/map")
    def world_map(world_id: int, conn: Db) -> dict[str, Any]:
        """The whole map as flat arrays in row order (y * width + x)."""
        row = world_row(conn, world_id)
        deposit_ids: list[str] = json.loads(row["deposit_ids"])
        biome: list[int] = []
        elevation: list[int] = []
        river: list[int] = []
        deposit: list[int] = []
        for tile in _rows(
            conn,
            "SELECT biome, elevation, river, deposit FROM tiles WHERE world_id = ? ORDER BY y, x",
            (world_id,),
        ):
            biome.append(BIOMES.index(tile["biome"]))
            elevation.append(tile["elevation"])
            river.append(tile["river"])
            deposit.append(-1 if tile["deposit"] is None else deposit_ids.index(tile["deposit"]))
        steps = conn.execute(
            "SELECT data FROM tile_layers WHERE world_id = ? AND layer = 'steps'", (world_id,)
        ).fetchone()
        return {
            "width": row["width"],
            "height": row["height"],
            "biomes": list(BIOMES),
            # How much of a growing resource a tile of each biome can hold, so the
            # map can show woods and bushes thinning out and growing back.
            "capacity": {
                resource: dict(sorted(packs.resources[resource].capacity.items()))
                for resource in ("wood", "plants")
                if resource in packs.resources
            },
            "deposits": [
                {
                    "id": deposit_id,
                    "de": packs.resources[deposit_id].name.de
                    if deposit_id in packs.resources
                    else deposit_id,
                    "en": packs.resources[deposit_id].name.en
                    if deposit_id in packs.resources
                    else deposit_id,
                }
                for deposit_id in deposit_ids
            ],
            "biome": biome,
            "elevation": elevation,
            "river": river,
            "deposit": deposit,
            "steps": [] if steps is None else _layer(steps["data"]),
            "path_levels": {
                "trail": 0 if packs.life is None else packs.life.path_trail_steps,
                "road": 0 if packs.life is None else packs.life.path_road_steps,
            },
        }

    def building_out(row: sqlite3.Row, language: Language) -> dict[str, Any]:
        known = packs.buildings.get(row["type"])
        return {
            "id": row["id"],
            "type": row["type"],
            "name": row["type"] if known is None else getattr(known.name, language),
            "y": row["y"],
            "x": row["x"],
            "state": row["state"],
            "started_year": row["started"] // 360,
            "finished_year": None if row["finished"] is None else row["finished"] // 360,
            "progress_percent": 100
            if row["state"] != "site" or known is None
            else min(99, 100 * row["progress"] // max(1, known.work)),
        }

    @api.get("/worlds/{world_id}/peoples")
    def peoples(world_id: int, conn: Db) -> list[dict[str, Any]]:
        """Every people that ever formed: descent, size, sounds and a few of its words."""
        world_row(conn, world_id)
        living = {
            row["culture"]: row
            for row in _rows(
                conn,
                "SELECT g.culture, COUNT(DISTINCT g.id) AS clans, "
                "SUM(g.settled) AS settlements FROM groups g "
                "WHERE g.world_id = ? AND g.dissolved IS NULL GROUP BY g.culture",
                (world_id,),
            )
        }
        heads = {
            row["culture"]: row["n"]
            for row in _rows(
                conn,
                "SELECT g.culture, COUNT(*) AS n FROM persons p "
                "JOIN groups g ON g.world_id = p.world_id AND g.id = p.clan "
                "WHERE p.world_id = ? AND p.died IS NULL GROUP BY g.culture",
                (world_id,),
            )
        }
        land: dict[int, int] = {}
        for held in held_land(conn, world_id)[1]:
            if held:
                land[held] = land.get(held, 0) + 1
        kept = store_totals(conn, world_id)
        rows = _rows(conn, "SELECT * FROM cultures WHERE world_id = ? ORDER BY id", (world_id,))
        names = {row["id"]: row["name"] for row in rows}
        out = []
        for row in rows:
            sounds = json.loads(row["sound_rules"])
            alive = living.get(row["id"])
            out.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "ways": json.loads(row["ways"]) if row["ways"] else {},
                    "parent_id": row["parent_culture"],
                    "parent": names.get(row["parent_culture"]),
                    "founded_year": row["founded"] // 360,
                    "ended_year": None if row["ended"] is None else row["ended"] // 360,
                    "clans": 0 if alive is None else alive["clans"],
                    "settlements": 0 if alive is None else alive["settlements"],
                    "population": heads.get(row["id"], 0),
                    "tiles": land.get(row["id"], 0),
                    "stores": dict(sorted(kept.get(row["id"], {}).items())),
                    "consonants": sounds["c"],
                    "vowels": sounds["v"],
                    "words": json.loads(row["words"]),
                }
            )
        out.sort(key=lambda item: (-item["population"], item["id"]))
        return out

    @api.get("/worlds/{world_id}/places")
    def places(world_id: int, conn: Db, lang: Lang = default_language) -> list[dict[str, Any]]:
        """Settlements, lived in or abandoned, with everything that stands there."""
        world_row(conn, world_id)
        built: dict[int, list[dict[str, Any]]] = {}
        for row in _rows(
            conn, "SELECT * FROM buildings WHERE world_id = ? ORDER BY id", (world_id,)
        ):
            built.setdefault(row["place_id"], []).append(building_out(row, lang))
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "y": row["y"],
                "x": row["x"],
                "founded_year": row["founded"] // 360,
                "abandoned_year": None if row["abandoned"] is None else row["abandoned"] // 360,
                "group_id": row["group_id"],
                "meaning": meaning_text(packs, row["meaning"], lang),
                "buildings": built.get(row["id"], []),
            }
            for row in _rows(
                conn, "SELECT * FROM places WHERE world_id = ? ORDER BY id", (world_id,)
            )
            if row["abandoned"] is None or row["id"] in built
        ]

    @api.get("/worlds/{world_id}/layers/{layer}")
    def layer(world_id: int, layer: str, conn: Db) -> dict[str, Any]:
        """One changing layer: 'steps' or the current stock of a resource."""
        world_row(conn, world_id)
        if layer in ("steps", "territory"):
            found = conn.execute(
                "SELECT data FROM tile_layers WHERE world_id = ? AND layer = ?", (world_id, layer)
            ).fetchone()
        else:
            found = conn.execute(
                "SELECT data FROM tile_stocks WHERE world_id = ? AND resource = ?",
                (world_id, layer),
            ).fetchone()
        if found is None:
            raise HTTPException(404, f"Layer '{layer}' does not exist")
        return {"layer": layer, "values": _layer(found["data"])}

    def held_land(conn: sqlite3.Connection, world_id: int) -> tuple[list[int], list[int]]:
        """For every tile the clan that holds it and that clan's people, 0 for nobody."""
        found = conn.execute(
            "SELECT data FROM tile_layers WHERE world_id = ? AND layer = 'territory'", (world_id,)
        ).fetchone()
        if found is None:
            return [], []
        held = conn.execute(
            "SELECT data FROM tile_layers WHERE world_id = ? AND layer = 'land_people'",
            (world_id,),
        ).fetchone()
        clans = _layer(found["data"])
        return clans, [0] * len(clans) if held is None else _layer(held["data"])

    def speed_out(conn: sqlite3.Connection) -> dict[str, Any]:
        wanted = Control() if data_dir is None else read_control(data_dir)
        report = {} if data_dir is None else read_pace(data_dir)
        latest = conn.execute("SELECT tick FROM worlds ORDER BY id DESC LIMIT 1").fetchone()
        return {
            **wanted.as_dict(),
            "speeds": list(SPEEDS),
            "days_per_minute": pace,
            "measured_days_per_minute": report.get("days_per_minute"),
            "running": bool(report.get("running", False)),
            "year": 0 if latest is None else latest["tick"] // 360,
            "changeable": data_dir is not None,
            "token_required": bool(api_token),
        }

    @api.get("/control")
    def control(conn: Db) -> dict[str, Any]:
        """How fast the world runs: what is wanted and what the worker reports."""
        return speed_out(conn)

    @api.put("/control")
    def set_control(
        wish: SpeedWish,
        conn: Db,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        """Pause, resume or speed up. Does not change what happens, only how fast.

        Written to a small file the worker reads; the database is not touched.
        """
        if data_dir is None:
            raise HTTPException(409, "This server has no data directory to pass the wish on.")
        if api_token and not secrets.compare_digest(
            (authorization or "").encode(), f"Bearer {api_token}".encode()
        ):
            raise HTTPException(401, "The API token is required to change the speed.")
        if wish.speed is not None and wish.speed not in SPEEDS:
            raise HTTPException(422, f"speed must be one of {list(SPEEDS)}")
        now = read_control(data_dir)
        speed = now.speed if wish.speed is None else wish.speed
        until = now.until_year if wish.speed is None else None
        if wish.for_years is not None and speed != 1:
            latest = conn.execute("SELECT tick FROM worlds ORDER BY id DESC LIMIT 1").fetchone()
            until = (0 if latest is None else latest["tick"] // 360) + wish.for_years
        if speed == 1:
            until = None
        write_control(
            data_dir,
            Control(
                paused=now.paused if wish.paused is None else wish.paused,
                speed=speed,
                until_year=until,
            ),
        )
        return speed_out(conn)

    @api.get("/worlds/{world_id}/stores")
    def stores(world_id: int, conn: Db, lang: Lang = default_language) -> list[dict[str, Any]]:
        """What the whole world keeps in store, food first."""
        world_row(conn, world_id)
        return [
            {"id": good, "name": good_name(good, lang), "amount": amount}
            for good, amount in sorted(
                store_totals(conn, world_id)[0].items(),
                key=lambda item: (item[0] != "food", item[0]),
            )
        ]

    @api.get("/worlds/{world_id}/trade")
    def trade(world_id: int, conn: Db) -> list[dict[str, Any]]:
        """Every standing trade partnership: who with whom, where and since when."""
        world_row(conn, world_id)
        return [
            {
                "a": row["group_a"],
                "b": row["group_b"],
                "since_year": row["since"] // 360,
                "ay": row["ay"],
                "ax": row["ax"],
                "by": row["by"],
                "bx": row["bx"],
            }
            for row in _rows(
                conn,
                "SELECT t.group_a, t.group_b, t.since, a.y AS ay, a.x AS ax, b.y AS by, b.x AS bx "
                "FROM trade_links t "
                "JOIN groups a ON a.world_id = t.world_id AND a.id = t.group_a "
                "JOIN groups b ON b.world_id = t.world_id AND b.id = t.group_b "
                "WHERE t.world_id = ? AND t.ended IS NULL ORDER BY t.group_a, t.group_b",
                (world_id,),
            )
        ]

    @api.get("/worlds/{world_id}/since")
    def since(
        world_id: int,
        conn: Db,
        year: Annotated[int, Query(ge=0)],
        lang: Lang = default_language,
    ) -> dict[str, Any]:
        """What happened since a given year: for "while you were away"."""
        world = world_row(conn, world_id)
        start = year * 360

        def count(event_type: str) -> int:
            return int(
                conn.execute(
                    "SELECT COALESCE(SUM(value), 0) FROM metrics WHERE world_id = ? "
                    "AND key = ? AND scope_type = 'world' AND tick > ?",
                    (world_id, event_type, start),
                ).fetchone()[0]
            )

        def happened(event_type: str) -> int:
            return int(
                conn.execute(
                    "SELECT COUNT(*) FROM events WHERE world_id = ? AND type = ? AND tick > ?",
                    (world_id, event_type, start),
                ).fetchone()[0]
            )

        then = conn.execute(
            "SELECT value FROM metrics WHERE world_id = ? AND key = 'people.population' "
            "AND scope_type = 'world' AND tick <= ? ORDER BY tick DESC LIMIT 1",
            (world_id, start + 360),
        ).fetchone()
        now = conn.execute(
            "SELECT COUNT(*) FROM persons WHERE world_id = ? AND died IS NULL", (world_id,)
        ).fetchone()[0]
        highlights = _rows(
            conn,
            "SELECT * FROM events WHERE world_id = ? AND tick > ? AND importance >= 3 "
            "ORDER BY importance DESC, seq DESC LIMIT 8",
            (world_id, start),
        )
        return {
            "from_year": year,
            "to_year": world["tick"] // 360,
            "years": max(0, world["tick"] // 360 - year),
            "population_then": None if then is None else int(then["value"]),
            "population_now": now,
            "births": count("people.births"),
            "deaths": count("people.deaths"),
            "discoveries": happened("discovery"),
            "knowledge_lost": happened("knowledge_lost"),
            "settlements_founded": happened("settlement_founded"),
            "settlements_abandoned": happened("settlement_abandoned"),
            "peoples_emerged": happened("people_emerged"),
            "peoples_vanished": happened("people_vanished"),
            "trade_begun": happened("trade_begun"),
            "highlights": [
                {
                    "year": item["tick"] // 360,
                    "importance": item["importance"],
                    "text": render_event(packs, item["type"], json.loads(item["data"]), lang),
                }
                for item in sorted(highlights, key=lambda item: item["seq"])
            ],
        }

    @api.get("/worlds/{world_id}/territory")
    def territory(world_id: int, conn: Db) -> dict[str, Any]:
        """Who holds the land: per tile the clan and its people, row by row."""
        world_row(conn, world_id)
        clans, peoples_held = held_land(conn, world_id)
        of_realm = {
            row["id"]: row["realm"]
            for row in _rows(
                conn,
                "SELECT g.id, g.realm FROM groups g JOIN realms r "
                "ON r.world_id = g.world_id AND r.id = g.realm "
                "WHERE g.world_id = ? AND g.dissolved IS NULL AND r.ended IS NULL",
                (world_id,),
            )
        }
        realms_held = [of_realm.get(clan, 0) for clan in clans]
        of_faith = {
            row["id"]: row["faith"]
            for row in _rows(
                conn,
                "SELECT id, faith FROM groups "
                "WHERE world_id = ? AND dissolved IS NULL AND faith > 0",
                (world_id,),
            )
        }
        faiths_held = [of_faith.get(clan, 0) for clan in clans]
        return {
            "clans": clans,
            "peoples": peoples_held,
            "realms": realms_held,
            "faiths": faiths_held,
        }

    @api.get("/worlds/{world_id}/wars")
    def wars(world_id: int, conn: Db) -> list[dict[str, Any]]:
        """Wars between chiefdoms, ongoing first, then the latest. With the seats, for the map."""
        world_row(conn, world_id)
        realm_rows = {
            row["id"]: row
            for row in _rows(
                conn,
                "SELECT r.id, r.name, g.y, g.x FROM realms r LEFT JOIN groups g "
                "ON g.world_id = r.world_id AND g.id = r.seat_group WHERE r.world_id = ?",
                (world_id,),
            )
        }

        def side(realm_id: int) -> dict[str, Any]:
            row = realm_rows.get(realm_id)
            return {
                "id": realm_id,
                "name": None if row is None else row["name"],
                "y": None if row is None else row["y"],
                "x": None if row is None else row["x"],
            }

        out = [
            {
                "id": row["id"],
                "attacker": side(row["attacker"]),
                "defender": side(row["defender"]),
                "started_year": row["started"] // 360,
                "ended_year": None if row["ended"] is None else row["ended"] // 360,
                "outcome": row["outcome"],
                "winner_id": row["winner"] or None,
                "field": None if row["field_y"] < 0 else {"y": row["field_y"], "x": row["field_x"]},
                "last_battle_year": row["last_battle"] // 360 if row["battles"] else None,
                "last_fallen": row["last_fallen"],
                "battles": row["battles"],
                "fallen": row["fallen"],
            }
            for row in _rows(conn, "SELECT * FROM wars WHERE world_id = ? ORDER BY id", (world_id,))
        ]
        out.sort(key=lambda w: (w["ended_year"] is not None, -w["started_year"], -w["id"]))
        return out[:100]

    @api.get("/worlds/{world_id}/faiths")
    def faiths(world_id: int, conn: Db, lang: Lang = default_language) -> list[dict[str, Any]]:
        """Faiths, kept ones first: what they worship, where they began, how many keep them."""
        world_row(conn, world_id)
        language = lang
        aspects = packs.life.faith_aspects if packs.life is not None else {}
        keepers = {
            row["faith"]: (row["clans"], row["n"])
            for row in _rows(
                conn,
                "SELECT g.faith, COUNT(DISTINCT g.id) AS clans, COUNT(p.id) AS n FROM groups g "
                "LEFT JOIN persons p ON p.world_id = g.world_id AND p.clan = g.id "
                "AND p.died IS NULL "
                "WHERE g.world_id = ? AND g.dissolved IS NULL AND g.faith > 0 GROUP BY g.faith",
                (world_id,),
            )
        }
        out = []
        for row in _rows(
            conn,
            "SELECT f.*, c.name AS people_name, g.name AS origin_name FROM faiths f "
            "LEFT JOIN cultures c ON c.world_id = f.world_id AND c.id = f.people "
            "LEFT JOIN groups g ON g.world_id = f.world_id AND g.id = f.origin_group "
            "WHERE f.world_id = ? ORDER BY f.id",
            (world_id,),
        ):
            clans, heads = keepers.get(row["id"], (0, 0))
            aspect = aspects.get(row["aspect"])
            out.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "aspect": row["aspect"],
                    "aspect_text": None if aspect is None else getattr(aspect, language),
                    "founded_year": row["founded"] // 360,
                    "ended_year": None if row["ended"] is None else row["ended"] // 360,
                    "origin_id": row["origin_group"],
                    "origin": row["origin_name"],
                    "people": row["people_name"],
                    "clans": clans,
                    "population": heads,
                }
            )
        out.sort(key=lambda f: (f["ended_year"] is not None, -f["population"], f["id"]))
        return out

    @api.get("/worlds/{world_id}/realms")
    def realms(world_id: int, conn: Db) -> list[dict[str, Any]]:
        """Chiefdoms, standing first: seat, ruler, people, clans, heads and land."""
        world_row(conn, world_id)
        clans, _ = held_land(conn, world_id)
        members: dict[int, list[int]] = {}
        for row in _rows(
            conn,
            "SELECT id, realm FROM groups WHERE world_id = ? AND dissolved IS NULL AND realm > 0 "
            "ORDER BY id",
            (world_id,),
        ):
            members.setdefault(row["realm"], []).append(row["id"])
        heads = {
            row["realm"]: row["n"]
            for row in _rows(
                conn,
                "SELECT g.realm, COUNT(*) AS n FROM persons p "
                "JOIN groups g ON g.world_id = p.world_id AND g.id = p.clan "
                "WHERE p.world_id = ? AND p.died IS NULL AND g.realm > 0 GROUP BY g.realm",
                (world_id,),
            )
        }
        clan_realm = {clan: realm for realm, ids in members.items() for clan in ids}
        land: dict[int, int] = {}
        for clan in clans:
            realm = clan_realm.get(clan)
            if realm:
                land[realm] = land.get(realm, 0) + 1
        out = []
        for row in _rows(
            conn,
            "SELECT r.*, g.name AS seat_name, p.name AS ruler_name, c.name AS people_name "
            "FROM realms r "
            "LEFT JOIN groups g ON g.world_id = r.world_id AND g.id = r.seat_group "
            "LEFT JOIN persons p ON p.world_id = r.world_id AND p.id = r.ruler "
            "LEFT JOIN cultures c ON c.world_id = r.world_id AND c.id = r.people "
            "WHERE r.world_id = ? ORDER BY r.id",
            (world_id,),
        ):
            standing = row["ended"] is None
            out.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "founded_year": row["founded"] // 360,
                    "ended_year": None if standing else row["ended"] // 360,
                    "seat_id": row["seat_group"],
                    "seat": row["seat_name"],
                    "ruler_id": row["ruler"],
                    "ruler": row["ruler_name"],
                    "people_id": row["people"],
                    "people": row["people_name"],
                    "clans": members.get(row["id"], []) if standing else [],
                    "population": heads.get(row["id"], 0) if standing else 0,
                    "tiles": land.get(row["id"], 0) if standing else 0,
                    "land_year": None if row["land_since"] is None else row["land_since"] // 360,
                }
            )
        out.sort(key=lambda item: (item["ended_year"] is not None, -item["population"], item["id"]))
        return out

    def good_name(good: str, language: Language) -> str:
        if good == "food":
            return "Nahrung" if language == "de" else "Food"
        resource = packs.resources.get(good)
        return good if resource is None else getattr(resource.name, language)

    def stores_out(raw: str, language: Language) -> list[dict[str, Any]]:
        """A clan's stores: food first, then every good it has or had movement in last year."""
        kept = json.loads(raw) if raw else {}
        goods: dict[str, int] = {"food": kept.get("food", 0), **kept.get("goods", {})}
        last = kept.get("last_year", {})
        out: list[dict[str, Any]] = []
        for good in ["food", *sorted(set(goods) | set(last) - {"food"})]:
            if good in [item["id"] for item in out]:
                continue
            gained, used, traded_in, traded_out = last.get(good, [0, 0, 0, 0])
            out.append(
                {
                    "id": good,
                    "name": good_name(good, language),
                    "amount": goods.get(good, 0),
                    "room": kept.get("food_room" if good == "food" else "room", 0),
                    "gained": gained,
                    "used": used,
                    "traded_in": traded_in,
                    "traded_out": traded_out,
                }
            )
        return out

    def store_totals(conn: sqlite3.Connection, world_id: int) -> dict[int, dict[str, int]]:
        """What all living clans keep, summed per people; people 0 is the whole world."""
        totals: dict[int, dict[str, int]] = {0: {}}
        for row in _rows(
            conn,
            "SELECT culture, stores FROM groups WHERE world_id = ? AND dissolved IS NULL "
            "ORDER BY id",
            (world_id,),
        ):
            kept = json.loads(row["stores"]) if row["stores"] else {}
            for good, amount in [("food", kept.get("food", 0)), *kept.get("goods", {}).items()]:
                for scope in (0, row["culture"]):
                    bucket = totals.setdefault(scope, {})
                    bucket[good] = bucket.get(good, 0) + amount
        return totals

    def group_out(conn: sqlite3.Connection, row: sqlite3.Row, language: Language) -> dict[str, Any]:
        place = None
        buildings: list[dict[str, Any]] = []
        if row["place"]:
            found = conn.execute(
                "SELECT name FROM places WHERE world_id = ? AND id = ?",
                (row["world_id"], row["place"]),
            ).fetchone()
            place = None if found is None else found["name"]
            buildings = [
                building_out(item, language)
                for item in _rows(
                    conn,
                    "SELECT * FROM buildings WHERE world_id = ? AND place_id = ? ORDER BY id",
                    (row["world_id"], row["place"]),
                )
            ]
        techs = _rows(
            conn,
            "SELECT technology, tick, how FROM discoveries "
            "WHERE world_id = ? AND group_id = ? AND lost IS NULL "
            "ORDER BY tick, technology",
            (row["world_id"], row["id"]),
        )
        people = conn.execute(
            "SELECT name FROM cultures WHERE world_id = ? AND id = ?",
            (row["world_id"], row["culture"]),
        ).fetchone()
        leader = conn.execute(
            "SELECT id, name FROM persons WHERE world_id = ? AND id = ?",
            (row["world_id"], row["leader"]),
        ).fetchone()
        realm = conn.execute(
            "SELECT id, name, seat_group, land_since FROM realms "
            "WHERE world_id = ? AND id = ? AND ended IS NULL",
            (row["world_id"], row["realm"]),
        ).fetchone()
        # A fever goes round until its tick; the world's clock is its newest tick.
        now = conn.execute("SELECT tick FROM worlds WHERE id = ?", (row["world_id"],)).fetchone()[0]
        faith = conn.execute(
            "SELECT id, name FROM faiths WHERE world_id = ? AND id = ?",
            (row["world_id"], row["faith"]),
        ).fetchone()
        return {
            "id": row["id"],
            "name": row["name"],
            "people_id": row["culture"],
            "sick": row["sick_until"] > now,
            "faith": None if faith is None else {"id": faith["id"], "name": faith["name"]},
            "people": None if people is None else people["name"],
            "leader": None if leader is None else {"id": leader["id"], "name": leader["name"]},
            "realm": None
            if realm is None
            else {
                "id": realm["id"],
                "name": realm["name"],
                "seat": realm["seat_group"] == row["id"],
                "land": realm["land_since"] is not None,
            },
            "type": row["type"],
            "y": row["y"],
            "x": row["x"],
            "settled": bool(row["settled"]),
            "place": place,
            "buildings": buildings,
            "stores": stores_out(row["stores"], language),
            "partners": [
                {"id": link["id"], "name": link["name"], "since_year": link["since"] // 360}
                for link in _rows(
                    conn,
                    "SELECT g.id, g.name, t.since FROM trade_links t JOIN groups g "
                    "ON g.world_id = t.world_id "
                    "AND g.id = CASE WHEN t.group_a = ? THEN t.group_b ELSE t.group_a END "
                    "WHERE t.world_id = ? AND t.ended IS NULL AND ? IN (t.group_a, t.group_b) "
                    "ORDER BY t.since, g.id",
                    (row["id"], row["world_id"], row["id"]),
                )
            ],
            "parent_group": row["parent_group"],
            "founded_year": row["founded"] // 360,
            "dissolved_year": None if row["dissolved"] is None else row["dissolved"] // 360,
            "technologies": [
                {
                    "id": tech["technology"],
                    "name": getattr(packs.technologies[tech["technology"]].name, language)
                    if tech["technology"] in packs.technologies
                    else tech["technology"],
                    "year": tech["tick"] // 360,
                    "how": tech["how"],
                }
                for tech in techs
            ],
        }

    @api.get("/worlds/{world_id}/groups")
    def groups(world_id: int, conn: Db, lang: Lang = default_language) -> list[dict[str, Any]]:
        """Living clans and settlements with their camp position and head count."""
        world_row(conn, world_id)
        counts = {
            row["clan"]: row["n"]
            for row in _rows(
                conn,
                "SELECT clan, COUNT(*) AS n FROM persons WHERE world_id = ? AND died IS NULL "
                "GROUP BY clan",
                (world_id,),
            )
        }
        out = []
        for row in _rows(
            conn,
            "SELECT * FROM groups WHERE world_id = ? AND dissolved IS NULL ORDER BY id",
            (world_id,),
        ):
            item = group_out(conn, row, lang)
            item["population"] = counts.get(row["id"], 0)
            out.append(item)
        return out

    @api.get("/worlds/{world_id}/groups/{group_id}")
    def group(
        world_id: int, group_id: int, conn: Db, lang: Lang = default_language
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM groups WHERE world_id = ? AND id = ?", (world_id, group_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Group {group_id} does not exist")
        item = group_out(conn, row, lang)
        members = _rows(
            conn,
            "SELECT id, name, sex, born, children, activity FROM persons "
            "WHERE world_id = ? AND clan = ? AND died IS NULL ORDER BY born",
            (world_id, group_id),
        )
        tick = world_row(conn, world_id)["tick"]
        item["population"] = len(members)
        item["members"] = [
            {
                "id": member["id"],
                "name": member["name"],
                "sex": "f" if member["sex"] == 0 else "m",
                "age": (tick - member["born"]) // 360,
                "children": member["children"],
                "activity": member["activity"],
                "activity_text": activity_text(member["activity"], lang),
            }
            for member in members
        ]
        return item

    def activity_text(activity: str, language: Language) -> str:
        """What a person is doing this month, in words."""
        kind, _, detail = activity.partition(":")
        if kind == "build" and not detail:
            return "baut" if language == "de" else "building"
        if kind == "build":
            known = packs.buildings.get(detail)
            name = detail if known is None else getattr(known.name, language)
            return f"baut: {name}" if language == "de" else f"building: {name}"
        if kind == "search":
            return "sucht Nahrung" if language == "de" else "searching for food"
        if kind == "pray":
            return "hält die Riten" if language == "de" else "keeps the rites"
        if kind == "sick":
            return "liegt krank" if language == "de" else "lies sick"
        if kind == "heal":
            return "pflegt die Kranken" if language == "de" else "tends the sick"
        if kind == "fight":
            return "zieht in den Krieg" if language == "de" else "off to war"
        resource = packs.resources.get(kind)
        if resource is None:
            return ""
        return getattr(resource.work or resource.name, language)

    @api.get("/worlds/{world_id}/people")
    def people(world_id: int, conn: Db, lang: Lang = default_language) -> list[dict[str, Any]]:
        """Everybody alive: who they are, what they do this month and where."""
        tick = world_row(conn, world_id)["tick"]
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "sex": "f" if row["sex"] == 0 else "m",
                "age": (tick - row["born"]) // 360,
                "clan": row["clan"],
                "activity": row["activity"],
                "text": activity_text(row["activity"], lang),
                "y": row["target_y"],
                "x": row["target_x"],
            }
            for row in _rows(
                conn,
                "SELECT id, name, sex, born, clan, activity, target_y, target_x FROM persons "
                "WHERE world_id = ? AND died IS NULL ORDER BY id",
                (world_id,),
            )
        ]

    @api.get("/worlds/{world_id}/persons/{person_id}/tree")
    def family_tree(
        world_id: int,
        person_id: int,
        conn: Db,
        up: Annotated[int, Query(ge=0, le=6)] = 3,
        down: Annotated[int, Query(ge=0, le=6)] = 3,
    ) -> dict[str, Any]:
        """A person with ancestors and descendants, generation by generation.

        Each entry carries its parents, so the tree can be drawn with lines.
        Descendants are cut off at 60 per generation to keep the answer small.
        """
        tick = world_row(conn, world_id)["tick"]

        def load(ids: list[int]) -> list[sqlite3.Row]:
            if not ids:
                return []
            marks = ",".join("?" * len(ids))
            return _rows(
                conn,
                f"SELECT id, name, sex, born, died, mother, father, partner, clan "
                f"FROM persons WHERE world_id = ? AND id IN ({marks}) ORDER BY born, id",
                (world_id, *ids),
            )

        def out(row: sqlite3.Row) -> dict[str, Any]:
            end = tick if row["died"] is None else row["died"]
            return {
                "id": row["id"],
                "name": row["name"],
                "sex": "f" if row["sex"] == 0 else "m",
                "born_year": row["born"] // 360,
                "died_year": None if row["died"] is None else row["died"] // 360,
                "age": max(0, (end - row["born"]) // 360),
                "mother": row["mother"],
                "father": row["father"],
                "partner": row["partner"],
                "clan": row["clan"],
            }

        centre = load([person_id])
        if not centre:
            raise HTTPException(404, f"No person {person_id} in world {world_id}.")
        partner = load([centre[0]["partner"]]) if centre[0]["partner"] else []

        ancestors: list[list[dict[str, Any]]] = []
        current = [centre[0]]
        for _ in range(up):
            parents = sorted(
                {parent for row in current for parent in (row["mother"], row["father"]) if parent}
            )
            current = load(parents)
            if not current:
                break
            ancestors.append([out(row) for row in current])

        descendants: list[list[dict[str, Any]]] = []
        parents_ids = [person_id]
        for _ in range(down):
            marks = ",".join("?" * len(parents_ids))
            rows = _rows(
                conn,
                f"SELECT id, name, sex, born, died, mother, father, partner, clan "
                f"FROM persons WHERE world_id = ? AND (mother IN ({marks}) OR father IN ({marks})) "
                f"ORDER BY born, id LIMIT 60",
                (world_id, *parents_ids, *parents_ids),
            )
            if not rows:
                break
            descendants.append([out(row) for row in rows])
            parents_ids = [row["id"] for row in rows]

        return {
            "person": out(centre[0]),
            "partner": out(partner[0]) if partner else None,
            "ancestors": ancestors,
            "descendants": descendants,
        }

    @api.get("/worlds/{world_id}/persons/{person_id}")
    def person(
        world_id: int, person_id: int, conn: Db, lang: Lang = default_language
    ) -> dict[str, Any]:
        row = conn.execute(
            "SELECT * FROM persons WHERE world_id = ? AND id = ?", (world_id, person_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Person {person_id} does not exist")
        tick = world_row(conn, world_id)["tick"]
        end = row["died"] if row["died"] is not None else tick

        def relative(relative_id: int) -> dict[str, Any] | None:
            if not relative_id:
                return None
            found = conn.execute(
                "SELECT id, name FROM persons WHERE world_id = ? AND id = ?",
                (world_id, relative_id),
            ).fetchone()
            return None if found is None else {"id": found["id"], "name": found["name"]}

        children = _rows(
            conn,
            "SELECT id, name FROM persons "
            "WHERE world_id = ? AND (mother = ? OR father = ?) ORDER BY born",
            (world_id, person_id, person_id),
        )
        traits = json.loads(row["traits"])
        clan_row = conn.execute(
            "SELECT name FROM groups WHERE world_id = ? AND id = ?", (world_id, row["clan"])
        ).fetchone()
        return {
            "id": row["id"],
            "name": row["name"],
            "sex": "f" if row["sex"] == 0 else "m",
            "born_year": row["born"] // 360,
            "died_year": None if row["died"] is None else row["died"] // 360,
            "cause": row["cause"],
            "age": (end - row["born"]) // 360,
            "clan": row["clan"],
            "clan_name": None if clan_row is None else clan_row["name"],
            "mother": relative(row["mother"]),
            "father": relative(row["father"]),
            "partner": relative(row["partner"]),
            "children": [{"id": child["id"], "name": child["name"]} for child in children],
            "traits": dict(
                zip(("vigor", "curiosity", "sociability", "craft"), traits, strict=False)
            ),
            "tiles_moved": row["moved"],
            "activity": row["activity"] if row["died"] is None else "",
            "activity_text": activity_text(row["activity"], lang) if row["died"] is None else "",
            "work_months": [
                {"activity": kind, "text": activity_text(kind, lang) or kind, "months": months}
                for kind, months in sorted(
                    json.loads(row["work"]).items(), key=lambda item: (-item[1], item[0])
                )
            ],
            "discoveries": row["discoveries"],
            "gift": row["gift"] or None,
        }

    @api.get("/worlds/{world_id}/technologies")
    def technologies(
        world_id: int, conn: Db, lang: Lang = default_language
    ) -> list[dict[str, Any]]:
        """Everything that can be discovered, with when it was first found and who knows it."""
        world_row(conn, world_id)
        first = {
            row["technology"]: row
            for row in _rows(
                conn,
                "SELECT d.technology, MIN(d.tick) AS tick FROM discoveries d "
                "WHERE d.world_id = ? AND d.how = 'invented' GROUP BY d.technology",
                (world_id,),
            )
        }
        knowing = {
            row["technology"]: row["n"]
            for row in _rows(
                conn,
                "SELECT d.technology, COUNT(*) AS n FROM discoveries d "
                "JOIN groups g ON g.world_id = d.world_id AND g.id = d.group_id "
                "WHERE d.world_id = ? AND g.dissolved IS NULL AND d.lost IS NULL "
                "GROUP BY d.technology",
                (world_id,),
            )
        }
        lost = {
            row["technology"]: row["n"]
            for row in _rows(
                conn,
                "SELECT technology, COUNT(*) AS n FROM discoveries "
                "WHERE world_id = ? AND lost IS NOT NULL GROUP BY technology",
                (world_id,),
            )
        }
        out = []
        for tech_id in sorted(packs.technologies):
            tech = packs.technologies[tech_id]
            found = first.get(tech_id)
            out.append(
                {
                    "id": tech_id,
                    "name": getattr(tech.name, lang),
                    "requires": [
                        getattr(packs.technologies[required].name, lang)
                        for required in tech.requires
                    ],
                    "known": found is not None,
                    "first_year": None if found is None else found["tick"] // 360,
                    "clans_knowing": knowing.get(tech_id, 0),
                    "times_lost": lost.get(tech_id, 0),
                }
            )
        out.sort(key=lambda item: (item["first_year"] is None, item["first_year"] or 0, item["id"]))
        return out

    @api.get("/worlds/{world_id}/events")
    def events(
        world_id: int,
        conn: Db,
        lang: Lang = default_language,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        min_importance: Annotated[int, Query(ge=1, le=5)] = 1,
        before_seq: int | None = None,
        after_seq: int | None = None,
        type: str | None = None,
    ) -> list[dict[str, Any]]:
        """The chronicle, newest first. Page with before_seq, follow with after_seq."""
        world_row(conn, world_id)
        clauses = ["world_id = ?", "importance >= ?"]
        args: list[Any] = [world_id, min_importance]
        if before_seq is not None:
            clauses.append("seq < ?")
            args.append(before_seq)
        if after_seq is not None:
            clauses.append("seq > ?")
            args.append(after_seq)
        if type is not None:
            clauses.append("type = ?")
            args.append(type)
        rows = _rows(
            conn,
            f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT ?",
            (*args, limit),
        )
        return [event_out(row, lang) for row in rows]

    @api.get("/worlds/{world_id}/events/{seq}/why")
    def why(world_id: int, seq: int, conn: Db, lang: Lang = default_language) -> dict[str, Any]:
        """The roll behind an event: rule, factors, chance and what the dice showed."""
        row = conn.execute(
            "SELECT * FROM events WHERE world_id = ? AND seq = ?", (world_id, seq)
        ).fetchone()
        if row is None:
            raise HTTPException(404, f"Event {seq} does not exist")
        data = json.loads(row["data"])
        candidates: list[tuple[str, str, int]] = []
        if "rule" in data and row["region"] is not None:
            candidates.append((data["rule"], "region", row["region"]))
        clan_id = data.get("clan_id")
        if clan_id is not None:
            rule = {
                "discovery": f"discover.{data.get('tech')}",
                "knowledge_shared": f"learn.{data.get('tech')}",
                "migration": "migration",
                "clan_split": "clan_split",
                "clan_merged": "clan_merge",
                "settlement_founded": "settle",
                "settlement_abandoned": "abandon_settlement",
            }.get(row["type"])
            if rule is not None:
                candidates.append((rule, "group", clan_id))
        person_id = data.get("person")
        if person_id is not None and row["type"] in ("birth", "pairing"):
            candidates.append((row["type"], "person", data.get("mother", person_id)))
        decisions = []
        for rule, scope_type, scope_id in candidates:
            for found in _rows(
                conn,
                "SELECT * FROM world_log WHERE world_id = ? AND tick = ? AND rule = ? "
                "AND scope_type = ? AND scope_id = ? ORDER BY seq",
                (world_id, row["tick"], rule, scope_type, scope_id),
            ):
                decisions.append(
                    {
                        "rule": found["rule"],
                        "scope_type": found["scope_type"],
                        "scope_id": found["scope_id"],
                        "factors": [
                            {"name": name, "factor": factor}
                            for name, factor in json.loads(found["factors"])
                        ],
                        "chance": found["chance"],
                        "roll": found["roll"],
                        "fired": None if found["fired"] is None else bool(found["fired"]),
                    }
                )
        oldest = conn.execute(
            "SELECT MIN(tick) FROM world_log WHERE world_id = ?", (world_id,)
        ).fetchone()[0]
        return {
            "event": event_out(row, lang),
            "decisions": decisions,
            # The decision log is a ring buffer: older rolls are gone.
            "expired": not decisions and (oldest is None or row["tick"] < oldest),
        }

    @api.get("/worlds/{world_id}/metrics")
    def metrics(
        world_id: int,
        conn: Db,
        keys: Annotated[str, Query(description="Comma separated metric keys")],
        scope_type: str = "world",
        scope_id: int = 0,
        from_year: int | None = None,
        to_year: int | None = None,
    ) -> dict[str, list[dict[str, float]]]:
        """Yearly time series. Each point is the value recorded at the start of that year."""
        world_row(conn, world_id)
        out: dict[str, list[dict[str, float]]] = {}
        for key in [k.strip() for k in keys.split(",") if k.strip()][:20]:
            clauses = ["world_id = ?", "key = ?", "scope_type = ?", "scope_id = ?"]
            args: list[Any] = [world_id, key, scope_type, scope_id]
            if from_year is not None:
                clauses.append("tick >= ?")
                args.append(from_year * 360)
            if to_year is not None:
                clauses.append("tick <= ?")
                args.append(to_year * 360)
            out[key] = [
                {"year": row["tick"] // 360, "value": row["value"]}
                for row in _rows(
                    conn,
                    f"SELECT tick, value FROM metrics WHERE {' AND '.join(clauses)} ORDER BY tick",
                    tuple(args),
                )
            ]
        return out

    @api.get("/worlds/{world_id}/metric-keys")
    def metric_keys(world_id: int, conn: Db) -> list[str]:
        world_row(conn, world_id)
        return [
            row["key"]
            for row in _rows(
                conn,
                "SELECT DISTINCT key FROM metrics WHERE world_id = ? ORDER BY key",
                (world_id,),
            )
        ]

    @api.get("/events/stream")
    async def stream(
        lang: Lang = default_language,
        min_importance: Annotated[int, Query(ge=1, le=5)] = 1,
        once: bool = False,
    ) -> StreamingResponse:
        """Server-sent events: every new chronicle entry of the active world."""

        async def generate() -> AsyncIterator[str]:
            last_seq: int | None = None
            world_id: int | None = None
            while True:
                try:
                    conn = connect()
                except sqlite3.OperationalError:
                    conn = None
                if conn is not None:
                    try:
                        world = active_world(conn)
                        if world is not None:
                            if world["id"] != world_id:
                                world_id, last_seq = world["id"], None
                            if last_seq is None:
                                newest = conn.execute(
                                    "SELECT COALESCE(MAX(seq), -1) FROM events WHERE world_id = ?",
                                    (world_id,),
                                ).fetchone()[0]
                                last_seq = newest
                            rows = _rows(
                                conn,
                                "SELECT * FROM events WHERE world_id = ? AND seq > ? "
                                "AND importance >= ? ORDER BY seq LIMIT 200",
                                (world_id, last_seq, min_importance),
                            )
                            newest = conn.execute(
                                "SELECT COALESCE(MAX(seq), -1) FROM events WHERE world_id = ?",
                                (world_id,),
                            ).fetchone()[0]
                            for row in rows:
                                payload = json.dumps(event_out(row, lang), ensure_ascii=False)
                                yield f"event: chronicle\ndata: {payload}\n\n"
                            last_seq = max(last_seq, rows[-1]["seq"]) if rows else last_seq
                            if not rows:
                                last_seq = newest
                            yield f"event: tick\ndata: {json.dumps(calendar(world['tick']))}\n\n"
                    finally:
                        conn.close()
                if once:
                    return
                await asyncio.sleep(2)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    app.include_router(api)

    if (WEB_DIR / "index.html").is_file():
        for folder in ("assets", "sprites"):
            if (WEB_DIR / folder).is_dir():
                app.mount(f"/{folder}", StaticFiles(directory=WEB_DIR / folder), name=folder)

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app
