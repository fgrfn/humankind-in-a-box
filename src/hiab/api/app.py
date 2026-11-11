"""The HTTP API. It only reads: the worker is the single writer of the database.

Everything the browser shows comes from here, and so does everything an
external consumer (a REST sensor, a script) can ask.
"""

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Annotated, Any, Literal

import numpy as np
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from hiab import __version__
from hiab.packs import BIOMES, PackSet
from hiab.render import calendar, render_event

Language = Literal["de", "en"]
WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _rows(conn: sqlite3.Connection, sql: str, args: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(sql, args).fetchall()


def _layer(blob: bytes) -> list[int]:
    values: list[int] = np.frombuffer(blob, dtype="<i4").tolist()
    return values


def create_app(db_path: Path, packs: PackSet, default_language: Language = "de") -> FastAPI:
    app = FastAPI(
        title="Humankind in a Box",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
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
        }

    @api.get("/worlds/{world_id}/layers/{layer}")
    def layer(world_id: int, layer: str, conn: Db) -> dict[str, Any]:
        """One changing layer: 'steps' or the current stock of a resource."""
        world_row(conn, world_id)
        if layer == "steps":
            found = conn.execute(
                "SELECT data FROM tile_layers WHERE world_id = ? AND layer = 'steps'", (world_id,)
            ).fetchone()
        else:
            found = conn.execute(
                "SELECT data FROM tile_stocks WHERE world_id = ? AND resource = ?",
                (world_id, layer),
            ).fetchone()
        if found is None:
            raise HTTPException(404, f"Layer '{layer}' does not exist")
        return {"layer": layer, "values": _layer(found["data"])}

    def group_out(conn: sqlite3.Connection, row: sqlite3.Row, language: Language) -> dict[str, Any]:
        place = None
        if row["place"]:
            found = conn.execute(
                "SELECT name FROM places WHERE world_id = ? AND id = ?",
                (row["world_id"], row["place"]),
            ).fetchone()
            place = None if found is None else found["name"]
        techs = _rows(
            conn,
            "SELECT technology, tick, how FROM discoveries WHERE world_id = ? AND group_id = ? "
            "ORDER BY tick, technology",
            (row["world_id"], row["id"]),
        )
        return {
            "id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "y": row["y"],
            "x": row["x"],
            "settled": bool(row["settled"]),
            "place": place,
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
            "SELECT id, name, sex, born, children FROM persons "
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
            }
            for member in members
        ]
        return item

    @api.get("/worlds/{world_id}/persons/{person_id}")
    def person(world_id: int, person_id: int, conn: Db) -> dict[str, Any]:
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
        return {
            "id": row["id"],
            "name": row["name"],
            "sex": "f" if row["sex"] == 0 else "m",
            "born_year": row["born"] // 360,
            "died_year": None if row["died"] is None else row["died"] // 360,
            "cause": row["cause"],
            "age": (end - row["born"]) // 360,
            "clan": row["clan"],
            "mother": relative(row["mother"]),
            "father": relative(row["father"]),
            "partner": relative(row["partner"]),
            "children": [{"id": child["id"], "name": child["name"]} for child in children],
            "traits": dict(
                zip(("vigor", "curiosity", "sociability", "craft"), traits, strict=False)
            ),
            "tiles_moved": row["moved"],
            "discoveries": row["discoveries"],
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
                "WHERE d.world_id = ? AND g.dissolved IS NULL GROUP BY d.technology",
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
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(WEB_DIR / "index.html")

    return app
