import { useMemo, useState } from "react";
import type { Lang } from "./api";
import { useWidth, type Point } from "./Chart";
import { formatNumber } from "./i18n";

export interface Mark {
  year: number;
  text: string;
}

interface Props {
  population: Point[];
  marks: Mark[];
  lang: Lang;
  yearLabel: string;
  peopleLabel: string;
  emptyLabel: string;
}

// The whole history of the world at a glance: how many people lived when,
// with a notch for every discovery.
export function HistoryBand({ population, marks, lang, yearLabel, peopleLabel, emptyLabel }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [at, setAt] = useState<number | null>(null);
  const height = 54;

  const model = useMemo(() => {
    if (population.length < 2 || width < 80) return null;
    const first = population[0].year;
    const last = population[population.length - 1].year;
    const peak = Math.max(...population.map((point) => point.value), 1);
    const x = (year: number) => ((year - first) / (last - first || 1)) * width;
    const y = (value: number) => height - 4 - (value / peak) * (height - 14);
    const line = population.map((point, index) => `${index ? "L" : "M"}${x(point.year).toFixed(1)} ${y(point.value).toFixed(1)}`).join("");
    return { first, last, x, y, line };
  }, [population, width]);

  const readout = useMemo(() => {
    if (at === null || !model) return null;
    const index = Math.round(at * (population.length - 1));
    const point = population[index];
    const near = marks
      .map((mark) => ({ mark, distance: Math.abs(model.x(mark.year) - model.x(point.year)) }))
      .filter((item) => item.distance <= 10)
      .sort((a, b) => a.distance - b.distance)[0];
    return { point, mark: near?.mark ?? null };
  }, [at, model, population, marks]);

  const onMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    setAt(Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)));
  };

  return (
    <div className="band">
      <div className="band-plot" ref={ref} onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setAt(null)}>
        {model ? (
          <svg width={width} height={height} aria-hidden="true">
            <path d={`${model.line}L${width} ${height}L0 ${height}Z`} className="band-area" />
            <path d={model.line} className="band-line" />
            {marks.map((mark, index) => (
              <g key={index} transform={`translate(${model.x(mark.year).toFixed(1)} 0)`}>
                <line y1="6" y2={height} className="band-mark" />
                <path d="M0 1l3.5 3.5L0 8l-3.5-3.5z" className="band-notch" />
              </g>
            ))}
            {readout ? <line x1={model.x(readout.point.year)} x2={model.x(readout.point.year)} y1="0" y2={height} className="band-cursor" /> : null}
          </svg>
        ) : (
          <span className="band-empty">{emptyLabel}</span>
        )}
      </div>
      <p className="band-readout" aria-live="polite">
        {readout ? (
          <>
            <strong>
              {yearLabel} {readout.point.year}
            </strong>{" "}
            {formatNumber(readout.point.value, lang)} {peopleLabel}
            {readout.mark ? <span> {readout.mark.text}</span> : null}
          </>
        ) : model ? (
          <>
            {yearLabel} {model.first} – {model.last}
          </>
        ) : null}
      </p>
    </div>
  );
}
