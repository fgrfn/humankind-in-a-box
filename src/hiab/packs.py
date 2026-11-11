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
SECTIONS = ("resources", "events", "rules")


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


class PackSet(_Model):
    """The merged, validated content a world runs on."""

    versions: dict[str, str]
    checksum: str
    resources: dict[str, Resource]
    events: dict[str, EventType]
    rules: dict[str, Rule]

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
        if len(parts) < 3 or parts[0] not in SECTIONS:
            raise PackError(
                f"{source}: '{dotted}' must look like <section>.<id>.<field>, "
                f"section one of {', '.join(SECTIONS)}"
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
    return problems


def load_packs(names: list[str], data_dir: Path | None = None) -> PackSet:
    raw: dict[str, dict[str, Any]] = {section: {} for section in SECTIONS}
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
        },
    )
    return pack
