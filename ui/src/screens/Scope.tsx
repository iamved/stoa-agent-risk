import { useMemo, useState, type ReactNode } from "react";
import { useApp } from "../app/context";
import { buildHash, navigate, useRoute } from "../app/router";
import { AgentDrawer } from "../components/AgentDrawer";
import { Pill } from "../components/Badge";
import { Chips } from "../components/KeyValue";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { AUTONOMY_INTENTS, DATA_CLASSES, DEPENDENCY_LEVELS, EVIDENCE_CATEGORIES, POLICY_TYPES, PRODUCTION_STATUSES, SECTORS, SOCIETAL_FLAGS, USERS, completeness, isEqualScope, scopeFromEnvelope, toDeclaredToml, toUnderwritingToml, type AgentState, type ScopeState } from "../data/scope";
import { agentById } from "../data/selectors";

/** Declared Scope: the business context a person supplies, next to what the scan inferred. Editable; saves as the two files the scanner reads. */
export function Scope() {
  const { envelope } = useApp();
  const route = useRoute();
  const initial = useMemo(() => scopeFromEnvelope(envelope), [envelope]);
  const [state, setState] = useState<ScopeState>(initial);
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const dirty = !isEqualScope(state, initial);
  const done = completeness(state);
  const declaredToml = useMemo(() => toDeclaredToml(state, envelope.registry.risk_register ?? []), [state, envelope]);
  const underwritingToml = useMemo(() => toUnderwritingToml(state, envelope.assessment.performance), [state, envelope]);
  const selected = route.id ? agentById(envelope.registry, route.id) : null;
  const patch = (p: Partial<ScopeState>) => setState({ ...state, ...p });
  const patchAgent = (id: string, p: Partial<AgentState>) => setState({ ...state, agents: state.agents.map((a) => (a.id === id ? { ...a, ...p } : a)) });
  const copy = async (which: string, text: string) => {
    try { await navigator.clipboard.writeText(text); setCopied(which); } catch { setCopied(null); }
  };

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Declared Scope</h1>
        <div className="flex flex-wrap items-center gap-2 no-print">
          {dirty ? <button type="button" onClick={() => setState(initial)} className="btn">Reset</button> : null}
          <button type="button" onClick={() => setEditing(!editing)} aria-pressed={editing} className={`btn ${editing ? "chip-gold" : "btn-primary"}`}>{editing ? "Done editing" : "Edit business context"}</button>
        </div>
      </div>
      <p className="caption mt-1 mb-0">What your organization says about itself and its agents. The scan cannot know these; it cross-checks them against the code, and the loss outlook and the insurance assessment read them. Declarations are saved to the repository and reviewed like code.</p>

      <div className="mt-4 grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard label="Business context complete" value={`${done.pct}%`} detail={`${done.filled} of ${done.total} fields that change what Stoa can say`} tone={done.pct < 60 ? "warn" : "neutral"} />
        <StatCard label="Agents declared" value={state.agents.filter((a) => a.owner.trim() || a.autonomy_intent).length} detail={`of ${state.agents.length} scanned agents`} />
        <StatCard label="Money-moving agents with a limit" value={`${state.agents.filter((a) => a.moneyMover && a.max_per_action.trim()).length} / ${state.agents.filter((a) => a.moneyMover).length}`} detail="the scan checks each limit is enforced" tone={state.agents.some((a) => a.moneyMover && !a.max_per_action.trim()) ? "warn" : "neutral"} />
        <StatCard label="Current policies declared" value={state.policies.length} detail="feeds the outlook's gap analysis" />
      </div>

      {done.gaps.length ? (
        <div className="mt-3 panel px-4 py-3 text-[13px]">
          <div className="caption uppercase text-[11px] tracking-wide mb-1.5">Worth filling in next</div>
          <ul className="m-0 p-0 list-none flex flex-wrap gap-x-5 gap-y-1">
            {done.gaps.slice(0, 8).map((g, i) => <li key={i}><span className="font-medium">{g.section}: {g.label}</span> <span className="caption">({g.why})</span></li>)}
            {done.gaps.length > 8 ? <li className="caption">and {done.gaps.length - 8} more</li> : null}
          </ul>
        </div>
      ) : null}

      <Section title="Organization" caption="Industry, regulated activities and customer dependency. Attestation only; the scanner never scores these.">
        <div className="panel p-4 grid gap-4 md:grid-cols-2">
          <Field label="Industries" hint="comma separated, e.g. financial_services, payments" editing={editing} value={state.org.industries} onChange={(v) => patch({ org: { ...state.org, industries: v } })} />
          <Field label="Regulated activities" hint="comma separated, e.g. payments, consumer_banking" editing={editing} value={state.org.regulated_activities} onChange={(v) => patch({ org: { ...state.org, regulated_activities: v } })} />
          <Select label="Customer dependency" editing={editing} value={state.org.max_customer_dependency} options={DEPENDENCY_LEVELS} onChange={(v) => patch({ org: { ...state.org, max_customer_dependency: v } })} />
          <Multi label="Societal risk flags" editing={editing} values={state.org.societal_risk_flags} options={SOCIETAL_FLAGS} onChange={(v) => patch({ org: { ...state.org, societal_risk_flags: v } })} />
        </div>
      </Section>

      <Section title="Business context for the outlook and the assessment" caption="Revenue, records and current insurance drive the loss outlook; the applicant identity fills the assessment.">
        <div className="panel p-4 grid gap-4 md:grid-cols-3">
          <Field label="Annual revenue (USD)" editing={editing} value={state.intake.revenue} onChange={(v) => patch({ intake: { ...state.intake, revenue: v } })} />
          <Select label="Sector" editing={editing} value={state.intake.sector} options={SECTORS} onChange={(v) => patch({ intake: { ...state.intake, sector: v } })} />
          <Field label="Jurisdictions" hint="comma separated codes: US, EU, AU, CA" editing={editing} value={state.intake.jurisdictions} onChange={(v) => patch({ intake: { ...state.intake, jurisdictions: v } })} />
          <Field label="Personal records held" editing={editing} value={state.intake.records} onChange={(v) => patch({ intake: { ...state.intake, records: v } })} />
          <Field label="Agent actions per month" editing={editing} value={state.intake.monthly_action_volume} onChange={(v) => patch({ intake: { ...state.intake, monthly_action_volume: v } })} />
          <div className="flex flex-col gap-2 justify-end">
            <Toggle label="Regulated sector" editing={editing} checked={state.intake.regulated} onChange={(v) => patch({ intake: { ...state.intake, regulated: v } })} />
            <Toggle label="Serves minors" editing={editing} checked={state.intake.minors} onChange={(v) => patch({ intake: { ...state.intake, minors: v } })} />
          </div>
        </div>
        <div className="panel p-4 mt-3">
          <div className="flex items-center justify-between gap-2 mb-2"><h3 className="m-0">Current insurance</h3>{editing ? <button type="button" onClick={() => patch({ policies: [...state.policies, { type: "cyber", limit: "", ai_exclusion: false }] })} className="btn btn-sm">Add policy</button> : null}</div>
          {state.policies.length === 0 ? <p className="caption m-0">No current policies declared. The outlook treats every loss type as not insured today.</p> : (
            <table className="tbl"><thead><tr><th>Type</th><th>Limit (USD)</th><th>AI exclusion</th>{editing ? <th /> : null}</tr></thead><tbody>
              {state.policies.map((p, i) => (
                <tr key={i}>
                  <td>{editing ? <select value={p.type} onChange={(e) => patch({ policies: state.policies.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)) })} className="field" aria-label={`Policy ${i + 1} type`}>{POLICY_TYPES.map((t) => <option key={t} value={t}>{t === "tech_eo" ? "Tech E&O" : t === "cyber" ? "Cyber" : "Crime"}</option>)}</select> : (p.type === "tech_eo" ? "Tech E&O" : p.type === "cyber" ? "Cyber" : "Crime")}</td>
                  <td className="tabular-nums">{editing ? <input value={p.limit} onChange={(e) => patch({ policies: state.policies.map((x, j) => (j === i ? { ...x, limit: e.target.value } : x)) })} className="field w-40" aria-label={`Policy ${i + 1} limit`} /> : Number(p.limit).toLocaleString()}</td>
                  <td>{editing ? <input type="checkbox" checked={p.ai_exclusion} onChange={(e) => patch({ policies: state.policies.map((x, j) => (j === i ? { ...x, ai_exclusion: e.target.checked } : x)) })} aria-label={`Policy ${i + 1} AI exclusion`} /> : p.ai_exclusion ? <Pill tone="warn">AI exclusion</Pill> : <span className="caption">none</span>}</td>
                  {editing ? <td><button type="button" onClick={() => patch({ policies: state.policies.filter((_, j) => j !== i) })} className="btn btn-sm">Remove</button></td> : null}
                </tr>
              ))}
            </tbody></table>
          )}
        </div>
        <div className="panel p-4 mt-3 grid gap-4 md:grid-cols-3">
          <div className="md:col-span-3"><h3 className="m-0">Applicant</h3><div className="caption">Who signs the assessment.</div></div>
          {([["company", "Company"], ["contact_name", "Contact name"], ["contact_title", "Contact title"], ["contact_email", "Contact email"], ["address", "Address"], ["home_state", "Home state"], ["model_name", "Covered model"], ["model_version", "Model version"], ["deployment", "Deployment"]] as const).map(([k, label]) => (
            <Field key={k} label={label} editing={editing} value={state.identity[k]} onChange={(v) => patch({ identity: { ...state.identity, [k]: v } })} />
          ))}
        </div>
      </Section>

      <Section title="Agents" caption="Every scanned agent. Declared intent sits next to what the scan inferred; the scanner reports the difference as a finding on the Risk Dashboard.">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl">
            <thead><tr><th>Agent</th><th>Owner</th><th>Purpose</th><th>Users</th><th>Status</th><th>Intended autonomy</th><th>Inferred</th><th>Data classes</th><th>Max per action</th></tr></thead>
            <tbody>
              {state.agents.map((a) => (
                <tr key={a.id} data-clickable={editing ? undefined : "true"} tabIndex={editing ? -1 : 0} onClick={editing ? undefined : () => navigate("scope", a.id)} onKeyDown={editing ? undefined : (e) => { if (e.key === "Enter") navigate("scope", a.id); }}>
                  <td><div className="font-medium">{a.label}</div><div className="caption mono">{a.path}</div>{a.moneyMover ? <div className="mt-1"><Pill tone="warn">moves money</Pill></div> : null}</td>
                  <td>{editing ? <input value={a.owner} onChange={(e) => patchAgent(a.id, { owner: e.target.value })} className="field w-44" aria-label={`${a.label} owner`} placeholder="team or person" /> : a.owner || <span className="caption">not declared</span>}</td>
                  <td>{editing ? <input value={a.purpose} onChange={(e) => patchAgent(a.id, { purpose: e.target.value })} className="field w-56" aria-label={`${a.label} purpose`} /> : <span className="caption">{a.purpose || "not declared"}</span>}</td>
                  <td>{editing ? <select value={a.users} onChange={(e) => patchAgent(a.id, { users: e.target.value })} className="field" aria-label={`${a.label} users`}><option value="">unset</option>{USERS.map((u) => <option key={u} value={u}>{u}</option>)}</select> : a.users || <span className="caption">–</span>}</td>
                  <td>{editing ? <select value={a.production_status} onChange={(e) => patchAgent(a.id, { production_status: e.target.value })} className="field" aria-label={`${a.label} status`}><option value="">unset</option>{PRODUCTION_STATUSES.map((u) => <option key={u} value={u}>{u}</option>)}</select> : a.production_status || <span className="caption">–</span>}</td>
                  <td>{editing ? <select value={a.autonomy_intent} onChange={(e) => patchAgent(a.id, { autonomy_intent: e.target.value })} className="field" aria-label={`${a.label} intended autonomy`}><option value="">unset</option>{AUTONOMY_INTENTS.map((u) => <option key={u} value={u}>{u}</option>)}</select> : a.autonomy_intent || <span className="caption">–</span>}</td>
                  <td className="caption">{a.inferredAutonomy ?? "indeterminate"}</td>
                  <td>{editing ? <Multi label={`${a.label} data classes`} editing values={a.data_classes} options={DATA_CLASSES} onChange={(v) => patchAgent(a.id, { data_classes: v })} compact /> : <Chips items={a.data_classes.map((d) => ({ label: d }))} empty="–" />}</td>
                  <td className="tabular-nums">{editing ? <span className="flex items-center gap-1"><input value={a.max_per_action} onChange={(e) => patchAgent(a.id, { max_per_action: e.target.value })} className="field w-24" aria-label={`${a.label} max per action`} placeholder={a.moneyMover ? "required" : ""} /><input value={a.currency} onChange={(e) => patchAgent(a.id, { currency: e.target.value })} className="field w-16" aria-label={`${a.label} currency`} /></span> : a.max_per_action ? `${Number(a.max_per_action).toLocaleString()} ${a.currency}` : <span className={a.moneyMover ? "text-sev-high" : "caption"}>{a.moneyMover ? "missing" : "–"}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {editing ? <p className="caption mt-2 mb-0">Daily aggregate and worst-case customer loss can be set per agent in the generated file; the table edits the per-action limit the scanner enforces.</p> : null}
      </Section>

      <Section title="Governance" caption="Where release approval, incident response and harmful-output policy are documented.">
        <div className="panel p-4 grid gap-4 md:grid-cols-2">
          <Field label="Release approval" hint="e.g. Documented in RELEASING.md" editing={editing} value={state.gov.release_approval} onChange={(v) => patch({ gov: { ...state.gov, release_approval: v } })} />
          <Field label="Incident response" hint="e.g. runbooks/ir.md" editing={editing} value={state.gov.incident_response} onChange={(v) => patch({ gov: { ...state.gov, incident_response: v } })} />
          <Field label="Harmful-output policy" editing={editing} value={state.gov.harmful_output_policy} onChange={(v) => patch({ gov: { ...state.gov, harmful_output_policy: v } })} />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Risk acceptance owner" editing={editing} value={state.gov.risk_acceptance_owner} onChange={(v) => patch({ gov: { ...state.gov, risk_acceptance_owner: v } })} />
            <Field label="Accepted on" editing={editing} value={state.gov.risk_acceptance_date} onChange={(v) => patch({ gov: { ...state.gov, risk_acceptance_date: v } })} type="date" />
          </div>
        </div>
      </Section>

      <Section title="Evidence references" caption="Pointers to external artifacts: adversarial testing, monitoring, contracts, vendor reviews. Listed in the assurance packet, never verified by the scan." actions={editing ? <button type="button" onClick={() => patch({ evidence: [...state.evidence, { category: "testing", kind: "", ref: "", date: "" }] })} className="btn btn-sm">Add reference</button> : undefined}>
        {state.evidence.length === 0 ? <p className="caption m-0">None declared.</p> : (
          <div className="panel overflow-x-auto" tabIndex={0}><table className="tbl"><thead><tr><th>Category</th><th>Kind</th><th>Reference</th><th>Date</th>{editing ? <th /> : null}</tr></thead><tbody>
            {state.evidence.map((e, i) => (
              <tr key={i}>
                <td>{editing ? <select value={e.category} onChange={(ev) => patch({ evidence: state.evidence.map((x, j) => (j === i ? { ...x, category: ev.target.value } : x)) })} className="field" aria-label={`Evidence ${i + 1} category`}>{EVIDENCE_CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}</select> : e.category}</td>
                <td>{editing ? <input value={e.kind} onChange={(ev) => patch({ evidence: state.evidence.map((x, j) => (j === i ? { ...x, kind: ev.target.value } : x)) })} className="field" aria-label={`Evidence ${i + 1} kind`} /> : e.kind}</td>
                <td>{editing ? <input value={e.ref} onChange={(ev) => patch({ evidence: state.evidence.map((x, j) => (j === i ? { ...x, ref: ev.target.value } : x)) })} className="field w-64" aria-label={`Evidence ${i + 1} reference`} /> : <span className="mono">{e.ref}</span>}</td>
                <td>{editing ? <input type="date" value={e.date} onChange={(ev) => patch({ evidence: state.evidence.map((x, j) => (j === i ? { ...x, date: ev.target.value } : x)) })} className="field" aria-label={`Evidence ${i + 1} date`} /> : <span className="caption">{e.date || "–"}</span>}</td>
                {editing ? <td><button type="button" onClick={() => patch({ evidence: state.evidence.filter((_, j) => j !== i) })} className="btn btn-sm">Remove</button></td> : null}
              </tr>
            ))}
          </tbody></table></div>
        )}
      </Section>

      {editing || dirty ? (
        <Section title="Save to the repository" caption="This file cannot write to your repository. Commit these two files; the next scan cross-checks the declarations and pre-fills the outlook and the assessment from them.">
          <div className="grid gap-4 lg:grid-cols-2">
            <SaveBox name="stoa-declared.toml" text={declaredToml} copied={copied === "declared"} onCopy={() => copy("declared", declaredToml)} />
            <SaveBox name=".stoa/underwriting.toml" text={underwritingToml} copied={copied === "underwriting"} onCopy={() => copy("underwriting", underwritingToml)} />
          </div>
        </Section>
      ) : null}

      <AgentDrawer agent={selected} onClose={() => navigate("scope")} />
      <p className="caption mt-6">Need the ids? <a href={buildHash("inventory")} className="link">Agent Inventory</a> lists every scanned agent; <span className="mono">stoa init declarations</span> writes a stub with them filled in.</p>
    </div>
  );
}

function Field({ label, hint, editing, value, onChange, type = "text" }: { label: string; hint?: string; editing: boolean; value: string; onChange: (v: string) => void; type?: string }) {
  return (
    <label className="flex flex-col gap-1 text-[13px] min-w-0">
      <span className="caption">{label}</span>
      {editing ? <input type={type} value={value} onChange={(e) => onChange(e.target.value)} className="field" aria-label={label} placeholder={hint} /> : <span className={`min-w-0 break-words ${value ? "" : "caption"}`}>{value || "not declared"}</span>}
    </label>
  );
}
function Select({ label, editing, value, options, onChange }: { label: string; editing: boolean; value: string; options: readonly string[]; onChange: (v: string) => void }) {
  return (
    <label className="flex flex-col gap-1 text-[13px]">
      <span className="caption">{label}</span>
      {editing ? <select value={value} onChange={(e) => onChange(e.target.value)} className="field" aria-label={label}><option value="">unset</option>{options.map((o) => <option key={o} value={o}>{o}</option>)}</select> : <span className={value ? "" : "caption"}>{value || "not declared"}</span>}
    </label>
  );
}
function Multi({ label, editing, values, options, onChange, compact }: { label: string; editing: boolean; values: string[]; options: readonly string[]; onChange: (v: string[]) => void; compact?: boolean }) {
  if (!editing) return <div className="flex flex-col gap-1 text-[13px]"><span className="caption">{label}</span><Chips items={values.map((v) => ({ label: v }))} empty="none" /></div>;
  return (
    <fieldset className={`m-0 p-0 border-0 ${compact ? "" : "text-[13px]"}`} aria-label={label}>
      {!compact ? <legend className="caption mb-1">{label}</legend> : null}
      <div className={`flex flex-wrap ${compact ? "gap-x-2 gap-y-0.5 text-[12px]" : "gap-x-3 gap-y-1"}`}>
        {options.map((o) => <label key={o} className="flex items-center gap-1 whitespace-nowrap"><input type="checkbox" checked={values.includes(o)} onChange={(e) => onChange(e.target.checked ? [...values, o] : values.filter((v) => v !== o))} aria-label={`${label}: ${o}`} />{o}</label>)}
      </div>
    </fieldset>
  );
}
function Toggle({ label, editing, checked, onChange }: { label: string; editing: boolean; checked: boolean; onChange: (v: boolean) => void }) {
  return <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={checked} disabled={!editing} onChange={(e) => onChange(e.target.checked)} />{label}</label>;
}
function SaveBox({ name, text, copied, onCopy }: { name: string; text: string; copied: boolean; onCopy: () => void }): ReactNode {
  return (
    <div>
      <div className="flex items-center justify-between gap-2 mb-1.5"><span className="mono text-[12.5px]">{name}</span><button type="button" onClick={onCopy} className="btn btn-sm">{copied ? "Copied" : "Copy"}</button></div>
      <textarea readOnly value={text} rows={Math.min(28, text.split("\n").length + 1)} className="w-full rounded-md border border-line bg-panel p-3 mono text-[11.5px]" aria-label={`${name} contents`} onFocus={(e) => e.currentTarget.select()} />
    </div>
  );
}
