import { useState } from "react";
import { buildHash } from "../app/router";
import { useApp } from "../app/context";
import { AssessabilityBadge, ExposureBadge, Pill } from "./Badge";
import { Sparkline } from "./Sparkline";
import { agentLabel, dimensionMatrix, dimensionTrend, pluralize, tagLabel, type MatrixCell } from "../data/selectors";

/** The 8-dimension matrix grouped by category. Every cell decomposes on click into the agents that produce it. */
export function DimensionMatrix() {
  const { envelope, framework } = useApp();
  const groups = dimensionMatrix(envelope, framework);
  const [openId, setOpenId] = useState<string | null>(null);
  const showTrend = envelope.history.length > 1;

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {groups.map((group) => (
        <div key={group.id} className="panel p-3">
          <div className="caption uppercase tracking-wide text-[11px] mb-2">
            {group.id ? `${group.id} · ` : ""}
            {group.label}
          </div>
          <div className="flex flex-col gap-2">
            {group.cells.map((cell) => (
              <Cell key={cell.dimension.id} cell={cell} open={openId === cell.dimension.id} onToggle={() => setOpenId(openId === cell.dimension.id ? null : cell.dimension.id)} showTrend={showTrend} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Cell({ cell, open, onToggle, showTrend }: { cell: MatrixCell; open: boolean; onToggle: () => void; showTrend: boolean }) {
  const { envelope, framework } = useApp();
  const trend = showTrend ? dimensionTrend(envelope.history, cell.dimension.id) : [];
  const findingsHref = buildHash("findings", null, { dimension: cell.dimension.id });
  return (
    <div className="rounded border border-line">
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full text-left p-3 flex flex-col gap-2 rounded hover:bg-paper">
        <div className="flex items-start justify-between gap-2">
          <div className="font-medium text-[13.5px] leading-tight">{cell.dimension.name}</div>
          <ExposureBadge exposure={cell.maxExposure} />
        </div>
        <div className="flex flex-wrap items-center gap-1.5 caption">
          <AssessabilityBadge assessability={cell.dimension.assessability} />
          <span>{pluralize(cell.findingCount, "finding")}</span>
          {cell.agentsElevated ? <span>· {cell.agentsElevated} elevated</span> : null}
          {cell.agentsModerate ? <span>· {cell.agentsModerate} moderate</span> : null}
          {trend.length > 1 ? (
            <span className="ml-auto">
              <Sparkline points={trend} max={3} label={cell.dimension.name} width={72} height={20} />
            </span>
          ) : null}
        </div>
        {cell.tags.length ? (
          <div className="flex flex-wrap gap-1">
            {cell.tags.map((t) => (
              <Pill key={t} tone="neutral" title={tagLabel(t, framework)}>
                {t}
              </Pill>
            ))}
          </div>
        ) : null}
      </button>
      {open ? (
        <div className="border-t border-line px-3 py-2 text-[13px]">
          <p className="caption m-0 mb-2">{cell.dimension.definition}</p>
          {cell.agents.length === 0 ? (
            <p className="m-0 caption">No exposure observed in scanned files.</p>
          ) : (
            <ul className="m-0 p-0 list-none flex flex-col gap-1">
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
