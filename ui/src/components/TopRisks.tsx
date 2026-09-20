import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "./Badge";
import { agentLabel, topRisks } from "../data/selectors";

/** The five findings to read first, each as a plain-English "so what". Ranked, so the numbers carry meaning. */
export function TopRisks() {
  const { envelope } = useApp();
  const risks = topRisks(envelope, 5);
  if (!risks.length) return <p className="caption m-0">No unsuppressed findings.</p>;
  return (
    <ol className="m-0 p-0 list-none panel divide-y divide-line">
      {risks.map(({ ref, soWhat }, i) => {
        const f = ref.finding;
        return (
          <li key={f.fingerprint} className="grid grid-cols-[28px_1fr] gap-3 px-4 py-3">
            <span className="mono text-[12px] text-ink-muted tabular-nums pt-0.5">{String(i + 1).padStart(2, "0")}</span>
            <div className="min-w-0">
              <a href={buildHash("findings", f.fingerprint)} className="link font-medium text-[13.5px]">
                {soWhat}
              </a>
              <div className="caption mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <SeverityBadge severity={f.severity} />
                <span className="mono">{f.rule_id}</span>
                {ref.agent ? <span>{agentLabel(ref.agent)}</span> : <span>repository</span>}
                <span className="mono truncate">
                  {f.path}:{f.line}
                </span>
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
