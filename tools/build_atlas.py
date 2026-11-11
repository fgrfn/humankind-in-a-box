"""Cut the generated picture sheets in art/ into the sprite atlas the map uses.

    uv run python tools/build_atlas.py

Reads art/manifest.yaml, writes frontend/public/sprites/atlas.png and atlas.json
(PixiJS spritesheet format). Run it again whenever a sheet is added or replaced,
then rebuild the frontend.

The sheets come out of an image generator, so nothing on them is exact: cells
have no fixed size and every ground tile carries a dark outline and an earth rim.
The cutter therefore measures each picture itself. It finds the ground diamond by
its widest row, takes only the inner part of the top face and stretches it to an
exact 2:1 diamond, so neighbouring tiles meet without a seam.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TILE_W, TILE_H = 64, 32
OBJECT_W = 96  # objects may overhang their tile on both sides
INSET = 0.86  # share of the ground diamond that lies inside its outline
PADDING = 2


def runs(flags: np.ndarray, shortest: int = 20) -> list[tuple[int, int]]:
    """Start and end of every stretch of True that is long enough to be a picture."""
    found, start = [], None
    for index, flag in enumerate([*flags.tolist(), False]):
        if flag and start is None:
            start = index
        if not flag and start is not None:
            if index - start > shortest:
                found.append((start, index))
            start = None
    return found


def cells(sheet: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Bounding boxes (top, bottom, left, right) of the pictures, row by row."""
    solid = sheet[..., 3] > 128
    boxes = []
    for top, bottom in runs(solid.any(axis=1)):
        for left, right in runs(solid[top:bottom].any(axis=0)):
            rows = np.flatnonzero(solid[top:bottom, left:right].any(axis=1))
            boxes.append((top + int(rows[0]), top + int(rows[-1]) + 1, left, right))
    return boxes


def ground(solid: np.ndarray) -> tuple[float, float, float]:
    """Centre and width of the ground diamond: (centre x, centre y, width).

    The diamond is widest at its left and right corners. Below them the rim
    keeps that width for a few rows, so the topmost of the widest rows is the
    middle of the top face. Only the lower part is searched, because a tree
    crown can be wider than the ground it stands on.
    """
    height = solid.shape[0]
    first = np.argmax(solid, axis=1)
    last = solid.shape[1] - np.argmax(solid[:, ::-1], axis=1)
    width = np.where(solid.any(axis=1), last - first, 0)
    lower = max(0, height - int(width[-height // 3 :].max() * 0.75))
    widest = int(width[lower:].max())
    middle = lower + int(np.argmax(width[lower:] >= widest - 6))
    return (first[middle] + last[middle]) / 2, float(middle), float(widest)


def resample(picture: np.ndarray, box: tuple[float, float, float, float], size: tuple[int, int]):
    """Scale a region down with premultiplied alpha, so edges do not turn dark."""
    margin = max(picture.shape[:2])  # the region may reach beyond the picture
    padded = np.pad(picture, ((margin, margin), (margin, margin), (0, 0)))
    image = Image.fromarray(padded, "RGBA").convert("RGBa")
    moved = tuple(edge + margin for edge in box)
    small = image.resize(size, Image.Resampling.BOX, box=moved).convert("RGBA")
    return np.asarray(small).copy()


def diamond_distance(width: int, height: int, cx: float, cy: float) -> np.ndarray:
    ys, xs = np.mgrid[0:height, 0:width]
    return np.abs(xs - cx) / (TILE_W / 2) + np.abs(ys - cy) / (TILE_H / 2)


def cut_terrain(picture: np.ndarray) -> np.ndarray:
    cx, cy, width = ground(picture[..., 3] > 128)
    half_w, half_h = width * INSET / 2, width * INSET / 4
    tile = resample(picture, (cx - half_w, cy - half_h, cx + half_w, cy + half_h), (TILE_W, TILE_H))
    inside = diamond_distance(TILE_W, TILE_H, TILE_W / 2 - 0.5, TILE_H / 2 - 0.5) <= 1.0
    tile[..., 3] = np.where(inside, 255, 0)
    return tile


def cut_object(picture: np.ndarray) -> np.ndarray:
    cx, cy, width = ground(picture[..., 3] > 128)
    scale = TILE_W / (width * INSET)
    above = int(np.ceil(cy * scale)) + 1
    height = above + TILE_H // 2
    half_w = OBJECT_W / 2 / scale
    box = (cx - half_w, cy - above / scale, cx + half_w, cy + (TILE_H / 2) / scale)
    sprite = resample(picture, box, (OBJECT_W, height))
    centre_x, centre_y = OBJECT_W / 2 - 0.5, above - 0.5
    distance = diamond_distance(OBJECT_W, height, centre_x, centre_y)
    ys, xs = np.mgrid[0:height, 0:OBJECT_W]
    alpha = sprite[..., 3].astype(np.float64)
    solid = alpha > 40

    # Colours of the bare ground, taken near the corners where nothing stands.
    corner = (distance > 0.6) & (distance < 0.95) & solid
    corner &= np.abs(ys - centre_y) < TILE_H / 5
    ground_colours = sprite[corner][:, :3].astype(np.int64)
    rgb = sprite[..., :3].astype(np.int64)
    if len(ground_colours):
        steps = ground_colours[:: max(1, len(ground_colours) // 48)]
        nearest = np.min(np.abs(rgb[:, :, None, :] - steps[None, None, :, :]).sum(axis=3), axis=2)
        is_ground = nearest < 36
    else:
        is_ground = np.zeros_like(solid)

    below = ys > centre_y

    # Is there open air a little further out from the tile's centre? Where an
    # object covers the edge of its ground there is not, and nothing is cut.
    open_air = np.zeros_like(solid)
    for step in (0.12, 0.2, 0.3):
        grow = (distance + step) / np.maximum(distance, 0.01)
        far_x = np.clip(np.round(centre_x + (xs - centre_x) * grow), 0, OBJECT_W - 1)
        far_y = np.clip(np.round(centre_y + (ys - centre_y) * grow), 0, height - 1)
        open_air |= ~solid[far_y.astype(int), far_x.astype(int)]

    # Inside the tile: bare ground fades out towards the edge so the tile below
    # shows through; whatever stands there stays.
    fade = np.clip((1.0 - distance) / 0.45, 0.0, 1.0)
    inside = distance <= 1.0
    alpha = np.where(inside & is_ground & (below | open_air), alpha * fade, alpha)

    # Outside the tile, below its middle: outline and earth rim, always dropped.
    alpha = np.where(~inside & below, 0, alpha)

    # Outside the tile, above its middle: the outline of the ground is dropped
    # where open air lies beyond it, a crown hanging over the edge is kept.
    band = ~inside & ~below & (distance <= 1.0 / INSET + 0.25)
    alpha = np.where(band & open_air, 0, alpha)

    sprite[..., 3] = np.clip(alpha, 0, 255).astype(np.uint8)
    sprite[sprite[..., 3] < 24] = 0

    # Crumbs of outline that survived along the edge of the ground.
    edge = (distance > 0.75) & (distance < 1.0 / INSET + 0.25)
    for _ in range(3):
        kept = np.pad(sprite[..., 3] > 96, 1)
        neighbours = sum(
            kept[1 + dy : 1 + dy + height, 1 + dx : 1 + dx + OBJECT_W].astype(int)
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
            if (dy, dx) != (0, 0)
        )
        sprite[edge & (neighbours < 3)] = 0
    rows = np.flatnonzero((sprite[..., 3] > 0).any(axis=1))
    return sprite[int(rows[0]) :] if len(rows) else sprite


def main() -> int:
    manifest = yaml.safe_load((ROOT / "art" / "manifest.yaml").read_text(encoding="utf-8"))
    sprites: dict[str, tuple[str, np.ndarray]] = {}
    for sheet in manifest["sheets"]:
        path = ROOT / "art" / sheet["file"]
        pixels = np.asarray(Image.open(path).convert("RGBA"))
        boxes = cells(pixels)
        names = sheet["cells"]
        if len(boxes) != len(names):
            print(
                f"{sheet['file']}: found {len(boxes)} pictures but the manifest names "
                f"{len(names)}. Check that the background is transparent and that "
                "pictures do not touch.",
                file=sys.stderr,
            )
            return 1
        for name, (top, bottom, left, right) in zip(names, boxes, strict=True):
            if name in sprites:
                print(f"{sheet['file']}: the name '{name}' is used twice", file=sys.stderr)
                return 1
            picture = pixels[top:bottom, left:right]
            cut = cut_terrain(picture) if sheet["kind"] == "terrain" else cut_object(picture)
            sprites[name] = (sheet["kind"], cut)

    # Simple shelf packing: ground tiles first, then objects sorted by height.
    order = sorted(sprites, key=lambda n: (sprites[n][0] != "terrain", sprites[n][1].shape[0], n))
    atlas_w = 8 * (TILE_W + PADDING) + PADDING
    frames: dict[str, dict[str, object]] = {}
    x = y = PADDING
    shelf = 0
    placed: list[tuple[str, int, int]] = []
    for name in order:
        h, w = sprites[name][1].shape[:2]
        if x + w + PADDING > atlas_w:
            x, y, shelf = PADDING, y + shelf + PADDING, 0
        placed.append((name, x, y))
        x, shelf = x + w + PADDING, max(shelf, h)
    atlas = np.zeros((y + shelf + PADDING, atlas_w, 4), dtype=np.uint8)
    for name, x, y in placed:
        kind, cut = sprites[name]
        h, w = cut.shape[:2]
        atlas[y : y + h, x : x + w] = cut
        frames[name] = {
            "frame": {"x": x, "y": y, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h},
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "anchor": {"x": 0.5, "y": 0.5} if kind == "terrain" else {"x": 0.5, "y": 1.0},
        }
    out = ROOT / "frontend" / "public" / "sprites"
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(atlas, "RGBA").save(out / "atlas.png", optimize=True)
    meta = {
        "image": "atlas.png",
        "format": "RGBA8888",
        "size": {"w": atlas.shape[1], "h": atlas.shape[0]},
        "scale": "1",
        "tile": {"w": TILE_W, "h": TILE_H},
        "kinds": {name: sprites[name][0] for name in sorted(sprites)},
    }
    (out / "atlas.json").write_text(
        json.dumps({"frames": frames, "meta": meta}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{len(sprites)} sprites -> {out / 'atlas.png'} ({atlas.shape[1]}x{atlas.shape[0]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
