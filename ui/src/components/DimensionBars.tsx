import { useState } from "react";
import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { ExposureBadge } from "./Badge";
import { RISK_LABEL, RISK_LEVELS, agentLabel, findingsByDimension, initials } from "../data/selectors";

const BAR: Record<string, string> = { high: "bg-sev-high", medium: "bg-sev-medium", low: "bg-sev-low" };

/** Findings by dimension as stacked bars, with the organization-wide exposure for each. A row expands to the agents behind it. */
export function DimensionBars() {
  const { envelope } = useApp();
  const rows = findingsByDimension(envelope);
  const max = Math.max(1, ...rows.map((r) => r.total));
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <div className="panel">
      <div className="flex flex-wrap items-center justify-between gap-2 px-5 pt-4 pb-3">
        <div>
          <h2 className="m-0">Findings by dimension</h2>
          <div className="caption">Where the open findings sit, and each dimension's exposure level.</div>
        </div>
        <div className="flex items-center gap-3 caption">
          {RISK_LEVELS.map((l) => <span key={l} className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`inline-block w-2.5 h-2.5 rounded-sm ${BAR[l]}`} />{RISK_LABEL[l]}</span>)}
        </div>
      </div>
      <div className="divide-y divide-line/70">
        {rows.map((r) => {
          const open = openId === r.dimension.id;
          return (
            <div key={r.dimension.id}>
              <button type="button" onClick={() => setOpenId(open ? null : r.dimension.id)} aria-expanded={open} className="w-full grid grid-cols-[minmax(150px,200px)_1fr_36px_auto] items-center gap-4 px-5 py-2.5 text-left hover:bg-paper/70" title={r.dimension.definition}>
                <span className="text-[13.5px] font-medium text-navy leading-tight">{r.dimension.name}</span>
                <span className="h-3 rounded-sm bg-paper overflow-hidden flex" aria-label={`${r.total} findings: ${RISK_LEVELS.map((l) => `${r.counts[l]} ${RISK_LABEL[l].toLowerCase()}`).join(", ")}`}>
                  {RISK_LEVELS.map((l) => (r.counts[l] ? <span key={l} className={`${BAR[l]} h-full`} style={{ width: `${(r.counts[l] / max) * 100}%` }} /> : null))}
                </span>
                <span className="num text-[14px] text-navy text-right">{r.total}</span>
                <ExposureBadge exposure={r.maxExposure} />
              </button>
              {open ? (
                <div className="border-t border-line/70 bg-paper/60 px-5 py-3 text-[13px]">
                  <p className="caption m-0 mb-2">{r.dimension.definition}</p>
                  {r.agents.length === 0 ? <p className="m-0 caption">Nothing observed.</p> : (
                    <ul className="m-0 p-0 list-none grid gap-1.5 md:grid-cols-2">
                      {r.agents.map(({ agent, entry }) => (
                        <li key={agent.id} className="flex items-center gap-2.5">
                          <span className="avatar" aria-hidden="true">{initials(agentLabel(agent))}</span>
                          <a href={buildHash("inventory", agent.id)} className="link truncate flex-1">{agentLabel(agent)}</a>
                          <ExposureBadge exposure={entry.exposure} />
                        </li>
                      ))}
                    </ul>
                  )}
                  <a href={buildHash("findings", null, { dimension: r.dimension.id })} className="link text-[12.5px] inline-block mt-2">See the findings</a>
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}
