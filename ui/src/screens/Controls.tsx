import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "../components/Badge";
import { Section } from "../components/Section";
import { definedIn } from "../data/agents";
import { COVERAGE_CONTROLS, SAFEGUARD_STATE_LABEL, controlLabel, recommendations, safeguardCoverage, safeguardRows, type SafeguardState } from "../data/controls";
import { pluralize } from "../data/selectors";

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
  const recommended = recommendations(envelope);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Controls & Safeguards</h1>
        <div className="caption">What the scan detected in the scanned sources. Detection is not proof that a safeguard works.</div>
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

      <Section title="Recommended controls to add" caption="Safeguards the scan looked for and did not find, most important first.">
        {recommended.length === 0 ? <p className="caption m-0">Nothing to add: every safeguard the scan looks for was detected.</p> : (
          <ol className="m-0 p-0 list-none panel divide-y divide-line">
            {recommended.map((rec, i) => (
              <li key={rec.ruleId} className="grid grid-cols-[28px_minmax(0,1fr)_auto] gap-x-3 items-start px-4 py-3.5">
                <span aria-hidden="true" className="num text-[18px] text-ink-muted leading-none pt-0.5">{i + 1}</span>
                <div className="min-w-0">
                  <div className="text-[14px] font-medium text-navy leading-snug">{rec.title}</div>
                  <div className="text-[13px] text-ink-soft mt-1">{rec.action}</div>
                  <a href={buildHash("findings", null, { rule: rec.ruleId })} className="link text-[12.5px] inline-block mt-1.5">{rec.agents === 1 ? "Affects 1 agent" : `Affects ${rec.agents} agents`}</a>
                </div>
                <SeverityBadge severity={rec.severity} />
              </li>
            ))}
          </ol>
        )}
      </Section>
    </div>
  );
}
