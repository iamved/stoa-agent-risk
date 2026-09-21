import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { printAs } from "../app/print";
import { AssessabilityBadge, ExposureBadge, Pill, SeverityBadge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { Chips } from "../components/KeyValue";
import { Section } from "../components/Section";
import { STATUS_LABEL, STATUS_ORDER, areaSummaries, controlsByAgent, packetTotals, type AreaSummary, type Status } from "../data/evidence";
import { changes } from "../data/drift";
import { agentLabel, dimensionMatrix, formatDate, initials, pluralize } from "../data/selectors";
import type { AssessmentField, AssessmentIdentity, AssessmentSource } from "../data/types";
import { EVENTS, indicate, money as fmtMoney } from "../data/lossModel";
import { agentToModel, candidateAgents, intakeFromEnvelope } from "../data/lossInputs";

const IDENTITY_FIELDS: { key: keyof AssessmentIdentity; label: string }[] = [
  { key: "company", label: "Applicant company" },
  { key: "address", label: "Address" },
  { key: "contact_name", label: "Contact name" },
  { key: "contact_title", label: "Contact title" },
  { key: "contact_email", label: "Contact email" },
  { key: "home_state", label: "Home state" },
  { key: "model_name", label: "Covered model" },
  { key: "model_version", label: "Model version" },
  { key: "deployment", label: "Deployment" },
  { key: "currency", label: "Currency" },
];
const SCHEDULE_TERMS = ["policy_limit", "sublimit_own_losses", "sublimit_consequential", "aggregate_deductible", "co_insurance", "coverage_trigger"] as const;
type PerfRow = { metric: string; value: string; cadence: string };

function tomlString(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n")}"`;
}

/** The .stoa/underwriting.toml that reproduces the edited form on the next scan. */
function toToml(identity: AssessmentIdentity, performance: PerfRow[], schedule: Record<string, string>, carrier: string, product: string): string {
  const lines: string[] = ["# .stoa/underwriting.toml — applicant identity, measured figures, and agreed schedule terms.", "", "[identity]"];
  for (const f of IDENTITY_FIELDS) lines.push(`${f.key.padEnd(14)} = ${tomlString(identity[f.key])}`);
  for (const row of performance) {
    if (!row.metric.trim()) continue;
    lines.push("", "[[performance]]", `metric  = ${tomlString(row.metric)}`, `value   = ${tomlString(row.value)}`, `cadence = ${tomlString(row.cadence)}`);
  }
  const declared = SCHEDULE_TERMS.filter((k) => schedule[k]);
  if (declared.length || carrier || product) {
    lines.push("", "[schedule]");
    if (carrier) lines.push(`carrier                = ${tomlString(carrier)}`);
    if (product) lines.push(`product                = ${tomlString(product)}`);
    for (const k of declared) lines.push(`${k.padEnd(22)} = ${tomlString(schedule[k] ?? "")}`);
  }
  return lines.join("\n") + "\n";
}

function generalRows(identity: AssessmentIdentity, source: AssessmentSource, edited: Set<string>): AssessmentField[] {
  const tbc = (v: string) => v || "To be confirmed";
  const contact = [identity.contact_name, identity.contact_title].filter(Boolean).join(", ");
  const model = identity.model_name + (identity.model_version ? ` (v${identity.model_version})` : "");
  const src = (keys: string[]): AssessmentSource => (keys.some((k) => edited.has(k)) ? "applicant" : source);
  return [
    { key: "company", label: "Applicant company", value: tbc(identity.company), source: src(["company"]), note: "" },
    { key: "address", label: "Address", value: tbc(identity.address), source: src(["address"]), note: "" },
    { key: "contact", label: "Contact", value: tbc(contact), source: src(["contact_name", "contact_title"]), note: "" },
    { key: "contact_email", label: "Contact email", value: tbc(identity.contact_email), source: src(["contact_email"]), note: "" },
    { key: "home_state", label: "Home state", value: tbc(identity.home_state), source: src(["home_state"]), note: "" },
    { key: "model", label: "Covered model", value: tbc(model), source: src(["model_name", "model_version"]), note: "" },
    { key: "deployment", label: "Deployment", value: tbc(identity.deployment), source: src(["deployment"]), note: "" },
  ];
}

const SOURCE_LABEL: Record<AssessmentSource, string> = {
  scan: "from scan",
  declared: "declared",
  applicant: "applicant",
  sample: "to confirm",
  indicative: "indicative",
};
const SOURCE_CLASS: Record<AssessmentSource, string> = {
  scan: "chip-ok",
  declared: "chip-info",
  applicant: "chip-info",
  sample: "chip-medium",
  indicative: "chip-muted chip-dashed",
};

function SourceChip({ source }: { source: AssessmentSource }) {
  return <span className={`chip chip-plain ${SOURCE_CLASS[source]}`}>{SOURCE_LABEL[source]}</span>;
}

/** The AI Risk Insurance page. With no agents there is nothing to insure, so no form is offered for signature. */
export function Evidence() {
  const { envelope } = useApp();
  if (envelope.registry.agents.length > 0) return <Assessment />;
  return (
    <div>
      <h1 className="m-0">AI Risk Insurance</h1>
      <div className="mt-5">
        <EmptyState title="No agents to assess">
          This scan found no AI agents in <span className="mono">{envelope.registry.repository.name}</span>, so there is no assessment to pre-fill or sign. If you expected agents here, check <span className="mono">include_extensions</span> and <span className="mono">ignore_paths</span> in <span className="mono">stoa.toml</span>, and <span className="mono">.stoaignore</span>, then scan again.
        </EmptyState>
      </div>
    </div>
  );
}

/** The pre-filled assessment as it would be submitted, the schedule, and the evidence behind it. */
function Assessment() {
  const { envelope } = useApp();
  const a = envelope.assessment;
  const r = envelope.registry;
  const head = r.repository.head_commit;
  const [copied, setCopied] = useState<"idle" | "done" | "manual">("idle");
  const transfers = envelope.register.filter((row) => row.declared?.treatment === "transfer");

  // Editable parts: identity, performance figures, schedule terms. Scan-derived
  // answers are evidence and stay read-only. Edits live in memory; the TOML
  // snippet is how they get back into the repository.
  const [editing, setEditing] = useState(false);
  const [identity, setIdentity] = useState<AssessmentIdentity>(a.identity);
  const [performance, setPerformance] = useState<PerfRow[]>(a.performance.map((r) => ({ metric: r.metric, value: r.value, cadence: r.cadence })));
  const initialSchedule = useMemo(() => Object.fromEntries(a.schedule.filter((f) => (SCHEDULE_TERMS as readonly string[]).includes(f.key)).map((f) => [f.key, f.value])) as Record<string, string>, [a.schedule]);
  const [schedule, setSchedule] = useState<Record<string, string>>(initialSchedule);
  const [carrier, setCarrier] = useState(a.carrier);
  const [product, setProduct] = useState(a.product);
  const [tomlCopied, setTomlCopied] = useState(false);
  const editedIdentity = new Set(IDENTITY_FIELDS.filter((f) => identity[f.key] !== a.identity[f.key]).map((f) => f.key as string));
  const editedSchedule = new Set(SCHEDULE_TERMS.filter((k) => (schedule[k] ?? "") !== (initialSchedule[k] ?? "")));
  const performanceEdited = JSON.stringify(performance) !== JSON.stringify(a.performance.map((r) => ({ metric: r.metric, value: r.value, cadence: r.cadence })));
  const anyEdit = editedIdentity.size > 0 || editedSchedule.size > 0 || performanceEdited || carrier !== a.carrier || product !== a.product;
  const general = generalRows(identity, a.identity_source, editedIdentity);
  // The loss outlook's suggested limit and retention fill indicative schedule
  // terms when business context is declared; declared or edited terms win.
  const outlook = useMemo(() => {
    const { intake, monthlyVolume, declared } = intakeFromEnvelope(envelope);
    const agent = candidateAgents(envelope)[0];
    if (!declared || !agent) return null;
    const { model } = agentToModel(envelope, agent, monthlyVolume);
    const r = indicate(EVENTS, model, intake, 42, {}, { years: 20000, noBoot: true });
    return { limit: fmtMoney(r.limits.standard), retention: fmtMoney(r.retention), agent: model.name, confidence: r.confidence };
  }, [envelope]);
  const outlookValue: Record<string, string> = outlook ? { policy_limit: outlook.limit, sublimit_own_losses: outlook.limit, aggregate_deductible: outlook.retention } : {};
  const scheduleRows: AssessmentField[] = a.schedule.map((f) => {
    if (!(SCHEDULE_TERMS as readonly string[]).includes(f.key)) return f;
    const edited = editedSchedule.has(f.key as (typeof SCHEDULE_TERMS)[number]);
    if (edited) return { ...f, value: schedule[f.key] ?? f.value, source: "declared" };
    if (f.source === "indicative" && outlookValue[f.key]) return { ...f, value: outlookValue[f.key]!, note: `from the loss outlook for ${outlook!.agent} (${outlook!.confidence} confidence)` };
    return { ...f, value: schedule[f.key] ?? f.value };
  });
  const scheduleDeclared = a.schedule_source === "declared" || editedSchedule.size > 0;
  const prefilled = a.counts.prefilled + editedIdentity.size + editedSchedule.size;
  const pct = a.counts.total ? Math.min(100, Math.round((prefilled / a.counts.total) * 100)) : 0;
  const toml = toToml(identity, performance, schedule, carrier, product);
  const copyToml = async () => {
    try {
      await navigator.clipboard.writeText(toml);
      setTomlCopied(true);
    } catch {
      setTomlCopied(false);
    }
  };
  const reset = () => {
    setIdentity(a.identity);
    setPerformance(a.performance.map((r) => ({ metric: r.metric, value: r.value, cadence: r.cadence })));
    setSchedule(initialSchedule);
    setCarrier(a.carrier);
    setProduct(a.product);
  };

  const json = useMemo(() => JSON.stringify(envelope.registry, null, 2), [envelope.registry]);
  const copyJson = async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied("done");
    } catch {
      setCopied("manual");
    }
  };
  const downloadHref = useMemo(() => `data:application/json;charset=utf-8,${encodeURIComponent(json)}`, [json]);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 no-pack">
        <h1 className="m-0">AI Risk Insurance</h1>
        <div className="flex flex-wrap items-center gap-2 no-print">
          <button type="button" onClick={() => setEditing(!editing)} aria-pressed={editing} className={`btn ${editing ? "chip-gold" : ""}`}>{editing ? "Done editing" : "Edit assessment"}</button>
          <button type="button" onClick={() => printAs("pack")} className="btn btn-primary">Print assessment (PDF)</button>
          <button type="button" onClick={() => printAs("summary")} className="btn">Print summary</button>
          <a href={downloadHref} download="stoa-registry.json" className="btn">Download report JSON</a>
          <button type="button" onClick={copyJson} className="btn">{copied === "done" ? "Copied" : "Copy JSON"}</button>
        </div>
      </div>
      <p className="caption mt-1 mb-0 no-pack">
        Your {carrier} {product} assessment, pre-filled from the scan. {carrier} prices and issues.
        {copied === "manual" ? " Clipboard access was blocked in this viewer; use Download instead." : ""}
      </p>

      <div className="screen-view">
        <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_320px] items-start">
          <div className="panel p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="eyebrow">Readiness</div>
                <div className="num text-[28px] text-navy leading-none mt-1">{pct}% pre-filled</div>
                <div className="caption mt-1">{prefilled} of {a.counts.total} fields come from the scan or your declarations. {Math.max(0, a.counts.to_confirm - editedIdentity.size)} still need your confirmation; {Math.max(0, a.counts.indicative - editedSchedule.size)} schedule terms are indicative until agreed.</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="h-2 w-40 rounded-full bg-paper border border-line overflow-hidden" aria-hidden="true"><span className="block h-full bg-gold" style={{ width: `${pct}%` }} /></span>
              </div>
            </div>
            <ol className="m-0 mt-4 p-0 list-none grid gap-3 md:grid-cols-4">
              <Step n={1} title="Review the pre-filled evidence" body="Every technical answer below points at scan evidence. Nothing is typed by hand." done />
              <Step n={2} title="Confirm identity and performance" body={a.performance_source === "applicant" && !anyEdit ? "Identity and performance figures were supplied in .stoa/underwriting.toml." : "Use Edit assessment, then save the config snippet to .stoa/underwriting.toml."} done={a.performance_source === "applicant" && a.identity_source === "applicant"} />
              <Step n={3} title="Sign the declaration" body="Print the assessment; the signature block is on the last page." />
              <Step n={4} title={`Submit to ${carrier}`} body={`Send the signed PDF and the evidence pack to your ${carrier} ${product} contact. ${carrier} sets the final terms.`} />
            </ol>
          </div>
          <div className="rounded-lg border border-navy bg-navy text-white p-5">
            <div className="text-[11px] uppercase tracking-[0.08em] text-white/70">Risks marked for transfer</div>
            <div className="num text-[28px] leading-none mt-1 text-gold">{transfers.length}</div>
            <div className="text-[12.5px] text-white/75 mt-2">
              {transfers.length ? transfers.map((t) => `${t.dimension_name} · ${t.agent_name ?? t.agent_id}`).join("; ") : "No register row has treatment = transfer yet. Mark one on the risk register to include it here."}
            </div>
            <a href={buildHash("register")} className="inline-block mt-3 text-[12.5px] text-gold underline underline-offset-2">Open the risk register</a>
          </div>
        </div>
      </div>

      <div className="screen-view">
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <div className="panel p-5 flex flex-col gap-2">
            <div className="eyebrow">Ready to proceed</div>
            <h2 className="m-0">Sign the assessment</h2>
            <p className="caption m-0">Print it, sign the declaration on the last page, and send it to {carrier}. {a.counts.to_confirm - editedIdentity.size > 0 ? `${a.counts.to_confirm - editedIdentity.size} fields still say To confirm; review them first.` : "Every field is filled."}</p>
            <div className="mt-auto pt-2 flex flex-wrap gap-2">
              <button type="button" onClick={() => printAs("pack")} className="btn btn-primary">Print and sign</button>
              {a.advisor.submit_email ? <a href={`mailto:${a.advisor.submit_email}?subject=${encodeURIComponent(`${product} assessment: ${identity.company || a.repository}`)}`} className="btn">Email the signed assessment</a> : null}
            </div>
          </div>
          <div className="panel p-5 flex flex-col gap-2">
            <div className="eyebrow">Not sure yet</div>
            <h2 className="m-0">Talk to a Stoa advisor</h2>
            <p className="caption m-0">A short call to walk through the assessment, the loss outlook, and what {carrier} will ask for. Stoa prepares the evidence; {carrier} prices and issues.</p>
            <div className="mt-auto pt-2 flex flex-wrap gap-2">
              <a href={a.advisor.url} target="_blank" rel="noreferrer" className="btn btn-primary">Schedule a call</a>
              {a.advisor.email ? <a href={`mailto:${a.advisor.email}?subject=${encodeURIComponent(`AI risk insurance: ${identity.company || a.repository}`)}`} className="btn">Email an advisor</a> : null}
            </div>
          </div>
        </div>
      </div>

      {/* The assessment document. Shown on screen and printed by "Print assessment". */}
      <div className="print-pack-doc mt-6">
        <div className="panel max-w-[880px] mx-auto px-8 py-7 assessment">
          <div className="flex items-end justify-between gap-4 border-b-2 border-navy pb-3">
            <div>
              <div className="text-[18px] font-semibold text-navy">{product}™ — {a.template}</div>
              <div className="caption mt-0.5">Pre-filled by Stoa from a static scan of <strong>{a.repository}</strong>{head ? `, committed ${formatDate(head.date)}` : ""}. Technical fields are populated from scan evidence; the applicant confirms identity and supplies performance figures before submission.</div>
            </div>
            <div className="hidden md:flex flex-col gap-1 text-[11px] caption whitespace-nowrap no-print">
              {(["scan", "declared", "applicant", "sample", "indicative"] as AssessmentSource[]).map((s) => <span key={s} className="flex items-center gap-1.5"><SourceChip source={s} /></span>)}
            </div>
          </div>

          {editing ? (
            <div className="mt-6 rounded-md border border-gold/50 bg-gold-100/40 p-4 no-print">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-[13px] font-medium text-navy">Editing. Scan-derived answers stay read-only; they change when the code changes.</div>
                <button type="button" onClick={reset} className="btn btn-sm" disabled={!anyEdit}>Reset</button>
              </div>
              <div className="grid gap-3 md:grid-cols-2 mt-3">
                {IDENTITY_FIELDS.map((f) => (
                  <label key={f.key} className="flex flex-col gap-1 text-[12.5px]">
                    <span className="caption">{f.label}</span>
                    <input value={identity[f.key]} onChange={(e) => setIdentity({ ...identity, [f.key]: e.target.value })} className="field" aria-label={f.label} />
                  </label>
                ))}
                <label className="flex flex-col gap-1 text-[12.5px]"><span className="caption">Carrier</span><input value={carrier} onChange={(e) => setCarrier(e.target.value)} className="field" aria-label="Carrier" /></label>
                <label className="flex flex-col gap-1 text-[12.5px]"><span className="caption">Product</span><input value={product} onChange={(e) => setProduct(e.target.value)} className="field" aria-label="Product" /></label>
              </div>
            </div>
          ) : null}

          <FormSection number={1} title="General information" fields={general} />
          {a.sections.filter((s) => s.id !== "general").map((section, i) => (
            <FormSection key={section.id} number={i + 2} title={section.title} fields={section.fields} />
          ))}

          <h3 className="mt-6 mb-2 text-navy border-b border-line pb-1.5">4. Data submission requirements</h3>
          <div className="caption mb-2 flex flex-wrap items-center gap-2">Model-performance data <SourceChip source={performanceEdited ? "applicant" : a.performance_source} />{a.performance_source === "sample" && !performanceEdited ? <span>sample values shown; the applicant supplies measured figures</span> : <span>provided by the applicant</span>}</div>
          <table className="tbl">
            <thead><tr><th>Performance metric</th><th>Value</th><th>Measurement cadence</th>{editing ? <th className="no-print" /> : null}</tr></thead>
            <tbody>
              {performance.map((row, i) => (
                <tr key={i}>
                  {editing ? (
                    <>
                      <td><input value={row.metric} onChange={(e) => setPerformance(performance.map((r, j) => (j === i ? { ...r, metric: e.target.value } : r)))} className="field w-full" aria-label={`Metric ${i + 1}`} /></td>
                      <td><input value={row.value} onChange={(e) => setPerformance(performance.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)))} className="field w-full tabular-nums" aria-label={`Value ${i + 1}`} /></td>
                      <td><input value={row.cadence} onChange={(e) => setPerformance(performance.map((r, j) => (j === i ? { ...r, cadence: e.target.value } : r)))} className="field w-full" aria-label={`Cadence ${i + 1}`} /></td>
                      <td className="no-print"><button type="button" onClick={() => setPerformance(performance.filter((_, j) => j !== i))} className="btn btn-sm" aria-label={`Remove metric ${i + 1}`}>Remove</button></td>
                    </>
                  ) : (
                    <>
                      <td>{row.metric}</td><td className="tabular-nums">{row.value}</td><td className="caption">{row.cadence}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {editing ? <button type="button" onClick={() => setPerformance([...performance, { metric: "", value: "", cadence: "" }])} className="btn btn-sm mt-2 no-print">Add metric</button> : null}

          <div className="mt-5 rounded-md border border-navy/30 overflow-hidden">
            <div className="bg-navy text-white px-4 py-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-[13px] font-semibold">Insurance requirements (schedule)</span>
              <span className="text-[11.5px] text-white/75">{scheduleDeclared ? `terms as declared; ${carrier} confirms them` : `indicative terms sized off exposure; ${carrier} sets the final terms`}</span>
            </div>
            <div className="divide-y divide-line">
              {scheduleRows.map((f) => (
                editing && (SCHEDULE_TERMS as readonly string[]).includes(f.key) ? (
                  <div key={f.key} className="grid grid-cols-[minmax(160px,260px)_1fr] gap-x-4 items-center px-1 py-2 text-[13px] no-print">
                    <span className="caption">{f.label}</span>
                    <input value={schedule[f.key] ?? ""} onChange={(e) => setSchedule({ ...schedule, [f.key]: e.target.value })} className="field w-full" aria-label={f.label} />
                  </div>
                ) : (
                  <FieldRow key={f.key} field={f} />
                )
              ))}
            </div>
          </div>

          <h3 className="mt-6 mb-2 text-navy border-b border-line pb-1.5">5. Declaration</h3>
          <p className="m-0 text-[13px] leading-relaxed">{a.declaration}</p>
          <div className="grid md:grid-cols-2 gap-10 mt-8">
            <div><div className="border-b border-ink h-9" /><div className="caption mt-1">Signature — {[identity.contact_name, identity.contact_title].filter(Boolean).join(", ") || "Authorized signatory"}</div></div>
            <div><div className="border-b border-ink h-9" /><div className="caption mt-1">Date</div></div>
          </div>
          <p className="caption italic mt-6 mb-0 text-[11.5px]">Form modeled on the {product}™ {a.template} template. Identity and model-performance figures are to be confirmed by the applicant before submission. Stoa prepares evidence; carriers price and issue.</p>
        </div>
      </div>

      <div className="screen-view">
        {editing || anyEdit ? (
          <Section title="Save your edits" caption="This file cannot write to your repository. Save the snippet as .stoa/underwriting.toml and commit it; the next scan pre-fills the form from it." actions={<button type="button" onClick={copyToml} className="btn btn-sm">{tomlCopied ? "Copied" : "Copy"}</button>}>
            <textarea readOnly value={toml} rows={Math.min(30, toml.split("\n").length)} className="w-full rounded-md border border-line bg-panel p-3 mono text-[12px]" aria-label="Underwriting config snippet" onFocus={(e) => e.currentTarget.select()} />
          </Section>
        ) : null}
        <Section title="Evidence pack" caption="What an underwriter can verify from this scan.">
          <details className="panel">
            <summary className="px-4 py-3 cursor-pointer text-[13.5px] font-medium text-navy">Show the evidence pack</summary>
            <div className="px-4 pb-4"><EvidencePack /></div>
          </details>
        </Section>
      </div>
    </div>
  );
}

function Step({ n, title, body, done }: { n: number; title: string; body: string; done?: boolean }) {
  return (
    <li className="flex gap-3">
      <span aria-hidden="true" className={`flex-none w-6 h-6 rounded-full text-[12px] font-semibold flex items-center justify-center ${done ? "bg-ok text-white" : "border border-line-strong text-ink-muted"}`}>{done ? "✓" : n}</span>
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-navy leading-snug">{title}</div>
        <div className="caption mt-0.5 leading-snug">{body}</div>
      </div>
    </li>
  );
}

function FormSection({ number, title, fields }: { number: number; title: string; fields: AssessmentField[] }) {
  return (
    <div>
      <h3 className="mt-6 mb-1 text-navy border-b border-line pb-1.5">{number}. {title}</h3>
      <div className="divide-y divide-line">
        {fields.map((f) => <FieldRow key={f.key} field={f} />)}
      </div>
    </div>
  );
}

function FieldRow({ field }: { field: AssessmentField }) {
  return (
    <div className="grid grid-cols-[minmax(160px,260px)_1fr_auto] gap-x-4 items-start px-1 py-2 text-[13px]">
      <span className="caption">{field.label}</span>
      <span className="min-w-0 break-words">
        {field.value}
        {field.note ? <span className="caption"> — {field.note}</span> : null}
      </span>
      <span className="no-print"><SourceChip source={field.source} /></span>
    </div>
  );
}

/** The underwriter view: what the agents can do, controls, contradictions, drift, confidence. */
function EvidencePack() {
  const { envelope, framework } = useApp();
  const r = envelope.registry;
  const highImpact = new Set(envelope.vocabulary.high_impact_capabilities);
  const sensitive = new Set(envelope.vocabulary.sensitive_integrations);
  const controls = controlsByAgent(envelope);
  const areas = areaSummaries(envelope.assurance);
  const totals = packetTotals(areas);
  const groups = dimensionMatrix(envelope, framework);
  const review = changes(envelope).filter((c) => c.needsReview);
  const contradictions = envelope.assurance.contradictions;

  return (
    <div>
      <Section title="What the agents can do" caption="Capabilities and integrations observed in code, declared limits, and autonomy declared versus inferred.">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl">
            <thead><tr><th>Agent</th><th>Capabilities</th><th>Integrations</th><th>Autonomy declared / inferred</th><th>Max per action</th><th>Worst exposure</th></tr></thead>
            <tbody>
              {r.agents.map((ag) => {
                const c = controls.find((x) => x.agentId === ag.id);
                const worst = (ag.dimension_assessment?.dimensions ?? []).reduce<string>((w, d) => (d.exposure === "elevated" ? "elevated" : w === "elevated" ? w : d.exposure === "moderate" ? "moderate" : w), "none-observed");
                const mismatch = Boolean(c?.declaredAutonomy && c?.inferredAutonomy && c.declaredAutonomy !== c.inferredAutonomy);
                return (
                  <tr key={ag.id}>
                    <td><span className="flex items-center gap-2.5"><span className="avatar" aria-hidden="true">{initials(agentLabel(ag))}</span><span className="font-medium">{agentLabel(ag)}<div className="caption mono font-normal">{ag.path}</div></span></span></td>
                    <td><Chips items={ag.capabilities.map((x) => ({ label: x, hot: highImpact.has(x) }))} empty="none observed" /></td>
                    <td><Chips items={ag.integrations.map((x) => ({ label: x, hot: sensitive.has(x) }))} empty="none observed" /></td>
                    <td className={mismatch ? "text-sev-high font-medium" : ""}>{c?.declaredAutonomy ?? "not declared"} / {c?.inferredAutonomy ?? "indeterminate"}</td>
                    <td>{c?.maxPerAction ?? <span className="caption">not declared</span>}</td>
                    <td><ExposureBadge exposure={worst as "elevated" | "moderate" | "none-observed"} /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Controls: observed versus declared" caption="Observed means the scanner saw the control in code or infrastructure; declared means a human wrote it down. Neither is a claim the control works.">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl">
            <thead><tr><th>Agent</th><th>Controls observed in code</th></tr></thead>
            <tbody>
              {controls.map((c) => (
                <tr key={c.agentId}><td>{c.name}</td><td><Chips items={c.observed.map((x) => ({ label: x }))} empty="none observed" /></td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 panel p-3">
          <div className="flex flex-wrap gap-3 text-[13px]">
            {STATUS_ORDER.map((st) => <span key={st} className="flex items-center gap-1.5"><StatusDot status={st} />{STATUS_LABEL[st]} <span className="tabular-nums caption">{totals[st]}</span></span>)}
          </div>
          <p className="caption mt-2 mb-0">Assurance packet {envelope.assurance.schema}: every row of the 18 areas carries exactly one status. Not provided is listed, never omitted.</p>
        </div>
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {areas.map((ar) => <AreaCard key={ar.key} area={ar} />)}
        </div>
      </Section>

      <Section title="Contradictions" caption="Where declarations do not match the code. What a self-attested questionnaire cannot catch.">
        {contradictions.length === 0 ? <p className="caption m-0">No declared-versus-scanned contradictions in this scan.</p> : (
          <ul className="m-0 p-0 list-none panel divide-y divide-line text-[13px]">
            {contradictions.map((c, i) => (
              <li key={i} className="p-3 flex flex-wrap items-center gap-2">
                {typeof c.severity === "string" ? <SeverityBadge severity={c.severity as "critical" | "high" | "medium" | "low" | "info"} /> : null}
                <span className="mono">{String(c.rule_id ?? "")}</span>
                <span>{String(c.title ?? c.message ?? "")}</span>
                {typeof c.agent === "string" ? <span className="caption">{c.agent}</span> : null}
                {typeof c.path === "string" ? <span className="caption mono">{c.path}{typeof c.line === "number" ? `:${c.line}` : ""}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Drift since last assessment" caption={envelope.diff ? `Against ${envelope.baseline?.git_ref ?? envelope.diff.base.commit ?? "baseline"}${envelope.baseline?.head_commit ? ` (${formatDate(envelope.baseline.head_commit.date)})` : ""}.` : "No baseline in this scan."}>
        {!envelope.diff ? <p className="caption m-0">Provide a baseline (stoa scan --diff-against, or stoa dashboard --baseline) to show what changed.</p> : (
          <div className="text-[13px]">
            <p className="m-0">{pluralize(envelope.diff.summary.agents_changed, "agent")} changed, {envelope.diff.summary.agents_added} added, {envelope.diff.summary.agents_removed} removed. {envelope.diff.summary.escalations.high} high-impact escalations. Unapproved max drift <strong>{envelope.diff.summary.unapproved_max_drift_severity}</strong>.</p>
            {review.length ? (
              <ul className="m-0 mt-2 p-0 list-none panel divide-y divide-line">
                {review.map((c, i) => <li key={i} className="p-2 flex flex-wrap items-center gap-2"><span className="font-medium">{c.agentName}</span><span className="caption">{c.kind.replace(/_/g, " ")}</span><span className="mono">{c.label}</span><span className="caption">{c.detail}</span><Pill tone="warn">needs review</Pill></li>)}
              </ul>
            ) : <p className="caption mt-1 mb-0">No unapproved authority increases.</p>}
          </div>
        )}
      </Section>

      <Section title="Confidence per dimension" caption="How directly static analysis observes each dimension. Proxy dimensions are capped at moderate by design.">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl">
            <thead><tr><th>Category</th><th>Dimension</th><th>Confidence</th><th>Organization-wide exposure</th><th>Agents elevated / moderate</th></tr></thead>
            <tbody>
              {groups.flatMap((g) => g.cells.map((c, i) => (
                <tr key={c.dimension.id}>
                  <td className="caption">{i === 0 ? `${g.id} · ${g.label}` : ""}</td>
                  <td>{c.dimension.name}<div className="caption">{c.dimension.definition}</div></td>
                  <td><AssessabilityBadge assessability={c.dimension.assessability} /></td>
                  <td><ExposureBadge exposure={c.maxExposure} /></td>
                  <td className="tabular-nums">{c.agentsElevated} / {c.agentsModerate}</td>
                </tr>
              )))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

function StatusDot({ status }: { status: Status }) {
  const cls: Record<Status, string> = { scanned: "bg-ok", declared: "bg-sev-info", ingested: "bg-navy", observed: "bg-gold", not_provided: "bg-line" };
  return <span aria-hidden="true" className={`inline-block w-2.5 h-2.5 rounded-full ${cls[status]}`} />;
}

function AreaCard({ area }: { area: AreaSummary }) {
  const [open, setOpen] = useState(false);
  const total = STATUS_ORDER.reduce((n, st) => n + area.counts[st], 0);
  return (
    <div className="panel p-3 text-[13px]">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="w-full text-left flex items-start justify-between gap-2">
        <span><span className="caption">{area.group} · </span><span className="font-medium">{area.name}</span><span className="caption"> · {area.layers}</span></span>
        <span className="flex gap-2 whitespace-nowrap">{STATUS_ORDER.filter((st) => area.counts[st]).map((st) => <span key={st} className="flex items-center gap-1 caption"><StatusDot status={st} />{area.counts[st]}</span>)}{total === 0 ? <span className="caption">no rows</span> : null}</span>
      </button>
      {open && area.rows.length ? (
        <ul className="m-0 mt-2 p-0 list-none flex flex-col gap-0.5 caption">
          {area.rows.map((row, i) => <li key={i} className="flex items-center gap-2"><StatusDot status={row.status} /><span className="mono">{row.field}</span>{row.agent ? <span>{row.agent}</span> : null}<span>{STATUS_LABEL[row.status]}</span></li>)}
        </ul>
      ) : null}
    </div>
  );
}
