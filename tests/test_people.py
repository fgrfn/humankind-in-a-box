from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from hiab.config import Settings
from hiab.packs import find_pack, load_packs
from hiab.sim.engine import DAYS_PER_YEAR, World
from hiab.worker import simulate


def test_world_starts_with_the_first_families() -> None:
    packs = load_packs(["base"])
    world = World.create(1, 12, packs, 48, 48, 45)
    society = world.society
    assert society is not None and packs.life is not None
    assert len(society.clans) == packs.life.start_peoples
    # Every starting people is a clan of its own, with a speech of its own.
    assert len(society.cultures) == packs.life.start_peoples
    assert len({clan.culture for clan in society.clans.values()}) == packs.life.start_peoples
    assert len({clan.language["c"] for clan in society.clans.values()}) == packs.life.start_peoples
    for clan in society.clans.values():
        adults = society.adults(clan)
        assert len(adults) == 2 * packs.life.start_families
        assert all(adult.partner for adult in adults)
        assert society.campable[clan.y, clan.x]
    # They begin apart from each other.
    camps = [(clan.y, clan.x) for clan in society.clans.values()]
    closest = min(
        max(abs(a[0] - b[0]), abs(a[1] - b[1])) for i, a in enumerate(camps) for b in camps[i + 1 :]
    )
    assert closest >= 6


def test_pack_without_life_has_no_people(tmp_path: Path) -> None:
    target = tmp_path / "packs" / "base"
    shutil.copytree(find_pack("base", None), target)
    (target / "life.yaml").unlink()
    world = World.create(1, 12, load_packs(["base"], tmp_path), 48, 48, 45)
    assert world.society is None
    for _ in range(2 * DAYS_PER_YEAR):
        world.step()


def test_society_stays_consistent(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, settings, 150, 5)
    society = world.society
    assert society is not None and society.living() > 0

    for clan in society.clans.values():
        assert clan.members == sorted(clan.members)
        for person_id in clan.members:
            person = society.persons[person_id]
            assert person.clan == clan.id and person.died is None
            if person.partner:
                partner = society.persons[person.partner]
                assert partner.partner == person.id and partner.sex != person.sex
                assert not society.related(person, partner)
    assert sum(len(ids) for ids in society.by_month.values()) == society.living()
    for resource in world.stock_ids:
        assert (world.stocks[resource] >= 0).all()

    conn = sqlite3.connect(path)
    try:
        living = conn.execute("SELECT COUNT(*) FROM persons WHERE died IS NULL").fetchone()[0]
        assert living == society.living()
        born, died = conn.execute(
            "SELECT SUM(CASE WHEN key = 'people.births' THEN value END), "
            "SUM(CASE WHEN key = 'people.deaths' THEN value END) FROM metrics"
        ).fetchone()
        assert born > 0 and died > 0
        clans = conn.execute("SELECT COUNT(*) FROM groups WHERE dissolved IS NULL").fetchone()[0]
        assert clans == len(society.clans)
        assert conn.execute("SELECT data FROM tile_layers WHERE layer = 'steps'").fetchone()
    finally:
        conn.close()


def test_every_discovery_can_be_explained(tmp_path: Path, settings: Settings) -> None:
    """The world log holds the roll behind each discovery: rule, factors, chance, roll."""
    local = settings.data_dir / "packs" / "local"
    local.mkdir(parents=True)
    (local / "overrides.yaml").write_text(
        "technologies.fire.base_chance_per_year: 0.2\n", encoding="utf-8"
    )
    path = tmp_path / "w.sqlite"
    simulate(path, settings, 40, 9)
    conn = sqlite3.connect(path)
    try:
        events = conn.execute("SELECT tick, data FROM events WHERE type = 'discovery'").fetchall()
        assert events, "with a 20 percent chance per year fire should be found within 40 years"
        for tick, data in events:
            info = json.loads(data)
            row = conn.execute(
                "SELECT chance, roll, fired FROM world_log "
                "WHERE tick = ? AND rule = ? AND scope_type = 'group' AND scope_id = ?",
                (tick, f"discover.{info['tech']}", info["clan_id"]),
            ).fetchone()
            assert row is not None and row[2] == 1 and row[1] < row[0]
        packs = conn.execute("SELECT pack FROM pack_versions").fetchall()
        assert ("local",) in packs
    finally:
        conn.close()


@pytest.mark.slow
def test_humankind_usually_survives(tmp_path: Path, settings: Settings) -> None:
    alive = 0
    for seed in range(1, 7):
        world = simulate(tmp_path / f"s{seed}.sqlite", settings, 200, seed)
        assert world.society is not None
        alive += world.society.living() > 0
    assert alive >= 5
