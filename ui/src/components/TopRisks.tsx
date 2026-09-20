import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "./Badge";
import { agentLabel, initials, topRisks } from "../data/selectors";

/** The five findings to read first, each as a plain-English sentence. */
export function TopRisks() {
  const { envelope } = useApp();
  const risks = topRisks(envelope, 5);
  return (
    <div className="panel h-full">
      <div className="px-5 pt-4 pb-3">
        <h2 className="m-0">Top findings</h2>
        <div className="caption">Highest risk first. Click one for the evidence and the fix.</div>
      </div>
      {!risks.length ? <p className="caption px-5 pb-4 m-0">No open findings.</p> : (
        <ol className="m-0 p-0 list-none divide-y divide-line/70">
          {risks.map(({ ref, soWhat }) => {
            const f = ref.finding;
            const who = ref.agent ? agentLabel(ref.agent) : "repository";
            return (
              <li key={f.fingerprint}>
                <a href={buildHash("findings", f.fingerprint)} className="grid grid-cols-[26px_1fr_auto] gap-3 items-start px-5 py-3 no-underline text-ink hover:bg-paper/70">
                  <span className="avatar mt-0.5" aria-hidden="true">{initials(who)}</span>
                  <span className="min-w-0">
                    <span className="block text-[13.5px] leading-snug text-navy">{soWhat}</span>
                    <span className="caption">{who}</span>
                  </span>
                  <SeverityBadge severity={f.severity} />
                </a>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
