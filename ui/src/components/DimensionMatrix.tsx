import { useState } from "react";
import { buildHash } from "../app/router";
import { useApp } from "../app/context";
import { ExposureBadge } from "./Badge";
import { agentLabel, dimensionMatrix, type MatrixCell } from "../data/selectors";

/** The eight dimensions by category. A row expands to the agents that produce its level. */
export function DimensionMatrix() {
  const { envelope, framework } = useApp();
  const groups = dimensionMatrix(envelope, framework);
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {groups.map((group) => (
        <div key={group.id} className="panel">
          <div className="eyebrow px-4 pt-3 pb-2 border-b border-line">{group.label}</div>
          <div className="divide-y divide-line">
            {group.cells.map((cell) => (
              <Row key={cell.dimension.id} cell={cell} open={openId === cell.dimension.id} onToggle={() => setOpenId(openId === cell.dimension.id ? null : cell.dimension.id)} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Row({ cell, open, onToggle }: { cell: MatrixCell; open: boolean; onToggle: () => void }) {
  return (
    <div>
      <button type="button" onClick={onToggle} aria-expanded={open} className="w-full text-left px-4 py-3 flex items-center justify-between gap-3 hover:bg-paper/70" title={cell.dimension.definition}>
        <span className="min-w-0">
          <span className="block text-[13.5px] font-medium leading-tight text-navy">{cell.dimension.name}</span>
          <span className="caption tabular-nums">{cell.findingCount} {cell.findingCount === 1 ? "finding" : "findings"}</span>
        </span>
        <ExposureBadge exposure={cell.maxExposure} />
      </button>
      {open ? (
        <div className="border-t border-line bg-paper/60 px-4 py-3 text-[13px]">
          <p className="caption m-0 mb-2">{cell.dimension.definition}</p>
          {cell.agents.length === 0 ? (
            <p className="m-0 caption">Nothing observed.</p>
          ) : (
            <ul className="m-0 p-0 list-none flex flex-col gap-1.5">
              {cell.agents.map(({ agent, entry }) => (
                <li key={agent.id} className="flex items-center justify-between gap-2">
                  <a href={buildHash("inventory", agent.id)} className="link truncate">{agentLabel(agent)}</a>
                  <ExposureBadge exposure={entry.exposure} />
                </li>
              ))}
            </ul>
          )}
          <a href={buildHash("findings", null, { dimension: cell.dimension.id })} className="link text-[12.5px] inline-block mt-2">See the findings</a>
        </div>
      ) : null}
    </div>
  );
}
