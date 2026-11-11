from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hiab.api.app import create_app
from hiab.config import Settings
from hiab.packs import load_packs
from hiab.worker import simulate


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
    assert len(techs) == 10
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
    assert {"grass", "deep_water", "oak", "path"} <= set(atlas["frames"])
    assert client.get("/sprites/atlas.png").headers["content-type"] == "image/png"
