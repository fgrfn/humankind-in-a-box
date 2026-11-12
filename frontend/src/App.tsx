import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Discovery, type Group, type Human, type Lang, type People, type PersonDetail, type Place, type Series, type Stats, type Why, type WorldEvent, type WorldMap } from "./api";
import { Chart, SERIES_COLOURS, type Point } from "./Chart";
import { HistoryBand, type Mark } from "./HistoryBand";
import { formatNumber, translator, type TextKey } from "./i18n";
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

function Numbers({ stats, series, discoveries, peoples, lang, t }: { stats: Stats; series: Series; discoveries: Discovery[]; peoples: People[]; lang: Lang; t: Translate }) {
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

      <h2>{t("peoples")}</h2>
      <p className="note">{t("peoplesNote")}</p>
      <ul className="peoples">
        {peoples.map((item) => {
          const largest = Math.max(1, ...peoples.map((other) => other.population));
          return (
            <li key={item.id} className={item.ended_year === null ? "" : "gone"}>
              <span className="name">{item.name}</span>
              <span className="bar" aria-hidden="true">
                <span style={{ width: `${(100 * item.population) / largest}%` }} />
              </span>
              <span className="count">{item.ended_year === null ? formatNumber(item.population, lang) : t("gone")}</span>
              <span className="state">
                {item.parent ? `${t("descendedFrom")} ${item.parent}` : t("firstPeople")}, {t("year")} {item.founded_year}
                {item.ended_year === null ? `, ${item.clans} ${item.clans === 1 ? t("clansOne") : t("clans")}` : ` – ${item.ended_year}`}
                , {t("sounds")} {item.consonants.split("").join(" ")} · {item.vowels.split("").join(" ")}
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

function ClanDetail({ detail, t, onShow, onPerson }: { detail: Group; t: Translate; onShow: () => void; onPerson: (id: number) => void }) {
  return (
    <article className="detail">
      <h2>{detail.name}</h2>
      <p className="lede">
        {detail.people ? `${t("ofThePeople")} ${detail.people}, ` : ""}
        {detail.population} {t("people")}, {detail.settled ? `${t("settled")}${detail.place ? ` (${detail.place})` : ""}` : t("wandering")}, {t("founded")} {detail.founded_year}
      </p>
      <button className="plain" onClick={onShow}>
        {t("showOnMap")}
      </button>
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
  const [stats, setStats] = useState<Stats | null>(null);
  const [map, setMap] = useState<WorldMap | null>(null);
  const [steps, setSteps] = useState<number[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [places, setPlaces] = useState<Place[]>([]);
  const [people, setPeople] = useState<Human[]>([]);
  const [person, setPerson] = useState<PersonDetail | null>(null);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [series, setSeries] = useState<Series>({});
  const [discoveries, setDiscoveries] = useState<Discovery[]>([]);
  const [peoples, setPeoples] = useState<People[]>([]);
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
      setGroups(nextGroups);
      setPlaces(nextPlaces);
    },
    5,
    [worldId, lang],
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
    });
    return () => {
      alive = false;
      source.close();
    };
  }, [worldId, lang, minImportance]);

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

  const selectFromMap = useCallback((id: number) => {
    setSelected(id);
    setView("clans");
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
        <div className="stage" hidden={view !== "map"}>
          <MapView map={map} steps={steps} groups={groups} places={places} people={people} selected={selected} focus={focus} onSelect={selectFromMap} onPerson={showPerson} />
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

        {view === "numbers" && stats ? <Numbers stats={stats} series={series} discoveries={discoveries} peoples={peoples} lang={lang} t={t} /> : null}

        {view === "clans" ? (
          <div className="page clans-page">
            <ul className="clans">
              {sortedGroups.map((group) => (
                <li key={group.id}>
                  <button className={group.id === selected ? "on" : ""} onClick={() => setSelected(group.id)}>
                    <span className="clan-name">{group.name}</span>
                    <span className="clan-where">
                      {group.people ? `${group.people}, ` : ""}
                      {group.settled ? (group.place ?? t("settled")) : t("wandering")}
                    </span>
                    <span className="clan-count">{group.population}</span>
                  </button>
                </li>
              ))}
            </ul>
            {detail ? <ClanDetail detail={detail} t={t} onShow={() => showOnMap(detail.id)} onPerson={showPerson} /> : <p className="note pick">{t("pickClan")}</p>}
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

      {person ? (
        <div className="overlay" onClick={() => setPerson(null)}>
          <div className="dialog" role="dialog" aria-modal="true" aria-label={person.name} onClick={(event) => event.stopPropagation()}>
            <h2>{person.name}</h2>
            <p className="lede">
              {person.clan_name ? `${person.clan_name}, ` : ""}
              {person.died_year === null ? `${t("age")} ${person.age}` : `${t("died")} ${t("year")} ${person.died_year}, ${t("age")} ${person.age}`}
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
                        <button key={relative.id} className="plain name" onClick={() => showPerson(relative.id)}>
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
            <button className="solid" onClick={() => setPerson(null)}>
              {t("close")}
            </button>
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
