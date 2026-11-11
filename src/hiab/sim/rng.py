"""Seeded random streams.

One seed per world, one named sub-stream per subsystem. A new subsystem gets
its own stream, so adding it never shifts the dice of existing ones.
"""

from __future__ import annotations

import zlib
from typing import Any

import numpy as np


class RandomStreams:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._streams: dict[str, np.random.Generator] = {}

    def get(self, name: str) -> np.random.Generator:
        stream = self._streams.get(name)
        if stream is None:
            # crc32 is stable across runs and platforms, unlike hash().
            sequence = np.random.SeedSequence([self.seed, zlib.crc32(name.encode("utf-8"))])
            stream = np.random.Generator(np.random.PCG64(sequence))
            self._streams[name] = stream
        return stream

    def dump(self) -> dict[str, Any]:
        return {name: self._streams[name].bit_generator.state for name in sorted(self._streams)}

    def load(self, states: dict[str, Any]) -> None:
        self._streams.clear()
        for name in sorted(states):
            bit_generator = np.random.PCG64()
            bit_generator.state = states[name]
            self._streams[name] = np.random.Generator(bit_generator)
