"""World generation on a square grid.

Everything here is integer arithmetic on purpose: integer results are identical
on every platform, floating point transcendental functions are not.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from hiab.packs import BIOMES, PackSet

REGION_SIZE = 16
BIOME_INDEX = {name: index for index, name in enumerate(BIOMES)}
WATER_BIOMES = (BIOME_INDEX["ocean"], BIOME_INDEX["coast"])


@dataclass
class WorldMap:
    width: int
    height: int
    elevation: np.ndarray  # int32, relative to sea level (land > 0)
    water: np.ndarray  # bool, sea tiles
    river: np.ndarray  # bool
    temperature: np.ndarray  # int32, tenths of a degree Celsius, yearly mean
    moisture: np.ndarray  # int32, 0..1000
    biome: np.ndarray  # int8, index into packs.BIOMES
    region: np.ndarray  # int16
    deposit: np.ndarray  # int8, index into deposit_ids, -1 for none
    deposit_ids: list[str]

    @property
    def region_count(self) -> int:
        return int(self.region.max()) + 1


def _value_noise(rng: np.random.Generator, height: int, width: int) -> np.ndarray:
    """Three octaves of bilinear value noise, result 0..1023."""
    total = np.zeros((height, width), dtype=np.int64)
    weights = 0
    for cell, weight in ((16, 4), (8, 2), (4, 1)):
        lattice = rng.integers(
            0, 1024, size=(height // cell + 2, width // cell + 2), dtype=np.int64
        )
        ys, xs = np.arange(height), np.arange(width)
        y0, fy = (ys // cell)[:, None], (ys % cell)[:, None]
        x0, fx = (xs // cell)[None, :], (xs % cell)[None, :]
        value = (
            lattice[y0, x0] * (cell - fx) * (cell - fy)
            + lattice[y0, x0 + 1] * fx * (cell - fy)
            + lattice[y0 + 1, x0] * (cell - fx) * fy
            + lattice[y0 + 1, x0 + 1] * fx * fy
        ) // (cell * cell)
        total += value * weight
        weights += weight
    return total // weights


def _neighbour_any(mask: np.ndarray, diagonal: bool) -> np.ndarray:
    """True where any neighbour of a tile is set in ``mask``."""
    padded = np.pad(mask, 1, constant_values=False)
    out = padded[:-2, 1:-1] | padded[2:, 1:-1] | padded[1:-1, :-2] | padded[1:-1, 2:]
    if diagonal:
        out = out | padded[:-2, :-2] | padded[:-2, 2:] | padded[2:, :-2] | padded[2:, 2:]
    return out


def _trace_rivers(rng: np.random.Generator, raw: np.ndarray, water: np.ndarray) -> np.ndarray:
    height, width = raw.shape
    river = np.zeros_like(water)
    land = np.argwhere(~water)
    if len(land) == 0:
        return river
    land_heights = np.sort(raw[~water])
    threshold = land_heights[(len(land_heights) * 60) // 100]
    sources = land[raw[~water] >= threshold]
    if len(sources) == 0:
        return river
    for _ in range(max(1, (height * width) // 400)):
        y, x = (int(v) for v in sources[int(rng.integers(0, len(sources)))])
        for _step in range(200):
            if water[y, x]:
                break
            river[y, x] = True
            best = (int(raw[y, x]), y, x)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < height and 0 <= nx < width:
                    candidate = (int(raw[ny, nx]), ny, nx)
                    if candidate < best:
                        best = candidate
            if best[1:] == (y, x):
                break  # a basin: the river ends in a lake
            y, x = best[1], best[2]
    return river


def generate_world(
    rng: np.random.Generator, width: int, height: int, land_share: int, packs: PackSet
) -> WorldMap:
    raw = _value_noise(rng, height, width)
    ys, xs = np.arange(height)[:, None], np.arange(width)[None, :]
    edge = np.minimum(np.minimum(xs, width - 1 - xs), np.minimum(ys, height - 1 - ys))
    raw = raw - np.maximum(0, 8 - edge) * 60

    ordered = np.sort(raw, axis=None)
    sea_level = int(ordered[min(len(ordered) - 1, (len(ordered) * (100 - land_share)) // 100)])
    water = raw < sea_level
    elevation = (raw - sea_level).astype(np.int32)
    river = _trace_rivers(rng, raw, water)

    max_height = max(1, int(elevation.max()))
    temperature = (
        -100 + (400 * ys) // max(1, height - 1) - (np.maximum(elevation, 0) * 150) // max_height
    ).astype(np.int32)

    wet = water | river
    distance = np.full((height, width), 6, dtype=np.int64)
    reached = wet.copy()
    distance[reached] = 0
    for step in range(1, 6):
        grown = _neighbour_any(reached, diagonal=False) & ~reached
        distance[grown] = step
        reached |= grown
    moisture = np.clip(
        (_value_noise(rng, height, width) * 700) // 1023 + (6 - distance) * 50, 0, 1000
    ).astype(np.int32)

    land = ~water
    land_sorted = np.sort(elevation[land]) if land.any() else np.array([0])
    mountain_level = int(land_sorted[(len(land_sorted) * 92) // 100])

    biome = np.full((height, width), BIOME_INDEX["desert"], dtype=np.int8)
    biome[moisture > 220] = BIOME_INDEX["steppe"]
    biome[moisture > 380] = BIOME_INDEX["grassland"]
    biome[moisture > 550] = BIOME_INDEX["forest"]
    biome[(moisture > 750) & (elevation < mountain_level // 3)] = BIOME_INDEX["marsh"]
    biome[(temperature > 220) & (moisture < 300)] = BIOME_INDEX["desert"]
    biome[temperature < 40] = BIOME_INDEX["tundra"]
    biome[(temperature < 40) & (temperature >= -20) & (moisture > 300)] = BIOME_INDEX["taiga"]
    biome[elevation >= mountain_level] = BIOME_INDEX["mountain"]
    biome[river] = BIOME_INDEX["river"]
    biome[water] = BIOME_INDEX["ocean"]
    biome[water & _neighbour_any(land, diagonal=True)] = BIOME_INDEX["coast"]

    regions_per_row = -(-width // REGION_SIZE)
    region = ((ys // REGION_SIZE) * regions_per_row + xs // REGION_SIZE).astype(np.int16)

    deposit_ids = packs.deposits()
    deposit = np.full((height, width), -1, dtype=np.int8)
    rolls = rng.integers(0, 1000, size=(len(deposit_ids), height, width))
    for index, deposit_id in enumerate(deposit_ids):
        permille = np.zeros(len(BIOMES), dtype=np.int64)
        occurrence = packs.resources[deposit_id].occurrence_permille
        for biome_name in sorted(occurrence):
            permille[BIOME_INDEX[biome_name]] = occurrence[biome_name]
        hit = (deposit == -1) & land & ~river & (rolls[index] < permille[biome])
        deposit[hit] = index

    return WorldMap(
        width=width,
        height=height,
        elevation=elevation,
        water=water,
        river=river,
        temperature=temperature,
        moisture=moisture,
        biome=biome,
        region=region,
        deposit=deposit,
        deposit_ids=deposit_ids,
    )


def region_static_facts(world: WorldMap) -> list[set[str]]:
    """Facts about each region that never change. Regions without land get none."""
    facts: list[set[str]] = []
    for region_id in range(world.region_count):
        inside = world.region == region_id
        land = inside & ~world.water
        count = int(land.sum())
        found: set[str] = set()
        if count:
            found.add("land")
            moisture = int(world.moisture[land].sum())
            temperature = int(world.temperature[land].sum())
            if moisture < 300 * count:
                found.add("arid")
            if moisture > 600 * count:
                found.add("wet")
            if temperature < 30 * count:
                found.add("cold")
            if temperature > 200 * count:
                found.add("hot")
            if bool((world.biome[inside] == BIOME_INDEX["coast"]).any()):
                found.add("coastal")
            if int((world.biome[land] == BIOME_INDEX["mountain"]).sum()) * 100 >= 15 * count:
                found.add("mountainous")
            wooded = (world.biome[land] == BIOME_INDEX["forest"]) | (
                world.biome[land] == BIOME_INDEX["taiga"]
            )
            if int(wooded.sum()) * 100 >= 35 * count:
                found.add("forested")
        facts.append(found)
    return facts
