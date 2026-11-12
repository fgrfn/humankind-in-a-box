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
MANY_PEOPLES = (
    "technologies.fire.base_chance_per_year: 0.03\n"
    "technologies.shelter.base_chance_per_year: 0.03\n"
    "technologies.shelter.requires: []\n"
    "life.people_sound_distance: 1\n"
    "life.people_emerge_chance_per_year: 0.2\n"
    "life.people_join_chance_per_year: 0.2\n"
)
TRADERS = "technologies.fire.base_chance_per_year: 0.03\nlife.trade_chance_per_year: 0.5\n"


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


def test_peoples_form_split_and_name_their_places(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, world_with(settings, MANY_PEOPLES), 150, 3)
    society = world.society
    assert society is not None
    assert len(society.cultures) > 1, "one people stayed one in a world built to part"
    first = society.cultures[1]
    assert first.parent == 0 and first.founded == 0
    for culture in society.cultures.values():
        assert culture.parent == 0 or culture.parent in society.cultures
        assert culture.name
        members = [clan for clan in society.clans.values() if clan.culture == culture.id]
        assert bool(members) == (culture.ended is None), culture.name
    assert all(clan.culture in society.cultures for clan in society.clans.values())

    conn = sqlite3.connect(path)
    stored = dict(conn.execute("SELECT id, name FROM cultures"))
    assert stored == {culture.id: culture.name for culture in society.cultures.values()}
    assert dict(conn.execute("SELECT id, culture FROM groups WHERE dissolved IS NULL")) == {
        clan.id: clan.culture for clan in society.clans.values()
    }
    types = {row[0] for row in conn.execute("SELECT DISTINCT type FROM events")}
    assert "people_emerged" in types
    assert conn.execute(
        "SELECT COUNT(*) FROM metrics WHERE key = 'people.population' AND scope_type = 'culture'"
    ).fetchone()[0]

    # A place is called after what is found there, in the words of its people.
    places = list(society.places.values())
    assert places, "somebody settles within 150 years in this world"
    for place in places:
        assert place["meaning"]
        words = {word for culture in society.cultures.values() for word in culture.words.values()}
        assert any(place["name"].startswith(word) for word in words), place["name"]
    assert len({place["name"] for place in places}) == len(places)


@pytest.mark.parametrize("overrides", [EARLY_FARMERS, FORGETFUL, MANY_PEOPLES, TRADERS])
def test_such_worlds_resume_identically(tmp_path: Path, settings: Settings, overrides: str) -> None:
    prepared = world_with(settings, overrides)
    simulate(tmp_path / "straight.sqlite", prepared, 110, 5)
    for years in (41, 23, 46):
        simulate(tmp_path / "resumed.sqlite", prepared, years, 5)
    assert table_digests(tmp_path / "resumed.sqlite") == table_digests(tmp_path / "straight.sqlite")


def test_land_is_held_and_borders_follow_strength(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, world_with(settings, MANY_PEOPLES), 120, 3)
    society = world.society
    assert society is not None
    stored_before = society.territory.copy()
    assert (stored_before > 0).any(), "nobody holds any land after 120 years"
    # Land is shared out at new year and clans move during the year, so share it
    # out once more to compare it with where everybody stands now.
    society.claim()
    territory, land_people = society.territory, society.land_people
    assert not (territory[world.map.water] > 0).any(), "open water is nobody's"
    holders = {int(clan_id) for clan_id in set(territory.ravel().tolist()) if clan_id}
    assert holders <= set(society.clans), "only living clans hold land"
    for clan_id in sorted(holders)[:20]:
        clan = society.clans[clan_id]
        ys, xs = (territory == clan_id).nonzero()
        _strength, radius = society.hold(clan)
        # Nothing is held beyond a clan's reach, and what it holds belongs to its people.
        assert max(abs(ys - clan.y).max(), abs(xs - clan.x).max()) <= max(radius, 0) + 1
        assert (land_people[ys, xs] == clan.culture).all()

    # A stronger clan reaches further than a weaker one.
    clans = sorted(society.clans.values(), key=lambda clan: society.hold(clan)[0])
    assert society.hold(clans[-1])[1] >= society.hold(clans[0])[1]

    conn = sqlite3.connect(path)
    stored = conn.execute("SELECT data FROM tile_layers WHERE layer = 'territory'").fetchone()[0]
    assert stored == stored_before.astype("<i4").tobytes()
    assert (
        conn.execute(
            "SELECT MAX(value) FROM metrics WHERE key = 'territory.tiles' AND scope_type = 'world'"
        ).fetchone()[0]
        > 0
    )


def test_strangers_gather_less_on_held_land(settings: Settings) -> None:
    packs = load_packs(settings.packs, settings.data_dir)
    from hiab.sim.engine import World

    def gathered(foreign: bool) -> int:
        world = World.create(1, 9, packs, 48, 48, 45)
        society = world.society
        assert society is not None
        clan = next(iter(society.clans.values()))
        if foreign:
            society.land_people[:] = clan.culture + 1
        clan.food = 0
        society.forage(clan)
        return clan.food

    assert 0 < gathered(foreign=True) < gathered(foreign=False)


def test_partners_trade_goods_food_and_knowledge(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, world_with(settings, TRADERS), 150, 3)
    society = world.society
    assert society is not None
    linked = [clan for clan in society.clans.values() if clan.partners]
    assert linked, "nobody trades in a world built for trade"
    for clan in linked:
        assert len(clan.partners) <= 3
        for partner_id in clan.partners:
            assert clan.id in society.clans[partner_id].partners, "a partnership has two sides"
    # What a partner has within reach counts as within reach.
    for clan in linked:
        own = set(society.goods(clan))
        for partner_id in clan.partners:
            for resource in set(society.goods(society.clans[partner_id])) - own:
                assert society.nearby(clan, resource)

    conn = sqlite3.connect(path)
    open_links = {
        (a, b)
        for a, b in conn.execute("SELECT group_a, group_b FROM trade_links WHERE ended IS NULL")
    }
    assert open_links == {
        (min(clan.id, other), max(clan.id, other)) for clan in linked for other in clan.partners
    }
    keys = {row[0] for row in conn.execute("SELECT DISTINCT key FROM metrics")}
    assert {"trade.begun", "trade.journeys", "trade.partnerships"} <= keys
    assert conn.execute("SELECT COUNT(*) FROM events WHERE type = 'trade_begun'").fetchone()[0]


def test_stores_fill_are_bounded_and_books_balance(tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "w.sqlite"
    world = simulate(path, world_with(settings, TRADERS), 80, 3)
    society = world.society
    assert society is not None
    assert any(clan.stores.get("wood", 0) > 0 for clan in society.clans.values())
    for clan in society.clans.values():
        assert all(amount >= 0 for amount in clan.stores.values()), clan.name
        assert set(clan.stores) <= set(society.good_ids)
        assert clan.food >= 0
        for good, (gained, used, traded_in, traded_out) in clan.last_flows.items():
            assert good == "food" or good in society.good_ids
            assert min(gained, used, traded_in, traded_out) >= 0

    # Over a year, what a clan has is what it had plus what came minus what went.
    clan = max(society.clans.values(), key=lambda item: len(item.members))
    before = {"food": clan.food, **clan.stores}
    start_flows = {good: list(values) for good, values in clan.flows.items()}
    members = len(clan.members)
    month = world.tick // 30
    while world.tick // 30 == month:
        world.step()
    if clan.id in society.clans and len(clan.members) == members and clan.flows:
        for good, (gained, used, traded_in, traded_out) in clan.flows.items():
            was = start_flows.get(good, [0, 0, 0, 0])
            if gained < was[0]:
                continue  # the clan's year turned in between and the books were closed
            change = (
                (gained - was[0]) - (used - was[1]) + (traded_in - was[2]) - (traded_out - was[3])
            )
            now = clan.food if good == "food" else clan.stores.get(good, 0)
            assert now - before.get(good, 0) == change, good
