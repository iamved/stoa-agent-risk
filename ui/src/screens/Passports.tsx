import { useApp } from "../app/context";
import { buildHash, useRoute } from "../app/router";
import { ExposureBadge, Pill } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { Section } from "../components/Section";
import { dimensionLabel, EVIDENCE_LABEL } from "../data/labels";
import { formatDate, pluralize } from "../data/selectors";
import type { Passport } from "../data/types";

/** One passport per agent: identity, what it can do, how it reads, what protects it, what the traces showed, and how far to trust the page. */
export function Passports() {
  const { envelope } = useApp();
  const route = useRoute();
  const passports = envelope.passports ?? [];
  const selected = route.id ? passports.find((p) => p.agent.id === route.id || p.agent.name === route.id) ?? null : null;
  if (!passports.length) {
    return (
      <div>
        <h1 className="m-0 mb-3">Passports</h1>
        <EmptyState title="No passports in this scan">This page was built before passports existed; rebuild it with <span className="mono">stoa dashboard stoa-registry.json</span>.</EmptyState>
      </div>
    );
  }
  if (selected) return <PassportView passport={selected} />;
  const lapsed = passports.filter((p) => p.validity.status === "lapsed").length;
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
        <h1 className="m-0">Passports</h1>
        <div className="caption">{pluralize(passports.length, "agent")}{lapsed ? `, ${lapsed} lapsed` : ", all valid"} · {passports[0]!.validity.rule}</div>
      </div>
      <div className="panel overflow-x-auto mt-3" tabIndex={0}>
        <table className="tbl w-full">
          <thead><tr><th>Agent</th><th>Risk type</th><th>Owner</th><th>Policies</th><th>Observed</th><th>Evidence</th><th>Validity</th><th>Verify</th></tr></thead>
          <tbody>
            {passports.map((p) => (
              <tr key={p.agent.id}>
                <td><a href={buildHash("passports", p.agent.id)} className="link font-medium">{p.agent.name}</a><div className="caption">{p.agent.source === "iac" ? `on ${p.agent.platform ?? "infrastructure"}` : "in code"}</div></td>
                <td>{"primary" in p.risk_type && p.risk_type.primary ? <><Pill tone={p.risk_type.driver_exposure === "elevated" ? "warn" : "neutral"}>{p.risk_type.primary}</Pill><div className="caption">{p.risk_type.driver ? dimensionLabel(p.risk_type.driver) : "no exposure"}</div></> : <span className="caption">none</span>}</td>
                <td className="text-[12.5px]">{p.agent.owner ?? <span className="caption">not declared</span>}</td>
                <td className="tabular-nums">{p.policies.attached.length}{p.policies.attached.some((a) => a.enforced) ? <span className="caption"> ({p.policies.attached.filter((a) => a.enforced).length} enforced)</span> : null}</td>
                <td className="text-[12.5px]">{p.runtime ? `${p.runtime.span_count} spans` : <span className="caption">not yet</span>}</td>
                <td className="text-[12.5px]">{Object.entries(p.evidence_mix).filter(([, n]) => n).map(([l, n]) => `${n} ${l}`).join(", ")}</td>
                <td><span className={`chip chip-plain ${p.validity.status === "valid" ? "chip-ok" : "chip-critical"}`}>{p.validity.status}</span>{p.validity.reason ? <div className="caption">{p.validity.reason}</div> : p.validity.expires ? <div className="caption">to {formatDate(p.validity.expires)}</div> : null}</td>
                <td className="mono caption">{p.verify_hash}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PassportView({ passport: p }: { passport: Passport }) {
  const { envelope } = useApp();
  const company = envelope.assessment.identity.company.trim() || envelope.registry.repository.name;
  const rt = "primary" in p.risk_type ? p.risk_type : null;
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 no-print">
        <a href={buildHash("passports")} className="link text-[13px]">All passports</a>
        <button type="button" onClick={() => window.print()} className="btn btn-sm">Print</button>
      </div>
      <h1 className="m-0 mt-2">Agent passport: {p.agent.name}</h1>
      <div className="caption">{company} · scanned {formatDate(p.scan_date)} · registry {p.registry_hash} · stoa {p.scanner_version}</div>
      <section aria-label="Verdict" className="mt-3 rounded-sm bg-navy text-white px-5 py-4 text-[14.5px] leading-[1.5]">
        <strong className="text-[#e3c88a]">{rt?.primary ?? "No exposure"}</strong>{rt?.driver ? <> driven by {dimensionLabel(rt.driver).toLowerCase()} ({rt.driver_exposure}) · confidence {rt.confidence}</> : null} · passport <strong className="text-[#e3c88a]">{p.validity.status}</strong>{p.validity.reason ? ` (${p.validity.reason})` : ""}, {p.validity.rule}{p.validity.expires ? `, expires ${formatDate(p.validity.expires)}` : ""}
      </section>

      <Section title="Identity">
        <dl className="m-0 grid grid-cols-[160px_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
          {([["Owner", p.agent.owner], ["Purpose", p.agent.purpose], ["Status", p.agent.production_status], ["Users", p.agent.users], ["Declared autonomy", p.agent.declared_autonomy], ["Inferred autonomy", p.agent.inferred_autonomy], ["Defined in", p.agent.defined_in]] as [string, string | null][]).map(([k, v]) => <div key={k} className="contents"><dt className="text-ink-muted">{k}</dt><dd className={`m-0 ${k === "Defined in" ? "mono" : ""}`}>{v ?? <span className="caption">not declared</span>}</dd></div>)}
        </dl>
      </Section>

      <Section title="In plain words">
        <div className="text-[13.5px] flex flex-col gap-1">
          <p className="m-0">{p.explanation.can_do}</p><p className="m-0">{p.explanation.could_go_wrong}</p><p className="m-0">{p.explanation.protects}</p><p className="m-0">{p.explanation.missing}</p><p className="m-0 caption">{p.explanation.evidence}</p>
        </div>
      </Section>

      <Section title="Capabilities and reach" caption="Each capability says how it was established.">
        <div className="flex flex-wrap gap-1.5">{p.capabilities.length ? p.capabilities.map((c) => <span key={c.id} className="chip chip-plain">{c.id} <span className="text-ink-muted">{EVIDENCE_LABEL[c.evidence_level]?.toLowerCase() ?? c.evidence_level}</span></span>) : <span className="caption">none detected</span>}</div>
        <p className="caption mt-2 mb-0">Reachable from infrastructure: {p.reach.reachable.join(", ") || "none"} · observed at runtime: {p.reach.observed.join(", ") || "none"}</p>
      </Section>

      <Section title="Tools">
        {p.tools.length ? <div className="panel overflow-x-auto"><table className="tbl w-full"><thead><tr><th>Tool</th><th>Kind</th><th>Guardrails detected</th></tr></thead><tbody>{p.tools.map((t) => <tr key={t.name}><td className="mono text-[12px]">{t.name}</td><td>{t.money_action ? "money" : t.high_impact ? "high impact" : ""}</td><td>{t.guardrails.join(", ") || <span className="caption">none</span>}</td></tr>)}</tbody></table></div> : <p className="caption m-0">No tool definitions detected.</p>}
      </Section>

      <Section title="Exposure by category">
        <div className="panel overflow-x-auto"><table className="tbl w-full"><thead><tr><th>Category</th><th>Exposure</th><th>Score</th><th>Assessed from</th></tr></thead><tbody>{p.dimensions.map((d) => <tr key={d.id}><td>{dimensionLabel(d.id)}</td><td><ExposureBadge exposure={d.exposure} /></td><td className="tabular-nums">{d.score}</td><td className="text-[12.5px]">{d.assessability === "runtime" ? "traces" : d.assessability}</td></tr>)}</tbody></table></div>
      </Section>

      <Section title={`Policies${p.policies.mode ? ` (mode ${p.policies.mode})` : ""}`}>
        {p.policies.attached.length ? <div className="panel overflow-x-auto"><table className="tbl w-full"><thead><tr><th>Policy</th><th>Action</th><th>Condition</th><th>In the window</th></tr></thead><tbody>{p.policies.attached.map((a) => <tr key={a.id}><td><span className="mono text-[12px]">{a.id}</span><div className="caption">{a.title}</div></td><td>{a.action}{a.enforced ? <span className="chip chip-plain chip-critical ml-1.5">enforced</span> : null}</td><td className="mono text-[12px]">{a.condition}</td><td className="text-[12.5px]">{Object.entries(a.counts).filter(([, v]) => v).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ") || <span className="caption">not evaluated</span>}</td></tr>)}</tbody></table></div> : <p className="caption m-0">No policy scoped to this agent.</p>}
      </Section>

      <Section title="Runtime, drills and tests">
        <dl className="m-0 grid grid-cols-[160px_minmax(0,1fr)] gap-x-4 gap-y-1 text-[13px]">
          <div className="contents"><dt className="text-ink-muted">Observed</dt><dd className="m-0">{p.runtime ? `${p.runtime.span_count} spans, ${p.runtime.money_actions ?? 0} money actions, approval rate ${p.runtime.approval_rate_money ?? "n/a"}, ${formatDate(p.runtime.window?.start)} to ${formatDate(p.runtime.window?.end)}` : <span className="caption">nothing observed at runtime yet</span>}</dd></div>
          <div className="contents"><dt className="text-ink-muted">Safeguards detected</dt><dd className="m-0">{p.controls_observed.join(", ") || <span className="caption">none</span>}</dd></div>
          <div className="contents"><dt className="text-ink-muted">Kill switch drill</dt><dd className="m-0">{p.killswitch_drill?.seconds_to_stop !== null && p.killswitch_drill?.seconds_to_stop !== undefined ? `stopped in ${p.killswitch_drill.seconds_to_stop}s${p.killswitch_drill.by ? ` (${p.killswitch_drill.by})` : ""}` : <span className="caption">none recorded</span>}</dd></div>
          <div className="contents"><dt className="text-ink-muted">Policy test</dt><dd className="m-0">{p.policy_test ? `${p.policy_test.scenarios} scenarios, ${p.policy_test.matched} matched, ${p.policy_test.false_positives} false positives` : <span className="caption">none run</span>}</dd></div>
          <div className="contents"><dt className="text-ink-muted">Drift</dt><dd className="m-0">{p.drift.status}{p.drift.severity ? ` · ${p.drift.severity}` : ""} · {p.drift.detail}</dd></div>
          <div className="contents"><dt className="text-ink-muted">Evidence</dt><dd className="m-0">{Object.entries(p.evidence_mix).filter(([, n]) => n).map(([l, n]) => `${n} ${l}`).join(", ") || "none"}</dd></div>
        </dl>
        <p className="caption mt-3 mb-0">Verify hash {p.verify_hash}. Generated from registry {p.registry_hash}; the hash changes when the registry changes.</p>
      </Section>
    </div>
  );
}
