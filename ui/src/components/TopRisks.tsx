import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "./Badge";
import { agentLabel, topRisks } from "../data/selectors";

/** The five findings to read first, each as a plain-English sentence. */
export function TopRisks() {
  const { envelope } = useApp();
  const risks = topRisks(envelope, 5);
  if (!risks.length) return <p className="caption m-0">No open findings.</p>;
  return (
    <ol className="m-0 p-0 list-none panel divide-y divide-line">
      {risks.map(({ ref, soWhat }, i) => {
        const f = ref.finding;
        return (
          <li key={f.fingerprint} className="grid grid-cols-[24px_1fr_auto] gap-3 items-baseline px-4 py-3">
            <span className="mono text-[12px] text-ink-muted tabular-nums">{i + 1}</span>
            <div className="min-w-0">
              <a href={buildHash("findings", f.fingerprint)} className="link text-[13.5px]">{soWhat}</a>
              <span className="caption"> {ref.agent ? agentLabel(ref.agent) : "repository"}</span>
            </div>
            <SeverityBadge severity={f.severity} />
          </li>
        );
      })}
    </ol>
  );
}
