import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "./Badge";
import { agentLabel, topRisks } from "../data/selectors";

/** The five findings to read first, each as a plain-English "so what". */
export function TopRisks() {
  const { envelope } = useApp();
  const risks = topRisks(envelope, 5);
  if (!risks.length) return <p className="caption m-0">No unsuppressed findings.</p>;
  return (
    <ol className="m-0 p-0 list-none flex flex-col divide-y divide-line panel">
      {risks.map(({ ref, soWhat }, i) => {
        const f = ref.finding;
        return (
          <li key={f.fingerprint} className="flex gap-3 p-3">
            <span className="font-serif text-gold text-[20px] leading-none w-6 shrink-0 tabular-nums">{i + 1}</span>
            <div className="min-w-0 flex-1">
              <a href={buildHash("findings", f.fingerprint)} className="link font-medium">
                {soWhat}
              </a>
              <div className="caption mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
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
