import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { Section } from "../components/Section";
import { detectr, runtimeWindow } from "../data/runtime";
import { pluralize } from "../data/selectors";
import type { DetectrFinding } from "../data/types";

/** The claim in the agent's own words, with each value that did not hold marked. */
function ClaimText({ finding }: { finding: DetectrFinding }) {
  const text = finding.detectr.claim.text;
  const marks = finding.detectr.issues.map((i) => i.raw ?? i.value).filter((v): v is string => Boolean(v && text.includes(v)));
  if (!marks.length) return <span>{text}</span>;
  const pattern = new RegExp(`(${marks.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return <span>{text.split(pattern).map((part, i) => (marks.includes(part) ? <mark key={i} className="rounded bg-gold-100 px-0.5 text-navy font-semibold underline decoration-sev-high decoration-2">{part}</mark> : <span key={i}>{part}</span>))}</span>;
}

/** DetectR: what each agent said and did, checked against what it saw. */
export function Detectr() {
  const { envelope } = useApp();
  const data = detectr(envelope);
  const window = runtimeWindow(envelope);
  const caption = "What each agent said and did, checked against what it saw. Only sessions recorded with content are checked.";
  if (!data) {
    return (
      <div>
        <h1 className="m-0 mb-1">DetectR</h1>
        <p className="m-0 mb-4 caption">{caption}</p>
        {window && window.spans ? (
          <EmptyState title="No session carried content"><span>Record sessions with <span className="mono">configure(capture_content=True)</span>; redacted traces hold hashes only.</span></EmptyState>
        ) : (
          <EmptyState title="No traces in this scan"><span>Instrument an agent with <span className="mono">stoa.runtime</span> and record sessions with <span className="mono">capture_content=True</span>, then build the page with <span className="mono">--runtime stoa-traces</span>.</span></EmptyState>
        )}
      </div>
    );
  }
  const { block, agents, findings } = data;
  const summary = `${pluralize(block.with_content, "session")} of ${block.trajectories} checked, ${pluralize(findings.length, "finding")}.`;
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-4">
        <h1 className="m-0">DetectR</h1>
        <div className="caption">{caption} {summary}</div>
      </div>
      <Section title="By agent" caption="Unverifiable claims had no evidence to check against and are counted apart.">
      <div className="panel overflow-x-auto" tabIndex={0}>
        <table className="tbl w-full">
          <thead><tr><th>Agent</th><th>Sessions</th><th>Claims</th><th>Grounded</th><th>Unsupported</th><th>Contradicted</th><th>Unverifiable</th></tr></thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <td>{a.agentId ? <a href={buildHash("inventory", a.agentId)} className="link font-medium">{a.name}</a> : <span className="font-medium">{a.name}</span>}</td>
                <td>{a.row.trajectories}</td>
                <td>{a.row.claims}</td>
                <td>{a.row.labels.grounded}</td>
                <td className={a.row.labels.unsupported ? "text-sev-high font-medium" : ""}>{a.row.labels.unsupported}</td>
                <td className={a.row.labels.contradicted ? "text-sev-critical font-medium" : ""}>{a.row.labels.contradicted}</td>
                <td className="text-ink-muted">{a.row.labels.unverifiable}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </Section>
      <Section title="What did not hold" caption="Each finding shows the agent's own words with the value that did not hold marked, and the tool result it was checked against.">
      {findings.length ? (
        <ol className="panel m-0 p-0 list-none divide-y divide-line/70">
          {findings.map((f) => {
            const agent = agents.find((a) => a.id === f.detectr.agent_id);
            const evidence = f.detectr.evidence[0];
            return (
              <li key={f.fingerprint} className="grid grid-cols-[68px_minmax(0,1fr)] gap-x-3 items-start px-4 py-3">
                <span className="pt-0.5"><SeverityBadge severity={f.severity} /></span>
                <div className="min-w-0">
                  <div className="text-[13.5px] font-medium leading-snug text-navy">{f.title}</div>
                  <div className="caption mt-0.5">{agent?.name ?? "Agent"} · {f.rule_id}{f.detectr.claim.source === "tool_call" ? " · tool call" : " · reply"}</div>
                  <blockquote className="m-0 mt-1.5 border-l-2 border-line pl-3 text-[13px] text-ink"><ClaimText finding={f} /></blockquote>
                  <div className="text-[12.5px] text-ink-soft mt-1.5">{f.message}</div>
                  {evidence ? <div className="caption mt-1">Checked against {evidence.kind.replace("_", " ")} <span className="mono">{evidence.excerpt.replace(/\n/g, " | ").slice(0, 120)}</span></div> : null}
                  {f.detectr.blast_radius ? <div className="caption mt-0.5">{pluralize(f.detectr.blast_radius, "later claim")} reused this value.</div> : null}
                </div>
              </li>
            );
          })}
        </ol>
      ) : <EmptyState title="Nothing unsupported">Every checked claim traces to something the agent saw.</EmptyState>}
      </Section>
    </div>
  );
}

