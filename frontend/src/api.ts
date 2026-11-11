export type Lang = "de" | "en";

export interface Calendar {
  tick: number;
  year: number;
  month: number;
  day: number;
  season: "spring" | "summer" | "autumn" | "winter";
}

export interface Stats extends Calendar {
  seed: number;
  population: number;
  ever_lived: number;
  clans: number;
  settlements: number;
  discoveries: number;
  discoveries_possible: number;
  births_total: number;
  deaths_total: number;
  migrations_total: number;
  events_total: number;
  climate_anomaly: number | null;
  last_event: string | null;
  last_event_year: number | null;
}

export interface WorldMap {
  width: number;
  height: number;
  biomes: string[];
  deposits: { id: string; de: string; en: string }[];
  biome: number[];
  elevation: number[];
  river: number[];
  deposit: number[];
  steps: number[];
}

export interface Technology {
  id: string;
  name: string;
  year: number;
  how: "invented" | "learned" | "inherited";
}

export interface Group {
  id: number;
  name: string;
  type: string;
  y: number;
  x: number;
  settled: boolean;
  place: string | null;
  parent_group: number;
  founded_year: number;
  population: number;
  technologies: Technology[];
  members?: { id: number; name: string; sex: "f" | "m"; age: number; children: number }[];
}

export interface WorldEvent extends Calendar {
  seq: number;
  type: string;
  importance: number;
  region: number | null;
  text: string;
  data: Record<string, unknown>;
}

export interface Why {
  event: WorldEvent;
  decisions: {
    rule: string;
    scope_type: string;
    scope_id: number;
    factors: { name: string; factor: number }[];
    chance: number | null;
    roll: number;
    fired: boolean | null;
  }[];
  expired: boolean;
}

export interface Discovery {
  id: string;
  name: string;
  requires: string[];
  known: boolean;
  first_year: number | null;
  clans_knowing: number;
}

export type Series = Record<string, { year: number; value: number }[]>;

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${path}`);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => get<{ status: string; version: string; world: (Calendar & { id: number }) | null }>("/health"),
  stats: (world: number, lang: Lang) => get<Stats>(`/worlds/${world}/stats?lang=${lang}`),
  map: (world: number) => get<WorldMap>(`/worlds/${world}/map`),
  steps: (world: number) => get<{ values: number[] }>(`/worlds/${world}/layers/steps`),
  groups: (world: number, lang: Lang) => get<Group[]>(`/worlds/${world}/groups?lang=${lang}`),
  group: (world: number, id: number, lang: Lang) => get<Group>(`/worlds/${world}/groups/${id}?lang=${lang}`),
  events: (world: number, lang: Lang, minImportance: number, limit = 80) =>
    get<WorldEvent[]>(`/worlds/${world}/events?lang=${lang}&min_importance=${minImportance}&limit=${limit}`),
  why: (world: number, seq: number, lang: Lang) => get<Why>(`/worlds/${world}/events/${seq}/why?lang=${lang}`),
  technologies: (world: number, lang: Lang) => get<Discovery[]>(`/worlds/${world}/technologies?lang=${lang}`),
  discoveries: (world: number, lang: Lang) =>
    get<WorldEvent[]>(`/worlds/${world}/events?lang=${lang}&type=discovery&limit=500`),
  metrics: (world: number, keys: string[]) => get<Series>(`/worlds/${world}/metrics?keys=${keys.join(",")}`),
};
