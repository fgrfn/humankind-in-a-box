"""Command line entry point: ``hiab``."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from hiab import __version__
from hiab.config import ConfigError, Settings, load_settings
from hiab.db.store import Store, WorldNotFound, table_digests
from hiab.logging_setup import get_logger, setup_logging
from hiab.packs import PackError, load_packs
from hiab.sim.engine import DAYS_PER_MONTH, DAYS_PER_YEAR
from hiab.worker import Worker, open_world, simulate

log = get_logger("cli")


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", dest="data_dir", help="data folder (default: per-user folder)")
    parser.add_argument("--log-level", dest="log_level")
    parser.add_argument("--packs", help="comma separated pack names, default: base")


def _settings(args: argparse.Namespace, to_file: bool) -> Settings:
    cli: dict[str, Any] = {}
    for name in ("data_dir", "log_level", "seed", "pace", "port", "map_width", "map_height"):
        if getattr(args, name, None) is not None:
            cli[name] = getattr(args, name)
    if getattr(args, "packs", None):
        cli["packs"] = [p.strip() for p in args.packs.split(",") if p.strip()]
    settings = load_settings(cli)
    setup_logging(
        settings.log_level,
        settings.log_levels,
        settings.data_dir / "logs" if to_file and settings.log_to_file else None,
    )
    return settings


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings(args, to_file=True)
    log.info("starting", extra={"version": __version__, "settings": settings.public_dict()})
    Worker(settings).run(args.seed)
    return 0


def cmd_new_world(args: argparse.Namespace) -> int:
    settings = _settings(args, to_file=True)
    packs = load_packs(settings.packs, settings.data_dir)
    store = Store(settings.db_path)
    try:
        current = store.active_world_id()
        if current is not None:
            with store.conn:
                store.conn.execute("UPDATE worlds SET status = 'archived' WHERE id = ?", (current,))
        world = open_world(store, settings, packs, args.seed, force_new=True)
    finally:
        store.close()
    print(f"World {world.id} created with seed {world.seed}")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    settings = _settings(args, to_file=False)
    world = simulate(Path(args.out), settings, args.years, args.seed)
    print(f"World {world.id}, seed {world.seed}: now in year {world.year} ({args.out})")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    first, second = table_digests(Path(args.first)), table_digests(Path(args.second))
    different = [table for table in first if first[table] != second[table]]
    for table in first:
        mark = "DIFFERENT" if table in different else "identical"
        print(f"{table:15} {first[table][0]:>9} / {second[table][0]:<9} rows  {mark}")
    if different:
        print(f"Result: the worlds differ in {len(different)} table(s).")
        return 1
    print("Result: both worlds are identical.")
    return 0


def cmd_events(args: argparse.Namespace) -> int:
    settings = _settings(args, to_file=False)
    packs = load_packs(settings.packs, settings.data_dir)
    path = Path(args.db) if args.db else settings.db_path
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT tick, type, data FROM events WHERE importance >= ? "
            "ORDER BY world_id, seq DESC LIMIT ?",
            (args.min_importance, args.limit),
        ).fetchall()
    finally:
        conn.close()
    language = args.lang or settings.language
    for tick, event_type, data_json in reversed(rows):
        data = json.loads(data_json)
        definition = packs.events.get(event_type)
        template = getattr(definition.text, language) if definition else event_type
        values = {key: str(value) for key, value in data.items()}
        if "region" in data:
            values["region"] = f"Region {data['region']}"
        technology = packs.technologies.get(str(data.get("tech")))
        if technology is not None:
            values["tech"] = getattr(technology.name, language)
        text = template
        for key in sorted(values):
            text = text.replace("{" + key + "}", values[key])
        year, day = divmod(tick, DAYS_PER_YEAR)
        print(f"{year:>5}-{day // DAYS_PER_MONTH + 1:02}-{day % DAYS_PER_MONTH + 1:02}  {text}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    settings = _settings(args, to_file=False)
    packs = load_packs(settings.packs, settings.data_dir)
    path = Path(args.db) if args.db else settings.db_path
    language = args.lang or settings.language
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        world = conn.execute(
            "SELECT id, seed, tick FROM worlds WHERE status = 'active' ORDER BY id LIMIT 1"
        ).fetchone()
        if world is None:
            print("No active world.")
            return 1
        world_id, seed, tick = world
        living = conn.execute(
            "SELECT COUNT(*) FROM persons WHERE world_id = ? AND died IS NULL", (world_id,)
        ).fetchone()[0]
        ever = conn.execute(
            "SELECT COUNT(*) FROM persons WHERE world_id = ?", (world_id,)
        ).fetchone()[0]
        groups = conn.execute(
            "SELECT g.name, g.settled, COUNT(p.id) FROM groups g "
            "LEFT JOIN persons p ON p.world_id = g.world_id AND p.clan = g.id AND p.died IS NULL "
            "WHERE g.world_id = ? AND g.dissolved IS NULL GROUP BY g.id ORDER BY 3 DESC, g.id",
            (world_id,),
        ).fetchall()
        known = conn.execute(
            "SELECT technology, MIN(tick), COUNT(*) FROM discoveries WHERE world_id = ? "
            "GROUP BY technology ORDER BY 2, 1",
            (world_id,),
        ).fetchall()
        events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE world_id = ?", (world_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    german = language == "de"
    print(f"{'Welt' if german else 'World'} {world_id}, Seed {seed}")
    print(f"{'Jahr' if german else 'Year'}: {tick // DAYS_PER_YEAR}")
    living_label = "Lebende" if german else "Living"
    ever_label = "je gelebt" if german else "ever lived"
    print(f"{living_label}: {living} ({ever_label}: {ever})")
    settled = sum(1 for _name, is_settled, _count in groups if is_settled)
    print(f"Clans: {len(groups)}, {'davon sesshaft' if german else 'settled'}: {settled}")
    for name, is_settled, count in groups[: args.limit]:
        mark = " *" if is_settled else ""
        print(f"  {name}{mark}: {count}")
    print(f"{'Entdeckungen' if german else 'Discoveries'}: {len(known)}")
    for tech_id, first, clans in known:
        technology = packs.technologies.get(tech_id)
        label = getattr(technology.name, language) if technology else tech_id
        since = "seit Jahr" if german else "since year"
        print(f"  {label}: {since} {first // DAYS_PER_YEAR}, Clans: {clans}")
    print(f"{'Ereignisse' if german else 'Events'}: {events}")
    return 0


def cmd_check_packs(args: argparse.Namespace) -> int:
    settings = _settings(args, to_file=False)
    packs = load_packs(settings.packs, settings.data_dir)
    print(
        f"Packs OK: {packs.versions} with {len(packs.resources)} resources, "
        f"{len(packs.events)} event types, {len(packs.rules)} rules"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hiab", description="Humankind in a Box")
    parser.add_argument("--version", action="version", version=f"hiab {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the world and keep it running")
    _common(run)
    run.add_argument("--seed", type=int, help="seed if a new world has to be created")
    run.add_argument("--pace", type=float, help="world days per real minute")
    run.add_argument("--port", type=int)
    run.set_defaults(func=cmd_run)

    new_world = sub.add_parser("new-world", help="archive the active world and start a new one")
    _common(new_world)
    new_world.add_argument("--seed", type=int)
    new_world.add_argument("--map-width", dest="map_width", type=int)
    new_world.add_argument("--map-height", dest="map_height", type=int)
    new_world.set_defaults(func=cmd_new_world)

    sim = sub.add_parser("simulate", help="run a world as fast as possible into a database file")
    _common(sim)
    sim.add_argument("--years", type=int, required=True)
    sim.add_argument("--seed", type=int)
    sim.add_argument("--out", required=True, help="database file; continued if it has a world")
    sim.add_argument("--map-width", dest="map_width", type=int)
    sim.add_argument("--map-height", dest="map_height", type=int)
    sim.set_defaults(func=cmd_simulate)

    verify = sub.add_parser("verify", help="compare two database files table by table")
    verify.add_argument("first")
    verify.add_argument("second")
    verify.set_defaults(func=cmd_verify)

    events = sub.add_parser("events", help="print the chronicle")
    _common(events)
    events.add_argument("--db", help="database file (default: the one in the data folder)")
    events.add_argument("--lang", choices=("de", "en"))
    events.add_argument("--limit", type=int, default=30)
    events.add_argument("--min-importance", dest="min_importance", type=int, default=1)
    events.set_defaults(func=cmd_events)

    status = sub.add_parser("status", help="print a short summary of the world")
    _common(status)
    status.add_argument("--db", help="database file (default: the one in the data folder)")
    status.add_argument("--lang", choices=("de", "en"))
    status.add_argument("--limit", type=int, default=10, help="how many clans to list")
    status.set_defaults(func=cmd_status)

    check = sub.add_parser("check-packs", help="load and validate the data packs")
    _common(check)
    check.set_defaults(func=cmd_check_packs)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (ConfigError, PackError, WorldNotFound) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except sqlite3.OperationalError as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 2
