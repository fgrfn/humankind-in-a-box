from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from hiab.config import Settings
from hiab.db.store import table_digests
from hiab.packs import load_packs
from hiab.worker import simulate

EARLY_FARMERS = (
    "technologies.fire.base_chance_per_year: 0.03\n"
    "technologies.shelter.base_chance_per_year: 0.03\n"
    "technologies.shelter.requires: []\n"
    "technologies.grinding_stones.base_chance_per_year: 0.03\n"
    "technologies.grinding_stones.requires: []\n"
    "technologies.farming.base_chance_per_year: 0.03\n"
)
FORGETFUL = (
    "technologies.fire.base_chance_per_year: 0.05\n"
    "technologies.herbal_lore.base_chance_per_year: 0.05\n"
    "life.knowledge_keepers: 1000\n"
    "life.knowledge_loss_chance_per_year: 0.1\n"
)


def world_with(settings: Settings, overrides: str) -> Settings:
    local = settings.data_dir / "packs" / "local"
    local.mkdir(parents=True)
    (local / "overrides.yaml").write_text(overrides, encoding="utf-8")
    return settings


def test_graph_is_sound() -> None:
    packs = load_packs(["base"])
    techs = packs.technologies
    assert len(techs) >= 35
    foods = set(packs.foods())
    for tech_id, tech in techs.items():
        assert set(tech.requires) <= set(techs), tech_id
        assert set(tech.effects.harvest_percent) <= foods, tech_id
    # Nothing requires itself, however long the way round.
    for start in techs:
        seen, todo = set(), list(techs[start].requires)
        while todo:
            current = todo.pop()
            assert current != start, f"{start} requires itself"
            if current not in seen:
                seen.add(current)
                todo.extend(techs[current].requires)
    # Soil feeds nobody who has not learned to farm it.
    assert packs.resources["soil"].harvest_base_percent == 0


def test_farmers_live_off_the_soil_and_stay_together(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, world_with(settings, EARLY_FARMERS), 150, 3)
    society = world.society
    assert society is not None and world.packs.life is not None
    farmers = [clan for clan in society.clans.values() if "farming" in clan.techs]
    assert farmers, "somebody farms within 150 years in this world"
    for clan in farmers:
        harvest, _mortality, _storage, together = society.effects(clan)
        assert harvest["soil"] > 0
        assert together > world.packs.life.clan_split_adults
    conn = sqlite3.connect(path)
    gathered = conn.execute(
        "SELECT SUM(value) FROM metrics WHERE key = 'food.soil.gathered'"
    ).fetchone()[0]
    assert gathered and gathered > 0
    assert conn.execute("SELECT SUM(value) FROM metrics WHERE key = 'work.soil'").fetchone()[0] > 0


def test_knowledge_can_be_lost_and_stays_on_record(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, world_with(settings, FORGETFUL), 120, 5)
    society = world.society
    assert society is not None
    conn = sqlite3.connect(path)
    lost = conn.execute("SELECT COUNT(*) FROM discoveries WHERE lost IS NOT NULL").fetchone()[0]
    assert lost > 0, "nothing was forgotten in a world built to forget"
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type = 'knowledge_lost'").fetchone()[0]
    assert conn.execute("SELECT SUM(value) FROM metrics WHERE key = 'knowledge.lost'").fetchone()[0]
    # What the database says a living clan knows is what it knows.
    for clan in society.clans.values():
        stored = {
            row[0]
            for row in conn.execute(
                "SELECT technology FROM discoveries WHERE group_id = ? AND lost IS NULL",
                (clan.id,),
            )
        }
        assert stored == set(clan.techs), clan.name
        # Nothing is forgotten while something else still builds on it.
        for tech_id in clan.techs:
            assert set(world.packs.technologies[tech_id].requires) <= set(clan.techs)


@pytest.mark.parametrize("overrides", [EARLY_FARMERS, FORGETFUL])
def test_such_worlds_resume_identically(tmp_path: Path, settings: Settings, overrides: str) -> None:
    prepared = world_with(settings, overrides)
    simulate(tmp_path / "straight.sqlite", prepared, 110, 5)
    for years in (41, 23, 46):
        simulate(tmp_path / "resumed.sqlite", prepared, years, 5)
    assert table_digests(tmp_path / "resumed.sqlite") == table_digests(tmp_path / "straight.sqlite")
