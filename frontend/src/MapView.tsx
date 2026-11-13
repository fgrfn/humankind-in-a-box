import { Application, Assets, Container, Graphics, Sprite, type Spritesheet, Text } from "pixi.js";
import { useEffect, useRef } from "react";
import { faithColour, peopleColour, realmColour } from "./colours";
import type { Building, Faith, Group, Human, Land, Place, Realm, TradeLink, War, WorldMap } from "./api";

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
  granary: "granary",
  well: "well",
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

// The land stands in terraces, as in Letopis: every tile sits at one of a few
// heights and shows its earth or rock wall where the land in front is lower.
const STEP = 6; // screen pixels per terrace
let terraces: Uint8Array | null = null;
let terraceWidth = 0;

function terrace(x: number, y: number): number {
  if (!terraces) return 0;
  const tx = Math.round(x);
  const ty = Math.round(y);
  if (tx < 0 || ty < 0 || tx >= terraceWidth || ty * terraceWidth + tx >= terraces.length) return 0;
  return terraces[ty * terraceWidth + tx];
}

function project(x: number, y: number): [number, number] {
  return [((x - y) * TILE_W) / 2, ((x + y) * TILE_H) / 2 - terrace(x, y) * STEP];
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
      if (child.label === "tag" || child instanceof Text) {
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
  techs: Set<string>;
  leader: number;
  reach: Map<number, number>; // tile index -> tile it was reached from
  near: number[];
}

const NEIGHBOURS = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]];
const REACH = 5;
const WALK_SPEED = 0.6; // tiles per second
const FIGURE_SCALE = SPRITE_SCALE * 0.5;

// Until a figure has its own picture, a close one stands in for it.
const STAND_INS: Record<string, string> = { sick: "fallen", healer: "elder", shaman: "elder" };

function figureFor(person: Human, band: Band): string {
  if (person.age < 16) return "child";
  const kind = person.activity.split(":")[0];
  if (kind === "fight") {
    // What they carry follows what their clan knows; who carries what is fixed per person.
    if (band.techs.has("bronze")) return "bronze_warrior";
    if (band.techs.has("bow") && person.id % 3 === 0) return "archer";
    return person.id % 2 === 0 ? "shield_warrior" : "warrior";
  }
  if (kind === "pray") return person.sex === "f" ? "priestess" : "shaman";
  if (kind === "sick") return "sick";
  if (kind === "heal") return "healer";
  if (person.id === band.leader) return "chieftain";
  if (person.age >= 55) return "elder";
  if (kind === "soil") return "farmer";
  if (kind === "pasture") return "herder";
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
  // Tiles with a building or a tree on them; people idle elsewhere.
  blocked = new Set<number>();

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
      // Where people linger around the camp: open ground, not where a hut or tree stands.
      if (steps === 1 && !this.blocked.has(index)) band.near.push(index);
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

  // To war the way is longer than to work: straight towards the field, tile by
  // tile, as far as dry land goes.
  private march(band: Band, tx: number, ty: number): [number, number][] {
    const tiles: [number, number][] = [[band.x, band.y]];
    const steps = Math.max(Math.abs(tx - band.x), Math.abs(ty - band.y));
    for (let n = 1; n <= steps; n++) {
      const x = Math.round(band.x + ((tx - band.x) * n) / steps);
      const y = Math.round(band.y + ((ty - band.y) * n) / steps);
      if (!this.dry(x, y)) break;
      tiles.push([x, y]);
    }
    return tiles;
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
      const band: Band = old ?? { x: group.x, y: group.y, spear: false, techs: new Set(), leader: 0, reach: new Map(), near: [] };
      if (old && (old.x !== group.x || old.y !== group.y)) moved.add(group.id);
      band.techs = new Set(group.technologies.map((tech) => tech.id));
      band.spear = band.techs.has("spear");
      band.leader = group.leader?.id ?? 0;
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
      const figure = figureFor(person, band);
      const texture = sheet.textures[figure] ?? sheet.textures[STAND_INS[figure] ?? "man"] ?? sheet.textures.man;
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
          // Straight to the new camp only over land; across water they simply arrive.
          const steps = Math.ceil(Math.max(Math.abs(band.x - fx), Math.abs(band.y - fy)));
          let overLand = steps <= 12;
          for (let n = 1; overLand && n < steps; n++) {
            overLand = this.dry(Math.round(fx + ((band.x - fx) * n) / steps), Math.round(fy + ((band.y - fy) * n) / steps));
          }
          walker.path = overLand ? [[fx, fy], [band.x, band.y]] : [[band.x, band.y]];
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

  // `view` is the part of the map on screen, in map units: figures outside it are
  // not drawn, so a big world costs no more than what you are looking at.
  step(seconds: number, view: { left: number; top: number; right: number; bottom: number }): void {
    const map = this.map;
    if (!map) return;
    for (const walker of this.walkers.values()) {
      const band = this.bands.get(walker.clan);
      if (!band) continue;
      walker.clock += seconds;
      let lift = 0;
      if (walker.task === "rest" || walker.task === "work") {
        walker.wait -= seconds;
        // Calm motion: a slow bend at work, a turn now and then in a fight.
        if (walker.task === "work") lift = Math.abs(Math.sin(walker.clock * 2.6)) * 0.6;
        if (walker.task === "work" && walker.person.activity === "sick") lift = 0; // the sick lie still
        if (walker.task === "work" && walker.person.activity.startsWith("fight:")) {
          lift = Math.abs(Math.sin(walker.clock * 4)) * 0.9;
          walker.sprite.scale.x = Math.sin(walker.clock * 0.7 + walker.dx) > 0 ? FIGURE_SCALE : -FIGURE_SCALE;
        }
        if (walker.wait <= 0) {
          if (walker.task === "work") {
            walker.path = [...walker.path].reverse();
            walker.task = "back";
          } else {
            const person = walker.person;
            if (person.activity.startsWith("fight:") && person.x >= 0) {
              walker.path = this.march(band, person.x, person.y);
            } else if (person.activity && person.x >= 0) {
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
        lift = Math.abs(Math.sin(walker.clock * 6)) * 0.35;
        const heading = b[0] - a[0] - (b[1] - a[1]); // on screen: positive walks right
        if (heading !== 0) walker.sprite.scale.x = heading > 0 ? FIGURE_SCALE : -FIGURE_SCALE;
        if (walker.along >= 1) {
          walker.along = 0;
          walker.leg += 1;
          if (walker.leg >= walker.path.length - 1) {
            walker.leg = walker.path.length - 1;
            walker.wait = walker.task === "out" ? 10 + Math.random() * 14 : 8 + Math.random() * 20;
            walker.task = walker.task === "out" ? "work" : "rest";
          }
        }
      }
      const [fx, fy] = this.where(walker);
      const [sx, sy] = project(fx, fy);
      const seen = sx >= view.left && sx <= view.right && sy >= view.top && sy <= view.bottom;
      walker.sprite.visible = seen;
      if (!seen) continue;
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
  borders: Container;
  names: Container;
  routes: Container;
  fields: Container;
  nature: Container;
  wildlife: Container;
  buildings: Container;
  lodges: Container;
  people: Container;
  camps: Container;
  sheet: Spritesheet | null;
  natureAt: Map<number, Sprite>;
  natureKind: Map<number, string>;
}

// Where to send the camera: a clan, or a tile.
export interface Focus {
  nonce: number;
  id?: number;
  y?: number;
  x?: number;
}

interface Props {
  map: WorldMap | null;
  steps: number[];
  groups: Group[];
  places: Place[];
  people: Human[];
  land: Land | null;
  landBy: "peoples" | "realms" | "faiths";
  realms: Realm[];
  wars: War[];
  faiths: Faith[];
  year: number;
  stocks: Record<string, number[]>;
  links: TradeLink[];
  active: boolean;
  selected: number | null;
  focus: Focus | null;
  onSelect: (id: number) => void;
  onPerson: (id: number) => void;
}

export function MapView({ active, map, steps, groups, places, people, land, landBy, realms, wars, faiths, year, stocks, links, selected, focus, onSelect, onPerson }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<Scene | null>(null);
  const ready = useRef<Promise<void> | null>(null);
  const placed = useRef(false);
  const crowd = useRef(new Crowd());
  const campsAt = useRef(new Map<number, [number, number]>());
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  crowd.current.onTap = onPerson;

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const app = new Application();
    let disposed = false;
    let resizer: ResizeObserver | null = null;
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
        const fields = new Container();
        const borders = new Container();
        const routes = new Container();
        const names = new Container();
        const nature = new Container();
        const wildlife = new Container();
        const buildings = new Container();
        const people = new Container();
        people.sortableChildren = true;
        const camps = new Container();
        // Camps' huts and tents stand with the buildings, below the people;
        // big names and the small name plates are drawn over everything.
        const lodges = new Container();
        world.addChild(terrain, fields, paths, borders, routes, nature, wildlife, buildings, lodges, people, names, camps);
        app.stage.addChild(world);
        scene.current = { app, world, terrain, paths, borders, names, routes, fields, nature, wildlife, buildings, lodges, people, camps, sheet, natureAt: new Map(), natureKind: new Map() };
        app.ticker.add((ticker) => {
          people.visible = world.scale.x >= 0.9; // too small to read from far away
          if (!people.visible) return;
          const scale = world.scale.x;
          const edge = 24;
          crowd.current.step(Math.min(0.1, ticker.deltaMS / 1000), {
            left: -world.position.x / scale - edge,
            top: -world.position.y / scale - edge,
            right: (app.screen.width - world.position.x) / scale + edge,
            bottom: (app.screen.height - world.position.y) / scale + edge,
          });
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
        // The map's box changes not only with the window: rows above it appear
        // once the first numbers arrive, panels open and close. Follow the box.
        resizer = new ResizeObserver(() => {
          if (!disposed) app.resize();
        });
        resizer.observe(element);
      });

    return () => {
      disposed = true;
      resizer?.disconnect();
      const current = scene.current;
      scene.current = null;
      if (current) current.app.destroy(true, { children: true });
    };
  }, []);

  // While another view is open the map keeps its size but stops drawing:
  // a canvas shrunk to nothing and grown again is slow to recover, and drawing
  // what nobody sees wastes the battery.
  useEffect(() => {
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      if (active) current.app.ticker.start();
      else current.app.ticker.stop();
    });
  }, [active]);

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
      current.natureKind.clear();
      const textures = current.sheet?.textures ?? {};
      const fallback = new Graphics();
      const marks = new Graphics();
      const peaks = map.biome
        .map((biome, index) => (map.biomes[biome] === "mountain" ? map.elevation[index] : -1))
        .filter((height) => height >= 0)
        .sort((a, b) => a - b);
      const snowLine = peaks.length ? peaks[Math.floor(peaks.length * 0.7)] : Infinity;
      // The highest land outside the mountains is hill country.
      const lowland = map.biome
        .map((biome, index) => (["ocean", "coast", "mountain"].includes(map.biomes[biome]) ? -1 : map.elevation[index]))
        .filter((height) => height >= 0)
        .sort((a, b) => a - b);
      // Terraces: land rises in steps of a sixth of its height range, water lies flat.
      const highest = lowland.length ? Math.max(lowland[lowland.length - 1], peaks.length ? peaks[peaks.length - 1] : 0) : 1;
      terraceWidth = map.width;
      terraces = new Uint8Array(map.width * map.height);
      for (let index = 0; index < terraces.length; index++) {
        const name = map.biomes[map.biome[index]];
        if (name === "ocean" || name === "coast") continue;
        const level = Math.max(1, Math.min(7, 1 + Math.floor((map.elevation[index] * 7) / Math.max(1, highest))));
        // A river runs a step below the land around it.
        terraces[index] = map.river[index] ? Math.max(1, level - 1) : level;
      }
      // Diagonal by diagonal, so things further south cover what is behind them.
      const levels = terraces;
      for (let sum = 0; sum <= map.width + map.height - 2; sum++) {
        const walls = new Graphics();
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
          // Walls on the two sides facing the viewer, down to the lower neighbour.
          const level = levels[index];
          if (level > 0) {
            const rocky = biome === "mountain" || ground === "rock" || ground === "snow";
            const left = rocky ? 0x6a6560 : 0x6f4d33;
            const right = rocky ? 0x524e4a : 0x573b27;
            const lx = cx - TILE_W / 2;
            const midY = cy + TILE_H / 2;
            const bottomY = cy + TILE_H;
            const below = (nx: number, ny: number) => (nx < map.width && ny < map.height ? levels[ny * map.width + nx] : 0);
            const dl = level - below(x, y + 1);
            if (dl > 0) {
              walls.poly([lx, midY, cx, bottomY, cx, bottomY + dl * STEP, lx, midY + dl * STEP]).fill(left);
              walls.moveTo(lx, midY + dl * STEP).lineTo(cx, bottomY + dl * STEP).stroke({ color: 0x2b1d14, width: 0.5, alpha: 0.5 });
            }
            const dr = level - below(x + 1, y);
            if (dr > 0) {
              walls.poly([cx, bottomY, cx + TILE_W / 2, midY, cx + TILE_W / 2, midY + dr * STEP, cx, bottomY + dr * STEP]).fill(right);
              walls.moveTo(cx, bottomY + dr * STEP).lineTo(cx + TILE_W / 2, midY + dr * STEP).stroke({ color: 0x2b1d14, width: 0.5, alpha: 0.5 });
            }
          }
          if (water) continue;
          // The terraces carry the height; mountains add rock and, highest up, peaks.
          const hill = map.river[index] || biome !== "mountain" ? null : map.elevation[index] >= snowLine ? "mountain" : tileNoise(x, y, 11) < 45 ? "rocky_hill" : null;
          if (hill && textures[hill]) {
            const sprite = new Sprite(textures[hill]);
            sprite.anchor.set(0.5, 1);
            sprite.position.set(cx, cy + TILE_H);
            const size = SPRITE_SCALE * (hill === "mountain" ? 1 : 0.92);
            sprite.scale.set(tileNoise(x, y, 12) < 50 ? size : -size, size);
            current.nature.addChild(sprite);
          }
          const deposit = map.deposit[index];
          let object: string | null = null;
          if (deposit >= 0) {
            object = DEPOSIT_SPRITES[map.deposits[deposit]?.id] ?? null;
            if (!object) marks.circle(cx, cy + TILE_H / 2, 1.6).fill(DEPOSIT_COLOURS[deposit % DEPOSIT_COLOURS.length]);
          } else if (!hill) {
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
            if (deposit < 0) current.natureKind.set(index, object);
          }
        }
        current.terrain.addChild(walls);
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

  // Territories: land tinted in the colour of the people (or chiefdom) that
  // holds it, a strong line where two meet and a faint one between its clans.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      for (const child of current.borders.removeChildren()) child.destroy();
      for (const child of current.names.removeChildren()) child.destroy();
      if (!land || land.peoples.length !== map.width * map.height) return;
      const owners = landBy === "realms" ? land.realms ?? [] : landBy === "faiths" ? land.faiths ?? [] : land.peoples;
      if (owners.length !== map.width * map.height) return;
      const ownerNames =
        landBy === "realms"
          ? new Map(realms.filter((realm) => realm.ended_year === null).map((realm) => [realm.id, realm.name]))
          : landBy === "faiths"
            ? new Map(groups.filter((group) => group.faith).map((group) => [group.faith!.id, group.faith!.name]))
            : new Map(groups.filter((group) => group.people).map((group) => [group.people_id, group.people as string]));
      const colourOf = landBy === "realms" ? realmColour : landBy === "faiths" ? faithColour : peopleColour;
      const wash = new Graphics();
      const inner = new Graphics();
      const casing = new Graphics();
      const outer = new Graphics();
      const at = (x: number, y: number, list: number[]) => (x < 0 || y < 0 || x >= map.width || y >= map.height ? 0 : list[y * map.width + x]);
      const centre = new Map<number, { x: number; y: number; n: number }>();
      for (let y = 0; y < map.height; y++) {
        for (let x = 0; x < map.width; x++) {
          const people = owners[y * map.width + x];
          if (!people) continue;
          const clan = land.clans[y * map.width + x];
          const colour = colourOf(people);
          diamond(wash, x, y);
          wash.fill({ color: colour, alpha: 0.26 });
          const [cx, top] = project(x, y);
          const cy = top + TILE_H / 2;
          const sum = centre.get(people) ?? { x: 0, y: 0, n: 0 };
          sum.x += cx;
          sum.y += cy;
          sum.n += 1;
          centre.set(people, sum);
          // The four edges of the tile and the neighbour behind each.
          const edges: [number, number, number, number, number, number][] = [
            [cx, top, cx + TILE_W / 2, cy, x, y - 1],
            [cx + TILE_W / 2, cy, cx, top + TILE_H, x + 1, y],
            [cx, top + TILE_H, cx - TILE_W / 2, cy, x, y + 1],
            [cx - TILE_W / 2, cy, cx, top, x - 1, y],
          ];
          for (const [x1, y1, x2, y2, nx, ny] of edges) {
            if (at(nx, ny, owners) !== people) {
              // Dark underneath, colour on top: readable on grass, snow and sand alike.
              casing.moveTo(x1, y1).lineTo(x2, y2).stroke({ color: 0x10242d, width: 4, alpha: 0.75, cap: "round" });
              outer.moveTo(x1, y1).lineTo(x2, y2).stroke({ color: colour, width: 2.2, alpha: 1, cap: "round" });
            } else if (at(nx, ny, land.clans) !== clan && (nx > x || ny > y)) {
              inner.moveTo(x1, y1).lineTo(x2, y2).stroke({ color: colour, width: 0.7, alpha: 0.55 });
            }
          }
        }
      }
      const layer = current.borders;
      layer.addChild(wash, inner, casing, outer);
      // The name of each people on its land, so colour and name can be told together.
      const names = current.names;
      for (const [people, sum] of centre) {
        const name = ownerNames.get(people);
        if (!name || sum.n < 12) continue;
        // The middle of a scattered territory can lie in the sea: take the
        // people's own tile nearest to it.
        const mx = sum.x / sum.n;
        const my = sum.y / sum.n;
        let best = Infinity;
        let px = mx;
        let py = my;
        for (let index = 0; index < owners.length; index++) {
          if (owners[index] !== people) continue;
          const tx = index % map.width;
          const [cx, top] = project(tx, (index - tx) / map.width);
          const gap = (cx - mx) ** 2 + (top + TILE_H / 2 - my) ** 2;
          if (gap < best) {
            best = gap;
            px = cx;
            py = top + TILE_H / 2;
          }
        }
        const text = new Text({
          text: name,
          style: { fontFamily: "'Vollkorn', Georgia, serif", fontSize: Math.min(30, 11 + Math.sqrt(sum.n)), fontWeight: "600", fill: colourOf(people), stroke: { color: 0x10242d, width: 4 }, letterSpacing: 1 },
        });
        text.anchor.set(0.5);
        text.position.set(px, py);
        text.alpha = 0.92;
        text.resolution = 2;
        names.addChild(text);
      }
    });
  }, [map, land, landBy, realms, groups]);

  // Trade: a dashed line between partners.
  useEffect(() => {
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      for (const child of current.routes.removeChildren()) child.destroy();
      const g = new Graphics();
      for (const link of links) {
        const [x1, top1] = project(link.ax, link.ay);
        const [x2, top2] = project(link.bx, link.by);
        const y1 = top1 + TILE_H / 2;
        const y2 = top2 + TILE_H / 2;
        const length = Math.hypot(x2 - x1, y2 - y1);
        const dashes = Math.max(1, Math.floor(length / 7));
        for (let n = 0; n < dashes; n++) {
          const from = n / dashes;
          const to = (n + 0.55) / dashes;
          g.moveTo(x1 + (x2 - x1) * from, y1 + (y2 - y1) * from).lineTo(x1 + (x2 - x1) * to, y1 + (y2 - y1) * to);
        }
        g.stroke({ color: 0x10242d, width: 2.6, alpha: 0.55 });
        for (let n = 0; n < dashes; n++) {
          const from = n / dashes;
          const to = (n + 0.55) / dashes;
          g.moveTo(x1 + (x2 - x1) * from, y1 + (y2 - y1) * from).lineTo(x1 + (x2 - x1) * to, y1 + (y2 - y1) * to);
        }
        g.stroke({ color: 0xf2efe6, width: 1.2, alpha: 0.9 });
      }
      // War: a red line from each seat to the field where the two sides meet,
      // crossed marks on the field, graves of the fallen that fade over ten
      // years, and the winner's banner where a chiefdom was conquered.
      const sprites: Sprite[] = [];
      const point = (x: number, y: number): [number, number] => {
        const [px, top] = project(x, y);
        return [px, top + TILE_H / 2];
      };
      for (const war of wars) {
        const field = war.field;
        if (!field) continue;
        const [fx, fy] = point(field.x, field.y);
        if (war.ended_year === null) {
          for (const side of [war.attacker, war.defender]) {
            if (side.x === null || side.y === null) continue;
            const [sx, sy] = point(side.x, side.y);
            g.moveTo(sx, sy).lineTo(fx, fy).stroke({ color: 0x10242d, width: 4.5, alpha: 0.6, cap: "round" });
            g.moveTo(sx, sy).lineTo(fx, fy).stroke({ color: realmColour(side.id), width: 2, alpha: 0.95, cap: "round" });
          }
          g.moveTo(fx - 7, fy - 7).lineTo(fx + 7, fy + 7).moveTo(fx + 7, fy - 7).lineTo(fx - 7, fy + 7).stroke({ color: 0x10242d, width: 5.5, cap: "round" });
          g.moveTo(fx - 7, fy - 7).lineTo(fx + 7, fy + 7).moveTo(fx + 7, fy - 7).lineTo(fx - 7, fy + 7).stroke({ color: 0xe8453c, width: 2.6, cap: "round" });
        }
        const since = war.last_battle_year === null ? Infinity : year - war.last_battle_year;
        const textures = current.sheet?.textures ?? {};
        const place = (name: string, x: number, y: number, alpha: number, flip: boolean, size = SPRITE_SCALE * 0.6) => {
          const texture = textures[name];
          if (!texture) return false;
          const sprite = new Sprite(texture);
          sprite.anchor.set(0.5, 1);
          sprite.position.set(x, y);
          sprite.scale.set(flip ? -size : size, size);
          sprite.alpha = alpha;
          sprites.push(sprite);
          return true;
        };
        if (since <= 10 && war.last_fallen > 0) {
          const fade = 1 - since / 11;
          // The year of the battle the fallen still lie on the field; after that, mounds.
          const lying = since < 1;
          const count = lying ? Math.min(12, war.last_fallen) : Math.min(4, Math.ceil(war.fallen / 8));
          for (let n = 0; n < count; n++) {
            const ox = (tileNoise(war.id, n, 7) - 50) / 50;
            const oy = (tileNoise(n, war.id, 8) - 50) / 50;
            const gx = fx + ox * TILE_W * (lying ? 1.1 : 0.8);
            const gy = fy + oy * TILE_H * (lying ? 1.1 : 0.8) + 4;
            if (place(lying ? "fallen" : "burial_mound", gx, gy, fade, tileNoise(n, war.id, 9) < 50, SPRITE_SCALE * (lying ? 0.5 : 0.62))) continue;
            g.ellipse(gx, gy, 4.4, 2.2).fill({ color: 0x5b4632, alpha: 0.9 * fade });
          }
        }
        if (war.outcome === "conquest" && war.winner_id !== null && war.ended_year !== null && year - war.ended_year <= 5) {
          const fade = 1 - (year - war.ended_year) / 6;
          if (!place("war_banner", fx, fy + 6, fade, false, SPRITE_SCALE * 0.75)) {
            g.moveTo(fx, fy + 2).lineTo(fx, fy - 18).stroke({ color: 0x3a2a1a, width: 1.4, alpha: fade });
          }
          // A pennant in the winner's colour, so one can tell whose it is.
          g.poly([fx + 1, fy - 26, fx + 10, fy - 23, fx + 1, fy - 20]).fill({ color: realmColour(war.winner_id), alpha: fade }).stroke({ color: 0x10242d, width: 0.8, alpha: fade });
        }
      }
      current.routes.addChild(g);
      for (const sprite of sprites.sort((a, b) => a.y - b.y)) current.routes.addChild(sprite);
    });
  }, [links, wars, year]);

  // Woods and bushes thin out where people take from them and grow back when
  // left alone: a tree shows full, young, or not at all, by what the tile holds.
  useEffect(() => {
    if (!map?.capacity) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      for (const [index, kind] of current.natureKind) {
        const resource = kind === "berry_bush" || kind === "reeds" ? "plants" : "wood";
        const values = stocks[resource];
        const capacity = map.capacity?.[resource]?.[map.biomes[map.biome[index]]] ?? 0;
        const sprite = current.natureAt.get(index);
        if (!values || values.length !== map.width * map.height || !sprite || capacity <= 0) continue;
        const ratio = values[index] / capacity;
        const base = (sprite as Sprite & { base?: number }).base ?? Math.abs(sprite.scale.y);
        (sprite as Sprite & { base?: number }).base = base;
        const size = ratio < 0.2 ? base * 0.45 : ratio < 0.55 ? base * 0.72 : base;
        sprite.alpha = ratio < 0.12 ? 0 : 1;
        sprite.scale.set(Math.sign(sprite.scale.x) * size, size);
      }
    });
  }, [map, stocks]);

  // Wild animals: where game is plentiful, now and then one stands about, of a
  // kind that fits the land. Fewer where people hunt; mammoths only in the
  // early world.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      const textures = current?.sheet?.textures;
      if (!current || !textures) return;
      for (const child of current.wildlife.removeChildren()) child.destroy();
      const game = stocks.game;
      if (!game || game.length !== map.width * map.height) return;
      const kinds: Record<string, string[]> = {
        forest: ["deer", "deer", "boar", "boar", "wolf", "bear"],
        taiga: ["deer", "wolf", "bear", "boar"],
        tundra: year < 400 ? ["mammoth", "deer", "wolf"] : ["deer", "wolf"],
        grassland: ["aurochs", "wild_horse", "deer", "aurochs"],
        steppe: ["wild_horse", "wild_horse", "aurochs"],
        marsh: ["geese", "geese", "boar"],
      };
      for (let index = 0; index < game.length; index++) {
        if (map.river[index]) continue;
        const x = index % map.width;
        const y = (index - x) / map.width;
        const biome = map.biomes[map.biome[index]];
        const options = kinds[biome];
        const capacity = map.capacity?.game?.[biome] ?? 0;
        if (!options || capacity <= 0 || game[index] < capacity * 0.6) continue;
        if (tileNoise(x, y, 31) >= 3) continue;
        const kind = options[tileNoise(x, y, 32) % options.length];
        const texture = textures[kind];
        if (!texture) continue;
        const [cx, cy] = project(x, y);
        const sprite = new Sprite(texture);
        sprite.anchor.set(0.5, 1);
        sprite.position.set(cx + (tileNoise(x, y, 33) - 50) / 6, cy + TILE_H * 0.8);
        const size = FIGURE_SCALE * (kind === "mammoth" ? 1.1 : kind === "geese" ? 0.5 : kind === "bear" || kind === "aurochs" ? 0.8 : 0.65);
        sprite.scale.set(tileNoise(x, y, 34) < 50 ? size : -size, size);
        current.wildlife.addChild(sprite);
      }
    });
  }, [map, stocks, year]);

  // Fields: the tiles where people work the soil this month.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      const texture = current?.sheet?.textures.farmland;
      const crop = current?.sheet?.textures.crop_field;
      if (!current || !texture) return;
      for (const child of current.fields.removeChildren()) child.destroy();
      const tilled = new Set<number>();
      for (const person of people) {
        if (person.activity === "soil" && person.x >= 0) tilled.add(person.y * map.width + person.x);
      }
      for (const index of tilled) {
        const x = index % map.width;
        const y = (index - x) / map.width;
        if (map.river[index] || ["ocean", "coast"].includes(map.biomes[map.biome[index]])) continue;
        const [cx, cy] = project(x, y);
        const tile = new Sprite(texture);
        tile.anchor.set(0.5);
        tile.position.set(cx, cy + TILE_H / 2);
        tile.scale.set(SPRITE_SCALE);
        current.fields.addChild(tile);
        if (crop) {
          const field = new Sprite(crop);
          field.anchor.set(0.5, 1);
          field.position.set(cx, cy + TILE_H);
          field.scale.set(SPRITE_SCALE * 0.8);
          current.fields.addChild(field);
        }
        const grown = current.natureAt.get(index);
        if (grown) grown.visible = false;
      }
    });
  }, [map, people]);

  // Where huts and trees stand, so people idle beside them rather than in them.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      const blocked = new Set<number>();
      for (const place of places) for (const building of place.buildings) blocked.add(building.y * map.width + building.x);
      for (const [index, kind] of current.natureKind) if (kind !== "berry_bush" && kind !== "reeds") blocked.add(index);
      crowd.current.blocked = blocked;
    });
  }, [map, places]);

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
      for (const child of current.lodges.removeChildren()) child.destroy({ children: true });
      const before = campsAt.current;
      const now = new Map<number, [number, number]>();
      const gliding: [Container, number, number, number, number][] = [];
      for (const group of [...groups].sort((a, b) => a.y + a.x - (b.y + b.x))) {
        const [cx, cy] = project(group.x, group.y);
        const marker = new Container();
        const lodge = new Container();
        marker.position.set(cx, cy + TILE_H / 2);
        lodge.position.set(cx, cy + TILE_H / 2);
        now.set(group.id, [cx, cy + TILE_H / 2]);
        const was = before.get(group.id);
        if (was && (was[0] !== cx || was[1] !== cy + TILE_H / 2)) {
          // A camp that moved glides to its new place instead of jumping.
          gliding.push([marker, was[0], was[1], cx, cy + TILE_H / 2]);
          gliding.push([lodge, was[0], was[1], cx, cy + TILE_H / 2]);
          marker.position.set(was[0], was[1]);
          lodge.position.set(was[0], was[1]);
        }
        current.lodges.addChild(lodge);
        const g = new Graphics();
        const chosen = group.id === selected;
        if (chosen) g.ellipse(0, 0, 13, 6.5).stroke({ color: 0xffffff, width: 1.5 });
        const texture = current.sheet?.textures[group.settled ? "campfire" : "tent"];
        if (texture) {
          const camp = new Sprite(texture);
          camp.anchor.set(0.5, 1);
          camp.position.set(0, TILE_H / 2);
          camp.scale.set(SPRITE_SCALE * 0.85);
          lodge.addChild(camp);
        } else if (group.settled) {
          g.rect(-5, -7, 10, 7).fill(0xc9895a);
          g.poly([-7, -7, 0, -13, 7, -7]).fill(0x8a4f38);
        } else {
          g.poly([-6, 0, 0, -10, 6, 0]).fill(0xe2c98a);
          g.poly([-1.5, 0, 0, -4, 1.5, 0]).fill(0x5a4a34);
        }
        // The seat of a chiefdom has the chieftain's longhouse, fenced while at war;
        // a settlement that works metal has a smithy.
        const sheetTextures = current.sheet?.textures ?? {};
        const extra = (name: string, x: number, y: number, size: number, flip = false) => {
          const texture = sheetTextures[name];
          if (!texture) return;
          const sprite = new Sprite(texture);
          sprite.anchor.set(0.5, 1);
          sprite.position.set(x, y);
          sprite.scale.set(flip ? -size : size, size);
          lodge.addChildAt(sprite, 0);
        };
        if (group.herd) {
          // The herd beside the camp: more kinds of animal as it grows, a pen
          // where people have settled. Shown once the animal pictures exist.
          if (group.settled) extra("pen", -TILE_W * 0.75, TILE_H * 0.6, FIGURE_SCALE * 0.9);
          extra("sheep", -TILE_W * 0.75, TILE_H * 0.5, FIGURE_SCALE * 0.6);
          if (group.herd >= 20) extra("goats", -TILE_W * 0.45, TILE_H * 0.85, FIGURE_SCALE * 0.6, true);
          if (group.herd >= 40) extra("cow", -TILE_W * 1.05, TILE_H * 0.8, FIGURE_SCALE * 0.7);
          if (group.technologies.some((tech) => tech.id === "horse_riding")) extra("tame_horse", TILE_W * 0.95, TILE_H * 0.65, FIGURE_SCALE * 0.75, true);
        }
        if (group.faith) {
          // Where a faith began stands a stone circle; settled believers keep a
          // shrine, wanderers a sacred fire.
          const origin = faiths.find((faith) => faith.id === group.faith!.id)?.origin_id === group.id;
          if (origin) extra("stone_circle", -TILE_W * 0.7, -TILE_H * 0.3, SPRITE_SCALE * 0.7);
          else if (group.settled) extra("shrine", -TILE_W * 0.6, -TILE_H * 0.35, SPRITE_SCALE * 0.6);
          else extra("sacred_fire", -TILE_W * 0.45, TILE_H * 0.2, SPRITE_SCALE * 0.5);
        }
        if (group.sick) {
          // While a fever goes round, the sick lie by a healer's hut.
          extra("healer_hut", TILE_W * 0.1, -TILE_H * 0.35, SPRITE_SCALE * 0.6);
        }
        if (group.settled && group.technologies.some((tech) => tech.id === "copper_working")) {
          extra("smithy", -TILE_W * 0.55, TILE_H * 0.1, SPRITE_SCALE * 0.7);
        }
        if (group.realm?.seat) {
          extra("longhouse", TILE_W * 0.6, TILE_H * 0.15, SPRITE_SCALE * 0.85);
          const atWar = wars.some((war) => war.ended_year === null && (war.attacker.id === group.realm!.id || war.defender.id === group.realm!.id));
          if (atWar) {
            extra("palisade", -TILE_W * 0.35, TILE_H * 0.85, SPRITE_SCALE * 0.6);
            extra("palisade", TILE_W * 0.35, TILE_H * 0.85, SPRITE_SCALE * 0.6, true);
          }
        }
        marker.addChild(g);
        // A name plate: dark ground, framed in the colour of the people; a
        // chiefdom's clans carry its colour as a band on the left.
        const tag = new Container();
        tag.label = "tag";
        tag.position.set(0, -14);
        // In a land the clans are villages: they go by their place, framed in
        // the land's colour, and the seat carries the land's name.
        const village = Boolean(group.realm?.land);
        const home = group.settled && group.place ? group.place : group.name;
        const label = new Text({
          text: village && group.realm?.seat ? `${group.realm.name} ${group.population}` : `${home} ${group.population}`,
          style: {
            fontFamily: "'Barlow Semi Condensed', system-ui, sans-serif",
            fontSize: village && !group.realm?.seat ? 10 : 11,
            fontWeight: village && group.realm?.seat ? "700" : "600",
            fill: 0xf2efe6,
          },
        });
        label.anchor.set(0.5, 1);
        label.resolution = 3;
        const band = group.realm ? 5 : 0;
        const width = label.width + 10 + band;
        const plate = new Graphics();
        plate.roundRect(-width / 2, -label.height - 3, width, label.height + 4, 3).fill({ color: 0x10242d, alpha: 0.88 }).stroke({ color: village ? realmColour(group.realm!.id) : peopleColour(group.people_id), width: village && group.realm?.seat ? 2 : 1.4 });
        if (group.realm) plate.rect(-width / 2 + 1.5, -label.height - 1.5, 3.5, label.height + 1).fill(realmColour(group.realm.id));
        if (group.sick) {
          // A fever goes round: a small red cross at the plate's corner.
          const sx = width / 2 + 5;
          const sy = -label.height / 2 - 1;
          plate.circle(sx, sy, 4.6).fill(0xf2efe6).stroke({ color: 0x10242d, width: 1 });
          plate.rect(sx - 0.9, sy - 3, 1.8, 6).fill(0xc8352c);
          plate.rect(sx - 3, sy - 0.9, 6, 1.8).fill(0xc8352c);
        }
        label.position.set(band / 2, 0);
        tag.addChild(plate, label);
        marker.addChild(tag);
        marker.eventMode = "static";
        marker.cursor = "pointer";
        marker.hitArea = { contains: (x: number, y: number) => Math.abs(x) < 12 && y > -24 && y < 6 };
        marker.on("pointertap", () => {
          if (!layer.wasDragged?.()) onSelectRef.current(group.id);
        });
        layer.addChild(marker);
      }
      fitLabels(layer, current.world.scale.x);
      campsAt.current = now;
      if (gliding.length) {
        const start = performance.now();
        const frame = (time: number) => {
          const t = Math.min(1, (time - start) / 2500);
          const ease = t * t * (3 - 2 * t);
          for (const [marker, x0, y0, x1, y1] of gliding) {
            if (marker.destroyed) return;
            marker.position.set(x0 + (x1 - x0) * ease, y0 + (y1 - y0) * ease);
          }
          if (t < 1) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
      }
    });
  }, [groups, selected, wars, faiths]);

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
      const group = focus.id === undefined ? undefined : groups.find((item) => item.id === focus.id);
      const target = group ? { x: group.x, y: group.y } : focus.x !== undefined && focus.y !== undefined ? { x: focus.x, y: focus.y } : null;
      if (!current || !target) return;
      const [cx, cy] = project(target.x, target.y);
      const world = current.world;
      const from = { x: world.position.x, y: world.position.y, scale: world.scale.x };
      // Close enough to see the people at work, but never further out than one was.
      const scale = Math.max(from.scale, 2.8);
      // Centre in the part of the map that is not covered by a drawer, panel or the chronicle.
      const box = host.current?.getBoundingClientRect();
      let left = 0;
      let right = current.app.screen.width;
      if (box && box.width > 820) {
        for (const selector of [".drawer", ".inspector"]) {
          const cover = document.querySelector(selector)?.getBoundingClientRect();
          if (cover && cover.left - box.left < box.width / 2) left = Math.max(left, cover.right - box.left);
        }
        const ledger = document.querySelector(".ledger.open")?.getBoundingClientRect();
        if (ledger) right = Math.min(right, ledger.left - box.left);
      }
      if (right - left < 200) {
        left = 0;
        right = current.app.screen.width;
      }
      const to = { x: (left + right) / 2 - cx * scale, y: current.app.screen.height / 2 - cy * scale - (TILE_H * scale) / 2 };
      // A short glide rather than a jump, so one sees where one went.
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const duration = reduce ? 0 : 650;
      const start = performance.now();
      const frame = (now: number) => {
        const t = duration === 0 ? 1 : Math.min(1, (now - start) / duration);
        const ease = 1 - Math.pow(1 - t, 3);
        const s = from.scale + (scale - from.scale) * ease;
        world.scale.set(s);
        world.position.set(from.x + (to.x - from.x) * ease, from.y + (to.y - from.y) * ease);
        if (t < 1) requestAnimationFrame(frame);
        else fitLabels(current.camps, scale);
      };
      requestAnimationFrame(frame);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  return <div className="map" ref={host} />;
}
