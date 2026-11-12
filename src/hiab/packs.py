"""Data packs: all world content lives in YAML, the core knows no concrete resource.

A pack is a folder with ``pack.yaml`` and optional ``resources.yaml``,
``events.yaml`` and ``rules.yaml``. Packs are merged in order; a later pack
replaces entries with the same id. ``packs/local/overrides.yaml`` in the data
folder then overrides single values by dotted path, for example
``rules.drought.base_chance_per_year: 0.08``.
"""

from __future__ import annotations

import hashlib
import json
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hiab.logging_setup import get_logger

log = get_logger("packs")

BIOMES = (
    "ocean",
    "coast",
    "river",
    "tundra",
    "taiga",
    "forest",
    "grassland",
    "steppe",
    "desert",
    "mountain",
    "marsh",
)
SEASONS = ("spring", "summer", "autumn", "winter")
STATIC_FACTS = ("arid", "wet", "cold", "hot", "coastal", "mountainous", "forested")
DYNAMIC_FACTS = ("warm_phase", "cold_phase")
CLAN_FACTS = (
    "hungry",
    "well_fed",
    "large",
    "small",
    "curious",
    "crafty",
    "coastal",
    "cold",
    "settled",
)
SECTIONS = ("resources", "events", "rules", "technologies", "buildings")


class PackError(Exception):
    """A pack is missing or invalid. The message names the file and the problem."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Text(_Model):
    de: str
    en: str


class Resource(_Model):
    kind: Literal["stock", "deposit"]
    name: Text
    # stock: amount a tile of that biome can hold (0..1000) and how it regrows
    capacity: dict[str, int] = Field(default_factory=dict)
    regrowth_percent_per_month: int = Field(0, ge=0, le=100)
    season_percent: dict[str, int] = Field(default_factory=dict)
    # stock that people can eat: food per harvested unit, and how much of the
    # harvestable amount people get without any knowledge (percent)
    food_value: int = Field(0, ge=0, le=100)
    # what somebody is doing who goes out for this resource, for display
    work: Text | None = None
    harvest_base_percent: int = Field(0, ge=0, le=300)
    # Stores: how many units one person brings home in a month of going out for
    # it (0: nobody stores it), and what a clan must know to do so.
    gather_per_worker: int = Field(0, ge=0, le=100000)
    gather_requires: list[str] = Field(default_factory=list)
    # deposit: chance per land tile of that biome, in permille
    occurrence_permille: dict[str, int] = Field(default_factory=dict)


class EventType(_Model):
    importance: int = Field(ge=1, le=5)
    text: Text


class Effect(_Model):
    type: Literal["stock_loss", "stock_gain", "regrowth_modifier"]
    resources: list[str]
    percent: int = Field(ge=0, le=1000)
    months: int = Field(0, ge=0, le=1200)


class Rule(_Model):
    scope: Literal["region", "world"]
    check: Literal["yearly"] = "yearly"
    month: int = Field(1, ge=1, le=12, description="Month of the year in which it is checked")
    base_chance_per_year: float = Field(ge=0.0, le=1.0)
    requires: list[str] = Field(default_factory=list)
    factors: dict[str, float] = Field(default_factory=dict)
    event: str
    effects: list[Effect] = Field(default_factory=list)


class TechEffects(_Model):
    harvest_percent: dict[str, int] = Field(default_factory=dict)  # added to the base percent
    mortality_percent: int = Field(100, ge=10, le=200)  # multiplies every death chance
    storage_months: int = Field(0, ge=0, le=60)  # added to the months of food a clan can keep
    enables_settlement: bool = False
    group_adults: int = Field(0, ge=0, le=100000)  # more adults a group can hold together


class Technology(_Model):
    name: Text
    requires: list[str] = Field(default_factory=list)
    needs_nearby: list[str] = Field(default_factory=list)
    base_chance_per_year: float = Field(ge=0.0, le=1.0)
    factors: dict[str, float] = Field(default_factory=dict)
    effects: TechEffects = Field(default_factory=TechEffects)


class Building(_Model):
    name: Text
    requires: list[str] = Field(default_factory=list)
    materials: dict[str, int] = Field(default_factory=dict)  # stock resource -> units
    work: int = Field(ge=1, le=100000)  # adult-months
    houses: int = Field(0, ge=0, le=1000)  # people one of these gives a home to
    per_people: int = Field(0, ge=0, le=100000)  # one more of these per this many people
    storage_months: int = Field(0, ge=0, le=60)
    storage_units: int = Field(0, ge=0, le=1000000)  # room for this much more of every good
    mortality_percent: int = Field(100, ge=10, le=200)


class LifeParams(_Model):
    start_families: int = Field(ge=1, le=200)  # per starting people
    # How many peoples the world begins with, far apart, each with its own speech.
    start_peoples: int = Field(1, ge=1, le=12)
    adult_age: int = Field(ge=10, le=30)
    elder_age: int = Field(ge=30, le=90)
    max_fertile_age: int = Field(ge=20, le=60)
    birth_spacing_years: int = Field(ge=1, le=10)
    birth_chance_per_year: float = Field(ge=0.0, le=1.0)
    pairing_chance_per_year: float = Field(ge=0.0, le=1.0)
    death_chance_infant: float = Field(ge=0.0, le=1.0)
    death_chance_child: float = Field(ge=0.0, le=1.0)
    death_chance_adult: float = Field(ge=0.0, le=1.0)
    death_chance_elder: float = Field(ge=0.0, le=1.0)
    elder_extra_per_year: float = Field(ge=0.0, le=1.0)
    hunger_death_factor: float = Field(ge=0.0, le=100.0)
    hunger_birth_factor: float = Field(ge=0.0, le=20.0)
    food_need_per_person_month: int = Field(ge=1, le=1000)
    child_need_percent: int = Field(ge=1, le=100)
    harvest_per_adult_month: int = Field(ge=1, le=10000)
    harvest_share_percent: int = Field(ge=1, le=100)
    forage_radius: int = Field(ge=1, le=4)
    storage_months: int = Field(ge=0, le=60)
    move_radius: int = Field(ge=1, le=12)
    wander_chance_per_month: float = Field(ge=0.0, le=1.0)
    clan_split_adults: int = Field(ge=4, le=10000)
    clan_split_chance_per_year: float = Field(ge=0.0, le=1.0)
    clan_merge_adults: int = Field(ge=0, le=100)
    contact_radius: int = Field(ge=1, le=64)
    contact_learning_chance_per_year: float = Field(ge=0.0, le=1.0)
    settle_years: int = Field(ge=1, le=1000)
    settle_chance_per_year: float = Field(ge=0.0, le=1.0)
    settled_forage_bonus: int = Field(1, ge=0, le=3)
    abandon_hunger_percent: int = Field(25, ge=1, le=100)
    abandon_chance_per_year: float = Field(0.3, ge=0.0, le=1.0)
    steps_decay_percent_per_year: int = Field(8, ge=0, le=100)
    path_trail_steps: int = Field(250, ge=1)
    path_road_steps: int = Field(1000, ge=1)
    build_start_chance_per_month: float = Field(0.25, ge=0.0, le=1.0)
    ruin_chance_per_year: float = Field(0.15, ge=0.0, le=1.0)
    builders_share_percent: int = Field(25, ge=1, le=100)
    # Knowledge is kept by people. A group with too few adults, or one that has
    # lost what a craft needs, can forget what nothing else it knows builds on.
    knowledge_keepers: int = Field(6, ge=0, le=1000)
    knowledge_loss_chance_per_year: float = Field(0.015, ge=0.0, le=1.0)
    # Peoples. A clan whose speech has moved this many sounds away from that of
    # its people may found a people of its own; a clan alone among strangers may
    # join them.
    people_sound_distance: int = Field(4, ge=1, le=20)
    people_emerge_chance_per_year: float = Field(0.002, ge=0.0, le=1.0)
    people_join_chance_per_year: float = Field(0.01, ge=0.0, le=1.0)
    # A people that has spread over more clans than this does not hold together:
    # its outlying clans break away and form peoples of their own, even before
    # their speech has drifted far. Large peoples need something to bind them
    # (a ruler, a faith), which comes with later stages.
    people_max_clans: int = Field(10, ge=1, le=10000)
    # Land. Every clan holds the tiles around its camp on which nobody presses
    # harder. How hard it presses follows from its adults, what it has built and
    # whether it is settled; hunger weakens it. Strangers gather less on held land.
    territory_strength_per_tile: int = Field(7, ge=1, le=10000)
    territory_max_radius: int = Field(7, ge=0, le=40)
    territory_hold_bonus_percent: int = Field(30, ge=0, le=500)
    foreign_harvest_percent: int = Field(50, ge=0, le=100)
    border_event_tiles: int = Field(25, ge=1, le=100000)
    # Trade. Neighbours who have something the other lacks may become partners.
    # Partners count each other's deposits as within reach, help each other
    # through hunger, learn from each other more readily and wear a path between them.
    trade_chance_per_year: float = Field(0.01, ge=0.0, le=1.0)
    trade_partners_max: int = Field(3, ge=0, le=100)
    trade_walkers_per_year: int = Field(6, ge=0, le=10000)
    trade_learning_factor: float = Field(3.0, ge=1.0, le=100.0)
    # Stores. Besides food a clan keeps goods: wood and what it digs up. When
    # nobody is hungry a share of the adults goes out for them. Room is limited
    # by heads and by storage buildings. Crafts use up a little every year, and
    # partners pass on what one has plenty of and the other lacks.
    gatherers_share_percent: int = Field(15, ge=0, le=100)
    store_per_adult: int = Field(30, ge=0, le=100000)
    craft_use_per_year: int = Field(3, ge=0, le=100000)


class PackSet(_Model):
    """The merged, validated content a world runs on."""

    versions: dict[str, str]
    checksum: str
    resources: dict[str, Resource]
    events: dict[str, EventType]
    rules: dict[str, Rule]
    technologies: dict[str, Technology] = Field(default_factory=dict)
    buildings: dict[str, Building] = Field(default_factory=dict)
    life: LifeParams | None = None  # without it the world has no people

    def foods(self) -> list[str]:
        return [rid for rid in self.stocks() if self.resources[rid].food_value > 0]

    def stocks(self) -> list[str]:
        return [rid for rid in sorted(self.resources) if self.resources[rid].kind == "stock"]

    def deposits(self) -> list[str]:
        return [rid for rid in sorted(self.resources) if self.resources[rid].kind == "deposit"]


def _read_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackError(f"{path}: not valid YAML ({exc})") from exc


def _builtin_dir(name: str) -> Path | None:
    candidate = importlib_resources.files("hiab") / "data" / "packs" / name
    path = Path(str(candidate))
    return path if (path / "pack.yaml").is_file() else None


def find_pack(name: str, data_dir: Path | None) -> Path:
    """A pack in the data folder wins over the built-in pack of the same name."""
    if data_dir is not None:
        local = data_dir / "packs" / name
        if (local / "pack.yaml").is_file():
            return local
    builtin = _builtin_dir(name)
    if builtin is None:
        raise PackError(f"Pack '{name}' not found (looked in the data folder and built-in packs)")
    return builtin


def _apply_overrides(
    raw: dict[str, dict[str, Any]], overrides: dict[str, Any], source: Path
) -> None:
    for dotted in sorted(overrides):
        parts = dotted.split(".")
        valid = (len(parts) >= 3 and parts[0] in SECTIONS) or (
            len(parts) == 2 and parts[0] == "life"
        )
        if not valid:
            raise PackError(
                f"{source}: '{dotted}' must look like <section>.<id>.<field> "
                f"(section one of {', '.join(SECTIONS)}) or life.<field>"
            )
        node: Any = raw[parts[0]]
        for part in parts[1:-1]:
            if not isinstance(node, dict) or part not in node:
                raise PackError(f"{source}: '{dotted}' does not exist in the loaded packs")
            node = node[part]
        if not isinstance(node, dict):
            raise PackError(f"{source}: '{dotted}' does not point at a field")
        node[parts[-1]] = overrides[dotted]


def _check_keys(where: str, keys: Any, allowed: tuple[str, ...], what: str) -> list[str]:
    return [
        f"{where}: unknown {what} '{key}' (known: {', '.join(allowed)})"
        for key in sorted(keys)
        if key not in allowed
    ]


def _cross_check(pack: PackSet) -> list[str]:
    problems: list[str] = []
    facts = STATIC_FACTS + DYNAMIC_FACTS + tuple(f"recent:{eid}" for eid in sorted(pack.events))
    for rid in sorted(pack.resources):
        res = pack.resources[rid]
        problems += _check_keys(f"resources.{rid}.capacity", res.capacity, BIOMES, "biome")
        problems += _check_keys(
            f"resources.{rid}.occurrence_permille", res.occurrence_permille, BIOMES, "biome"
        )
        problems += _check_keys(
            f"resources.{rid}.season_percent", res.season_percent, SEASONS, "season"
        )
        for biome in sorted(res.capacity):
            if not 0 <= res.capacity[biome] <= 1000:
                problems.append(f"resources.{rid}.capacity.{biome}: must be between 0 and 1000")
    stocks = set(pack.stocks())
    for rule_id in sorted(pack.rules):
        rule = pack.rules[rule_id]
        if rule.event not in pack.events:
            problems.append(f"rules.{rule_id}.event: unknown event type '{rule.event}'")
        problems += _check_keys(f"rules.{rule_id}.requires", rule.requires, facts, "fact")
        problems += _check_keys(f"rules.{rule_id}.factors", rule.factors, facts, "fact")
        for fact in sorted(rule.factors):
            if rule.factors[fact] <= 0:
                problems.append(f"rules.{rule_id}.factors.{fact}: must be greater than 0")
        for index, effect in enumerate(rule.effects):
            for res_id in effect.resources:
                if res_id not in stocks:
                    problems.append(
                        f"rules.{rule_id}.effects[{index}]: '{res_id}' is not a stock resource"
                    )
    clan_facts = CLAN_FACTS + tuple(f"has:{tid}" for tid in sorted(pack.technologies))
    for tech_id in sorted(pack.technologies):
        tech = pack.technologies[tech_id]
        where = f"technologies.{tech_id}"
        for required in tech.requires:
            if required not in pack.technologies:
                problems.append(f"{where}.requires: unknown technology '{required}'")
        for needed in tech.needs_nearby:
            if needed not in pack.resources:
                problems.append(f"{where}.needs_nearby: unknown resource '{needed}'")
        problems += _check_keys(f"{where}.factors", tech.factors, clan_facts, "fact")
        for fact in sorted(tech.factors):
            if tech.factors[fact] <= 0:
                problems.append(f"{where}.factors.{fact}: must be greater than 0")
        for res_id in sorted(tech.effects.harvest_percent):
            if res_id not in stocks:
                problems.append(f"{where}.effects.harvest_percent: '{res_id}' is not a stock")
    for building_id in sorted(pack.buildings):
        building = pack.buildings[building_id]
        where = f"buildings.{building_id}"
        for required in building.requires:
            if required not in pack.technologies:
                problems.append(f"{where}.requires: unknown technology '{required}'")
        for res_id in sorted(building.materials):
            if res_id not in stocks:
                problems.append(f"{where}.materials: '{res_id}' is not a stock resource")
        if building.houses == 0 and building.per_people == 0:
            problems.append(
                f"{where}: needs either 'houses' or 'per_people' to say how many are wanted"
            )
    if pack.life is not None and not pack.foods():
        problems.append("life: people need at least one stock resource with food_value > 0")
    return problems


def load_packs(names: list[str], data_dir: Path | None = None) -> PackSet:
    raw: dict[str, Any] = {section: {} for section in SECTIONS}
    versions: dict[str, str] = {}

    for name in names:
        folder = find_pack(name, data_dir)
        meta = _read_yaml(folder / "pack.yaml")
        if not isinstance(meta, dict) or "id" not in meta or "version" not in meta:
            raise PackError(f"{folder / 'pack.yaml'}: needs at least 'id' and 'version'")
        versions[str(meta["id"])] = str(meta["version"])
        for section in SECTIONS:
            path = folder / f"{section}.yaml"
            if not path.is_file():
                continue
            content = _read_yaml(path) or {}
            if not isinstance(content, dict):
                raise PackError(f"{path}: must be a mapping of id to definition")
            raw[section].update(content)
        life_path = folder / "life.yaml"
        if life_path.is_file():
            life = _read_yaml(life_path) or {}
            if not isinstance(life, dict):
                raise PackError(f"{life_path}: must be a mapping of setting to value")
            raw["life"] = {**raw.get("life", {}), **life}

    if data_dir is not None:
        override_file = data_dir / "packs" / "local" / "overrides.yaml"
        if override_file.is_file():
            overrides = _read_yaml(override_file) or {}
            if not isinstance(overrides, dict):
                raise PackError(f"{override_file}: must be a mapping of dotted path to value")
            _apply_overrides(raw, overrides, override_file)
            versions["local"] = hashlib.sha256(
                json.dumps(overrides, sort_keys=True, default=str).encode()
            ).hexdigest()[:12]

    checksum = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    try:
        pack = PackSet(versions=versions, checksum=checksum, **raw)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors(include_input=False)
        )
        raise PackError(f"Pack data is invalid: {details}") from exc

    problems = _cross_check(pack)
    if problems:
        raise PackError("Pack data is invalid: " + "; ".join(problems))

    log.info(
        "packs loaded",
        extra={
            "versions": versions,
            "checksum": checksum[:12],
            "resources": len(pack.resources),
            "events": len(pack.events),
            "rules": len(pack.rules),
            "technologies": len(pack.technologies),
            "buildings": len(pack.buildings),
            "people": pack.life is not None,
        },
    )
    return pack
