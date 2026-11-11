import { Application, Container, Graphics, Text } from "pixi.js";
import { useEffect, useRef } from "react";
import type { Group, WorldMap } from "./api";

// Placeholder graphics: flat coloured diamonds until the sprite atlas exists.
const TILE_W = 32;
const TILE_H = 16;

const BIOME_COLOURS: Record<string, number> = {
  ocean: 0x1f3d4d,
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
const DEPOSIT_COLOURS = [0xd9d2c0, 0xc97b4a, 0x8a8f98, 0xb7c4cc, 0xe9e4d8, 0xb04a3a];

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

interface Scene {
  app: Application;
  world: Container;
  terrain: Graphics;
  paths: Graphics;
  camps: Container;
}

interface Props {
  map: WorldMap | null;
  steps: number[];
  groups: Group[];
  selected: number | null;
  focus: { id: number; nonce: number } | null;
  onSelect: (id: number) => void;
}

export function MapView({ map, steps, groups, selected, focus, onSelect }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<Scene | null>(null);
  const ready = useRef<Promise<void> | null>(null);
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
      .init({ resizeTo: element, background: 0x14181c, antialias: false, resolution: window.devicePixelRatio || 1, autoDensity: true })
      .then(() => {
        if (disposed) {
          app.destroy(true);
          return;
        }
        element.appendChild(app.canvas);
        const world = new Container();
        const terrain = new Graphics();
        const paths = new Graphics();
        const camps = new Container();
        world.addChild(terrain, paths, camps);
        app.stage.addChild(world);
        scene.current = { app, world, terrain, paths, camps };

        const canvas = app.canvas;
        canvas.style.touchAction = "none";
        const zoomAt = (px: number, py: number, factor: number) => {
          const next = Math.max(0.35, Math.min(6, world.scale.x * factor));
          const ratio = next / world.scale.x;
          world.position.set(px - (px - world.x) * ratio, py - (py - world.y) * ratio);
          world.scale.set(next);
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

  // Terrain: drawn once per map.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      const g = current.terrain;
      g.clear();
      for (let y = 0; y < map.height; y++) {
        for (let x = 0; x < map.width; x++) {
          const index = y * map.width + x;
          const name = map.river[index] ? "river" : map.biomes[map.biome[index]];
          const height = Math.max(0, Math.min(400, map.elevation[index]));
          const water = name === "ocean" || name === "coast" || name === "river";
          const colour = shade(BIOME_COLOURS[name] ?? 0x555555, water ? 1 : 0.85 + height / 1300);
          diamond(g, x, y);
          g.fill(colour);
          const deposit = map.deposit[index];
          if (deposit >= 0) {
            const [cx, cy] = project(x, y);
            g.circle(cx, cy + TILE_H / 2, 1.6).fill(DEPOSIT_COLOURS[deposit % DEPOSIT_COLOURS.length]);
          }
        }
      }
      const [cx, cy] = project(map.width / 2, map.height / 2);
      const screen = current.app.screen;
      const fit = Math.min(screen.width / (map.width * TILE_W), screen.height / (map.height * TILE_H)) * 1.6;
      const scale = Math.max(0.35, Math.min(3, fit));
      current.world.scale.set(scale);
      current.world.position.set(screen.width / 2 - cx * scale, screen.height / 2 - cy * scale);
    });
  }, [map]);

  // Paths: tiles that many feet have crossed.
  useEffect(() => {
    if (!map) return;
    void ready.current?.then(() => {
      const current = scene.current;
      if (!current) return;
      const g = current.paths;
      g.clear();
      if (steps.length !== map.width * map.height) return;
      for (let y = 0; y < map.height; y++) {
        for (let x = 0; x < map.width; x++) {
          const count = steps[y * map.width + x];
          if (count < 40) continue;
          diamond(g, x, y, 2.5);
          g.fill({ color: 0xd8c08a, alpha: Math.min(0.75, 0.12 + Math.log10(count / 40) * 0.25) });
        }
      }
    });
  }, [map, steps]);

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
        if (group.settled) {
          g.rect(-5, -7, 10, 7).fill(0xc9895a);
          g.poly([-7, -7, 0, -13, 7, -7]).fill(0x8a4f38);
        } else {
          g.poly([-6, 0, 0, -10, 6, 0]).fill(0xe2c98a);
          g.poly([-1.5, 0, 0, -4, 1.5, 0]).fill(0x5a4a34);
        }
        marker.addChild(g);
        const label = new Text({
          text: `${group.settled && group.place ? group.place : group.name} ${group.population}`,
          style: { fontFamily: "system-ui, sans-serif", fontSize: 9, fill: 0xf2efe6, stroke: { color: 0x14181c, width: 3 } },
        });
        label.anchor.set(0.5, 1);
        label.position.set(0, -14);
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
    });
  }, [groups, selected]);

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
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus]);

  return <div className="map" ref={host} />;
}
