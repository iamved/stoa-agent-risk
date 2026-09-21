import { useApp } from "../app/context";
import { dimensionState } from "../data/exposure";
import { dimensionSubtitle } from "../data/labels";
import { RISK_LEVELS, findingsByDimension, type RiskLevel } from "../data/selectors";
import { DimensionStateBadge } from "./Badge";
import { ExposureTip, SeverityTip } from "./InfoTip";

const BAR: Record<RiskLevel, string> = { high: "bg-sev-high", medium: "bg-sev-medium", low: "bg-sev-low" };
const LEVEL_NAME: Record<RiskLevel, string> = { high: "High", medium: "Medium", low: "Low" };

/**
 * All eight dimensions: how many findings sit in each, by severity, and the
 * dimension's exposure. Two scales, each named and explained where it appears.
 */
export function DimensionChart({ selected, onSelect }: { selected: string | null; onSelect: (id: string | null) => void }) {
  const { envelope } = useApp();
  const bars = findingsByDimension(envelope);
  const max = Math.max(1, ...bars.map((b) => b.total));
  return (
    <section className="panel" aria-labelledby="dimension-chart-title">
      <div className="px-5 pt-4 pb-3 flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div>
          <h2 id="dimension-chart-title" className="m-0">Findings by dimension</h2>
          <div className="caption">A finding can affect more than one dimension. Select a dimension to filter the table.</div>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 caption">
          <span className="flex items-center gap-1.5 font-medium text-ink-soft">Severity <SeverityTip align="right" /></span>
          {RISK_LEVELS.map((level) => <span key={level} className="flex items-center gap-1.5"><span aria-hidden="true" className={`inline-block w-2.5 h-2.5 rounded-sm ${BAR[level]}`} />{LEVEL_NAME[level]}</span>)}
        </div>
      </div>
      <div role="table" aria-label="Findings by dimension" className="border-t border-line/70">
        <div role="row" className="grid grid-cols-[minmax(0,1.5fr)_minmax(80px,1fr)_56px_150px] gap-x-4 px-5 py-2 text-[11px] uppercase tracking-wide font-semibold text-ink-muted border-b border-line/70">
          <span role="columnheader">Dimension</span>
          <span role="columnheader">Findings by severity</span>
          <span role="columnheader" className="text-right">Total</span>
          <span role="columnheader" className="flex items-center gap-1.5">Exposure <ExposureTip align="right" /></span>
        </div>
        {bars.map((bar) => {
          const on = selected === bar.dimension.id;
          return (
            <div role="row" key={bar.dimension.id} className={`grid grid-cols-[minmax(0,1.5fr)_minmax(80px,1fr)_56px_150px] gap-x-4 items-center px-5 py-2.5 border-b border-line/50 last:border-b-0 ${on ? "bg-gold-100/60" : ""}`}>
              <span role="cell" className="min-w-0">
                <button type="button" aria-pressed={on} disabled={bar.total === 0} onClick={() => onSelect(on ? null : bar.dimension.id)} className="text-left text-[13.5px] font-medium text-navy bg-transparent border-0 p-0 cursor-pointer enabled:hover:underline disabled:cursor-default">{bar.dimension.name}</button>
                <span className="caption block">{dimensionSubtitle(bar.dimension.id, bar.dimension.definition)}</span>
              </span>
              <span role="cell" className="flex h-2 rounded-full overflow-hidden bg-line/50" aria-label={RISK_LEVELS.map((l) => `${bar.counts[l]} ${LEVEL_NAME[l].toLowerCase()}`).join(", ")}>
                {RISK_LEVELS.filter((l) => bar.counts[l] > 0).map((l) => <span key={l} className={BAR[l]} style={{ width: `${(bar.counts[l] / max) * 100}%` }} />)}
              </span>
              <span role="cell" className="text-right tabular-nums text-[13px]">{bar.total}</span>
              <span role="cell"><DimensionStateBadge state={dimensionState(envelope, bar.dimension, bar.maxExposure, bar.total)} /></span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
