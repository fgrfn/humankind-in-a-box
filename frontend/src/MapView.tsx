import { Application, Assets, Container, Graphics, Sprite, type Spritesheet, Text } from "pixi.js";
import { useEffect, useRef } from "react";
import type { Building, Group, Human, Place, WorldMap } from "./api";

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
// Every figure is one living person. What they do and where comes from the
// simulation, which decides it once a month. The walk there and back is that
// month played out on screen; the single steps are display only.

type Task = "out" | "work" | "back" | "rest";

interface Walker {
  sprite: Sprite;
  person: Human;
  clan: number;
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
  spear: boolean;
  reach: Map<number, number>; // tile index -> tile it was reached from
  near: number[];
}

const NEIGHBOURS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
const REACH = 5;
const WALK_SPEED = 0.9; // tiles per second
const FIGURE_SCALE = SPRITE_SCALE * 0.5;

function figureFor(person: Human, band: Band): string {
  if (person.age < 16) return "child";
  if (person.age >= 55) return "elder";
  const kind = person.activity.split(":")[0];
  if (kind === "fish") return "fisher";
  if (kind === "game" && band.spear) return "hunter";
  if (kind === "plants" && person.sex === "f") return "gatherer";
  return person.sex === "f" ? "woman" : "man";
}

class Crowd {
  private bands = new Map<number, Band>();
  private walkers = new Map<number, Walker>();
  private map: WorldMap | null = null;
  onTap: (person: number) => void = () => undefined;
  wasDragged: () => boolean = () => false;

  private dry(x: number, y: number): boolean {
    const map = this.map;
    if (!map || x < 0 || y < 0 || x >= map.width || y >= map.height) return false;
    const biome = map.biomes[map.biome[y * map.width + x]];
    return biome !== "ocean" && biome !== "coast";
  }

  // Everywhere a clan can walk to from its camp without crossing open water.
  private explore(band: Band): void {
    const map = this.map!;
    const start = band.y * map.width + band.x;
    const distance = new Map<number, number>([[start, 0]]);
    band.reach = new Map([[start, start]]);
    band.near = [];
    const queue = [start];
    for (let head = 0; head < queue.length; head++) {
      const index = queue[head];
      const steps = distance.get(index)!;
      if (steps === 1) band.near.push(index);
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
  }

  // The walk from the camp to the tile nearest to where the work is. Fish live
  // in the water, so a fisher ends up on the shore next to it.
  private route(band: Band, tx: number, ty: number): [number, number][] {
    const map = this.map!;
    let best = band.y * map.width + band.x;
    let bestGap = Infinity;
    for (const index of band.reach.keys()) {
      const x = index % map.width;
      const gap = Math.max(Math.abs(x - tx), Math.abs((index - x) / map.width - ty));
      if (gap < bestGap) {
        best = index;
        bestGap = gap;
      }
    }
    const tiles: [number, number][] = [];
    for (let index = best, guard = 0; guard < 64; guard++) {
      tiles.push([index % map.width, Math.floor(index / map.width)]);
      const from = band.reach.get(index);
      if (from === undefined || from === index) break;
      index = from;
    }
    return tiles.reverse();
  }

  sync(layer: Container, sheet: Spritesheet, map: WorldMap, groups: Group[], people: Human[]): void {
    if (this.map !== map) {
      for (const walker of this.walkers.values()) walker.sprite.destroy();
      this.walkers.clear();
      this.bands.clear();
      this.map = map;
    }
    const moved = new Set<number>();
    const bands = new Map<number, Band>();
    for (const group of groups) {
      const old = this.bands.get(group.id);
      const band: Band = old ?? { x: group.x, y: group.y, spear: false, reach: new Map(), near: [] };
      if (old && (old.x !== group.x || old.y !== group.y)) moved.add(group.id);
      band.spear = group.technologies.some((tech) => tech.id === "spear");
      if (!old || moved.has(group.id)) {
        band.x = group.x;
        band.y = group.y;
        this.explore(band);
      }
      bands.set(group.id, band);
    }
    this.bands = bands;
    const alive = new Set<number>();
    for (const person of people) {
      const band = bands.get(person.clan);
      if (!band) continue;
      alive.add(person.id);
      let walker = this.walkers.get(person.id);
      const texture = sheet.textures[figureFor(person, band)] ?? sheet.textures.man;
      if (!walker) {
        const sprite = new Sprite(texture);
        sprite.anchor.set(0.5, 1);
        sprite.scale.set(FIGURE_SCALE);
        sprite.eventMode = "static";
        sprite.cursor = "pointer";
        const id = person.id;
        sprite.on("pointertap", () => {
          if (!this.wasDragged()) this.onTap(id);
        });
        layer.addChild(sprite);
        walker = { sprite, person, clan: person.clan, path: [[band.x, band.y]], leg: 0, along: 0, task: "rest", wait: Math.random() * 20, clock: Math.random() * 10, dx: (Math.random() - 0.5) * 12, dy: (Math.random() - 0.5) * 5 };
        this.walkers.set(person.id, walker);
      } else {
        if (walker.sprite.texture !== texture) walker.sprite.texture = texture;
        if (walker.clan !== person.clan || moved.has(person.clan)) {
          // A new camp, or a new clan: walk straight there from wherever one stands.
          const [fx, fy] = this.where(walker);
          walker.path = [[fx, fy], [band.x, band.y]];
          walker.leg = 0;
          walker.along = 0;
          walker.task = "back";
          walker.clan = person.clan;
        }
        walker.person = person;
      }
    }
    for (const [id, walker] of this.walkers) {
      if (alive.has(id)) continue;
      walker.sprite.destroy();
      this.walkers.delete(id);
    }
  }

  private where(walker: Walker): [number, number] {
    const a = walker.path[walker.leg];
    const b = walker.path[Math.min(walker.leg + 1, walker.path.length - 1)];
    return [a[0] + (b[0] - a[0]) * walker.along, a[1] + (b[1] - a[1]) * walker.along];
  }

  step(seconds: number): void {
    const map = this.map;
    if (!map) return;
    for (const walker of this.walkers.values()) {
      const band = this.bands.get(walker.clan);
      if (!band) continue;
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
            const person = walker.person;
            if (person.activity && person.x >= 0) {
              walker.path = this.route(band, person.x, person.y);
            } else if (band.near.length) {
              // Children and those without work stay around the camp.
              const index = band.near[Math.floor(Math.random() * band.near.length)];
              walker.path = [[band.x, band.y], [index % map.width, Math.floor(index / map.width)]];
            } else {
              walker.wait = 6;
              continue;
            }
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
        if (heading !== 0) walker.sprite.scale.x = heading > 0 ? FIGURE_SCALE : -FIGURE_SCALE;
        if (walker.along >= 1) {
          walker.along = 0;
          walker.leg += 1;
          if (walker.leg >= walker.path.length - 1) {
            walker.leg = walker.path.length - 1;
            walker.wait = walker.task === "out" ? 6 + Math.random() * 10 : 4 + Math.random() * 14;
            walker.task = walker.task === "out" ? "work" : "rest";
          }
        }
      }
      const [fx, fy] = this.where(walker);
      const [sx, sy] = project(fx, fy);
      const spread = walker.task === "rest" ? 1 : 0.5;
      walker.sprite.position.set(sx + walker.dx * spread, sy + TILE_H / 2 + 2 + walker.dy * spread - lift);
      walker.sprite.zIndex = sy + walker.dy;
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
  people: Human[];
  selected: number | null;
  focus: { id: number; nonce: number } | null;
  onSelect: (id: number) => void;
  onPerson: (id: number) => void;
}

export function MapView({ map, steps, groups, places, people, selected, focus, onSelect, onPerson }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<Scene | null>(null);
  const ready = useRef<Promise<void> | null>(null);
  const placed = useRef(false);
  const crowd = useRef(new Crowd());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  crowd.current.onTap = onPerson;

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
        crowd.current.wasDragged = () => moved > 6;
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
      crowd.current.sync(current.people, current.sheet, map, groups, people);
    });
  }, [map, groups, people]);

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
