import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { ConfidenceBadge, Pill, SeverityBadge } from "./Badge";
import { Drawer } from "./Drawer";
import { Chips, KeyValue } from "./KeyValue";
import { Snippet } from "./Snippet";
import { agentLabel, dimensionName, tagLabel, type FindingRef } from "../data/selectors";
import { euArticleName, owaspName } from "../data/frameworks";

/** What this check does / Why it matters / How to fix, plus the evidence. */
export function FindingDrawer({ ref, onClose, backQuery }: { ref: FindingRef | null; onClose: () => void; backQuery?: URLSearchParams }) {
  const { envelope, framework } = useApp();
  if (!ref) return null;
  const f = ref.finding;
  const rule = envelope.rules[f.rule_id];
  const cw = f.crosswalk ?? rule?.crosswalk;
  const tag = framework === "owasp" ? cw?.owasp_llm_2025 : framework === "eu" ? cw?.eu_ai_act : "";

  return (
    <Drawer open title={`${f.rule_id} · ${f.title}`} onClose={onClose}>
      <div className="flex flex-wrap items-center gap-1.5 mb-4">
        <SeverityBadge severity={f.severity} />
        <ConfidenceBadge confidence={f.confidence} />
        {f.is_new ? <Pill tone="gold">new since base</Pill> : null}
        {f.suppressed ? <Pill tone="neutral" title={f.suppression_reason ?? ""}>suppressed</Pill> : null}
        {f.gate_eligible ? <Pill tone="navy" title="Can fail a build at high confidence">gate eligible</Pill> : null}
        {tag ? <Pill tone="neutral" title={tagLabel(tag, framework)}>{tag}</Pill> : null}
      </div>

      <KeyValue
        rows={[
          { k: "Affected asset", v: ref.agents.length ? ref.agents.map((a, i) => (
            <span key={a.id}>
              <a href={buildHash("inventory", a.id, backQuery)} className="link">{agentLabel(a)}</a>
              {i < ref.agents.length - 1 ? ", " : ""}
            </span>
          )) : "repository (not attached to an agent)" },
          { k: "Location", v: <span className="mono">{f.path}:{f.line}{f.column ? `:${f.column}` : ""}</span> },
          { k: "Dimensions", v: <Chips items={(f.dimensions ?? []).map((d) => ({ label: dimensionName(envelope, d) }))} /> },
        ]}
      />

      <div className="mt-4">
        <Snippet text={f.snippet} label="Evidence" />
      </div>

      {f.flow && f.flow.length ? (
        <div className="mt-4">
          <div className="caption mb-1">Data flow ({f.flow.length} steps, intra-file)</div>
          <ol className="m-0 p-0 list-none flex flex-col gap-1">
            {f.flow.map((step, i) => (
              <li key={i} className="grid grid-cols-[84px_1fr] gap-2 text-[12.5px]">
                <span className="caption">{step.role} · line {step.line}</span>
                <code className="whitespace-pre-wrap break-words">{step.snippet}</code>
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      <Doc title="What this check does">
        {rule ? <p className="m-0">{rule.title}.{rule.gateable ? " Can fail a build at high confidence." : ""}</p> : <p className="m-0 caption">Rule metadata not available.</p>}
        {f.message ? <p className="m-0 mt-2">{f.message}</p> : null}
      </Doc>

      <Doc title="Why it matters">
        <p className="m-0">{cw?.so_what ?? f.title}</p>
        {cw ? (
          <p className="caption m-0 mt-2">{cw.owasp_llm_2025 ? `OWASP ${cw.owasp_llm_2025} ${owaspName(cw.owasp_llm_2025)}` : "Not an OWASP LLM class"}{cw.eu_ai_act ? ` · EU AI Act ${cw.eu_ai_act} ${euArticleName(cw.eu_ai_act)}` : ""}</p>
        ) : null}
      </Doc>

      <Doc title="How to fix">
        <p className="m-0">{f.remediation}</p>
      </Doc>

      {f.declared_ref || (f.suppressed && f.suppression_reason) ? (
        <Doc title="Notes">
          {f.declared_ref ? <p className="caption m-0">Declared at <span className="mono">{f.declared_ref.path}</span>, key <span className="mono">{f.declared_ref.key}</span></p> : null}
          {f.suppressed && f.suppression_reason ? <p className="caption m-0">Suppressed: {f.suppression_reason}</p> : null}
        </Doc>
      ) : null}
    </Drawer>
  );
}

function Doc({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="text-[14px] m-0 mb-1.5">{title}</h3>
      <div className="text-[13px]">{children}</div>
    </section>
  );
}
