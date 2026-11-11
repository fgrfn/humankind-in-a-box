import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Group, type Lang, type Series, type Stats, type Why, type WorldEvent, type WorldMap } from "./api";
import { formatNumber, translator } from "./i18n";
import { MapView } from "./MapView";

type Tab = "chronicle" | "statistics" | "clans";

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

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <svg className="spark" viewBox="0 0 100 28" />;
  const recent = values.slice(-200);
  const low = Math.min(...recent);
  const high = Math.max(...recent);
  const span = high - low || 1;
  const points = recent
    .map((value, index) => `${((index / (recent.length - 1)) * 100).toFixed(1)},${(26 - ((value - low) / span) * 24).toFixed(1)}`)
    .join(" ");
  return (
    <svg className="spark" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Tile({ label, value, series }: { label: string; value: string; series?: number[] }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {series ? <Sparkline values={series} /> : null}
    </div>
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
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [series, setSeries] = useState<Series>({});
  const [tab, setTab] = useState<Tab>("chronicle");
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
      const [nextStats, nextGroups] = await Promise.all([api.stats(worldId, lang), api.groups(worldId, lang)]);
      setStats(nextStats);
      setGroups(nextGroups);
    },
    5,
    [worldId, lang],
  );

  usePolling(
    async () => {
      if (worldId === null) return;
      const [nextSteps, nextSeries] = await Promise.all([api.steps(worldId), api.metrics(worldId, METRIC_KEYS)]);
      setSteps(nextSteps.values);
      setSeries(nextSeries);
    },
    30,
    [worldId],
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

  const select = useCallback((id: number) => {
    setSelected(id);
    setTab("clans");
  }, []);

  const explain = useCallback(
    (event: WorldEvent) => {
      if (worldId === null) return;
      void api.why(worldId, event.seq, lang).then(setWhy);
    },
    [worldId, lang],
  );

  const values = (key: string) => (series[key] ?? []).map((point) => point.value);
  const fed = useMemo(() => {
    const eaten = series["food.eaten"] ?? [];
    const needed = new Map((series["food.needed"] ?? []).map((point) => [point.year, point.value]));
    return eaten.map((point) => (needed.get(point.year) ? (100 * point.value) / needed.get(point.year)! : 100));
  }, [series]);

  const sortedGroups = useMemo(() => [...groups].sort((a, b) => b.population - a.population || a.id - b.id), [groups]);

  return (
    <div className="app">
      <header>
        <h1>{t("title")}</h1>
        {stats ? (
          <div className="clock">
            <strong>
              {t("year")} {formatNumber(stats.year, lang)}
            </strong>
            <span>{t(stats.season)}</span>
            <span>
              {formatNumber(stats.population, lang)} {t("people")}
            </span>
          </div>
        ) : (
          <div className="clock">{t("waiting")}</div>
        )}
        <div className="lang" role="group" aria-label="Language">
          {(["de", "en"] as const).map((code) => (
            <button key={code} className={lang === code ? "on" : ""} onClick={() => setLang(code)} aria-pressed={lang === code}>
              {code.toUpperCase()}
            </button>
          ))}
        </div>
      </header>

      <main>
        <MapView map={map} steps={steps} groups={groups} selected={selected} focus={focus} onSelect={select} />

        <section className="panel">
          <nav role="tablist">
            {(["chronicle", "statistics", "clans"] as const).map((name) => (
              <button key={name} role="tab" aria-selected={tab === name} className={tab === name ? "on" : ""} onClick={() => setTab(name)}>
                {t(name)}
              </button>
            ))}
          </nav>

          {tab === "chronicle" ? (
            <div className="scroll">
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
              {stats && stats.population === 0 && stats.ever_lived > 0 ? <p className="note">{t("extinct")}</p> : null}
              {events.length === 0 ? <p className="note">{t("noEvents")}</p> : null}
              <ol className="events">
                {events.map((event) => (
                  <li key={event.seq} className={`importance-${event.importance}`}>
                    <button onClick={() => explain(event)} title={t("why")}>
                      <span className="when">
                        {event.year}·{String(event.month).padStart(2, "0")}
                      </span>
                      <span className="what">{event.text}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
          ) : null}

          {tab === "statistics" && stats ? (
            <div className="scroll">
              <div className="tiles">
                <Tile label={t("year")} value={formatNumber(stats.year, lang)} />
                <Tile label={t("population")} value={formatNumber(stats.population, lang)} series={values("people.population")} />
                <Tile label={t("everLived")} value={formatNumber(stats.ever_lived, lang)} />
                <Tile label={t("clans")} value={formatNumber(stats.clans, lang)} series={values("clans.count")} />
                <Tile label={t("settlements")} value={formatNumber(stats.settlements, lang)} series={values("settlements.count")} />
                <Tile label={t("discoveries")} value={`${stats.discoveries} / ${stats.discoveries_possible}`} />
                <Tile label={t("births")} value={formatNumber(values("people.births").at(-1) ?? 0, lang)} series={values("people.births")} />
                <Tile label={t("deaths")} value={formatNumber(values("people.deaths").at(-1) ?? 0, lang)} series={values("people.deaths")} />
                <Tile label={t("fed")} value={`${formatNumber(fed.at(-1) ?? 100, lang)} %`} series={fed} />
                <Tile
                  label={t("climate")}
                  value={stats.climate_anomaly === null ? "–" : `${stats.climate_anomaly > 0 ? "+" : ""}${formatNumber(stats.climate_anomaly, lang, 1)} °C`}
                  series={values("climate.anomaly")}
                />
                <Tile label={t("migrations")} value={formatNumber(stats.migrations_total, lang)} />
                <Tile label={t("events")} value={formatNumber(stats.events_total, lang)} />
                <Tile label={t("seed")} value={String(stats.seed)} />
              </div>
              {stats.last_event ? (
                <p className="note">
                  {t("lastEvent")} ({t("year")} {stats.last_event_year}): {stats.last_event}
                </p>
              ) : null}
            </div>
          ) : null}

          {tab === "clans" ? (
            <div className="scroll">
              {detail ? (
                <article className="detail">
                  <h2>{detail.name}</h2>
                  <p>
                    {detail.population} {t("people")}, {detail.settled ? `${t("settled")}${detail.place ? ` (${detail.place})` : ""}` : t("wandering")}, {t("founded")} {detail.founded_year}
                  </p>
                  <button className="link" onClick={() => setFocus({ id: detail.id, nonce: Date.now() })}>
                    {t("showOnMap")}
                  </button>
                  <h3>{t("knowledge")}</h3>
                  {detail.technologies.length === 0 ? <p>{t("noKnowledge")}</p> : null}
                  <ul>
                    {detail.technologies.map((tech) => (
                      <li key={tech.id}>
                        {tech.name} <small>({t(tech.how)}, {t("year")} {tech.year})</small>
                      </li>
                    ))}
                  </ul>
                  <h3>{t("members")}</h3>
                  <ul className="members">
                    {(detail.members ?? []).slice(0, 40).map((member) => (
                      <li key={member.id}>
                        {member.name} <small>{member.age} {t("years")}</small>
                      </li>
                    ))}
                  </ul>
                </article>
              ) : null}
              <ul className="clans">
                {sortedGroups.map((group) => (
                  <li key={group.id}>
                    <button className={group.id === selected ? "on" : ""} onClick={() => setSelected(group.id)}>
                      <span>{group.name}{group.settled ? ` · ${group.place ?? t("settled")}` : ""}</span>
                      <span>{group.population}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      </main>

      {why ? (
        <div className="overlay" onClick={() => setWhy(null)}>
          <div className="dialog" role="dialog" aria-modal="true" aria-label={t("why")} onClick={(event) => event.stopPropagation()}>
            <h2>{t("why")}</h2>
            <p>{why.event.text}</p>
            {why.decisions.length === 0 ? <p className="note">{why.expired ? t("expired") : t("noDecision")}</p> : null}
            {why.decisions.map((decision, index) => (
              <dl key={index}>
                <dt>{t("rule")}</dt>
                <dd><code>{decision.rule}</code></dd>
                <dt>{t("factors")}</dt>
                <dd>
                  {decision.factors.length === 0
                    ? t("noFactors")
                    : decision.factors.map((factor) => `${factor.name} ×${formatNumber(factor.factor, lang, 2)}`).join(", ")}
                </dd>
                <dt>{t("chance")}</dt>
                <dd>{decision.chance === null ? "–" : `${formatNumber(decision.chance * 100, lang, 2)} %`}</dd>
                <dt>{t("roll")}</dt>
                <dd>{formatNumber(decision.roll * (decision.chance === null ? 1 : 100), lang, 2)}{decision.chance === null ? "" : " %"}</dd>
              </dl>
            ))}
            <button onClick={() => setWhy(null)}>{t("close")}</button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
