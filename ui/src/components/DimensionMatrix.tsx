import { useState } from "react";
import { buildHash } from "../app/router";
import { useApp } from "../app/context";
import { AssessabilityBadge, ExposureBadge } from "./Badge";
import { Sparkline } from "./Sparkline";
import { agentLabel, dimensionMatrix, dimensionTrend, tagLabel, type MatrixCell } from "../data/selectors";

/** The eight dimensions by category. Every row decomposes on click into the agents that produce its level. */
export function DimensionMatrix() {
  const { envelope, framework } = useApp();
  const groups = dimensionMatrix(envelope, framework);
  const [openId, setOpenId] = useState<string | null>(null);
  const showTrend = envelope.history.length > 1;

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {groups.map((group) => (
        <div key={group.id} className="panel">
          <div className="eyebrow px-4 pt-3 pb-2 border-b border-line">
            {group.id ? `${group.id} · ` : ""}
            {group.label}
          </div>
          <div className="divide-y divide-line">
            {group.cells.map((cell) => (
              <Row key={cell.dimension.id} cell={cell} open={openId === cell.dimension.id} onToggle={() => setOpenId(openId === cell.dimension.id ? null : cell.dimension.id)} showTrend={showTrend} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Row({ cell, open, onToggle, showTrend }: { cell: MatrixCell; open: boolean; onToggle: () => void; showTrend: boolean }) {
  const { envelope, framework } = useApp();
  const trend = showTrend ? dimensionTrend(envelope.history, cell.dimension.id) : [];
  const findingsHref = buildHash("findings", null, { dimension: cell.dimension.id });
  return (
    <div>
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full text-left px-4 py-3 flex flex-col gap-1.5 hover:bg-paper/70">
        <div className="flex items-start justify-between gap-3">
          <div className="text-[13.5px] font-medium leading-tight text-navy">{cell.dimension.name}</div>
          <ExposureBadge exposure={cell.maxExposure} />
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 caption">
          <AssessabilityBadge assessability={cell.dimension.assessability} />
          <span className="tabular-nums">{cell.findingCount} {cell.findingCount === 1 ? "finding" : "findings"}</span>
          {cell.agentsElevated ? <span className="tabular-nums">{cell.agentsElevated} elevated</span> : null}
          {cell.agentsModerate ? <span className="tabular-nums">{cell.agentsModerate} moderate</span> : null}
          {trend.length > 1 ? (
            <span className="ml-auto">
              <Sparkline points={trend} max={3} label={cell.dimension.name} width={64} height={18} />
            </span>
          ) : null}
        </div>
        {cell.tags.length ? <div className="mono text-[11px] text-ink-muted">{cell.tags.map((t) => tagLabel(t, framework)).join(" · ")}</div> : null}
      </button>
      {open ? (
        <div className="border-t border-line bg-paper/60 px-4 py-3 text-[13px]">
          <p className="caption m-0 mb-2">{cell.dimension.definition}</p>
          {cell.agents.length === 0 ? (
            <p className="m-0 caption">No exposure observed in scanned files.</p>
          ) : (
            <ul className="m-0 p-0 list-none flex flex-col gap-1.5">
              {cell.agents.map(({ agent, entry }) => (
                <li key={agent.id} className="flex items-center justify-between gap-2">
                  <a href={buildHash("inventory", agent.id)} className="link truncate">
                    {agentLabel(agent)}
                  </a>
                  <span className="flex items-center gap-2 caption whitespace-nowrap">
                    <span className="tabular-nums">score {entry.score}</span>
                    <ExposureBadge exposure={entry.exposure} />
                  </span>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-2">
            <a href={findingsHref} className="link text-[12.5px]">
              Findings in this dimension
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
