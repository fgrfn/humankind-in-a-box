import { useEffect, useMemo, useRef, useState } from "react";
import type { Lang } from "./api";
import { formatNumber } from "./i18n";

export interface Point {
  year: number;
  value: number;
}

export interface ChartSeries {
  name: string;
  colour: string;
  points: Point[];
}

// Validated as a pair against the panel surface (lightness band, chroma,
// colour-vision separation, contrast). Do not swap one without re-checking.
export const SERIES_COLOURS = ["#b98a2e", "#2b93b3"] as const;

export function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => setWidth(Math.round(entries[0].contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const lead = value / power;
  return (lead <= 1 ? 1 : lead <= 2 ? 2 : lead <= 5 ? 5 : 10) * power;
}

interface Props {
  title: string;
  series: ChartSeries[];
  lang: Lang;
  unit?: string;
  digits?: number;
  fixedMax?: number;
  signed?: boolean;
  yearLabel: string;
  tableLabel: string;
}

export function Chart({ title, series, lang, unit = "", digits = 0, fixedMax, signed = false, yearLabel, tableLabel }: Props) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const height = 190;
  // Room on the left for the axis labels: more when the numbers are long.
  const peak = Math.max(0, ...series.flatMap((item) => item.points.map((point) => Math.abs(point.value))));
  const pad = { left: peak >= 1e6 ? 76 : peak >= 1e5 ? 64 : peak >= 1e4 ? 54 : 46, right: 14, top: 12, bottom: 24 };

  const model = useMemo(() => {
    const years = series[0]?.points.map((point) => point.year) ?? [];
    if (years.length < 2 || width < 120) return null;
    const all = series.flatMap((item) => item.points.map((point) => point.value));
    const high = fixedMax ?? niceCeiling(Math.max(...all.map(Math.abs), 0.0001));
    const low = signed ? -high : 0;
    const innerW = width - pad.left - pad.right;
    const innerH = height - pad.top - pad.bottom;
    const first = years[0];
    const last = years[years.length - 1];
    const x = (year: number) => pad.left + ((year - first) / (last - first || 1)) * innerW;
    const y = (value: number) => pad.top + (1 - (value - low) / (high - low)) * innerH;
    const paths = series.map((item) => item.points.map((point, index) => `${index ? "L" : "M"}${x(point.year).toFixed(1)} ${y(point.value).toFixed(1)}`).join(""));
    const grid = signed ? [low, 0, high] : [0, high / 2, high];
    return { years, first, last, x, y, paths, grid, innerW, low };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, width, fixedMax, signed]);

  const show = (value: number) => `${formatNumber(value, lang, digits)}${unit}`;

  const onMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!model) return;
    const box = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - box.left - pad.left) / model.innerW));
    setHover(Math.round(ratio * (model.years.length - 1)));
  };

  const sampled = useMemo(() => {
    const points = series[0]?.points ?? [];
    const step = Math.max(1, Math.ceil(points.length / 12));
    const indexes = points.map((_, index) => index).filter((index) => index % step === 0 || index === points.length - 1);
    return indexes;
  }, [series]);

  return (
    <figure className="chart" ref={ref}>
      <figcaption>
        <span className="chart-title">{title}</span>
        {series.length > 1 ? (
          <span className="legend">
            {series.map((item) => (
              <span key={item.name}>
                <i style={{ background: item.colour }} />
                {item.name}
              </span>
            ))}
          </span>
        ) : null}
      </figcaption>
      {model ? (
        <div className="plot">
          <svg width={width} height={height} onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} role="img" aria-label={title}>
            {model.grid.map((value) => (
              <g key={value}>
                <line x1={pad.left} x2={width - pad.right} y1={model.y(value)} y2={model.y(value)} className={value === 0 && signed ? "axis" : "grid"} />
                <text x={pad.left - 8} y={model.y(value) + 4} textAnchor="end" className="tick">
                  {show(value)}
                </text>
              </g>
            ))}
            <text x={pad.left} y={height - 6} className="tick">
              {model.first}
            </text>
            <text x={width - pad.right} y={height - 6} textAnchor="end" className="tick">
              {model.last}
            </text>
            {series.length === 1 && !signed ? (
              <path d={`${model.paths[0]}L${model.x(model.last).toFixed(1)} ${model.y(0).toFixed(1)}L${model.x(model.first).toFixed(1)} ${model.y(0).toFixed(1)}Z`} fill={series[0].colour} opacity="0.16" />
            ) : null}
            {model.paths.map((path, index) => (
              <path key={series[index].name} d={path} fill="none" stroke={series[index].colour} strokeWidth="2" strokeLinejoin="round" />
            ))}
            {hover !== null ? (
              <g>
                <line x1={model.x(model.years[hover])} x2={model.x(model.years[hover])} y1={pad.top} y2={height - pad.bottom} className="cross" />
                {series.map((item) => (
                  <circle key={item.name} cx={model.x(model.years[hover])} cy={model.y(item.points[hover]?.value ?? 0)} r="4" fill={item.colour} stroke="var(--panel)" strokeWidth="2" />
                ))}
              </g>
            ) : null}
          </svg>
          {hover !== null ? (
            <div className="tip" style={{ left: Math.min(Math.max(model.x(model.years[hover]), 70), width - 70) }}>
              <strong>
                {yearLabel} {model.years[hover]}
              </strong>
              {series.map((item) => (
                <span key={item.name}>
                  {series.length > 1 ? <i style={{ background: item.colour }} /> : null}
                  {series.length > 1 ? `${item.name}: ` : ""}
                  {show(item.points[hover]?.value ?? 0)}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : (
        <div className="plot empty" style={{ height }} />
      )}
      <details>
        <summary>{tableLabel}</summary>
        <table>
          <thead>
            <tr>
              <th>{yearLabel}</th>
              {series.map((item) => (
                <th key={item.name}>{item.name}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sampled.map((index) => (
              <tr key={index}>
                <td>{series[0].points[index].year}</td>
                {series.map((item) => (
                  <td key={item.name}>{show(item.points[index]?.value ?? 0)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}
