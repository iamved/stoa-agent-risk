import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { printAs } from "../app/print";
import { AssessabilityBadge, ExposureBadge, Pill, SeverityBadge } from "../components/Badge";
import { Chips } from "../components/KeyValue";
import { Section } from "../components/Section";
import { STATUS_LABEL, STATUS_ORDER, areaSummaries, controlsByAgent, packetTotals, type AreaSummary, type Status } from "../data/evidence";
import { changes } from "../data/drift";
import { agentLabel, dimensionMatrix, formatDate, pluralize } from "../data/selectors";
import type { AssessmentField, AssessmentSource } from "../data/types";

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

/** The AI Risk Insurance page: the pre-filled assessment as it would be submitted, the schedule, and the evidence behind it. */
export function Evidence() {
  const { envelope } = useApp();
  const a = envelope.assessment;
  const r = envelope.registry;
  const head = r.repository.head_commit;
  const [copied, setCopied] = useState<"idle" | "done" | "manual">("idle");
  const transfers = envelope.register.filter((row) => row.declared?.treatment === "transfer");
  const pct = a.counts.total ? Math.round((a.counts.prefilled / a.counts.total) * 100) : 0;

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
          <button type="button" onClick={() => printAs("pack")} className="btn btn-primary">Print assessment (PDF)</button>
          <button type="button" onClick={() => printAs("summary")} className="btn">Print summary</button>
          <a href={downloadHref} download="stoa-registry.json" className="btn">Download report JSON</a>
          <button type="button" onClick={copyJson} className="btn">{copied === "done" ? "Copied" : "Copy JSON"}</button>
        </div>
      </div>
      <p className="caption mt-1 mb-0 no-pack">
        What a submission to {a.carrier} {a.product} looks like for this codebase. Stoa prepares the evidence; {a.carrier} prices and issues.
        {copied === "manual" ? " Clipboard access was blocked in this viewer; use Download instead." : ""}
      </p>

      <div className="screen-view">
        <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_320px] items-start">
          <div className="panel p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="eyebrow">Readiness</div>
                <div className="num text-[28px] text-navy leading-none mt-1">{pct}% pre-filled</div>
                <div className="caption mt-1">{a.counts.prefilled} of {a.counts.total} fields come from the scan or your declarations. {a.counts.to_confirm} need your confirmation.</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="h-2 w-40 rounded-full bg-paper border border-line overflow-hidden" aria-hidden="true"><span className="block h-full bg-gold" style={{ width: `${pct}%` }} /></span>
              </div>
            </div>
            <ol className="m-0 mt-4 p-0 list-none grid gap-3 md:grid-cols-4">
              <Step n={1} title="Review the pre-filled evidence" body="Every technical answer below points at scan evidence. Nothing is typed by hand." done />
              <Step n={2} title="Confirm identity and performance" body={a.performance_source === "applicant" ? "Identity and performance figures were supplied in the underwriting config." : "Replace the sample identity and performance figures in .stoa/underwriting.toml."} done={a.performance_source === "applicant"} />
              <Step n={3} title="Sign the declaration" body="Print the assessment; the signature block is on the last page." />
              <Step n={4} title={`Submit to ${a.carrier}`} body={`Send the signed PDF and the evidence pack to your ${a.carrier} ${a.product} contact. ${a.carrier} sets the final terms.`} />
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

      {/* The assessment document. Shown on screen and printed by "Print assessment". */}
      <div className="print-pack-doc mt-6">
        <div className="panel max-w-[880px] mx-auto px-8 py-7 assessment">
          <div className="flex items-end justify-between gap-4 border-b-2 border-navy pb-3">
            <div>
              <div className="text-[18px] font-semibold text-navy">{a.product}™ — {a.template}</div>
              <div className="caption mt-0.5">Pre-filled by Stoa from a static scan of <strong>{a.repository}</strong>{head ? `, committed ${formatDate(head.date)}` : ""}. Technical fields are populated from scan evidence; the applicant confirms identity and supplies performance figures before submission.</div>
            </div>
            <div className="hidden md:flex flex-col gap-1 text-[11px] caption whitespace-nowrap no-print">
              {(["scan", "declared", "applicant", "sample", "indicative"] as AssessmentSource[]).map((s) => <span key={s} className="flex items-center gap-1.5"><SourceChip source={s} /></span>)}
            </div>
          </div>

          {a.sections.map((section, i) => (
            <FormSection key={section.id} number={i + 1} title={section.title} fields={section.fields} />
          ))}

          <h3 className="mt-6 mb-2 text-navy border-b border-line pb-1.5">4. Data submission requirements</h3>
          <div className="caption mb-2 flex items-center gap-2">Model-performance data <SourceChip source={a.performance_source} />{a.performance_source === "sample" ? <span>sample values shown; the applicant supplies measured figures</span> : <span>provided by the applicant</span>}</div>
          <table className="tbl">
            <thead><tr><th>Performance metric</th><th>Value</th><th>Measurement cadence</th></tr></thead>
            <tbody>
              {a.performance.map((row) => (
                <tr key={row.metric}><td>{row.metric}</td><td className="tabular-nums">{row.value}</td><td className="caption">{row.cadence}</td></tr>
              ))}
            </tbody>
          </table>

          <div className="mt-5 rounded-md border border-navy/30 overflow-hidden">
            <div className="bg-navy text-white px-4 py-2 flex flex-wrap items-center justify-between gap-2">
              <span className="text-[13px] font-semibold">Insurance requirements (schedule)</span>
              <span className="text-[11.5px] text-white/75">{a.schedule_source === "declared" ? "terms declared in the underwriting config" : `indicative terms sized off exposure; ${a.carrier} sets the final terms`}</span>
            </div>
            <div className="divide-y divide-line">
              {a.schedule.map((f) => <FieldRow key={f.key} field={f} />)}
            </div>
          </div>

          <h3 className="mt-6 mb-2 text-navy border-b border-line pb-1.5">5. Declaration</h3>
          <p className="m-0 text-[13px] leading-relaxed">{a.declaration}</p>
          <div className="grid md:grid-cols-2 gap-10 mt-8">
            <div><div className="border-b border-ink h-9" /><div className="caption mt-1">Signature — {a.signatory}</div></div>
            <div><div className="border-b border-ink h-9" /><div className="caption mt-1">Date</div></div>
          </div>
          <p className="caption italic mt-6 mb-0 text-[11.5px]">Form modeled on the {a.product}™ {a.template} template. Identity and model-performance figures are to be confirmed by the applicant before submission. Stoa prepares evidence; carriers price and issue.</p>
        </div>
      </div>

      <div className="screen-view">
        <Section title="Evidence behind the assessment" caption="What an underwriter can verify from this scan: reach, controls observed versus declared, contradictions, drift, and confidence per dimension.">
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
                    <td className="font-medium">{agentLabel(ag)}<div className="caption mono">{ag.path}</div></td>
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
