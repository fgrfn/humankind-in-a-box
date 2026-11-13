import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, NeedsToken, type Speed, type FamilyTree, type TreePerson, type Discovery, type Group, type Human, type Lang, type Land, type People, type Realm, type War, type Since, type TradeLink, type PersonDetail, type Place, type Series, type Stats, type Why, type WorldEvent, type WorldMap } from "./api";
import { Chart, SERIES_COLOURS, type Point } from "./Chart";
import { HistoryBand, type Mark } from "./HistoryBand";
import { formatNumber, translator, type TextKey } from "./i18n";
import { peopleCss, realmCss } from "./colours";
import { MapView } from "./MapView";

type View = "map" | "numbers" | "clans";
type Translate = (key: TextKey) => string;

const METRIC_KEYS = [
  "people.population",
  "clans.count",
  "settlements.count",
  "people.births",
  "people.deaths",
  "climate.anomaly",
  "food.eaten",
  "food.needed",
  "stores.food",
  "stores.wood",
];

function initialLang(): Lang {
  try {
    const stored = window.localStorage.getItem("hiab.lang");
    if (stored === "de" || stored === "en") return stored;
  } catch {
    // storage may be unavailable; fall through to the browser language
  }
  return navigator.language.toLowerCase().startsWith("de") ? "de" : "en";
}

function usePolling(task: () => Promise<void>, seconds: number, deps: unknown[]) {
  useEffect(() => {
    let alive = true;
    const run = () => {
      if (alive && !document.hidden) void task().catch(() => undefined);
    };
    run();
    const timer = window.setInterval(run, seconds * 1000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

function BoxGlyph() {
  return (
    <svg className="glyph" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2.5 21 7v10l-9 4.5L3 17V7z" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M3 7l9 4.5L21 7M12 11.5v10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M12 6.2l3 1.5-3 1.5-3-1.5z" fill="currentColor" />
    </svg>
  );
}

const BANNER_EVENTS = ["war_begun", "realm_conquered", "peace_made", "realm_founded"];
const BANNER_TITLES: Record<string, TextKey> = {
  war_begun: "bannerWar",
  realm_conquered: "bannerConquest",
  peace_made: "bannerPeace",
  realm_founded: "bannerRealm",
};

function Chronicle({ events, t, minImportance, setMinImportance, explain, extinct }: {
  events: WorldEvent[];
  t: Translate;
  minImportance: number;
  setMinImportance: (level: number) => void;
  explain: (event: WorldEvent) => void;
  extinct: boolean;
}) {
  return (
    <>
      <label className="filter">
        {t("importance")}
        <select value={minImportance} onChange={(event) => setMinImportance(Number(event.target.value))}>
          {[1, 2, 3, 4, 5].map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </label>
      {extinct ? <p className="note">{t("extinct")}</p> : null}
      {events.length === 0 ? <p className="note">{t("noEvents")}</p> : null}
      <ol className="events">
        {events.map((event, index) => {
          const newYear = index === 0 || events[index - 1].year !== event.year;
          return (
            <li key={event.seq} className={`weight-${event.importance}`}>
              {newYear ? (
                <span className="year-mark">
                  {t("year")} {event.year}
                </span>
              ) : null}
              <button onClick={() => explain(event)} title={t("why")}>
                {event.text}
              </button>
            </li>
          );
        })}
      </ol>
    </>
  );
}

function Numbers({ stats, series, discoveries, peoples, realms, wars, worldStores, lang, t }: { stats: Stats; series: Series; discoveries: Discovery[]; peoples: People[]; realms: Realm[]; wars: War[]; worldStores: { id: string; name: string; amount: number }[]; lang: Lang; t: Translate }) {
  const points = (key: string): Point[] => series[key] ?? [];
  const fed = useMemo(() => {
    const needed = new Map((series["food.needed"] ?? []).map((point) => [point.year, point.value]));
    return (series["food.eaten"] ?? []).map((point) => ({
      year: point.year,
      value: needed.get(point.year) ? (100 * point.value) / needed.get(point.year)! : 100,
    }));
  }, [series]);
  const climate = useMemo(() => points("climate.anomaly").map((point) => ({ year: point.year, value: point.value / 10 })), [series]);
  // Yearly births and deaths jump around; a ten-year mean shows the trend.
  const smooth = (key: string): Point[] => {
    const raw = points(key);
    return raw.map((point, index) => {
      const window = raw.slice(Math.max(0, index - 9), index + 1);
      return { year: point.year, value: window.reduce((sum, item) => sum + item.value, 0) / window.length };
    });
  };
  const common = { lang, yearLabel: t("year"), tableLabel: t("table") };
  const facts: [string, string][] = [
    [t("year"), formatNumber(stats.year, lang)],
    [t("population"), formatNumber(stats.population, lang)],
    [t("everLived"), formatNumber(stats.ever_lived, lang)],
    [t("peoples"), formatNumber(stats.peoples, lang)],
    [t("realms"), formatNumber(stats.realms ?? 0, lang)],
    [t("warsNow"), formatNumber(stats.wars_ongoing ?? 0, lang)],
    [t("partnerships"), formatNumber(stats.trade_partnerships, lang)],
    [t("clans"), formatNumber(stats.clans, lang)],
    [t("settlements"), formatNumber(stats.settlements, lang)],
    [t("discoveries"), `${stats.discoveries} / ${stats.discoveries_possible}`],
    [t("migrations"), formatNumber(stats.migrations_total, lang)],
    [t("events"), formatNumber(stats.events_total, lang)],
    [t("seed"), String(stats.seed)],
  ];
  return (
    <div className="page">
      <h2>{t("worldInNumbers")}</h2>
      <dl className="facts">
        {facts.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      <div className="charts">
        <Chart title={t("populationChart")} series={[{ name: t("population"), colour: SERIES_COLOURS[0], points: points("people.population") }]} {...common} />
        <Chart
          title={t("perYear")}
          series={[
            { name: t("birthsShort"), colour: SERIES_COLOURS[0], points: smooth("people.births") },
            { name: t("deathsShort"), colour: SERIES_COLOURS[1], points: smooth("people.deaths") },
          ]}
          digits={1}
          {...common}
        />
        <Chart
          title={t("groupsChart")}
          series={[
            { name: t("clans"), colour: SERIES_COLOURS[0], points: points("clans.count") },
            { name: t("settlements"), colour: SERIES_COLOURS[1], points: points("settlements.count") },
          ]}
          {...common}
        />
        <Chart title={t("fedChart")} series={[{ name: t("fed"), colour: SERIES_COLOURS[0], points: fed }]} unit=" %" fixedMax={100} {...common} />
        <Chart title={t("climateChart")} series={[{ name: t("climate"), colour: SERIES_COLOURS[1], points: climate }]} unit=" °C" digits={1} signed {...common} />
      </div>

      <h2>{t("storesWorld")}</h2>
      <p className="note">{t("storesNote")}</p>
      <dl className="facts">
        {worldStores.map((item) => (
          <div key={item.id}>
            <dt>{item.name}</dt>
            <dd>{formatNumber(item.amount, lang)}</dd>
          </div>
        ))}
      </dl>
      <div className="charts">
        <Chart
          title={t("storesChart")}
          series={[
            { name: t("food"), colour: SERIES_COLOURS[0], points: points("stores.food") },
            { name: t("wood"), colour: SERIES_COLOURS[1], points: points("stores.wood") },
          ]}
          {...common}
        />
      </div>

      <h2>{t("peoples")}</h2>
      <p className="note">{t("peoplesNote")}</p>
      <ul className="peoples">
        {peoples.map((item) => {
          const largest = Math.max(1, ...peoples.map((other) => other.population));
          return (
            <li key={item.id} className={item.ended_year === null ? "" : "gone"}>
              <span className="name">
                <i className="chip" style={{ background: peopleCss(item.id) }} aria-hidden="true" />
                {item.name}
              </span>
              <span className="bar" aria-hidden="true">
                <span style={{ width: `${(100 * item.population) / largest}%`, background: peopleCss(item.id) }} />
              </span>
              <span className="count">{item.ended_year === null ? formatNumber(item.population, lang) : t("gone")}</span>
              <span className="state">
                {item.parent ? `${t("descendedFrom")} ${item.parent}` : t("firstPeople")}, {t("year")} {item.founded_year}
                {item.ended_year === null ? `, ${item.clans} ${item.clans === 1 ? t("clansOne") : t("clans")}` : ` – ${item.ended_year}`}
                {item.tiles ? `, ${formatNumber(item.tiles, lang)} ${t("tilesOfLand")}` : ""}, {t("sounds")} {item.consonants.split("").join(" ")} · {item.vowels.split("").join(" ")}
              </span>
              {item.ended_year === null && Object.values(item.stores).some((amount) => amount > 0) ? (
                <span className="state">
                  {t("inStore")}:{" "}
                  {Object.entries(item.stores)
                    .filter(([, amount]) => amount > 0)
                    .map(([good, amount]) => `${worldStores.find((entry) => entry.id === good)?.name ?? good} ${formatNumber(amount, lang)}`)
                    .join(", ")}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>

      <h2>{t("realms")}</h2>
      <p className="note">{t("realmsNote")}</p>
      {realms.length === 0 ? <p className="note">{t("noRealms")}</p> : null}
      <ul className="peoples">
        {realms.map((item) => {
          const largest = Math.max(1, ...realms.map((other) => other.population));
          const standing = item.ended_year === null;
          return (
            <li key={item.id} className={standing ? "" : "gone"}>
              <span className="name">
                <i className="chip" style={{ background: realmCss(item.id) }} aria-hidden="true" />
                {item.name}
              </span>
              <span className="bar" aria-hidden="true">
                <span style={{ width: `${(100 * item.population) / largest}%`, background: realmCss(item.id) }} />
              </span>
              <span className="count">{standing ? formatNumber(item.population, lang) : t("gone")}</span>
              <span className="state">
                {t("year")} {item.founded_year}
                {standing
                  ? `, ${item.clans.length} ${item.clans.length === 1 ? t("clansOne") : t("clans")}${item.ruler ? `, ${t("ruler")} ${item.ruler}` : ""}${item.seat ? `, ${t("seat")} ${item.seat}` : ""}${item.people ? `, ${t("ofThePeople")} ${item.people}` : ""}${item.tiles ? `, ${formatNumber(item.tiles, lang)} ${t("tilesOfLand")}` : ""}`
                  : ` – ${item.ended_year}`}
              </span>
            </li>
          );
        })}
      </ul>

      <h2>{t("wars")}</h2>
      {wars.length === 0 ? <p className="note">{t("noWars")}</p> : null}
      <ul className="wars">
        {wars.slice(0, 30).map((war) => {
          const winner = war.winner_id === war.attacker.id ? war.attacker.name : war.winner_id === war.defender.id ? war.defender.name : null;
          const outcome =
            war.ended_year === null
              ? t("warOngoing")
              : war.outcome === "conquest"
                ? `${t("conqueredBy")} ${winner ?? ""}`
                : war.outcome === "peace"
                  ? t("peace")
                  : t("warFaded");
          return (
            <li key={war.id} className={war.ended_year === null ? "ongoing" : ""}>
              <span className="name">
                <i className="chip" style={{ background: realmCss(war.attacker.id) }} aria-hidden="true" />
                {war.attacker.name} {t("against")} <i className="chip" style={{ background: realmCss(war.defender.id) }} aria-hidden="true" />
                {war.defender.name}
              </span>
              <span className="state">
                {t("year")} {war.started_year}
                {war.ended_year === null ? "" : `–${war.ended_year}`}, {outcome}, {war.battles} {war.battles === 1 ? t("battleOne") : t("battles")}, {formatNumber(war.fallen, lang)} {t("fallen")}
              </span>
            </li>
          );
        })}
      </ul>

      <h2>{t("discoveries")}</h2>
      <ul className="discoveries">
        {discoveries.map((item) => (
          <li key={item.id} className={item.known ? "known" : ""}>
            <span className="pip" aria-hidden="true" />
            <span className="name">{item.name}</span>
            <span className="state">
              {item.known
                ? `${t("since")} ${item.first_year}, ${t("knownBy")} ${item.clans_knowing} ${item.clans_knowing === 1 ? t("clansOne") : t("clans")}${item.times_lost ? `, ${item.times_lost}× ${t("forgotten")}` : ""}`
                : item.requires.length
                  ? `${t("unknown")}, ${t("needs")} ${item.requires.join(", ")}`
                  : t("unknown")}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// The one control over the world: how fast it runs. Nothing else can be changed from here.
function TimeControl({ lang, t, onFast }: { lang: Lang; t: Translate; onFast: (fast: boolean) => void }) {
  const [speed, setSpeed] = useState<Speed | null>(null);
  const [asking, setAsking] = useState(false);
  const [draft, setDraft] = useState("");
  const pending = useRef<{ paused?: boolean; speed?: number; for_years?: number } | null>(null);

  const [busy, setBusy] = useState(false);
  usePolling(async () => setSpeed(await api.speed()), busy ? 1 : 4, [busy]);
  // While the world runs faster than normal, everything else is asked for more often.
  const sped = speed !== null && !speed.paused && speed.speed !== 1;
  useEffect(() => {
    onFast(sped);
    setBusy(sped);
  }, [sped, onFast]);

  const token = () => {
    try {
      return window.localStorage.getItem("hiab.token");
    } catch {
      return null;
    }
  };
  const ask = async (wish: { paused?: boolean; speed?: number; for_years?: number }) => {
    try {
      setSpeed(await api.setSpeed(wish, token()));
      setAsking(false);
    } catch (error) {
      if (error instanceof NeedsToken) {
        pending.current = wish;
        setAsking(true);
      }
    }
  };
  if (!speed || !speed.changeable) return null;

  const rate = speed.measured_days_per_minute ?? 0;
  // From a year a minute on, years say more than days.
  const shown = speed.paused
    ? t("paused")
    : !speed.running
      ? t("notRunning")
      : rate >= 360
        ? `${formatNumber(rate >= 3600 ? Math.round(rate / 360) : Math.round((rate / 360) * 10) / 10, lang)} ${t("perMinuteYears")}`
        : `${formatNumber(Math.round(rate), lang)} ${t("perMinuteDays")}`;
  return (
    <div className="time" role="group" aria-label={t("time")}>
      <button className={speed.paused ? "on" : ""} aria-pressed={speed.paused} onClick={() => void ask({ paused: !speed.paused })}>
        {speed.paused ? t("resume") : t("pause")}
      </button>
      {speed.speeds.map((factor) => (
        <button key={factor} className={!speed.paused && speed.speed === factor ? "on" : ""} aria-pressed={speed.speed === factor} onClick={() => void ask({ speed: factor, paused: false })}>
          {factor === 0 ? t("asFast") : `${factor}×`}
        </button>
      ))}
      <button onClick={() => void ask({ speed: 0, for_years: 10, paused: false })}>{t("tenYears")}</button>
      <span className="rate" aria-live="polite">
        {shown}
        {speed.until_year ? `, ${t("untilYear")} ${speed.until_year}` : ""}
      </span>
      {asking ? (
        <form
          className="token"
          onSubmit={(event) => {
            event.preventDefault();
            try {
              window.localStorage.setItem("hiab.token", draft);
            } catch {
              // Without storage the token is asked for again next time.
            }
            if (pending.current) void ask(pending.current);
          }}
        >
          <label>
            {t("tokenAsk")}
            <input type="password" value={draft} onChange={(event) => setDraft(event.target.value)} autoComplete="off" />
          </label>
          <button type="submit">{t("tokenSave")}</button>
        </form>
      ) : null}
    </div>
  );
}

// ---- Family tree --------------------------------------------------------
// Drawn as a tree: ancestors branch upwards, two parents above each person;
// descendants branch downwards under their parents. Elbow lines join them.

const NODE_W = 132;
const NODE_H = 48;
const GAP_X = 14;
const GAP_Y = 46;

interface Placed {
  person: TreePerson;
  x: number; // centre
  y: number; // top
}

function layoutTree(tree: FamilyTree) {
  const nodes: Placed[] = [];
  const lines: string[] = [];
  const unit = NODE_W + GAP_X;
  const rowY = (generation: number) => generation * (NODE_H + GAP_Y);

  // Descendants: every child hangs under the first of its parents found one generation up.
  const childrenOf = new Map<number, TreePerson[]>();
  let parents = [tree.person];
  for (const generation of tree.descendants) {
    const ids = new Set(parents.map((person) => person.id));
    for (const child of generation) {
      const parent = ids.has(child.mother) ? child.mother : child.father;
      const list = childrenOf.get(parent) ?? [];
      list.push(child);
      childrenOf.set(parent, list);
    }
    parents = generation;
  }
  const below = new Map<number, number>();
  const widthBelow = (person: TreePerson): number => {
    const kids = childrenOf.get(person.id) ?? [];
    const width = Math.max(1, kids.reduce((sum, kid) => sum + widthBelow(kid), 0));
    below.set(person.id, width);
    return width;
  };

  // Ancestors: everybody's parents, looked up by id.
  const byId = new Map<number, TreePerson>();
  for (const person of tree.ancestors.flat()) byId.set(person.id, person);
  const parentsOf = (person: TreePerson) => [byId.get(person.mother), byId.get(person.father)].filter((p): p is TreePerson => p !== undefined);
  const above = new Map<number, number>();
  const widthAbove = (person: TreePerson): number => {
    const width = Math.max(1, parentsOf(person).reduce((sum, parent) => sum + widthAbove(parent), 0));
    above.set(person.id, width);
    return width;
  };

  const top = tree.ancestors.length;
  // The person and partner side by side; the person's tree hangs below the person.
  const rootWidth = Math.max(widthBelow(tree.person), widthAbove(tree.person), tree.partner ? 2 : 1);
  const rootX = (rootWidth * unit) / 2;

  const placeDown = (person: TreePerson, left: number, generation: number) => {
    const width = below.get(person.id) ?? 1;
    const x = left + (width * unit) / 2;
    if (generation > 0) nodes.push({ person, x, y: rowY(top + generation) });
    const kids = childrenOf.get(person.id) ?? [];
    let cursor = left;
    const kidXs: number[] = [];
    for (const kid of kids) {
      kidXs.push(cursor + ((below.get(kid.id) ?? 1) * unit) / 2);
      placeDown(kid, cursor, generation + 1);
      cursor += (below.get(kid.id) ?? 1) * unit;
    }
    if (kids.length) {
      const fromY = rowY(top + generation) + NODE_H;
      const midY = fromY + GAP_Y / 2;
      const toY = rowY(top + generation + 1);
      lines.push(`M${x},${fromY}V${midY}`);
      lines.push(`M${Math.min(x, ...kidXs)},${midY}H${Math.max(x, ...kidXs)}`);
      for (const kidX of kidXs) lines.push(`M${kidX},${midY}V${toY}`);
    }
  };
  const placeUp = (person: TreePerson, centre: number, generation: number) => {
    const parentsHere = parentsOf(person);
    if (!parentsHere.length) return;
    const total = parentsHere.reduce((sum, parent) => sum + (above.get(parent.id) ?? 1), 0);
    let cursor = centre - (total * unit) / 2;
    const parentXs: number[] = [];
    for (const parent of parentsHere) {
      const width = above.get(parent.id) ?? 1;
      const x = cursor + (width * unit) / 2;
      parentXs.push(x);
      nodes.push({ person: parent, x, y: rowY(top - generation - 1) });
      placeUp(parent, x, generation + 1);
      cursor += width * unit;
    }
    const toY = rowY(top - generation);
    const midY = toY - GAP_Y / 2;
    lines.push(`M${centre},${toY}V${midY}`);
    lines.push(`M${Math.min(centre, ...parentXs)},${midY}H${Math.max(centre, ...parentXs)}`);
    for (const parentX of parentXs) lines.push(`M${parentX},${midY}V${midY - GAP_Y / 2}`);
  };

  const rootLeft = rootX - ((below.get(tree.person.id) ?? 1) * unit) / 2;
  placeDown(tree.person, rootLeft, 0);
  placeUp(tree.person, rootX, 0);
  nodes.push({ person: tree.person, x: rootX, y: rowY(top) });
  const couples: string[] = [];
  if (tree.partner) {
    const partnerX = rootX + unit;
    nodes.push({ person: tree.partner, x: partnerX, y: rowY(top) });
    couples.push(`M${rootX + NODE_W / 2},${rowY(top) + NODE_H / 2}H${partnerX - NODE_W / 2}`);
  }
  const minX = Math.min(...nodes.map((node) => node.x)) - NODE_W / 2 - GAP_X;
  const maxX = Math.max(...nodes.map((node) => node.x)) + NODE_W / 2 + GAP_X;
  const height = rowY(top + tree.descendants.length) + NODE_H + 8;
  return { nodes, lines, couples, minX, width: maxX - minX, height, rootX, rootY: rowY(top) };
}

function TreeView({ tree, t, onPick }: { tree: FamilyTree; t: Translate; onPick: (id: number) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const layout = useMemo(() => layoutTree(tree), [tree]);
  const shift = -layout.minX;
  useEffect(() => {
    // Open with the chosen person in the middle.
    const element = box.current;
    if (!element) return;
    element.scrollLeft = layout.rootX + shift - element.clientWidth / 2;
    element.scrollTop = Math.max(0, layout.rootY - element.clientHeight / 2 + NODE_H);
  }, [layout, shift]);
  const generationName = (offset: number) => {
    if (offset === 0) return "";
    const n = Math.abs(offset);
    if (offset < 0) return n <= 3 ? t(`generationUp${n}` as "generationUp1") : `${t("generationAbove")} ${n}`;
    return n <= 3 ? t(`generationDown${n}` as "generationDown1") : `${t("generationBelow")} ${n}`;
  };
  return (
    <>
      {tree.ancestors.length === 0 ? <p className="note">{t("noAncestors")}</p> : null}
      <div className="tree-scroll" ref={box}>
        <svg className="tree-svg" width={layout.width} height={layout.height} viewBox={`${layout.minX} 0 ${layout.width} ${layout.height}`} role="img" aria-label={`${t("familyTree")}: ${tree.person.name}`}>
          {Array.from({ length: tree.ancestors.length + tree.descendants.length + 1 }, (_, row) => (
            <text key={row} className="tree-gen" x={layout.minX + 4} y={row * (NODE_H + GAP_Y) - 6}>
              {generationName(row - tree.ancestors.length)}
            </text>
          ))}
          <path className="tree-line" d={layout.lines.join("")} />
          <path className="tree-couple" d={layout.couples.join("")} />
          {layout.nodes.map(({ person, x, y }) => {
            const centre = person.id === tree.person.id;
            return (
              <g
                key={`${person.id}-${x}`}
                className={`tree-node ${person.sex} ${centre ? "centre" : ""} ${person.died_year === null ? "" : "dead"}`}
                transform={`translate(${x - NODE_W / 2},${y})`}
                role="button"
                tabIndex={0}
                onClick={() => onPick(person.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") onPick(person.id);
                }}
              >
                <rect width={NODE_W} height={NODE_H} rx={6} />
                <rect className="sex" width={4} height={NODE_H} rx={2} />
                <text x={12} y={20} className="name">
                  {person.name}
                </text>
                <text x={12} y={38} className="years">
                  {person.born_year}–{person.died_year ?? ""} {person.died_year === null ? `(${t("alive")}, ${person.age})` : `(${person.age})`}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="note">{t("treeNote")}</p>
    </>
  );
}

function PersonCard({ person, t, onPerson, onTree }: { person: PersonDetail; t: Translate; onPerson: (id: number) => void; onTree: (id: number) => void }) {
  return (
    <>
      <h2>{person.name}</h2>
      <p className="lede">
        {person.clan_name ? `${person.clan_name}, ` : ""}
        {person.died_year === null ? `${t("age")} ${person.age}` : `${t("died")} ${t("year")} ${person.died_year}, ${t("age")} ${person.age}${person.cause === "war" ? `, ${t("fellInWar")}` : person.cause === "hunger" ? `, ${t("diedOfHunger")}` : ""}`}
      </p>
      <dl>
        {person.died_year === null ? (
          <>
            <dt>{t("doing")}</dt>
            <dd>{person.activity_text || (person.age < 16 ? t("tooYoung") : t("nothingNow"))}</dd>
          </>
        ) : null}
        {person.work_months.length > 0 ? (
          <>
            <dt>{t("lifeWork")}</dt>
            <dd>{person.work_months.map((entry) => `${entry.text}: ${entry.months} ${t("months")}`).join(", ")}</dd>
          </>
        ) : null}
        <dt>{t("family")}</dt>
        <dd>
          {[
            person.mother ? [t("mother"), [person.mother]] : null,
            person.father ? [t("father"), [person.father]] : null,
            person.partner ? [t("partner"), [person.partner]] : null,
            person.children.length ? [t("childrenOf"), person.children] : null,
          ]
            .filter((entry): entry is [string, { id: number; name: string }[]] => entry !== null)
            .map(([label, relatives]) => (
              <span key={label} className="kin">
                {label}:{" "}
                {relatives.map((relative) => (
                  <button key={relative.id} className="plain name" onClick={() => onPerson(relative.id)}>
                    {relative.name}
                  </button>
                ))}
              </span>
            ))}
        </dd>
        <dt>{t("nature")}</dt>
        <dd>
          {Object.entries(person.traits)
            .map(([trait, value]) => `${t(trait as "vigor" | "curiosity" | "sociability" | "craft")} ${value}`)
            .join(", ")}
          , {person.tiles_moved} {t("walked")}
        </dd>
      </dl>
      <button className="plain link" onClick={() => onTree(person.id)}>
        {t("familyTree")}
      </button>
    </>
  );
}

function ClanDetail({ detail, t, lang, onShow, onPerson, onClan }: { detail: Group; t: Translate; lang: Lang; onShow?: () => void; onPerson: (id: number) => void; onClan: (id: number) => void }) {
  return (
    <article className="detail">
      <h2>{detail.name}</h2>
      <p className="lede">
        {detail.people ? `${t("ofThePeople")} ${detail.people}, ` : ""}
        {detail.population} {t("people")}, {detail.settled ? `${t("settled")}${detail.place ? ` (${detail.place})` : ""}` : t("wandering")}, {t("founded")} {detail.founded_year}
      </p>
      {detail.leader || detail.realm ? (
        <p className="lede">
          {detail.leader ? (
            <>
              {t("leader")}:{" "}
              <button className="plain" onClick={() => onPerson(detail.leader!.id)}>
                {detail.leader.name}
              </button>
            </>
          ) : null}
          {detail.leader && detail.realm ? ". " : ""}
          {detail.realm ? (
            <>
              <i className="chip" style={{ background: realmCss(detail.realm.id) }} aria-hidden="true" /> {detail.realm.seat ? t("seatOf") : t("belongsTo")} {detail.realm.name}
            </>
          ) : null}
        </p>
      ) : null}
      {onShow ? (
        <button className="plain" onClick={onShow}>
        {t("showOnMap")}
      </button>
      ) : null}
      <h3>{t("stores")}</h3>
      <ul className="stores">
        {detail.stores.map((item) => (
          <li key={item.id}>
            <span className="name">{item.name}</span>
            <span className="bar" aria-hidden="true">
              <span style={{ width: `${item.room > 0 ? Math.min(100, (100 * item.amount) / item.room) : 0}%` }} />
            </span>
            <span className="count">{formatNumber(item.amount, lang)}</span>
            <small>
              {t("roomFor")} {formatNumber(item.room, lang)}. {t("lastYear")}: {t("gained")} {formatNumber(item.gained, lang)}, {t("usedUp")} {formatNumber(item.used, lang)}
              {item.traded_in ? `, ${t("tradedIn")} ${formatNumber(item.traded_in, lang)}` : ""}
              {item.traded_out ? `, ${t("tradedOut")} ${formatNumber(item.traded_out, lang)}` : ""}
            </small>
          </li>
        ))}
      </ul>
      {detail.partners.length > 0 ? (
        <>
          <h3>{t("tradesWith")}</h3>
          <ul className="knowledge">
            {detail.partners.map((partner) => (
              <li key={partner.id}>
                <button className="plain name" onClick={() => onClan(partner.id)}>
                  {partner.name}
                </button>
                <small>
                  {t("since")} {partner.since_year}
                </small>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <h3>{t("knowledge")}</h3>
      {detail.technologies.length === 0 ? <p className="note">{t("noKnowledge")}</p> : null}
      <ul className="knowledge">
        {detail.technologies.map((tech) => (
          <li key={tech.id}>
            <span>{tech.name}</span>
            <small>
              {t(tech.how)}, {t("year")} {tech.year}
            </small>
          </li>
        ))}
      </ul>
      {detail.buildings.length > 0 ? (
        <>
          <h3>{t("buildings")}</h3>
          <ul className="knowledge">
            {detail.buildings.map((building) => (
              <li key={building.id}>
                <span>{building.name}</span>
                <small>
                  {building.state === "site"
                    ? `${t("site")}, ${building.progress_percent} %`
                    : building.state === "ruin"
                      ? t("ruin")
                      : `${t("since")} ${building.finished_year}`}
                </small>
              </li>
            ))}
          </ul>
        </>
      ) : null}
      <h3>{t("members")}</h3>
      <ul className="members">
        {(detail.members ?? []).slice(0, 60).map((member) => (
          <li key={member.id}>
            <button className="plain name" onClick={() => onPerson(member.id)}>
              {member.name}
            </button>
            <small>
              {member.activity_text ? `${member.activity_text}, ` : ""}
              {member.age}
            </small>
          </li>
        ))}
      </ul>
    </article>
  );
}

export function App() {
  const [lang, setLang] = useState<Lang>(initialLang);
  const t = useMemo(() => translator(lang), [lang]);
  const [worldId, setWorldId] = useState<number | null>(null);
  const [fast, setFast] = useState(false); // the world runs faster than normal
  const [stats, setStats] = useState<Stats | null>(null);
  const [map, setMap] = useState<WorldMap | null>(null);
  const [steps, setSteps] = useState<number[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [people, setPeople] = useState<Human[]>([]);
  const [person, setPerson] = useState<PersonDetail | null>(null);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  // Great moments are announced over the map for a few seconds.
  const [banner, setBanner] = useState<{ kind: string; text: string; seq: number } | null>(null);
  const [series, setSeries] = useState<Series>({});
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [peoples, setPeoples] = useState<People[]>([]);
  const [land, setLand] = useState<Land>({ clans: [], peoples: [], realms: [] });
  const [realms, setRealms] = useState<Realm[]>([]);
  const [wars, setWars] = useState<War[]>([]);
  const [landBy, setLandBy] = useState<"peoples" | "realms" | "off">("peoples");
  const [links, setLinks] = useState<TradeLink[]>([]);
  const [worldStores, setWorldStores] = useState<{ id: string; name: string; amount: number }[]>([]);
  const [showTrade, setShowTrade] = useState(true);
  const [away, setAway] = useState<Since | null>(null);
  const seenChecked = useRef<number | null>(null);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [view, setView] = useState<View>("map");
  const [ledgerOpen, setLedgerOpen] = useState(() => window.matchMedia("(min-width: 821px)").matches);
  const [minImportance, setMinImportance] = useState(3);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<Group | null>(null);
  const [focus, setFocus] = useState<{ id: number; nonce: number } | null>(null);
  const [why, setWhy] = useState<Why | null>(null);
  const newestSeq = useRef(-1);

  useEffect(() => {
    document.documentElement.lang = lang;
    try {
      window.localStorage.setItem("hiab.lang", lang);
    } catch {
      // not being able to remember the language is harmless
    }
  }, [lang]);

  usePolling(
    async () => {
      const health = await api.health();
      setWorldId(health.world?.id ?? null);
    },
    10,
    [],
  );

  useEffect(() => {
    if (worldId === null) return;
    setMap(null);
    void api.map(worldId).then((loaded) => {
      setMap(loaded);
      setSteps(loaded.steps);
    });
  }, [worldId]);

  usePolling(
    async () => {
      if (worldId === null) return;
      const [nextStats, nextGroups, nextPlaces] = await Promise.all([
        api.stats(worldId, lang),
        api.groups(worldId, lang),
        api.places(worldId, lang),
      ]);
      setStats(nextStats);
      // "While you were away": the browser remembers the last year it saw of this world.
      const key = `hiab.seen.${worldId}`;
      try {
        if (seenChecked.current !== worldId) {
          seenChecked.current = worldId;
          const seen = Number(window.localStorage.getItem(key));
          if (Number.isFinite(seen) && seen > 0 && nextStats.year - seen >= 5) {
            void api.since(worldId, seen, lang).then(setAway);
          }
        }
        window.localStorage.setItem(key, String(nextStats.year));
      } catch {
        // No storage in this browser: then there is simply no summary.
      }
      setGroups(nextGroups);
      setPlaces(nextPlaces);
    },
    fast ? 1 : 5,
    [worldId, lang, fast],
  );

  usePolling(
    async () => {
      if (worldId === null) return;
      const [nextSteps, nextSeries, nextDiscoveries, found, nextPeoples] = await Promise.all([
        api.steps(worldId),
        api.metrics(worldId, METRIC_KEYS),
        api.technologies(worldId, lang),
        api.discoveries(worldId, lang),
        api.peoples(worldId),
      ]);
      setPeoples(nextPeoples);
      setLand(await api.territory(worldId));
      setRealms(await api.realms(worldId));
      setWars(await api.wars(worldId));
      setLinks(await api.trade(worldId));
      setWorldStores(await api.stores(worldId, lang));
      setSteps(nextSteps.values);
      setSeries(nextSeries);
      setDiscoveries(nextDiscoveries);
      setMarks(found.map((event) => ({ year: event.year, text: event.text })));
    },
    30,
    [worldId, lang],
  );

  usePolling(
    async () => {
      if (worldId === null) return;
      setPeople(await api.people(worldId, lang));
    },
    15,
    [worldId, lang],
  );

  const [tree, setTree] = useState<FamilyTree | null>(null);
  const showTree = useCallback(
    (id: number) => {
      if (worldId === null) return;
      void api.tree(worldId, id).then(setTree);
    },
    [worldId],
  );

  const showPerson = useCallback(
    (id: number) => {
      if (worldId === null) return;
      void api.person(worldId, id, lang).then(setPerson);
    },
    [worldId, lang],
  );

  // Chronicle: load the recent past, then follow live.
  useEffect(() => {
    if (worldId === null) return;
    let alive = true;
    newestSeq.current = -1;
    void api.events(worldId, lang, minImportance).then((loaded) => {
      if (!alive) return;
      setEvents(loaded);
      newestSeq.current = loaded.length ? loaded[0].seq : -1;
    });
    const source = new EventSource(`/api/v1/events/stream?lang=${lang}&min_importance=${minImportance}`);
    source.addEventListener("chronicle", (message) => {
      const event = JSON.parse((message as MessageEvent<string>).data) as WorldEvent;
      if (event.seq <= newestSeq.current) return;
      newestSeq.current = event.seq;
      setEvents((current) => [event, ...current].slice(0, 300));
      if (BANNER_EVENTS.includes(event.type)) setBanner({ kind: event.type, text: event.text, seq: event.seq });
    });
    return () => {
      alive = false;
      source.close();
    };
  }, [worldId, lang, minImportance]);

  useEffect(() => {
    if (!banner) return;
    const timer = window.setTimeout(() => setBanner(null), 6000);
    return () => window.clearTimeout(timer);
  }, [banner]);

  useEffect(() => {
    if (worldId === null || selected === null) {
      setDetail(null);
      return;
    }
    let alive = true;
    void api
      .group(worldId, selected, lang)
      .then((loaded) => {
        if (alive) setDetail(loaded);
      })
      .catch(() => {
        if (alive) setDetail(null);
      });
    return () => {
      alive = false;
    };
  }, [worldId, selected, lang, stats?.year]);

  // On the map a tap opens a panel beside it; the map stays in view and in use.
  const [panelOpen, setPanelOpen] = useState(false);
  const selectFromMap = useCallback((id: number) => {
    setPerson(null);
    setSelected(id);
    setPanelOpen(true);
  }, []);

  const explain = useCallback(
    (event: WorldEvent) => {
      if (worldId === null) return;
      void api.why(worldId, event.seq, lang).then(setWhy);
    },
    [worldId, lang],
  );

  const showOnMap = useCallback((id: number) => {
    setView("map");
    setFocus({ id, nonce: Date.now() });
  }, []);

  const sortedGroups = useMemo(() => [...groups].sort((a, b) => b.population - a.population || a.id - b.id), [groups]);
  const extinct = stats !== null && stats.population === 0 && stats.ever_lived > 0;
  const views: View[] = ["map", "numbers", "clans"];

  return (
    <div className={`app view-${view}`}>
      <header className="top">
        <div className="brand">
          <BoxGlyph />
          <span>{t("title")}</span>
        </div>
        <p className="now">
          {stats ? (
            <>
              <strong>
                {t("year")} {formatNumber(stats.year, lang)}
              </strong>
              <span>{t(stats.season)}</span>
              <span>
                {formatNumber(stats.population, lang)} {t("people")}
              </span>
            </>
          ) : (
            t("waiting")
          )}
        </p>
        <TimeControl lang={lang} t={t} onFast={setFast} />
        <nav className="views" aria-label="Views">
          {views.map((name) => (
            <button key={name} className={view === name ? "on" : ""} aria-current={view === name ? "page" : undefined} onClick={() => setView(name)}>
              {t(name)}
            </button>
          ))}
        </nav>
        <div className="lang" role="group" aria-label="Language">
          {(["de", "en"] as const).map((code) => (
            <button key={code} className={lang === code ? "on" : ""} onClick={() => setLang(code)} aria-pressed={lang === code}>
              {code.toUpperCase()}
            </button>
          ))}
        </div>
      </header>

      <HistoryBand population={series["people.population"] ?? []} marks={marks} lang={lang} yearLabel={t("year")} peopleLabel={t("people")} emptyLabel={t("historyEmpty")} />

      <main>
        <div className={`stage ${view === "map" ? "" : "away"}`} aria-hidden={view !== "map"}>
          <MapView active={view === "map"} map={map} steps={steps} groups={groups} places={places} people={people} land={landBy === "off" ? null : land} landBy={landBy === "realms" ? "realms" : "peoples"} realms={realms} wars={wars} year={stats?.year ?? 0} links={showTrade ? links : []} selected={selected} focus={focus} onSelect={selectFromMap} onPerson={showPerson} />
          {banner ? (
            <div key={banner.seq} className={`banner ${banner.kind}`} role="status" onClick={() => setBanner(null)}>
              <strong>{t(BANNER_TITLES[banner.kind])}</strong>
              <span>{banner.text}</span>
            </div>
          ) : null}
          <button
            className={`map-toggle ${landBy === "off" ? "" : "on"}`}
            aria-label={`${t("land")}: ${t(landBy === "peoples" ? "landPeoples" : landBy === "realms" ? "landRealms" : "landOff")}`}
            onClick={() => setLandBy((shown) => (shown === "peoples" ? "realms" : shown === "realms" ? "off" : "peoples"))}
          >
            {landBy === "peoples" ? t("landPeoples") : landBy === "realms" ? t("landRealms") : t("land")}
          </button>
          <button className={`map-toggle second ${showTrade ? "on" : ""}`} aria-pressed={showTrade} onClick={() => setShowTrade((shown) => !shown)}>
            {t("trade")}
          </button>
          {person || (panelOpen && detail) ? (
            <aside className="inspector" aria-label={person ? person.name : detail?.name}>
              <button
                className="inspector-close"
                aria-label={t("close")}
                onClick={() => {
                  if (person) setPerson(null);
                  else setPanelOpen(false);
                }}
              >
                ×
              </button>
              {person ? (
                <>
                  <PersonCard person={person} t={t} onPerson={showPerson} onTree={showTree} />
                  <button
                    className="plain link"
                    onClick={() => {
                      setSelected(person.clan);
                      setPanelOpen(true);
                      setPerson(null);
                    }}
                  >
                    {person.clan_name}
                  </button>
                </>
              ) : detail ? (
                <>
                  <ClanDetail detail={detail} t={t} lang={lang} onPerson={showPerson} onClan={setSelected} />
                </>
              ) : null}
            </aside>
          ) : null}
          <aside className={`ledger ${ledgerOpen ? "open" : ""}`} aria-label={t("chronicle")}>
            <button className="ledger-head" onClick={() => setLedgerOpen((open) => !open)} aria-expanded={ledgerOpen} title={ledgerOpen ? t("hideChronicle") : t("showChronicle")}>
              <span className="ledger-title">{t("chronicle")}</span>
              {!ledgerOpen && events[0] ? <span className="ledger-peek">{events[0].text}</span> : null}
              <svg viewBox="0 0 12 12" aria-hidden="true">
                <path d={ledgerOpen ? "M2 4l4 4 4-4" : "M2 8l4-4 4 4"} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
            {ledgerOpen ? (
              <div className="ledger-body">
                <Chronicle events={events} t={t} minImportance={minImportance} setMinImportance={setMinImportance} explain={explain} extinct={extinct} />
              </div>
            ) : null}
          </aside>
        </div>

        {view === "numbers" && stats ? <Numbers stats={stats} series={series} discoveries={discoveries} peoples={peoples} realms={realms} wars={wars} worldStores={worldStores} lang={lang} t={t} /> : null}

        {view === "clans" ? (
          <div className="page clans-page">
            <ul className="clans">
              {sortedGroups.map((group) => (
                <li key={group.id}>
                  <button className={group.id === selected ? "on" : ""} onClick={() => setSelected(group.id)}>
                    <span className="clan-name">{group.name}</span>
                    <span className="clan-where">
                      {group.people ? <i className="chip" style={{ background: peopleCss(group.people_id) }} aria-hidden="true" /> : null}
                      {group.people ? `${group.people}, ` : ""}
                      {group.settled ? (group.place ?? t("settled")) : t("wandering")}
                    </span>
                    <span className="clan-count">{group.population}</span>
                  </button>
                </li>
              ))}
            </ul>
            {detail ? <ClanDetail detail={detail} t={t} lang={lang} onShow={() => showOnMap(detail.id)} onPerson={showPerson} onClan={setSelected} /> : <p className="note pick">{t("pickClan")}</p>}
          </div>
        ) : null}
      </main>

      <nav className="tabbar" aria-label="Views">
        {views.map((name) => (
          <button key={name} className={view === name ? "on" : ""} aria-current={view === name ? "page" : undefined} onClick={() => setView(name)}>
            {t(name)}
          </button>
        ))}
      </nav>

      {away ? (
        <div className="overlay" onClick={() => setAway(null)}>
          <div className="dialog" role="dialog" aria-modal="true" aria-label={t("awayTitle")} onClick={(event) => event.stopPropagation()}>
            <h2>{t("awayTitle")}</h2>
            <p className="lede">
              {formatNumber(away.years, lang)} {t("awayYears")}: {t("year")} {away.from_year} – {away.to_year}
            </p>
            <dl className="facts">
              {(
                [
                  [t("awayPeople"), away.population_then === null ? formatNumber(away.population_now, lang) : `${formatNumber(away.population_then, lang)} → ${formatNumber(away.population_now, lang)}`],
                  [t("awayBorn"), formatNumber(away.births, lang)],
                  [t("awayDied"), formatNumber(away.deaths, lang)],
                  [t("awayDiscoveries"), String(away.discoveries)],
                  [t("awayLost"), String(away.knowledge_lost)],
                  [t("awayFounded"), String(away.settlements_founded)],
                  [t("awayAbandoned"), String(away.settlements_abandoned)],
                  [t("awayPeoples"), String(away.peoples_emerged)],
                  [t("awayVanished"), String(away.peoples_vanished)],
                  [t("awayTrade"), String(away.trade_begun)],
                ] as [string, string][]
              ).map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <h3>{t("awayHighlights")}</h3>
            {away.highlights.length === 0 ? <p className="note">{t("awayQuiet")}</p> : null}
            <ul className="away-list">
              {away.highlights.map((item, index) => (
                <li key={index}>
                  <small>
                    {t("year")} {item.year}
                  </small>
                  {item.text}
                </li>
              ))}
            </ul>
            <button className="solid" onClick={() => setAway(null)}>
              {t("close")}
            </button>
          </div>
        </div>
      ) : null}

      {person && view !== "map" ? (
        <div className="overlay" onClick={() => setPerson(null)}>
          <div className="dialog" role="dialog" aria-modal="true" aria-label={person.name} onClick={(event) => event.stopPropagation()}>
            <PersonCard person={person} t={t} onPerson={showPerson} onTree={showTree} />
            <button className="solid" onClick={() => setPerson(null)}>
              {t("close")}
            </button>
          </div>
        </div>
      ) : null}

      {tree ? (
        <div className="overlay" onClick={() => setTree(null)}>
          <div className="dialog wide" role="dialog" aria-modal="true" aria-label={`${t("familyTree")}: ${tree.person.name}`} onClick={(event) => event.stopPropagation()}>
            <h2>
              {t("familyTree")}: {tree.person.name}
            </h2>
            <TreeView tree={tree} t={t} onPick={showTree} />
            <div className="dialog-actions">
              <button
                className="solid"
                onClick={() => {
                  showPerson(tree.person.id);
                  setTree(null);
                }}
              >
                {tree.person.name}
              </button>
              <button className="solid" onClick={() => setTree(null)}>
                {t("close")}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {why ? (
        <div className="overlay" onClick={() => setWhy(null)}>
          <div className="dialog" role="dialog" aria-modal="true" aria-label={t("why")} onClick={(event) => event.stopPropagation()}>
            <h2>{t("why")}</h2>
            <p className="lede">{why.event.text}</p>
            {why.decisions.length === 0 ? <p className="note">{why.expired ? t("expired") : t("noDecision")}</p> : null}
            {why.decisions.map((decision, index) => (
              <dl key={index}>
                <dt>{t("rule")}</dt>
                <dd>{decision.rule}</dd>
                <dt>{t("factors")}</dt>
                <dd>
                  {decision.factors.length === 0
                    ? t("noFactors")
                    : decision.factors.map((factor) => `${factor.name} ×${formatNumber(factor.factor, lang, 2)}`).join(", ")}
                </dd>
                <dt>{t("chance")}</dt>
                <dd>{decision.chance === null ? "–" : `${formatNumber(decision.chance * 100, lang, 2)} %`}</dd>
                <dt>{t("roll")}</dt>
                <dd>
                  {formatNumber(decision.roll * (decision.chance === null ? 1 : 100), lang, 2)}
                  {decision.chance === null ? "" : " %"}
                </dd>
              </dl>
            ))}
            <button className="solid" onClick={() => setWhy(null)}>
              {t("close")}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
