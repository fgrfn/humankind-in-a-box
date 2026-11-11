"""The simulation worker: paces the world against real time and saves it."""

from __future__ import annotations

import random
import signal
import time
from pathlib import Path
from types import FrameType

from hiab.config import Settings
from hiab.db.store import Store
from hiab.logging_setup import get_logger
from hiab.packs import PackSet, load_packs
from hiab.sim.engine import DAYS_PER_YEAR, World

log = get_logger("worker")


def new_seed() -> int:
    """A fresh seed for a new world. The only randomness outside the world streams."""
    return random.SystemRandom().randrange(2**31)


def open_world(
    store: Store,
    settings: Settings,
    packs: PackSet,
    seed: int | None = None,
    force_new: bool = False,
) -> World:
    world_id = None if force_new else store.active_world_id()
    if world_id is not None:
        world = store.load_world(world_id, packs, settings.world_log)
        store.record_packs(world)
        log.info(
            "world loaded", extra={"world_id": world.id, "tick": world.tick, "seed": world.seed}
        )
        return world
    chosen = seed if seed is not None else settings.seed
    if chosen is None:
        chosen = new_seed()
    world = World.create(
        store.next_world_id(),
        chosen,
        packs,
        settings.map_width,
        settings.map_height,
        settings.land_share,
        settings.world_log,
    )
    store.insert_world(world)
    log.info(
        "world created",
        extra={
            "world_id": world.id,
            "seed": world.seed,
            "width": settings.map_width,
            "height": settings.map_height,
        },
    )
    return world


def simulate(db_path: Path, settings: Settings, years: int, seed: int | None) -> World:
    """Run as fast as possible, without pacing. Used for tests and calibration."""
    packs = load_packs(settings.packs, settings.data_dir)
    store = Store(db_path)
    try:
        world = open_world(store, settings, packs, seed)
        target = world.tick + years * DAYS_PER_YEAR
        started = time.perf_counter()
        while world.tick < target:
            world.step()
            if world.tick % (25 * DAYS_PER_YEAR) == 0:
                store.save(world, settings.world_log_years, settings.event_detail_years)
        store.save(world, settings.world_log_years, settings.event_detail_years)
        log.info(
            "simulation finished",
            extra={
                "world_id": world.id,
                "tick": world.tick,
                "year": world.year,
                "seconds": round(time.perf_counter() - started, 2),
            },
        )
        return world
    finally:
        store.close()


class Worker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stop = False

    def request_stop(self, _signum: int = 0, _frame: FrameType | None = None) -> None:
        self._stop = True

    def run(self, seed: int | None = None) -> None:
        settings = self.settings
        packs = load_packs(settings.packs, settings.data_dir)
        store = Store(settings.db_path)
        world = open_world(store, settings, packs, seed)
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        seconds_per_tick = 60.0 / settings.pace
        next_tick = time.monotonic()
        next_save = next_tick + settings.autosave_seconds
        log.info(
            "worker started",
            extra={"world_id": world.id, "tick": world.tick, "pace": settings.pace},
        )
        try:
            while not self._stop:
                now = time.monotonic()
                if now < next_tick:
                    time.sleep(min(0.25, next_tick - now))
                    continue
                started = time.perf_counter()
                world.step()
                duration = time.perf_counter() - started
                if duration > seconds_per_tick:
                    log.warning(
                        "tick slower than pace",
                        extra={
                            "world_id": world.id,
                            "tick": world.tick,
                            "ms": round(duration * 1000, 1),
                        },
                    )
                # No catching up after a pause: the world continues where it stood.
                next_tick = max(next_tick + seconds_per_tick, now)
                if now >= next_save:
                    store.save(world, settings.world_log_years, settings.event_detail_years)
                    next_save = now + settings.autosave_seconds
        finally:
            store.save(world, settings.world_log_years, settings.event_detail_years)
            store.close()
            log.info("worker stopped", extra={"world_id": world.id, "tick": world.tick})
