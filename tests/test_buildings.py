from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from hiab.config import Settings
from hiab.db.store import CONTENT_TABLES, table_digests
from hiab.packs import PackError, find_pack, load_packs
from hiab.sim.engine import World
from hiab.worker import simulate

EARLY_HUTS = (
    "technologies.fire.base_chance_per_year: 0.02\n"
    "technologies.shelter.base_chance_per_year: 0.02\n"
    "technologies.shelter.requires: []\n"
)


@pytest.fixture
def early(settings: Settings) -> Settings:
    """A world in which huts and fire are found within a few years."""
    local = settings.data_dir / "packs" / "local"
    local.mkdir(parents=True)
    (local / "overrides.yaml").write_text(EARLY_HUTS, encoding="utf-8")
    return settings


def test_settled_clans_build_and_tread_paths(tmp_path: Path, early: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, early, 120, 3)
    society = world.society
    assert society is not None
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    standing = conn.execute(
        "SELECT * FROM buildings WHERE state = 'standing' ORDER BY id"
    ).fetchall()
    assert standing, "nobody built anything in 120 years"
    assert "buildings" in CONTENT_TABLES
    assert {row["type"] for row in standing} <= set(world.packs.buildings)
    for row in standing:
        assert row["finished"] is not None and row["finished"] >= row["started"]
        assert row["progress"] >= world.packs.buildings[row["type"]].work

    # What the database holds is what the running world holds.
    in_memory = sorted(
        (b["id"], b["state"]) for place in society.places.values() for b in place["buildings"]
    )
    stored = [
        (row["id"], row["state"])
        for row in conn.execute("SELECT id, state FROM buildings ORDER BY id")
    ]
    assert stored == in_memory

    # Every building belongs to a place and stands on land near it.
    for row in conn.execute("SELECT * FROM buildings"):
        place = society.places[row["place_id"]]
        assert max(abs(row["y"] - place["y"]), abs(row["x"] - place["x"])) <= 4
        assert society.campable[row["y"], row["x"]]

    types = {row["type"] for row in conn.execute("SELECT DISTINCT type FROM events").fetchall()}
    assert {"construction_started", "building_finished"} <= types

    keys = {row[0] for row in conn.execute("SELECT DISTINCT key FROM metrics")}
    assert {"buildings.standing", "paths.trail_tiles", "materials.wood.used"} <= keys
    trails = conn.execute(
        "SELECT MAX(value) FROM metrics WHERE key = 'paths.trail_tiles'"
    ).fetchone()[0]
    assert trails > 0


def test_footsteps_fade(early: Settings) -> None:
    packs = load_packs(early.packs, early.data_dir)
    assert packs.life is not None
    world = World.create(1, 5, packs, 48, 48, 45)
    society = world.society
    assert society is not None
    society.steps[10, 10] = 1000
    society.new_year()
    assert society.steps[10, 10] == 1000 * (100 - packs.life.steps_decay_percent_per_year) // 100


def test_old_everyday_events_are_thinned(tmp_path: Path, early: Settings) -> None:
    path = tmp_path / "w.sqlite"
    thin = early.model_copy(update={"event_detail_years": 20})
    world = simulate(path, thin, 80, 3)
    conn = sqlite3.connect(path)
    cutoff = world.tick - 20 * 360
    old_minor = conn.execute(
        "SELECT COUNT(*) FROM events WHERE importance <= 1 AND tick < ?", (cutoff,)
    ).fetchone()[0]
    old_major = conn.execute(
        "SELECT COUNT(*) FROM events WHERE importance > 1 AND tick < ?", (cutoff,)
    ).fetchone()[0]
    assert old_minor == 0
    assert old_major > 0


def test_building_with_unknown_technology_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "packs" / "base"
    shutil.copytree(find_pack("base", None), target)
    with (target / "buildings.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            "tower:\n  name: {de: Turm, en: Tower}\n  requires: [alchemy]\n"
            "  materials: {wood: 10}\n  work: 5\n"
        )
    with pytest.raises(PackError, match="alchemy"):
        load_packs(["base"], tmp_path)


def test_building_worlds_resume_identically(tmp_path: Path, early: Settings) -> None:
    thin = early.model_copy(update={"event_detail_years": 20})
    simulate(tmp_path / "straight.sqlite", thin, 150, 3)
    for years in (37, 61, 52):
        simulate(tmp_path / "resumed.sqlite", thin, years, 3)
    straight = table_digests(tmp_path / "straight.sqlite")
    assert straight["buildings"][0] > 0
    assert table_digests(tmp_path / "resumed.sqlite") == straight


def test_every_adult_has_work_and_builders_build(tmp_path: Path, early: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, early, 120, 3)
    society = world.society
    assert society is not None and world.packs.life is not None
    foods = set(world.packs.foods())
    seen: set[str] = set()
    for clan in society.clans.values():
        grown = {person.id for person in society.adults(clan)}
        for person_id in clan.members:
            person = society.persons[person_id]
            kind = person.activity.split(":", 1)[0]
            if person_id in grown:
                assert kind in foods | {"build", "search"}, person.activity
                assert sum(person.work.values()) > 0
                # Work is done near the camp, never across the map.
                assert max(abs(person.target_y - clan.y), abs(person.target_x - clan.x)) <= 6
                seen.add(kind)
            else:
                assert person.activity == ""
    assert seen & foods

    conn = sqlite3.connect(path)
    keys = {row[0] for row in conn.execute("SELECT DISTINCT key FROM metrics")}
    assert "work.build" in keys, "somebody built in 120 years"
    assert any(key.startswith("work.") and key != "work.build" for key in keys)
    # A whole working life adds up: nobody worked more months than they were adult.
    tick = conn.execute("SELECT tick FROM worlds").fetchone()[0]
    adult_age = world.packs.life.adult_age
    for born, work in conn.execute("SELECT born, work FROM persons WHERE died IS NULL"):
        months = sum(json.loads(work).values())
        assert months <= max(0, (tick - born) // 30 - adult_age * 12) + 1
