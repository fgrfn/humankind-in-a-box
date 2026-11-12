from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hiab.api.app import create_app
from hiab.config import Settings
from hiab.control import Control, read_control, read_pace, write_control
from hiab.db.store import table_digests
from hiab.packs import load_packs
from hiab.worker import Worker, simulate


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    from hiab.config import load_settings

    root = tmp_path_factory.mktemp("api")
    settings: Settings = load_settings(
        {"data_dir": str(root / "data"), "map_width": 48, "map_height": 48, "world_log_years": 30},
        {},
    )
    local = settings.data_dir / "packs" / "local"
    local.mkdir(parents=True)
    (local / "overrides.yaml").write_text(
        "technologies.fire.base_chance_per_year: 0.2\n"
        "technologies.shelter.base_chance_per_year: 0.05\n"
        "technologies.shelter.requires: []\n",
        encoding="utf-8",
    )
    path = root / "w.sqlite"
    simulate(path, settings, 60, 9)
    return TestClient(create_app(path, load_packs(settings.packs, settings.data_dir), "de"))


def test_health_and_world(client: TestClient) -> None:
    health = client.get("/api/v1/health").json()
    assert health["status"] == "ok" and health["world"]["year"] == 60
    worlds = client.get("/api/v1/worlds").json()
    assert [w["id"] for w in worlds] == [1]
    assert client.get("/api/v1/worlds/99").status_code == 404


def test_stats_are_flat_and_plausible(client: TestClient) -> None:
    stats = client.get("/api/v1/worlds/1/stats").json()
    assert all(not isinstance(value, dict | list) for value in stats.values())
    assert stats["year"] == 60 and stats["season"] == "spring"
    assert 0 < stats["population"] <= stats["ever_lived"]
    assert stats["clans"] >= 1 and stats["discoveries"] >= 1
    assert stats["births_total"] > 0 and stats["deaths_total"] > 0


def test_map_has_one_value_per_tile(client: TestClient) -> None:
    world_map = client.get("/api/v1/worlds/1/map").json()
    tiles = world_map["width"] * world_map["height"]
    for layer in ("biome", "elevation", "river", "deposit", "steps"):
        assert len(world_map[layer]) == tiles, layer
    assert max(world_map["biome"]) < len(world_map["biomes"])
    assert sum(world_map["steps"]) > 0
    plants = client.get("/api/v1/worlds/1/layers/plants").json()
    assert len(plants["values"]) == tiles
    assert client.get("/api/v1/worlds/1/layers/unobtainium").status_code == 404


def test_groups_and_persons(client: TestClient) -> None:
    groups = client.get("/api/v1/worlds/1/groups").json()
    stats = client.get("/api/v1/worlds/1/stats").json()
    assert sum(group["population"] for group in groups) == stats["population"]
    detail = client.get(f"/api/v1/worlds/1/groups/{groups[0]['id']}").json()
    assert len(detail["members"]) == detail["population"]
    member = detail["members"][0]
    person = client.get(f"/api/v1/worlds/1/persons/{member['id']}").json()
    assert person["name"] == member["name"] and person["clan"] == groups[0]["id"]
    assert set(person["traits"]) == {"vigor", "curiosity", "sociability", "craft"}
    assert client.get("/api/v1/worlds/1/persons/999999").status_code == 404


def test_events_in_both_languages_and_paging(client: TestClient) -> None:
    german = client.get("/api/v1/worlds/1/events?limit=5&min_importance=3").json()
    english = client.get("/api/v1/worlds/1/events?limit=5&min_importance=3&lang=en").json()
    assert [e["seq"] for e in german] == [e["seq"] for e in english]
    assert german[0]["text"] != english[0]["text"]
    assert "{" not in german[0]["text"] and "{" not in english[0]["text"]
    older = client.get(
        f"/api/v1/worlds/1/events?limit=5&min_importance=3&before_seq={german[-1]['seq']}"
    ).json()
    assert all(e["seq"] < german[-1]["seq"] for e in older)
    assert client.get("/api/v1/worlds/1/events?limit=5000").status_code == 422


def test_why_explains_a_discovery(client: TestClient) -> None:
    recent = client.get("/api/v1/worlds/1/events?type=clan_split&limit=1").json()
    assert recent, "clans split within 60 years in this fixture"
    why = client.get(f"/api/v1/worlds/1/events/{recent[0]['seq']}/why").json()
    decision = why["decisions"][0]
    assert decision["rule"] == "clan_split" and why["expired"] is False
    assert decision["fired"] is True and decision["roll"] < decision["chance"]

    # Fire is found early in this fixture, long before the 30 years the log keeps.
    first = client.get("/api/v1/worlds/1/events?type=discovery&limit=500").json()[-1]
    old = client.get(f"/api/v1/worlds/1/events/{first['seq']}/why").json()
    assert old["decisions"] == [] and old["expired"] is True


def test_technologies_list_everything_discoverable(client: TestClient) -> None:
    techs = client.get("/api/v1/worlds/1/technologies").json()
    assert len(techs) >= 35
    assert all(tech["times_lost"] >= 0 for tech in techs)
    fire = next(tech for tech in techs if tech["id"] == "fire")
    assert fire["known"] and fire["first_year"] is not None and fire["clans_knowing"] >= 1
    assert techs[0]["known"], "known discoveries come first"
    groups = client.get("/api/v1/worlds/1/groups").json()
    assert fire["clans_knowing"] <= len(groups)


def test_metrics_series(client: TestClient) -> None:
    series = client.get(
        "/api/v1/worlds/1/metrics?keys=people.population,clans.count&from_year=10&to_year=20"
    ).json()
    assert [point["year"] for point in series["people.population"]] == list(range(10, 21))
    assert "people.population" in client.get("/api/v1/worlds/1/metric-keys").json()


def test_stream_delivers_the_clock(client: TestClient) -> None:
    body = client.get("/api/v1/events/stream?once=true").text
    assert "event: tick" in body
    tick = json.loads(body.split("event: tick\ndata: ")[1].split("\n")[0])
    assert tick["year"] == 60


def test_openapi_is_served(client: TestClient) -> None:
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/v1/worlds/{world_id}/stats" in paths
    assert Path(__file__).exists()


def test_places_list_what_was_built(client: TestClient) -> None:
    levels = client.get("/api/v1/worlds/1/map").json()["path_levels"]
    assert 0 < levels["trail"] < levels["road"]
    places = client.get("/api/v1/worlds/1/places").json()
    assert places, "somebody settles within 60 years in this fixture"
    buildings = [b for place in places for b in place["buildings"]]
    assert buildings
    assert {b["state"] for b in buildings} <= {"site", "standing", "ruin"}
    assert all(0 <= b["progress_percent"] <= 100 for b in buildings)
    english = client.get("/api/v1/worlds/1/places", params={"lang": "en"}).json()
    names = {b["name"] for place in english for b in place["buildings"]}
    assert names <= {"Gathering fire", "Hut", "Drying rack", "Storage pit", "Kiln"}
    lived_in = next(place for place in places if place["abandoned_year"] is None)
    group = client.get(f"/api/v1/worlds/1/groups/{lived_in['group_id']}").json()
    assert [b["id"] for b in group["buildings"]] == [b["id"] for b in lived_in["buildings"]]


def test_frontend_and_sprites_are_served(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    atlas = client.get("/sprites/atlas.json").json()
    assert {
        "grass",
        "deep_water",
        "oak",
        "path",
        "hut",
        "site",
        "ruin",
        "woman",
        "travellers",
    } <= set(atlas["frames"])
    assert client.get("/sprites/atlas.png").headers["content-type"] == "image/png"


def test_people_and_what_they_do(client: TestClient) -> None:
    people = client.get("/api/v1/worlds/1/people").json()
    assert len(people) == client.get("/api/v1/worlds/1/stats").json()["population"]
    working = [person for person in people if person["activity"]]
    assert working and all(person["text"] for person in working)
    assert all(person["age"] >= 15 for person in working)
    english = client.get("/api/v1/worlds/1/people", params={"lang": "en"}).json()
    assert {person["text"] for person in english} <= {
        "",
        "gathering plants",
        "hunting",
        "fishing",
        "searching for food",
        "building: Gathering fire",
        "building: Hut",
        "fetching wood",
        "collecting flint",
        "gathering salt",
    }
    detail = client.get(f"/api/v1/worlds/1/persons/{working[0]['id']}").json()
    assert detail["activity"] == working[0]["activity"]
    assert detail["clan_name"]
    assert sum(entry["months"] for entry in detail["work_months"]) > 0
    group = client.get(f"/api/v1/worlds/1/groups/{working[0]['clan']}").json()
    assert any(member["activity_text"] for member in group["members"])


def test_peoples_are_listed_with_descent(client: TestClient) -> None:
    peoples = client.get("/api/v1/worlds/1/peoples").json()
    assert peoples and peoples[0]["population"] >= peoples[-1]["population"]
    first = next(item for item in peoples if item["parent_id"] == 0)
    assert first["founded_year"] == 0 and first["parent"] is None
    assert len(first["consonants"]) == 8 and 3 <= len(first["vowels"]) <= 4
    stats = client.get("/api/v1/worlds/1/stats").json()
    assert stats["peoples"] == sum(1 for item in peoples if item["clans"] > 0)
    assert sum(item["population"] for item in peoples) == stats["population"]
    names = {item["name"] for item in peoples}
    groups = client.get("/api/v1/worlds/1/groups").json()
    assert all(group["people"] in names for group in groups)
    german = client.get("/api/v1/worlds/1/places").json()
    assert all(place["meaning"].startswith("Ort: ") for place in german)


def test_territory_layer_matches_the_peoples(client: TestClient) -> None:
    world_map = client.get("/api/v1/worlds/1/map").json()
    land = client.get("/api/v1/worlds/1/territory").json()
    size = world_map["width"] * world_map["height"]
    assert len(land["clans"]) == len(land["peoples"]) == size
    assert any(land["peoples"])
    peoples = client.get("/api/v1/worlds/1/peoples").json()
    for people in peoples:
        assert people["tiles"] == land["peoples"].count(people["id"])
    assert client.get("/api/v1/worlds/1/layers/territory").json()["values"] == land["clans"]


def test_trade_and_since_summary(client: TestClient) -> None:
    links = client.get("/api/v1/worlds/1/trade").json()
    stats = client.get("/api/v1/worlds/1/stats").json()
    assert stats["trade_partnerships"] == len(links)
    for link in links:
        assert link["a"] < link["b"]
        group = client.get(f"/api/v1/worlds/1/groups/{link['a']}").json()
        assert link["b"] in [partner["id"] for partner in group["partners"]]
    summary = client.get("/api/v1/worlds/1/since", params={"year": 20}).json()
    assert summary["from_year"] == 20 and summary["to_year"] == stats["year"]
    assert summary["years"] == stats["year"] - 20
    assert summary["population_now"] == stats["population"]
    assert 0 < summary["births"] < stats["births_total"]
    assert len(summary["highlights"]) <= 8
    assert all(item["importance"] >= 3 and item["year"] >= 20 for item in summary["highlights"])
    assert client.get("/api/v1/worlds/1/since").status_code == 422


def test_stores_are_shown_per_clan_people_and_world(client: TestClient) -> None:
    groups = client.get("/api/v1/worlds/1/groups").json()
    totals: dict[str, int] = {}
    for group in groups:
        goods = {item["id"]: item for item in group["stores"]}
        assert "food" in goods and goods["food"]["name"] == "Nahrung"
        for item in group["stores"]:
            assert item["amount"] >= 0 and item["room"] >= 0
            assert min(item["gained"], item["used"], item["traded_in"], item["traded_out"]) >= 0
            totals[item["id"]] = totals.get(item["id"], 0) + item["amount"]
    assert totals.get("wood", 0) > 0, "somebody has wood in store after 60 years"
    stats = client.get("/api/v1/worlds/1/stats").json()
    world = client.get("/api/v1/worlds/1/stores").json()
    assert world[0]["id"] == "food"
    for item in world:
        assert item["amount"] == totals[item["id"]] == stats[f"stored_{item['id']}"]
    peoples = client.get("/api/v1/worlds/1/peoples").json()
    for good, amount in totals.items():
        assert sum(item["stores"].get(good, 0) for item in peoples) == amount
    keys = client.get("/api/v1/worlds/1/metric-keys").json()
    assert "stores.food" in keys and "stores.wood" in keys


def test_speed_can_be_changed_through_a_file_only(tmp_path: Path, settings: Settings) -> None:
    db = tmp_path / "w.sqlite"
    simulate(db, settings, 3, 1)
    packs = load_packs(settings.packs, settings.data_dir)
    before = table_digests(db)
    with TestClient(create_app(db, packs, "de", data_dir=settings.data_dir)) as open_client:
        state = open_client.get("/api/v1/control").json()
        assert state["speed"] == 1 and state["paused"] is False and state["changeable"] is True
        assert state["speeds"] == [1, 5, 25, 0] and state["year"] == 3

        fast = open_client.put("/api/v1/control", json={"speed": 25, "for_years": 10}).json()
        assert fast["speed"] == 25 and fast["until_year"] == 13
        assert read_control(settings.data_dir).speed == 25

        paused = open_client.put("/api/v1/control", json={"paused": True}).json()
        assert paused["paused"] is True and paused["speed"] == 25 and paused["until_year"] == 13

        normal = open_client.put("/api/v1/control", json={"speed": 1, "paused": False}).json()
        assert normal == {**normal, "speed": 1, "paused": False, "until_year": None}
        assert open_client.put("/api/v1/control", json={"speed": 7}).status_code == 422
    assert table_digests(db) == before, "changing the speed must not touch the database"

    with TestClient(
        create_app(db, packs, "de", data_dir=settings.data_dir, api_token="s3cret")
    ) as locked:
        assert locked.get("/api/v1/control").json()["token_required"] is True
        assert locked.put("/api/v1/control", json={"speed": 5}).status_code == 401
        wrong = {"Authorization": "Bearer nope"}
        assert locked.put("/api/v1/control", json={"speed": 5}, headers=wrong).status_code == 401
        right = {"Authorization": "Bearer s3cret"}
        assert locked.put("/api/v1/control", json={"speed": 5}, headers=right).json()["speed"] == 5

    with TestClient(create_app(db, packs, "de")) as fixed:
        assert fixed.get("/api/v1/control").json()["changeable"] is False
        assert fixed.put("/api/v1/control", json={"speed": 5}).status_code == 409


def test_worker_follows_the_speed_file(tmp_path: Path, settings: Settings) -> None:
    def stored_tick() -> int:
        found = sqlite3.connect(quick.db_path).execute("SELECT tick FROM worlds").fetchone()
        return int(found[0])

    quick = settings.model_copy(update={"pace": 30.0, "autosave_seconds": 1.0, "api": False})
    write_control(quick.data_dir, Control(paused=True))
    worker = Worker(quick)
    thread = threading.Thread(target=lambda: worker.run(seed=4, handle_signals=False))
    thread.start()
    try:
        time.sleep(2.0)
        assert stored_tick() == 0, "a paused world stands still"
        write_control(quick.data_dir, Control(speed=0, until_year=2))
        deadline = time.monotonic() + 60
        while read_control(quick.data_dir).speed != 1 and time.monotonic() < deadline:
            time.sleep(0.2)
        assert read_control(quick.data_dir) == Control(), "back to normal once the year is reached"
        time.sleep(2.5)
        assert read_pace(quick.data_dir)["running"] is True
    finally:
        worker.request_stop()
        thread.join(timeout=30)
    # It stops speeding in the year asked for, not some years later.
    assert 2 * 360 <= stored_tick() < 3 * 360
