import type { TrendPoint } from "../data/selectors";
import { formatDate } from "../data/selectors";

/** Inline SVG trend; no chart library. Dots mark scans, the last one is emphasized. */
export function Sparkline({ points, max, label, width = 120, height = 28 }: { points: TrendPoint[]; max: number; label: string; width?: number; height?: number }) {
  if (points.length < 2) return null;
  const pad = 3;
  const span = Math.max(max, 1);
  const stepX = (width - pad * 2) / (points.length - 1);
  const coords = points.map((p, i) => ({ x: pad + i * stepX, y: height - pad - (Math.min(p.value, span) / span) * (height - pad * 2) }));
  const path = coords.map((c, i) => `${i === 0 ? "M" : "L"}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const last = coords[coords.length - 1];
  const first = points[0];
  const latest = points[points.length - 1];
  const title = `${label}: ${first?.label ?? ""} (${formatDate(first?.date)}) to ${latest?.label ?? ""} (${formatDate(latest?.date)}), ${points.length} scans`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title} className="overflow-visible">
      <title>{title}</title>
      <path d={path} fill="none" stroke="var(--color-navy)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
      {coords.map((c, i) => (
        <circle key={i} cx={c.x} cy={c.y} r={i === coords.length - 1 ? 3 : 1.75} fill={i === coords.length - 1 ? "var(--color-gold)" : "var(--color-navy)"} />
      ))}
      {last ? null : null}
    </svg>
  );
}
