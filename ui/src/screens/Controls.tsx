import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "../components/Badge";
import { Chips } from "../components/KeyValue";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { agentControlRows, controlLabel, coverage, gapGroups } from "../data/controls";
import { agentLabel, pluralize } from "../data/selectors";

/** Safeguards the scanner saw, and where it looked for one and found none. */
export function Controls() {
  const { envelope } = useApp();
  const rows = agentControlRows(envelope);
  const cov = coverage(envelope);
  const gaps = gapGroups(envelope);
  const gapCount = gaps.reduce((n, g) => n + g.refs.length, 0);
  const withApproval = rows.filter((r) => r.observed.includes("approval")).length;
  const unguarded = rows.reduce((n, r) => n + r.toolsWithoutGuards, 0);
  const retries = rows.reduce((n, r) => n + r.retriesWithoutIdempotency, 0);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Controls & Safeguards</h1>
        <div className="caption">A control is credited when the scanner observes it in code or infrastructure. Observed is not verified; none observed is not absent.</div>
      </div>

      <div className="mt-4 grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard label="Agents with an approval control" value={`${withApproval} / ${rows.length}`} detail="human approval construct observed" tone={withApproval < rows.length ? "warn" : "neutral"} />
        <StatCard label="Control gaps" value={gapCount} detail="control-family findings (CTRL, AI003, AI007, AI008)" href={buildHash("findings", null, { rule: "CTRL" })} tone={gapCount ? "warn" : "neutral"} />
        <StatCard label="High-impact tools without guards" value={unguarded} detail="money or high-impact tools with no numeric guard" tone={unguarded ? "warn" : "neutral"} />
        <StatCard label="Retries without idempotency" value={retries} detail="a retried money action can post twice" tone={retries ? "warn" : "neutral"} />
      </div>

      <Section title="Control coverage" caption="How many agents show each safeguard at least once.">
        <div className="panel p-3 grid gap-2 md:grid-cols-2">
          {cov.map((c) => {
            const pct = c.total ? Math.round((c.agents / c.total) * 100) : 0;
            return (
              <div key={c.id} className="grid grid-cols-[minmax(140px,1fr)_2fr_60px] items-center gap-3 text-[13px]">
                <span>{c.label}</span>
                <span className="h-2 rounded-full bg-paper border border-line overflow-hidden" aria-hidden="true"><span className="block h-full bg-gold" style={{ width: `${pct}%` }} /></span>
                <span className="tabular-nums caption text-right">{c.agents} / {c.total}</span>
              </div>
            );
          })}
        </div>
      </Section>

      <Section title="By agent" caption="Observed controls and tool guards per agent.">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl">
            <thead><tr><th>Agent</th><th>Controls observed</th><th>Tool guards</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.agent.id}>
                  <td><a href={buildHash("inventory", r.agent.id)} className="link font-medium">{r.name}</a><div className="caption mono">{r.agent.path}</div></td>
                  <td><Chips items={r.observed.map((c) => ({ label: controlLabel(c) }))} empty="none observed" /></td>
                  <td className="caption">
                    {(r.agent.tools ?? []).length === 0 ? "no tools bound" : `${r.toolGuards} of ${(r.agent.tools ?? []).length} tools guarded`}
                    {r.toolsWithoutGuards ? <div className="text-sev-high">{r.toolsWithoutGuards} high-impact without a guard</div> : null}
                    {r.retriesWithoutIdempotency ? <div className="text-sev-high">{r.retriesWithoutIdempotency} retried without idempotency key</div> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Gaps by rule" caption="Each is a review prompt, not a proven weakness: the scanner looked for a control and did not observe one.">
        {gaps.length === 0 ? <p className="caption m-0">No control gaps reported.</p> : (
          <ul className="m-0 p-0 list-none panel divide-y divide-line">
            {gaps.map((g) => (
              <li key={g.rule_id} className="p-3 text-[13px]">
                <div className="flex flex-wrap items-center gap-2"><SeverityBadge severity={g.worst} /><span className="mono">{g.rule_id}</span><span className="font-medium">{g.title}</span><span className="caption">{pluralize(g.refs.length, "finding")}</span></div>
                <p className="m-0 mt-1 caption">{g.refs[0]?.finding.crosswalk?.so_what ?? envelope.rules[g.rule_id]?.remediation}</p>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 caption">{g.refs.slice(0, 6).map((ref) => <a key={ref.finding.fingerprint} href={buildHash("findings", ref.finding.fingerprint)} className="link mono">{ref.agent ? `${agentLabel(ref.agent)} · ` : ""}{ref.finding.path}:{ref.finding.line}</a>)}{g.refs.length > 6 ? <span>and {g.refs.length - 6} more</span> : null}</div>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
