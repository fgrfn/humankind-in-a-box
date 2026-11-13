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
  peoples: number;
  trade_partnerships: number;
  realms?: number;
  wars_ongoing?: number;
  wars_total?: number;
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
  path_levels: { trail: number; road: number };
}

export interface Building {
  id: number;
  type: string;
  name: string;
  y: number;
  x: number;
  state: "site" | "standing" | "ruin";
  started_year: number;
  finished_year: number | null;
  progress_percent: number;
}

export interface Place {
  id: number;
  name: string;
  y: number;
  x: number;
  founded_year: number;
  abandoned_year: number | null;
  group_id: number;
  meaning: string;
  buildings: Building[];
}

export interface Technology {
  id: string;
  name: string;
  year: number;
  how: "invented" | "learned" | "inherited";
}

export interface Group {
  people_id: number;
  people: string | null;
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
  buildings: Building[];
  partners: { id: number; name: string; since_year: number }[];
  leader?: { id: number; name: string } | null;
  realm?: { id: number; name: string; seat: boolean } | null;
  stores: Store[];
  members?: { id: number; name: string; sex: "f" | "m"; age: number; children: number; activity: string; activity_text: string }[];
}

export interface Realm {
  id: number;
  name: string;
  founded_year: number;
  ended_year: number | null;
  seat_id: number;
  seat: string | null;
  ruler_id: number;
  ruler: string | null;
  people_id: number;
  people: string | null;
  clans: number[];
  population: number;
  tiles: number;
}

export interface WarSide {
  id: number;
  name: string | null;
  y: number | null;
  x: number | null;
}

export interface War {
  id: number;
  attacker: WarSide;
  defender: WarSide;
  started_year: number;
  ended_year: number | null;
  outcome: "" | "peace" | "conquest" | "faded";
  winner_id: number | null;
  field: { y: number; x: number } | null;
  last_battle_year: number | null;
  last_fallen: number;
  battles: number;
  fallen: number;
}

export interface Land {
  clans: number[];
  peoples: number[];
  realms: number[];
}

export interface People {
  id: number;
  name: string;
  parent_id: number;
  parent: string | null;
  founded_year: number;
  ended_year: number | null;
  clans: number;
  settlements: number;
  population: number;
  tiles: number;
  stores: Record<string, number>;
  consonants: string;
  vowels: string;
  words: Record<string, string>;
}

export interface Store {
  id: string;
  name: string;
  amount: number;
  room: number;
  gained: number;
  used: number;
  traded_in: number;
  traded_out: number;
}

export interface TreePerson {
  id: number;
  name: string;
  sex: "f" | "m";
  born_year: number;
  died_year: number | null;
  age: number;
  mother: number;
  father: number;
  partner: number;
  clan: number;
}

export interface FamilyTree {
  person: TreePerson;
  partner: TreePerson | null;
  ancestors: TreePerson[][];
  descendants: TreePerson[][];
}

export interface TradeLink {
  a: number;
  b: number;
  since_year: number;
  ay: number;
  ax: number;
  by: number;
  bx: number;
}

export interface Since {
  from_year: number;
  to_year: number;
  years: number;
  population_then: number | null;
  population_now: number;
  births: number;
  deaths: number;
  discoveries: number;
  knowledge_lost: number;
  settlements_founded: number;
  settlements_abandoned: number;
  peoples_emerged: number;
  peoples_vanished: number;
  trade_begun: number;
  highlights: { year: number; importance: number; text: string }[];
}

export interface Human {
  id: number;
  name: string;
  sex: "f" | "m";
  age: number;
  clan: number;
  activity: string;
  text: string;
  y: number;
  x: number;
}

export interface PersonDetail {
  id: number;
  name: string;
  sex: "f" | "m";
  born_year: number;
  died_year: number | null;
  cause: string | null;
  age: number;
  clan: number;
  clan_name: string | null;
  mother: { id: number; name: string } | null;
  father: { id: number; name: string } | null;
  partner: { id: number; name: string } | null;
  children: { id: number; name: string }[];
  traits: Record<string, number>;
  tiles_moved: number;
  discoveries: number;
  activity: string;
  activity_text: string;
  work_months: { activity: string; text: string; months: number }[];
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
  times_lost: number;
}

export type Series = Record<string, { year: number; value: number }[]>;

export interface Speed {
  paused: boolean;
  speed: number;
  until_year: number | null;
  speeds: number[];
  days_per_minute: number;
  measured_days_per_minute: number | null;
  running: boolean;
  year: number;
  changeable: boolean;
  token_required: boolean;
}

export class NeedsToken extends Error {}

async function put<T>(path: string, body: unknown, token: string | null): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/v1${path}`, { method: "PUT", headers, body: JSON.stringify(body) });
  if (response.status === 401) throw new NeedsToken();
  if (!response.ok) throw new Error(`${response.status} ${path}`);
  return (await response.json()) as T;
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`);
  if (!response.ok) {
    throw new Error(`${response.status} ${path}`);
  }
  return (await response.json()) as T;
}

export const api = {
  speed: () => get<Speed>("/control"),
  setSpeed: (wish: { paused?: boolean; speed?: number; for_years?: number }, token: string | null) => put<Speed>("/control", wish, token),
  health: () => get<{ status: string; version: string; world: (Calendar & { id: number }) | null }>("/health"),
  stats: (world: number, lang: Lang) => get<Stats>(`/worlds/${world}/stats?lang=${lang}`),
  map: (world: number) => get<WorldMap>(`/worlds/${world}/map`),
  steps: (world: number) => get<{ values: number[] }>(`/worlds/${world}/layers/steps`),
  stores: (world: number, lang: Lang) => get<{ id: string; name: string; amount: number }[]>(`/worlds/${world}/stores?lang=${lang}`),
  trade: (world: number) => get<TradeLink[]>(`/worlds/${world}/trade`),
  since: (world: number, year: number, lang: Lang) => get<Since>(`/worlds/${world}/since?year=${year}&lang=${lang}`),
  territory: (world: number) => get<Land>(`/worlds/${world}/territory`),
  realms: (world: number) => get<Realm[]>(`/worlds/${world}/realms`),
  wars: (world: number) => get<War[]>(`/worlds/${world}/wars`),
  peoples: (world: number) => get<People[]>(`/worlds/${world}/peoples`),
  people: (world: number, lang: Lang) => get<Human[]>(`/worlds/${world}/people?lang=${lang}`),
  // Two generations each way: a pedigree doubles with every generation, and on a
  // phone more than that no longer fits around the person. Tapping walks on.
  tree: (world: number, id: number) => get<FamilyTree>(`/worlds/${world}/persons/${id}/tree?up=2&down=2`),
  person: (world: number, id: number, lang: Lang) => get<PersonDetail>(`/worlds/${world}/persons/${id}?lang=${lang}`),
  places: (world: number, lang: Lang) => get<Place[]>(`/worlds/${world}/places?lang=${lang}`),
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
