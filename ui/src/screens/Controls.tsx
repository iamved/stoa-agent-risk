import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "../components/Badge";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { definedIn } from "../data/agents";
import { COVERAGE_CONTROLS, SAFEGUARD_STATE_LABEL, controlLabel, gapGroups, safeguardCoverage, safeguardRows, safeguardTotals, type SafeguardState } from "../data/controls";
import { prose } from "../data/labels";
import { findingTitle, pluralize } from "../data/selectors";

const STATE_CLASS: Record<SafeguardState, string> = {
  detected: "border-navy/30 bg-navy-100 text-navy",
  not_detected: "border-line bg-paper text-ink-muted",
  not_applicable: "border-dashed border-line bg-transparent text-ink-muted",
};

/** Safeguards the scan detected, and where it looked for one and did not find it. */
export function Controls() {
  const { envelope } = useApp();
  const rows = safeguardRows(envelope);
  const coverage = safeguardCoverage(envelope);
  const gaps = gapGroups(envelope);
  const totals = safeguardTotals(envelope);
  const double = totals.doublePayment[0];

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Controls & Safeguards</h1>
        <div className="caption">What the scan detected in the scanned sources. Detection is not proof that a safeguard works.</div>
      </div>

      <div className={`mt-4 grid gap-3 ${double ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
        <StatCard icon="controls" label="Safeguards not detected where expected" value={totals.gaps} detail="Items to verify, not confirmed weaknesses." href={buildHash("findings", null, { rule: "CTRL" })} tone={totals.gaps ? "warn" : "neutral"} />
        <StatCard icon="loss" label="Tools that can move money with no guardrail detected" value={totals.moneyTools ? `${totals.moneyToolsWithoutGuardrail} of ${totals.moneyTools}` : "0"} detail={totals.moneyTools ? undefined : "No tool that can move money was found."} tone={totals.moneyToolsWithoutGuardrail ? "warn" : "neutral"} />
        {double ? <StatCard icon="flag" label="A payment can post twice on retry" value={totals.doublePayment.length} detail={findingTitle(envelope, double.finding)} href={buildHash("findings", double.finding.fingerprint)} tone="warn" /> : null}
      </div>

      <Section title="Safeguards detected" caption="Counted against the agents each safeguard is relevant to.">
        <div className="panel divide-y divide-line/70">
          {coverage.map((c) => {
            const pct = c.applicable ? Math.round((c.detected / c.applicable) * 100) : 0;
            const none = c.applicable > 0 && c.detected === 0;
            return (
              <div key={c.id} className="grid grid-cols-[minmax(170px,240px)_minmax(60px,1fr)_minmax(150px,auto)] items-center gap-4 px-5 py-2.5 text-[13px]">
                <span><span className="font-medium text-navy block">{c.label}</span>{c.subtitle ? <span className="caption block">{c.subtitle}</span> : null}</span>
                <span className="h-2.5 rounded-sm bg-line/50 overflow-hidden" aria-hidden="true"><span className="block h-full bg-navy" style={{ width: `${pct}%` }} /></span>
                <span className="text-right"><span className={`num text-[14px] ${none ? "text-sev-high" : "text-navy"}`}>{c.applicable ? `Detected on ${c.detected}` : "Not applicable"}</span>{c.applicable ? <span className="caption block">{c.denominator}</span> : <span className="caption block">no agent it is relevant to</span>}</span>
              </div>
            );
          })}
        </div>
      </Section>

      <Section title="By agent">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl">
            <thead><tr><th>Agent</th><th>Safeguards</th><th>Tool guardrails</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.agent.id}>
                  <td><a href={buildHash("inventory", r.agent.records[0]!.id)} className="link font-medium">{r.agent.name}</a><div className="caption">{definedIn(r.agent)}</div></td>
                  <td>
                    <ul className="m-0 p-0 list-none flex flex-wrap gap-1">
                      {COVERAGE_CONTROLS.filter((id) => r.states[id] !== "not_detected").map((id) => <li key={id} className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[11.5px] leading-none ${STATE_CLASS[r.states[id]!]}`}>{controlLabel(id)}{r.states[id] === "not_applicable" ? " · not applicable" : ""}</li>)}
                    </ul>
                    <div className="caption mt-1">{(() => { const missing = COVERAGE_CONTROLS.filter((id) => r.states[id] === "not_detected"); return missing.length ? `${SAFEGUARD_STATE_LABEL.not_detected}: ${missing.map(controlLabel).join(", ")}` : "Every safeguard detected."; })()}</div>
                  </td>
                  <td className="caption">
                    {r.tools.length === 0 ? "No tools bound." : `${r.toolsWithGuardrail} of ${pluralize(r.tools.length, "tool")} ${r.tools.length === 1 ? "has" : "have"} a guardrail detected`}
                    {r.moneyToolsWithoutGuardrail ? <div className="text-sev-high">{r.moneyToolsWithoutGuardrail} of {r.moneyTools} that can move money {r.moneyToolsWithoutGuardrail === 1 ? "has" : "have"} none</div> : null}
                    {r.retriesWithoutIdempotency ? <div className="text-sev-high">{r.retriesWithoutIdempotency} retried with no idempotency protection</div> : null}
                  </td>
                </tr>
              ))}
              {rows.length === 0 ? <tr><td colSpan={3} className="caption text-center">No agents in this scan.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Safeguards not detected" caption="The scan looked for a safeguard and did not find one. Items to verify, not confirmed weaknesses.">
        {gaps.length === 0 ? <p className="caption m-0">Nothing to verify: no expected safeguard was missing.</p> : (
          <ul className="m-0 p-0 list-none panel divide-y divide-line">
            {gaps.map((g) => (
              <li key={g.rule_id} className="p-3 text-[13px]">
                <div className="flex flex-wrap items-center gap-2"><SeverityBadge severity={g.worst} /><span className="font-medium">{g.title}</span><span className="mono caption">{g.rule_id}</span><span className="caption">{pluralize(g.refs.length, "finding")}</span></div>
                <p className="m-0 mt-1 caption">{prose(envelope.rules[g.rule_id]?.remediation)}</p>
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 caption">{g.refs.slice(0, 6).map((ref) => <a key={ref.finding.fingerprint} href={buildHash("findings", ref.finding.fingerprint)} className="link">{ref.uniqueAgents[0] ? `${ref.uniqueAgents[0].name} · ` : ""}<span className="mono">{ref.finding.path}:{ref.finding.line}</span></a>)}{g.refs.length > 6 ? <a className="link" href={buildHash("findings", null, { rule: g.rule_id })}>and {g.refs.length - 6} more</a> : null}</div>
              </li>
            ))}
          </ul>
        )}
      </Section>
    </div>
  );
}
