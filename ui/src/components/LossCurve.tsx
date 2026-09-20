import type { Indication, Policy } from "../data/lossModel";
import { POLICY_NAME, money } from "../data/lossModel";

/** Exceedance curve: chance of a year's insurable loss exceeding a given amount, with the suggested coverage band shaded. */
export function LossCurve({ r, coverage }: { r: Indication; coverage: Policy[] }) {
  const W = 760, H = 330, L = 64, R = 18, T = 18, B = 44, S = r.summary;
  const pts = S.curve.filter((p) => p.x >= 1e4);
  if (pts.length < 3) return <p className="caption m-0">Losses are too small to chart for this deployment.</p>;
  const last = pts[pts.length - 1]!;
  const xmin = 4, xmax = Math.log10(Math.max(r.limits.conservative * 2, last.x * 1.3)), ymin = -3, ymax = Math.log10(0.5);
  const X = (v: number) => L + ((Math.log10(Math.max(v, 1e4)) - xmin) / (xmax - xmin)) * (W - L - R);
  const Y = (p: number) => T + ((ymax - Math.log10(p)) / (ymax - ymin)) * (H - T - B);
  const xTicks: number[] = [];
  for (let e = 4; e <= Math.floor(xmax); e++) xTicks.push(10 ** e);
  const yTicks: [number, string][] = [[0.1, "1 in 10"], [0.05, "1 in 20"], [0.01, "1 in 100"], [0.004, "1 in 250"], [0.001, "1 in 1,000"]];
  const path = pts.map((p, i) => (i ? "L" : "M") + X(p.x).toFixed(1) + " " + Y(p.p).toFixed(1)).join(" ");
  const marks: [number, number][] = [[1 - 0.95, S.pLow], [1 - 0.99, S.pMid], [1 - 0.996, S.pHigh]];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Chance of exceeding a given loss in one year, with the suggested coverage range shaded" className="block w-full h-auto" style={{ minWidth: 520 }}>
      {xTicks.map((v) => (
        <g key={v}>
          <line x1={X(v)} x2={X(v)} y1={T} y2={H - B} stroke="var(--color-line)" />
          <text x={X(v)} y={H - B + 18} fontSize="11.5" textAnchor="middle" fill="var(--color-ink-muted)">{money(v)}</text>
        </g>
      ))}
      {yTicks.map(([p, t]) => (
        <g key={t}>
          <line x1={L} x2={W - R} y1={Y(p)} y2={Y(p)} stroke="var(--color-line)" />
          <text x={L - 8} y={Y(p) + 4} fontSize="11.5" textAnchor="end" fill="var(--color-ink-muted)">{t}</text>
        </g>
      ))}
      <rect x={X(r.limits.lean)} y={T} width={Math.max(3, X(r.limits.conservative) - X(r.limits.lean))} height={H - T - B} fill="var(--color-gold)" opacity="0.22" />
      <path d={path} fill="none" stroke="var(--color-navy)" strokeWidth="2.4" strokeLinejoin="round" />
      {marks.map(([p, v]) => (v >= 1e4 ? <circle key={p} cx={X(v)} cy={Y(p)} r="4.5" fill="var(--color-gold)" stroke="var(--color-navy)" strokeWidth="1.5" /> : null))}
      {coverage.map((pol, i) => (pol.limit > 1e4 ? (
        <g key={i}>
          <line x1={X(pol.limit)} x2={X(pol.limit)} y1={T} y2={H - B} stroke={pol.ai_exclusion ? "var(--color-sev-critical)" : "var(--color-ok)"} strokeWidth="1.5" strokeDasharray="5 4" />
          <text x={X(pol.limit) + 5} y={T + 12} fontSize="11.5" fill="var(--color-ink-muted)">{POLICY_NAME[pol.type]} {money(pol.limit)}{pol.ai_exclusion ? ", AI excluded" : ""}</text>
        </g>
      ) : null))}
      <text x={(X(r.limits.lean) + X(r.limits.conservative)) / 2} y={H - B - 8} fontSize="12.5" fontWeight="600" textAnchor="middle" fill="var(--color-gold-ink)">suggested coverage</text>
      <text x={(L + W - R) / 2} y={H - 6} fontSize="12" textAnchor="middle" fill="var(--color-ink-muted)">Insurable loss in one year</text>
    </svg>
  );
}
