import { Application, Assets, Container, Graphics, Sprite, type Spritesheet, Text } from "pixi.js";
import { useEffect, useRef } from "react";
import type { Building, Group, Place, WorldMap } from "./api";

// One tile is 32 x 16 map units. The sprites are drawn at twice that size, so
// the map is pixel-exact at zoom 2 and stays sharp when zoomed further in.
const TILE_W = 32;
const TILE_H = 16;
const SPRITE_SCALE = 0.5;

// Ground per biome. Several names mean: pick one per tile, always the same one.
const GROUND: Record<string, string[]> = {
  ocean: ["deep_water"],
  coast: ["shallow_water"],
  river: ["shallow_water"],
  tundra: ["tundra", "tundra", "tundra", "snow"],
  taiga: ["forest_floor", "forest_floor", "moss"],
  forest: ["forest_floor", "moss", "grass"],
  grassland: ["grass", "grass", "grass", "dry_grass"],
  steppe: ["steppe", "steppe", "dry_grass"],
  desert: ["sand"],
  mountain: ["rock"],
  marsh: ["marsh", "marsh", "mud"],
};

// What grows or lies on a tile: [sprite, chance in percent], tried in order.
const NATURE: Record<string, [string, number][]> = {
  taiga: [["pine", 55], ["dead_tree", 3]],
  forest: [["oak", 38], ["birch", 14], ["berry_bush", 6]],
  grassland: [["berry_bush", 3], ["oak", 2], ["birch", 1]],
  steppe: [["dead_tree", 1], ["boulder", 1]],
  tundra: [["boulder", 2], ["dead_tree", 1]],
  marsh: [["reeds", 40]],
  mountain: [["boulder", 6]],
};
// Flat colours, used only when the sprite atlas cannot be loaded.
const FALLBACK_COLOURS: Record<string, number> = {
  ocean: 0x1b3947,
  coast: 0x2d5b6b,
  river: 0x3a7a8c,
  tundra: 0x9aa39a,
  taiga: 0x4c6b55,
  forest: 0x3f6a3c,
  grassland: 0x7c9a4e,
  steppe: 0xa9a260,
  desert: 0xcbb37a,
  mountain: 0x7b766f,
  marsh: 0x5c7460,
};
const DEPOSIT_SPRITES: Record<string, string> = {
  flint: "boulder",
  copper_ore: "copper_rock",
  tin_ore: "boulder",
  iron_ore: "boulder",
};
const DEPOSIT_COLOURS = [0xd9d2c0, 0xc97b4a, 0x8a8f98, 0xb7c4cc, 0xe9e4d8, 0xb04a3a];
const BUILDING_SPRITES: Record<string, string> = {
  fire_place: "campfire",
  hut: "hut",
  drying_rack: "drying_rack",
  storage_pit: "storage_pit",
  kiln: "kiln",
};

// A fixed number per tile, so the same world always looks the same.
function tileNoise(x: number, y: number, salt: number): number {
  let h = (x * 374761393 + y * 668265263 + salt * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) % 100;
}

function shade(colour: number, factor: number): number {
  const r = Math.min(255, Math.round(((colour >> 16) & 255) * factor));
  const g = Math.min(255, Math.round(((colour >> 8) & 255) * factor));
  const b = Math.min(255, Math.round((colour & 255) * factor));
  return (r << 16) | (g << 8) | b;
}

function project(x: number, y: number): [number, number] {
  return [((x - y) * TILE_W) / 2, ((x + y) * TILE_H) / 2];
}

function diamond(g: Graphics, x: number, y: number, inset = 0): void {
  const [cx, cy] = project(x, y);
  const w = TILE_W / 2 - inset * 2;
  const h = TILE_H / 2 - inset;
  g.poly([cx, cy - h + TILE_H / 2, cx + w, cy + TILE_H / 2, cx, cy + h + TILE_H / 2, cx - w, cy + TILE_H / 2]);
}

// Labels keep one size on screen whatever the zoom, and step aside when the
// map is too small to carry them.
function fitLabels(camps: Container, scale: number): void {
  for (const marker of camps.children) {
    for (const child of (marker as Container).children) {
      if (child instanceof Text) {
        child.visible = scale >= 0.8;
        child.scale.set(1.05 / scale);
      }
    }
  }
}

// ---- People on the map ---------------------------------------------------
// The simulation settles a clan's month in one step. What is drawn here is that
// month played out: who walks where follows from what the clan really knows and
// is really building, but the single steps are display only and never stored.

type Task = "out" | "work" | "back" | "rest";

interface Walker {
  sprite: Sprite;
  kind: string;
  path: [number, number][];
  leg: number;
  along: number;
  task: Task;
  wait: number;
  clock: number;
  dx: number;
  dy: number;
}

interface Band {
  x: number;
  y: number;
  walkers: Walker[];
  reach: Map<number, number>; // tile index -> tile it was reached from
  targets: Record<string, number[]>;
}

const NEIGHBOURS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
const REACH = 4;
const WALK_SPEED = 0.9; // tiles per second

class Crowd {
  private bands = new Map<number, Band>();
  private map: WorldMap | null = null;

  private dry(x: number, y: number): boolean {
    const map = this.map;
    if (!map || x < 0 || y < 0 || x >= map.width || y >= map.height) return false;
    const biome = map.biomes[map.biome[y * map.width + x]];
    return biome !== "ocean" && biome !== "coast";
  }

  // Everywhere a clan can walk to from its camp without crossing open water.
  private explore(band: Band, group: Group, places: Place[], natureAt: Map<number, Sprite>): void {
    const map = this.map!;
    const start = band.y * map.width + band.x;
    const distance = new Map<number, number>([[start, 0]]);
    band.reach = new Map([[start, start]]);
    const queue = [start];
    for (let head = 0; head < queue.length; head++) {
      const index = queue[head];
      const steps = distance.get(index)!;
      if (steps >= REACH) continue;
      const x = index % map.width;
      const y = (index - x) / map.width;
      for (const [dx, dy] of NEIGHBOURS) {
        const next = (y + dy) * map.width + x + dx;
        if (!this.dry(x + dx, y + dy) || distance.has(next)) continue;
        distance.set(next, steps + 1);
        band.reach.set(next, index);
        queue.push(next);
      }
    }
    const shore: number[] = [];
    const growth: number[] = [];
    const far: number[] = [];
    const near: number[] = [];
    for (const [index, steps] of distance) {
      if (steps === 0) continue;
      const x = index % map.width;
      const y = (index - x) / map.width;
      const wet = map.river[index] || NEIGHBOURS.slice(0, 4).some(([dx, dy]) => !this.dry(x + dx, y + dy));
      if (wet) shore.push(index);
      if (natureAt.has(index)) growth.push(index);
      if (steps >= 3) far.push(index);
      if (steps <= 1) near.push(index);
    }
    const sites = places
      .filter((place) => place.group_id === group.id && place.abandoned_year === null)
      .flatMap((place) => place.buildings.filter((building) => building.state === "site"))
      .map((building) => building.y * map.width + building.x)
      .filter((index) => band.reach.has(index));
    band.targets = { shore, growth, far, near, sites, any: [...distance.keys()].filter((index) => index !== start) };
  }

  private cast(group: Group, count: number): string[] {
    const knows = new Set(group.technologies.map((tech) => tech.id));
    const roles = ["gatherer", knows.has("spear") ? "hunter" : "man", "woman", knows.has("fishing") ? "fisher" : "child", "elder", "child"];
    return roles.slice(0, count);
  }

  private errand(band: Band, kind: string): number | null {
    const pick = (list: number[]) => (list.length ? list[Math.floor(Math.random() * list.length)] : null);
    const t = band.targets;
    if ((kind === "man" || kind === "woman" || kind === "hunter") && t.sites.length && Math.random() < 0.6) return pick(t.sites);
    if (kind === "fisher") return pick(t.shore) ?? pick(t.any);
    if (kind === "hunter" || kind === "man") return pick(t.far) ?? pick(t.any);
    if (kind === "elder" || kind === "child") return pick(t.near) ?? pick(t.any);
    return pick(t.growth) ?? pick(t.any);
  }

  private route(band: Band, target: number): [number, number][] {
    const map = this.map!;
    const tiles: [number, number][] = [];
    let index = target;
    for (let guard = 0; guard < 64; guard++) {
      tiles.push([index % map.width, Math.floor(index / map.width)]);
      const from = band.reach.get(index);
      if (from === undefined || from === index) break;
      index = from;
    }
    return tiles.reverse();
  }

  sync(layer: Container, sheet: Spritesheet, map: WorldMap, groups: Group[], places: Place[], natureAt: Map<number, Sprite>): void {
    if (this.map !== map) {
      for (const band of this.bands.values()) for (const walker of band.walkers) walker.sprite.destroy();
      this.bands.clear();
      this.map = map;
    }
    const alive = new Set(groups.map((group) => group.id));
    for (const [id, band] of this.bands) {
      if (alive.has(id)) continue;
      for (const walker of band.walkers) walker.sprite.destroy();
      this.bands.delete(id);
    }
    for (const group of groups) {
      let band = this.bands.get(group.id);
      const moved = band !== undefined && (band.x !== group.x || band.y !== group.y);
      if (!band) {
        band = { x: group.x, y: group.y, walkers: [], reach: new Map(), targets: {} };
        this.bands.set(group.id, band);
      }
      band.x = group.x;
      band.y = group.y;
      this.explore(band, group, places, natureAt);
      const roles = this.cast(group, Math.min(5, Math.ceil(group.population / 5)));
      while (band.walkers.length > roles.length) band.walkers.pop()!.sprite.destroy();
      roles.forEach((kind, n) => {
        let walker = band.walkers[n];
        if (!walker) {
          const sprite = new Sprite(sheet.textures[kind] ?? sheet.textures.man);
          sprite.anchor.set(0.5, 1);
          sprite.scale.set(SPRITE_SCALE * 0.5);
          layer.addChild(sprite);
          walker = { sprite, kind, path: [[group.x, group.y]], leg: 0, along: 0, task: "rest", wait: Math.random() * 6, clock: Math.random() * 10, dx: (Math.random() - 0.5) * 9, dy: (Math.random() - 0.5) * 4 };
          band.walkers[n] = walker;
        } else if (walker.kind !== kind) {
          walker.kind = kind;
          walker.sprite.texture = sheet.textures[kind] ?? sheet.textures.man;
        }
        if (moved) {
          // The clan has moved on: walk straight to the new camp from wherever one stands.
          const [fx, fy] = this.where(walker);
          walker.path = [[fx, fy], [group.x, group.y]];
          walker.leg = 0;
          walker.along = 0;
          walker.task = "back";
        }
      });
    }
  }

  private where(walker: Walker): [number, number] {
    const a = walker.path[walker.leg];
    const b = walker.path[Math.min(walker.leg + 1, walker.path.length - 1)];
    return [a[0] + (b[0] - a[0]) * walker.along, a[1] + (b[1] - a[1]) * walker.along];
  }

  step(seconds: number): void {
    for (const band of this.bands.values()) {
      for (const walker of band.walkers) {
        walker.clock += seconds;
        let lift = 0;
        if (walker.task === "rest" || walker.task === "work") {
          walker.wait -= seconds;
          if (walker.task === "work") lift = Math.abs(Math.sin(walker.clock * 5)) * 1.2;
          if (walker.wait <= 0) {
            if (walker.task === "work") {
              walker.path = [...walker.path].reverse();
              walker.task = "back";
            } else {
              const target = this.errand(band, walker.kind);
              if (target === null) {
                walker.wait = 4;
                continue;
              }
              walker.path = this.route(band, target);
              walker.task = "out";
            }
            walker.leg = 0;
            walker.along = 0;
          }
        } else {
          const a = walker.path[walker.leg];
          const b = walker.path[Math.min(walker.leg + 1, walker.path.length - 1)];
          const length = Math.max(0.5, Math.hypot(b[0] - a[0], b[1] - a[1]));
          walker.along += (seconds * WALK_SPEED) / length;
          lift = Math.abs(Math.sin(walker.clock * 9)) * 0.7;
          const heading = b[0] - a[0] - (b[1] - a[1]); // on screen: positive walks right
          const size = Math.abs(walker.sprite.scale.y);
          if (heading !== 0) walker.sprite.scale.x = heading > 0 ? size : -size;
          if (walker.along >= 1) {
            walker.along = 0;
            walker.leg += 1;
            if (walker.leg >= walker.path.length - 1) {
              walker.leg = walker.path.length - 1;
              walker.wait = walker.task === "out" ? 3 + Math.random() * 5 : 2 + Math.random() * 7;
              walker.task = walker.task === "out" ? "work" : "rest";
            }
          }
        }
        const [fx, fy] = this.where(walker);
        const [sx, sy] = project(fx, fy);
        const atCamp = walker.task === "rest" ? 1 : 0.35;
        walker.sprite.position.set(sx + walker.dx * atCamp, sy + TILE_H / 2 + 2 + walker.dy * atCamp - lift);
        walker.sprite.zIndex = sy + walker.dy;
      }
    }
  }
}

interface Scene {
  app: Application;
  world: Container;
  terrain: Container;
  paths: Container;
  nature: Container;
  buildings: Container;
  people: Container;
  camps: Container;
  sheet: Spritesheet | null;
  natureAt: Map<number, Sprite>;
}

interface Props {
  map: WorldMap | null;
  steps: number[];
  groups: Group[];
  places: Place[];
  selected: number | null;
  focus: { id: number; nonce: number } | null;
  onSelect: (id: number) => void;
}

export function MapView({ map, steps, groups, places, selected, focus, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<Scene | null>(null);
  const ready = useRef<Promise<void> | null>(null);
  const placed = useRef(false);
  const crowd = useRef(new Crowd());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const app = new Application();
    let disposed = false;
    const pointers = new Map<number, { x: number; y: number }>();
    let pinch = 0;
    let moved = 0;

    ready.current = app
      .init({ resizeTo: element, background: 0x1b3947, antialias: false, resolution: window.devicePixelRatio || 1, autoDensity: true })
      .then(() => Assets.load<Spritesheet>(new URL("sprites/atlas.json", document.baseURI).href).catch(() => null))
      .then((loaded) => {
        if (disposed) {
          app.destroy(true);
          return;
        }
        // Without the atlas the map falls back to flat colours instead of staying empty.
        const sheet = loaded && loaded.textures && loaded.textureSource ? loaded : null;
        if (sheet) sheet.textureSource.scaleMode = "nearest";
        element.appendChild(app.canvas);
        const world = new Container();
        const terrain = new Container();
        const paths = new Container();
        const nature = new Container();
        const buildings = new Container();
        const people = new Container();
        people.sortableChildren = true;
        const camps = new Container();
        world.addChild(terrain, paths, nature, buildings, people, camps);
        app.stage.addChild(world);
        scene.current = { app, world, terrain, paths, nature, buildings, people, camps, sheet, natureAt: new Map() };
        app.ticker.add((ticker) => {
          people.visible = world.scale.x >= 0.9; // too small to read from far away
          if (people.visible) crowd.current.step(Math.min(0.1, ticker.deltaMS / 1000));
        });

        const canvas = app.canvas;
        canvas.style.touchAction = "none";
        const zoomAt = (px: number, py: number, factor: number) => {
          const next = Math.max(0.35, Math.min(6, world.scale.x * factor));
          const ratio = next / world.scale.x;
          world.position.set(px - (px - world.x) * ratio, py - (py - world.y) * ratio);
          world.scale.set(next);
          fitLabels(camps, next);
        };
        canvas.addEventListener("wheel", (event) => {
          event.preventDefault();
          const box = canvas.getBoundingClientRect();
          zoomAt(event.clientX - box.left, event.clientY - box.top, event.deltaY < 0 ? 1.15 : 1 / 1.15);
        }, { passive: false });
        canvas.addEventListener("pointerdown", (event) => {
          pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
          moved = 0;
          pinch = 0;
        });
        canvas.addEventListener("pointermove", (event) => {
          const previous = pointers.get(event.pointerId);
          if (!previous) return;
          pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
          if (pointers.size === 1) {
            world.x += event.clientX - previous.x;
            world.y += event.clientY - previous.y;
            moved += Math.abs(event.clientX - previous.x) + Math.abs(event.clientY - previous.y);
          } else if (pointers.size === 2) {
            const [a, b] = [...pointers.values()];
            const distance = Math.hypot(a.x - b.x, a.y - b.y);
            const box = canvas.getBoundingClientRect();
            if (pinch > 0) zoomAt((a.x + b.x) / 2 - box.left, (a.y + b.y) / 2 - box.top, distance / pinch);
            pinch = distance;
            moved += 10;
          }
        });
        const release = (event: PointerEvent) => {
          pointers.delete(event.pointerId);
          pinch = 0;
        };
        canvas.addEventListener("pointerup", release);
        canvas.addEventListener("pointercancel", release);
        canvas.addEventListener("pointerleave", release);
        (camps as Container & { wasDragged?: () => boolean }).wasDragged = () => moved > 6;
      });

    return () => {
      disposed = true;
      const current = scene.current;
      scene.current = null;
      if (current) current.app.destroy(true, { children: true });
    };
  }, []);

  // Ground and everything that grows on it: built once per map.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      for (const layer of [current.terrain, current.nature]) {
        for (const child of layer.removeChildren()) child.destroy();
      }
      current.natureAt.clear();
      const textures = current.sheet?.textures ?? {};
      const fallback = new Graphics();
      const marks = new Graphics();
      const peaks = map.biome
        .map((biome, index) => (map.biomes[biome] === "mountain" ? map.elevation[index] : -1))
        .filter((height) => height >= 0)
        .sort((a, b) => a - b);
      const snowLine = peaks.length ? peaks[Math.floor(peaks.length * 0.7)] : Infinity;
      // Diagonal by diagonal, so things further south cover what is behind them.
      for (let sum = 0; sum <= map.width + map.height - 2; sum++) {
        for (let x = Math.max(0, sum - map.height + 1); x <= Math.min(sum, map.width - 1); x++) {
          const y = sum - x;
          const index = y * map.width + x;
          const biome = map.biomes[map.biome[index]];
          const name = map.river[index] ? "river" : biome;
          const water = name === "ocean" || name === "coast" || name === "river";
          const height = Math.max(0, Math.min(400, map.elevation[index]));
          const light = water ? 1 : Math.min(1, 0.8 + height / 1500);
          const [cx, cy] = project(x, y);
          const choices = GROUND[name] ?? ["grass"];
          let ground = choices[tileNoise(x >> 1, y >> 1, 1) % choices.length];
          if (name === "mountain" && map.elevation[index] >= snowLine) ground = "snow";
          const texture = textures[ground];
          if (texture) {
            const tile = new Sprite(texture);
            tile.anchor.set(0.5);
            tile.position.set(cx, cy + TILE_H / 2);
            tile.scale.set(tileNoise(x, y, 2) < 50 ? SPRITE_SCALE : -SPRITE_SCALE, SPRITE_SCALE);
            tile.tint = shade(0xffffff, light);
            current.terrain.addChild(tile);
          } else {
            diamond(fallback, x, y);
            fallback.fill(shade(FALLBACK_COLOURS[name] ?? 0x555555, light));
          }
          if (water) continue;
          const deposit = map.deposit[index];
          let object: string | null = null;
          if (deposit >= 0) {
            object = DEPOSIT_SPRITES[map.deposits[deposit]?.id] ?? null;
            if (!object) marks.circle(cx, cy + TILE_H / 2, 1.6).fill(DEPOSIT_COLOURS[deposit % DEPOSIT_COLOURS.length]);
          } else {
            const roll = tileNoise(x, y, 3);
            let edge = 0;
            for (const [candidate, chance] of NATURE[name] ?? []) {
              edge += chance;
              if (roll < edge) {
                object = candidate;
                break;
              }
            }
          }
          if (object && textures[object]) {
            const sprite = new Sprite(textures[object]);
            sprite.anchor.set(0.5, 1);
            const size = SPRITE_SCALE * (deposit >= 0 ? 0.7 : 0.82 + tileNoise(x, y, 4) / 500);
            sprite.position.set(cx, cy + TILE_H);
            sprite.scale.set(tileNoise(x, y, 5) < 50 ? size : -size, size);
            current.nature.addChild(sprite);
            current.natureAt.set(index, sprite);
          }
        }
      }
      current.terrain.addChildAt(fallback, 0);
      current.terrain.addChild(marks);
      placed.current = false;
    });
  }, [map]);

  // Paths: tiles that many feet have crossed. Where people walk, nothing grows.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      for (const child of current.paths.removeChildren()) child.destroy();
      if (steps.length !== map.width * map.height) return;
      const texture = current.sheet?.textures.path;
      const trail = map.path_levels?.trail || 250;
      const road = map.path_levels?.road || 1000;
      const fallback = new Graphics();
      const taken = new Set<number>();
      for (const group of groups) taken.add(group.y * map.width + group.x);
      for (const place of places) for (const building of place.buildings) taken.add(building.y * map.width + building.x);
      for (let y = 0; y < map.height; y++) {
        for (let x = 0; x < map.width; x++) {
          const index = y * map.width + x;
          const count = steps[index];
          const grown = current.natureAt.get(index);
          if (grown) grown.visible = count < trail && !taken.has(index);
          if (count < trail / 2 || map.river[index]) continue;
          const alpha = count >= road ? 1 : count >= trail ? 0.8 : 0.1 + (0.4 * count) / trail;
          const [cx, cy] = project(x, y);
          if (texture) {
            const tile = new Sprite(texture);
            tile.anchor.set(0.5);
            tile.position.set(cx, cy + TILE_H / 2);
            tile.scale.set(tileNoise(x, y, 6) < 50 ? SPRITE_SCALE : -SPRITE_SCALE, SPRITE_SCALE);
            tile.alpha = alpha;
            if (count >= road) tile.tint = 0xd9cdb4;
            current.paths.addChild(tile);
          } else {
            diamond(fallback, x, y, 2.5);
            fallback.fill({ color: 0xd8c08a, alpha: alpha * 0.7 });
          }
        }
      }
      current.paths.addChild(fallback);
    });
  }, [map, steps, groups, places]);

  // What people have built, is building, or has fallen into ruin.
  useEffect(() => {
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      for (const child of current.buildings.removeChildren()) child.destroy();
      const all: Building[] = places.flatMap((place) => place.buildings);
      const textures = current.sheet?.textures ?? {};
      const g = new Graphics();
      for (const building of all.sort((a, b) => a.y + a.x - (b.y + b.x))) {
        const [cx, top] = project(building.x, building.y);
        const name = building.state === "standing" ? (BUILDING_SPRITES[building.type] ?? "hut") : building.state;
        const texture = textures[name];
        if (texture) {
          const sprite = new Sprite(texture);
          sprite.anchor.set(0.5, 1);
          sprite.position.set(cx, top + TILE_H);
          const size = SPRITE_SCALE * 0.85;
          sprite.scale.set(tileNoise(building.x, building.y, 7) < 50 ? size : -size, size);
          current.buildings.addChild(sprite);
        } else {
          // No picture for it yet: a plain mark, so nothing built goes unseen.
          g.rect(cx - 3, top + TILE_H / 2 - 4, 6, 4).fill(building.state === "ruin" ? 0x6f6a60 : 0xc9895a);
        }
      }
      current.buildings.addChild(g);
    });
  }, [places]);

  // Camps and settlements.
  useEffect(() => {
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      const layer = current.camps as Container & { wasDragged?: () => boolean };
      for (const child of layer.removeChildren()) child.destroy({ children: true });
      for (const group of [...groups].sort((a, b) => a.y + a.x - (b.y + b.x))) {
        const [cx, cy] = project(group.x, group.y);
        const marker = new Container();
        marker.position.set(cx, cy + TILE_H / 2);
        const g = new Graphics();
        const chosen = group.id === selected;
        if (chosen) g.ellipse(0, 0, 13, 6.5).stroke({ color: 0xffffff, width: 1.5 });
        const texture = current.sheet?.textures[group.settled ? "campfire" : "tent"];
        if (texture) {
          const camp = new Sprite(texture);
          camp.anchor.set(0.5, 1);
          camp.position.set(0, TILE_H / 2);
          camp.scale.set(SPRITE_SCALE * 0.85);
          marker.addChild(camp);
        } else if (group.settled) {
          g.rect(-5, -7, 10, 7).fill(0xc9895a);
          g.poly([-7, -7, 0, -13, 7, -7]).fill(0x8a4f38);
        } else {
          g.poly([-6, 0, 0, -10, 6, 0]).fill(0xe2c98a);
          g.poly([-1.5, 0, 0, -4, 1.5, 0]).fill(0x5a4a34);
        }
        marker.addChild(g);
        const label = new Text({
          text: `${group.settled && group.place ? group.place : group.name} ${group.population}`,
          style: { fontFamily: "'Barlow Semi Condensed', system-ui, sans-serif", fontSize: 11, fontWeight: "500", fill: 0xf2efe6, stroke: { color: 0x10242d, width: 3 } },
        });
        label.anchor.set(0.5, 1);
        label.position.set(0, -16);
        label.resolution = 3;
        marker.addChild(label);
        marker.eventMode = "static";
        marker.cursor = "pointer";
        marker.hitArea = { contains: (x: number, y: number) => Math.abs(x) < 12 && y > -24 && y < 6 };
        marker.on("pointertap", () => {
          if (!layer.wasDragged?.()) onSelectRef.current(group.id);
        });
        layer.addChild(marker);
      }
      fitLabels(layer, current.world.scale.x);
    });
  }, [groups, selected]);

  // The people themselves: figures that walk out from the camp, work and come back.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current?.sheet) return;
      crowd.current.sync(current.people, current.sheet, map, groups, places, current.natureAt);
    });
  }, [map, groups, places]);

  // First view: centre on where the people are, at a scale that suits the screen.
  useEffect(() => {
    if (!map || placed.current) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current || placed.current) return;
      const screen = current.app.screen;
      if (screen.width < 10 || screen.height < 10) return;
      let tx = map.width / 2;
      let ty = map.height / 2;
      const people = groups.reduce((sum, group) => sum + group.population, 0);
      if (people > 0) {
        tx = groups.reduce((sum, group) => sum + group.x * group.population, 0) / people;
        ty = groups.reduce((sum, group) => sum + group.y * group.population, 0) / people;
      } else if (groups.length === 0 && map.width > 0) {
        return; // wait for the camps before deciding where to look
      }
      const narrow = screen.width < 700;
      const fit = Math.min(screen.width / (map.width * TILE_W), screen.height / (map.height * TILE_H));
      const scale = narrow ? 0.62 : Math.max(0.6, Math.min(1.5, fit * 1.15));
      const [cx, cy] = project(tx, ty);
      // On wide screens the chronicle covers the right edge, so look a little left of centre.
      const centreX = narrow ? screen.width / 2 : (screen.width - 380) / 2;
      current.world.scale.set(scale);
      current.world.position.set(centreX - cx * scale, screen.height * (narrow ? 0.45 : 0.5) - cy * scale);
      fitLabels(current.camps, scale);
      placed.current = true;
    });
  }, [map, groups]);

  // Centre the map on a clan when asked to.
  useEffect(() => {
    if (!focus) return;
    void ready.current?.then(() => {
      const current = scene.current;
      const group = groups.find((item) => item.id === focus.id);
      if (!current || !group) return;
      const [cx, cy] = project(group.x, group.y);
      const scale = Math.max(current.world.scale.x, 2);
      current.world.scale.set(scale);
      current.world.position.set(current.app.screen.width / 2 - cx * scale, current.app.screen.height / 2 - cy * scale);
      fitLabels(current.camps, scale);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  return <div className="map" ref={host} />;
}
