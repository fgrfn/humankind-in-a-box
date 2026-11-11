"""The world and its tick loop.

One tick is one world day. The simulation knows nothing about real time: pacing
lives in the worker. All state needed to continue lives in ``World`` and is
written by ``hiab.db.store``.

Every chance roll goes through ``World.roll``. It writes the decision to the
world log and counts it, so statistics and "why did this happen?" come for free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from hiab.packs import BIOMES, SEASONS, PackSet, Rule
from hiab.sim.rng import RandomStreams
from hiab.sim.worldgen import WorldMap, generate_world, region_static_facts

DAYS_PER_MONTH = 30
MONTHS_PER_YEAR = 12
DAYS_PER_YEAR = DAYS_PER_MONTH * MONTHS_PER_YEAR
PHASE_THRESHOLD = 5  # climate anomaly in tenths of a degree that counts as a phase


def season_of(tick: int) -> str:
    return SEASONS[(tick % DAYS_PER_YEAR) // (DAYS_PER_MONTH * 3)]


@dataclass
class Buffers:
    """Rows produced since the last save, in the order they happened."""

    events: list[tuple[Any, ...]] = field(default_factory=list)
    world_log: list[tuple[Any, ...]] = field(default_factory=list)
    metrics: list[tuple[Any, ...]] = field(default_factory=list)

    def clear(self) -> None:
        self.events.clear()
        self.world_log.clear()
        self.metrics.clear()


class World:
    def __init__(
        self,
        world_id: int,
        seed: int,
        packs: PackSet,
        world_map: WorldMap,
        world_log_level: str = "decisions",
    ) -> None:
        self.id = world_id
        self.seed = seed
        self.packs = packs
        self.map = world_map
        self.world_log_level = world_log_level
        self.streams = RandomStreams(seed)
        self.tick = 0
        self.event_seq = 0
        self.log_seq = 0
        self.climate_anomaly = 0  # tenths of a degree against the long-term mean
        self.climate_phase = "normal"
        # region -> event type -> tick of the last occurrence
        self.last_event: dict[int, dict[str, int]] = {}
        # active regrowth modifiers: (until_tick, region, resource, percent)
        self.modifiers: list[tuple[int, int, str, int]] = []
        # counters of the running year, flushed to metrics at new year
        self.counters: dict[str, float] = {}
        self.buffers = Buffers()

        self.static_facts = region_static_facts(world_map)
        self.stock_ids = packs.stocks()
        self.capacity = {rid: self._capacity_grid(rid) for rid in self.stock_ids}
        self.stocks = {rid: self.capacity[rid].copy() for rid in self.stock_ids}

    # ---- construction -------------------------------------------------

    @classmethod
    def create(
        cls,
        world_id: int,
        seed: int,
        packs: PackSet,
        width: int,
        height: int,
        land_share: int,
        world_log_level: str = "decisions",
    ) -> World:
        streams = RandomStreams(seed)
        world_map = generate_world(streams.get("worldgen"), width, height, land_share, packs)
        world = cls(world_id, seed, packs, world_map, world_log_level)
        world.streams = streams
        return world

    def _capacity_grid(self, resource_id: str) -> np.ndarray:
        by_biome = np.zeros(len(BIOMES), dtype=np.int32)
        capacity = self.packs.resources[resource_id].capacity
        for biome in sorted(capacity):
            by_biome[BIOMES.index(biome)] = capacity[biome]
        return by_biome[self.map.biome].astype(np.int32)

    # ---- calendar -----------------------------------------------------

    @property
    def year(self) -> int:
        return self.tick // DAYS_PER_YEAR

    # ---- the single place where dice are rolled -------------------------

    def count(self, key: str, amount: float = 1.0) -> None:
        self.counters[key] = self.counters.get(key, 0.0) + amount

    def roll(
        self,
        rule_id: str,
        scope_type: str,
        scope_id: int,
        base_chance: float,
        factors: list[tuple[str, float]],
    ) -> bool:
        chance = base_chance
        for _name, factor in factors:
            chance *= factor
        chance = min(chance, 1.0)
        value = float(self.streams.get("rules").random())
        fired = value < chance
        self.count(f"rule.{rule_id}.checked")
        self.count(f"rule.{rule_id}.chance_sum", chance)
        if fired:
            self.count(f"rule.{rule_id}.fired")
        if self.world_log_level != "chronicle":
            self.buffers.world_log.append(
                (
                    self.log_seq,
                    self.tick,
                    rule_id,
                    scope_type,
                    scope_id,
                    factors,
                    chance,
                    value,
                    fired,
                )
            )
            self.log_seq += 1
        return fired

    def draw_int(self, name: str, low: int, high: int) -> int:
        """A logged integer draw in [low, high]."""
        value = int(self.streams.get("rules").integers(low, high + 1))
        self.count(f"draw.{name}.count")
        if self.world_log_level != "chronicle":
            self.buffers.world_log.append(
                (self.log_seq, self.tick, name, "world", 0, [], None, float(value), None)
            )
            self.log_seq += 1
        return value

    def emit(
        self, event_type: str, region: int | None = None, data: dict[str, Any] | None = None
    ) -> None:
        definition = self.packs.events.get(event_type)
        if definition is None:
            return  # the loaded packs do not describe this event
        payload = dict(data or {})
        if region is not None:
            payload["region"] = region
            self.last_event.setdefault(region, {})[event_type] = self.tick
        self.buffers.events.append(
            (self.event_seq, self.tick, event_type, region, definition.importance, payload)
        )
        self.event_seq += 1
        self.count(f"event.{event_type}")

    # ---- facts ----------------------------------------------------------

    def region_has_fact(self, region: int, fact: str) -> bool:
        if fact.startswith("recent:"):
            last = self.last_event.get(region, {}).get(fact[7:])
            return last is not None and self.tick - last <= DAYS_PER_YEAR
        if fact == "warm_phase":
            return self.climate_phase == "warm"
        if fact == "cold_phase":
            return self.climate_phase == "cold"
        return fact in self.static_facts[region]

    # ---- systems --------------------------------------------------------

    def step(self) -> None:
        tick = self.tick
        if tick % DAYS_PER_YEAR == 0:
            if tick > 0:
                self._flush_year_metrics()
            self._climate()
        if tick % DAYS_PER_MONTH == 0:
            self._monthly_rules((tick % DAYS_PER_YEAR) // DAYS_PER_MONTH + 1)
            self._ecology()
        self.tick = tick + 1

    def _climate(self) -> None:
        drift = self.draw_int("climate_drift", -2, 2)
        if self.climate_anomaly > 15:
            drift -= 1
        elif self.climate_anomaly < -15:
            drift += 1
        self.climate_anomaly += drift
        if self.climate_anomaly >= PHASE_THRESHOLD:
            phase = "warm"
        elif self.climate_anomaly <= -PHASE_THRESHOLD:
            phase = "cold"
        else:
            phase = "normal"
        if phase != self.climate_phase:
            self.climate_phase = phase
            self.emit(
                {"warm": "warm_phase_begins", "cold": "cold_phase_begins"}.get(
                    phase, "climate_normalises"
                ),
                data={"anomaly": self.climate_anomaly},
            )

    def _monthly_rules(self, month: int) -> None:
        for rule_id in sorted(self.packs.rules):
            rule = self.packs.rules[rule_id]
            if rule.scope != "region" or rule.month != month:
                continue
            for region in range(self.map.region_count):
                if "land" not in self.static_facts[region]:
                    continue
                if not all(self.region_has_fact(region, fact) for fact in rule.requires):
                    continue
                applied = [
                    (fact, rule.factors[fact])
                    for fact in sorted(rule.factors)
                    if self.region_has_fact(region, fact)
                ]
                if self.roll(rule_id, "region", region, rule.base_chance_per_year, applied):
                    self.emit(rule.event, region=region, data={"rule": rule_id})
                    self._apply_effects(rule, region)

    def _apply_effects(self, rule: Rule, region: int) -> None:
        inside = self.map.region == region
        for effect in rule.effects:
            for resource in effect.resources:
                stock = self.stocks[resource]
                if effect.type == "stock_loss":
                    stock[inside] -= (stock[inside] * effect.percent) // 100
                elif effect.type == "stock_gain":
                    capacity = self.capacity[resource]
                    stock[inside] = np.minimum(
                        capacity[inside], stock[inside] + (capacity[inside] * effect.percent) // 100
                    )
                else:
                    until = self.tick + effect.months * DAYS_PER_MONTH
                    self.modifiers.append((until, region, resource, effect.percent))

    def _ecology(self) -> None:
        self.modifiers = [m for m in self.modifiers if m[0] > self.tick]
        season = season_of(self.tick)
        for resource in self.stock_ids:
            definition = self.packs.resources[resource]
            rate = definition.regrowth_percent_per_month * definition.season_percent.get(
                season, 100
            )
            modifier = np.full(self.map.region_count, 100, dtype=np.int64)
            for _until, region, modified, percent in self.modifiers:
                if modified == resource:
                    modifier[region] = (modifier[region] * percent) // 100
            stock = self.stocks[resource].astype(np.int64)
            capacity = self.capacity[resource].astype(np.int64)
            growth = ((capacity - stock) * rate * modifier[self.map.region]) // 1_000_000
            self.stocks[resource] = np.minimum(capacity, stock + growth).astype(np.int32)

    def _flush_year_metrics(self) -> None:
        tick = self.tick
        rows = self.buffers.metrics
        for key in sorted(self.counters):
            rows.append((tick, key, "world", 0, self.counters[key]))
        self.counters.clear()
        rows.append((tick, "climate.anomaly", "world", 0, float(self.climate_anomaly)))
        region_ids = self.map.region.ravel()
        for resource in self.stock_ids:
            sums = np.zeros(self.map.region_count, dtype=np.int64)
            np.add.at(sums, region_ids, self.stocks[resource].ravel().astype(np.int64))
            rows.append((tick, f"stock.{resource}.total", "world", 0, float(int(sums.sum()))))
            for region in range(self.map.region_count):
                if "land" in self.static_facts[region]:
                    rows.append(
                        (
                            tick,
                            f"stock.{resource}.total",
                            "region",
                            region,
                            float(int(sums[region])),
                        )
                    )

    # ---- state ----------------------------------------------------------

    def dump_state(self) -> dict[str, Any]:
        """Everything that is not in its own table and is needed to continue."""
        return {
            "tick": self.tick,
            "event_seq": self.event_seq,
            "log_seq": self.log_seq,
            "climate_anomaly": self.climate_anomaly,
            "climate_phase": self.climate_phase,
            "last_event": {
                str(region): dict(sorted(self.last_event[region].items()))
                for region in sorted(self.last_event)
            },
            "modifiers": [list(m) for m in self.modifiers],
            "counters": dict(sorted(self.counters.items())),
            "streams": self.streams.dump(),
        }

    def load_state(self, state: dict[str, Any]) -> None:
        self.tick = state["tick"]
        self.event_seq = state["event_seq"]
        self.log_seq = state["log_seq"]
        self.climate_anomaly = state["climate_anomaly"]
        self.climate_phase = state["climate_phase"]
        self.last_event = {int(r): dict(v) for r, v in state["last_event"].items()}
        self.modifiers = [(m[0], m[1], m[2], m[3]) for m in state["modifiers"]]
        self.counters = dict(state["counters"])
        self.streams.load(state["streams"])
