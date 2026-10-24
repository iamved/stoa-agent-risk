import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { Pill } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { Section } from "../components/Section";
import { dimensionLabel } from "../data/labels";
import { money } from "../data/lossModel";
import { ACTION_LABEL, OUTCOME_LABEL, policyEvents, policyMode, policyRows, policyTotals, unprotectedEdges } from "../data/policies";
import { runtimeSlot, runtimeWindow } from "../data/runtime";
import { formatDate, pluralize } from "../data/selectors";

/** The policy file the repository carries, what each policy did in the trace window, and which money edges have none. */
export function Policies() {
  const { envelope } = useApp();
  const block = runtimeSlot(envelope)?.policies ?? null;
  const rows = policyRows(envelope);
  if (!block || !rows.length) {
    return (
      <div>
        <h1 className="m-0 mb-3">Policies</h1>
        <EmptyState title="No policy file in this scan">Write one from the scan with <span className="mono">stoa policy recommend --registry stoa-registry.json</span>, then build the page with <span className="mono">--runtime stoa-traces</span> so the outcomes show here.</EmptyState>
      </div>
    );
  }
  const mode = policyMode(envelope);
  const totals = policyTotals(envelope);
  const window = runtimeWindow(envelope);
  const events = policyEvents(envelope);
  const unprotected = unprotectedEdges(envelope);
  const drills = block.killswitch_drills ?? [];
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
        <h1 className="m-0">Policies</h1>
        <div className="caption">{block.document ? <span className="mono">{block.document.path}</span> : "no policy file"}{mode ? <> · mode <strong className="text-navy">{mode}</strong></> : null}{window ? <> · outcomes {formatDate(window.start)} to {formatDate(window.end)}</> : null}</div>
      </div>
      <p className="m-0 mb-4 text-[13px] text-ink-soft">{pluralize(totals.policies, "policy", "policies")}, {totals.enforced} enforced. In the window: <strong className="text-navy">{totals.blocked} blocked</strong>, {totals.would_block} would block, {totals.escalated} escalated, {totals.masked} masked.</p>
      {block.document?.problems.length ? <p className="m-0 mb-4 text-[13px] text-sev-high">{pluralize(block.document.problems.length, "problem")} in the policy file: {block.document.problems.map((p) => `${p.at}: ${p.message}`).join("; ")}</p> : null}

      <Section title="Policies" caption="Observe records what would happen; enforce changes it. Block and escalate are enforced only when fail is closed under enforce, or the policy says enforce.">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl w-full">
            <thead><tr><th>Policy</th><th>Applies to</th><th>Condition</th><th>Action</th><th>Mode</th><th className="text-right">Evaluated</th><th className="text-right">Blocked</th><th className="text-right">Would block</th><th className="text-right">Escalated</th><th>Maps to</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td title={r.rationale || undefined}><div className="font-medium text-navy mono text-[12px]">{r.id}</div><div className="text-[12.5px]">{r.title}</div></td>
                  <td className="text-[12.5px]">{r.scope.agent === "*" ? "every agent" : r.agents[0] ? <a href={buildHash("inventory", r.agents[0].id)} className="link">{r.agents[0].name}</a> : r.scope.agent}{r.scope.tool ? <div className="mono caption">{r.scope.tool}</div> : null}<div className="caption">{r.trigger === "any" ? "any step" : r.trigger.replace("_", " ")}</div></td>
                  <td className="mono text-[12px] max-w-[30ch]">{r.condition_text}</td>
                  <td><Pill tone={r.action === "block" ? "warn" : r.action === "escalate" ? "gold" : "neutral"}>{ACTION_LABEL[r.action] ?? r.action}</Pill></td>
                  <td className="text-[12.5px]">{r.enforced ? <span className="chip chip-plain chip-critical">enforced</span> : <span className="chip chip-plain chip-muted">observe</span>}</td>
                  <td className="tabular-nums text-right">{r.counts?.evaluated ?? <span className="text-ink-muted">·</span>}</td>
                  <td className={`tabular-nums text-right ${r.counts?.blocked ? "text-sev-critical font-medium" : ""}`}>{r.counts?.blocked ?? <span className="text-ink-muted">·</span>}</td>
                  <td className={`tabular-nums text-right ${r.counts?.would_block ? "text-sev-high font-medium" : ""}`}>{r.counts?.would_block ?? <span className="text-ink-muted">·</span>}</td>
                  <td className="tabular-nums text-right">{r.counts?.escalated ?? <span className="text-ink-muted">·</span>}</td>
                  <td className="text-[12px] text-ink-soft">{r.maps_to?.dimension ? dimensionLabel(r.maps_to.dimension) : ""}{r.maps_to?.owasp_llm ? <div className="caption">OWASP {r.maps_to.owasp_llm}{r.maps_to.eu_ai_act ? ` · EU AI Act ${r.maps_to.eu_ai_act}` : ""}</div> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Unprotected money and high-impact tools" caption="Tools that can move money or change systems with no block or escalate policy scoped to them.">
        {unprotected.length ? (
          <ul className="panel m-0 p-0 list-none divide-y divide-line/70">
            {unprotected.map((e) => <li key={`${e.agent.id}:${e.tool}`} className="flex flex-wrap items-baseline gap-x-3 px-4 py-2.5 text-[13px]"><a href={buildHash("inventory", e.agent.id)} className="link font-medium">{e.agent.name}</a><span className="mono">{e.tool}</span><span className="caption">{e.why}</span></li>)}
          </ul>
        ) : <EmptyState title="Every money-moving and high-impact tool has a block or escalate policy">Nothing to add from the scan.</EmptyState>}
      </Section>

      <Section title="Decisions in the window" caption="Every call a policy blocked, would have blocked, escalated or masked, newest first. Each points at a span.">
        {events.length ? (
          <div className="panel overflow-x-auto" tabIndex={0}>
            <table className="tbl w-full">
              <thead><tr><th>When</th><th>Agent</th><th>Tool</th><th>Amount</th><th>Policy</th><th>Outcome</th><th>Span</th></tr></thead>
              <tbody>
                {events.map((e, i) => (
                  <tr key={i}>
                    <td className="tabular-nums text-[12.5px]">{e.ts ? `${formatDate(e.ts)} ${e.ts.slice(11, 16)}` : ""}</td>
                    <td>{e.agent}</td>
                    <td className="mono text-[12px]">{e.tool ?? ""}</td>
                    <td className="tabular-nums">{e.amount ? money(e.amount.amount) : ""}</td>
                    <td className="mono text-[12px]">{e.policy_id}</td>
                    <td><span className={`chip chip-plain ${e.outcome === "blocked" ? "chip-critical" : e.outcome === "would_block" ? "chip-high" : e.outcome === "escalated" ? "chip-medium" : "chip-muted"}`}>{OUTCOME_LABEL[e.outcome] ?? e.outcome}</span></td>
                    <td className="mono caption">{e.trace_ref.file}:{e.trace_ref.line}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No decision changed a call in the window">Every evaluated policy allowed or only logged.</EmptyState>}
      </Section>

      <Section title="Kill switch drills" caption="Set the flag, time the first blocked call, release. The time is evidence that the switch works.">
        {drills.length ? (
          <ul className="panel m-0 p-0 list-none divide-y divide-line/70">
            {drills.map((d, i) => <li key={i} className="flex flex-wrap items-baseline gap-x-3 px-4 py-2.5 text-[13px]"><span className="tabular-nums">{d.ts ? formatDate(d.ts) : ""}</span><span className="font-medium text-navy">{d.seconds_to_stop !== null && d.seconds_to_stop !== undefined ? `stopped in ${d.seconds_to_stop}s` : "did not stop before the timeout"}</span>{d.by ? <span className="caption">by {d.by}</span> : null}</li>)}
          </ul>
        ) : <EmptyState title="No drill recorded">Run <span className="mono">stoa kill --drill --agent-id NAME</span> while the agent is running.</EmptyState>}
      </Section>
    </div>
  );
}
