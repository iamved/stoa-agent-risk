import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { ConfidenceBadge, Pill, SeverityBadge } from "./Badge";
import { Drawer } from "./Drawer";
import { Chips, KeyValue } from "./KeyValue";
import { Snippet } from "./Snippet";
import { agentLabel, dimensionName, findingTitle, pluralize, tagLabel, type FindingRef } from "../data/selectors";
import { evidenceLines, howToFix, locationText, ruleName, whatThisCheckDoes, whatWeFound, whyItMatters } from "../data/findingCopy";
import { euArticleDescription, euArticleName, owaspDescription, owaspName } from "../data/frameworks";

/** What this check does / Why it matters / How to fix, plus the evidence. */
export function FindingDrawer({ ref, onClose, backQuery }: { ref: FindingRef | null; onClose: () => void; backQuery?: URLSearchParams }) {
  const { envelope, framework } = useApp();
  if (!ref) return null;
  const f = ref.finding;
  const rule = envelope.rules[f.rule_id];
  const cw = f.crosswalk ?? rule?.crosswalk;
  const tag = framework === "owasp" ? cw?.owasp_llm_2025 : framework === "eu" ? cw?.eu_ai_act : "";
  const found = whatWeFound(ref);

  return (
    <Drawer open title={findingTitle(envelope, f)} onClose={onClose}>
      <div className="flex flex-wrap items-center gap-1.5 mb-4">
        <SeverityBadge severity={f.severity} />
        <ConfidenceBadge confidence={f.confidence} />
        {f.is_new ? <Pill tone="gold">new since base</Pill> : null}
        {f.suppressed ? <Pill tone="neutral" title={f.suppression_reason ?? ""}>suppressed</Pill> : null}
        {f.gate_eligible ? <Pill tone="navy" title="Can fail a build at high confidence">gate eligible</Pill> : null}
        {tag ? <Pill tone="neutral" title={tagLabel(tag, framework)}>{framework === "owasp" ? "OWASP " : framework === "eu" ? "EU AI Act " : ""}{tag}</Pill> : null}
      </div>

      <KeyValue
        rows={[
          { k: "Rule", v: <span><span className="mono">{f.rule_id}</span> {ruleName(envelope, f.rule_id, f.title)}</span> },
          { k: "Affected agent", v: ref.uniqueAgents.length ? ref.uniqueAgents.map((u, i) => (
            <span key={u.id}>
              <a href={buildHash("inventory", u.records[0]!.id, backQuery)} className="link">{u.name}</a>
              {i < ref.uniqueAgents.length - 1 ? ", " : ""}
            </span>
          )) : "Repository (not attached to an agent)" },
          { k: ref.evidence.length > 1 ? "Evidence locations" : "Location", v: (
            <span className="flex flex-col gap-0.5">
              {ref.evidence.map((e) => {
                const record = ref.agents.find((a) => a.findings.some((x) => x.fingerprint === e.fingerprint));
                return <span key={e.fingerprint}><span className="mono">{locationText(e.path, e.line, e.column)}</span>{ref.evidence.length > 1 && record ? <span className="caption"> · {agentLabel(record)}</span> : null}</span>;
              })}
            </span>
          ) },
          { k: "Categories", v: <Chips items={(f.dimensions ?? []).map((d) => ({ label: dimensionName(envelope, d) }))} /> },
        ]}
      />

      {ref.evidence.length > 1 ? <p className="caption mt-3 mb-0">The same rule fired on {pluralize(ref.evidence.length, "scanned record")} of this agent. It is one finding; each record is evidence for it.</p> : null}
      {ref.evidence.map((e, i) => {
        const label = ref.evidence.length > 1 ? `Evidence ${i + 1} of ${ref.evidence.length} · ${locationText(e.path, e.line)}` : "Evidence";
        const lines = evidenceLines({ ...ref, finding: e });
        return (
          <div className="mt-4" key={e.fingerprint}>
            {lines ? (
              <div>
                <div className="caption mb-1">{label}</div>
                <dl className="m-0 mono text-[12px] rounded-md border border-line bg-paper px-3 py-2 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5">
                  {lines.map((l) => <div key={l.label} className="contents"><dt className="text-ink-muted">{l.label}:</dt><dd className="m-0 text-navy">{l.value}</dd></div>)}
                </dl>
              </div>
            ) : <Snippet text={e.snippet} label={label} />}
          </div>
        );
      })}

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
        {rule ? <p className="m-0">{whatThisCheckDoes(envelope, f.rule_id)}</p> : <p className="m-0 caption">Rule metadata not available.</p>}
      </Doc>

      {found ? <Doc title="What we found"><p className="m-0">{found}</p></Doc> : null}

      <Doc title="Why it matters">
        <p className="m-0">{whyItMatters(envelope, ref, findingTitle(envelope, f))}</p>
        {cw ? (
          <dl className="m-0 mt-3 grid gap-2 text-[12.5px]">
            {cw.owasp_llm_2025 ? (
              <div>
                <dt className="font-medium text-navy">OWASP {cw.owasp_llm_2025}: {owaspName(cw.owasp_llm_2025)}</dt>
                <dd className="m-0 caption">{owaspDescription(cw.owasp_llm_2025)}</dd>
              </div>
            ) : (
              <div><dt className="font-medium text-navy">OWASP LLM Top 10</dt><dd className="m-0 caption">Not an LLM-specific class; a classic software weakness.</dd></div>
            )}
            {cw.eu_ai_act ? (
              <div>
                <dt className="font-medium text-navy">EU AI Act {cw.eu_ai_act}: {euArticleName(cw.eu_ai_act)}</dt>
                <dd className="m-0 caption">{euArticleDescription(cw.eu_ai_act)}</dd>
              </div>
            ) : null}
          </dl>
        ) : null}
      </Doc>

      <Doc title="How to fix">
        <p className="m-0">{howToFix(ref)}</p>
        {f.declared_ref ? <p className="mono text-[12px] mt-2 mb-0 rounded-md border border-line bg-paper px-3 py-1.5 break-all" title={`In ${f.declared_ref.path}`}>{f.declared_ref.key}</p> : null}
      </Doc>

      {f.suppressed && f.suppression_reason ? (
        <Doc title="Notes">
          <p className="caption m-0">Suppressed: {f.suppression_reason}</p>
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
