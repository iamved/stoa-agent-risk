import { useApp } from "../app/context";
import { AgentMark } from "../components/AgentMark";
import { RiskTabs } from "../components/RiskTabs";
import { buildHash } from "../app/router";
import { Pill, SeverityBadge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { changes, groupChanges, type Change } from "../data/drift";
import { formatDate, pluralize } from "../data/selectors";
import type { DriftSeverity } from "../data/types";

const DRIFT_BADGE: Record<DriftSeverity, "critical" | "high" | "medium" | "info"> = { high: "high", medium: "medium", low: "info", info: "info" };

export function Drift() {
  const { envelope } = useApp();
  const diff = envelope.diff;
  const r = envelope.registry;

  if (!diff) {
    return (
      <div>
        <RiskTabs current="drift" />
        <h1 className="m-0 mb-4">Drift</h1>
        <EmptyState title="No baseline in this scan">
          <p className="m-0">Drift compares two registries produced by the same Stoa version and reports what changed in each agent's reach: capabilities, integrations, providers, findings, and dimension exposure.</p>
          <p className="mt-2 mb-0">Inside a repository, run <code>stoa scan . --diff-against origin/main</code> so the base ref is rescanned with the current scanner. From saved registries, run <code>stoa dashboard stoa-registry.json --baseline previous-registry.json</code>.</p>
        </EmptyState>
      </div>
    );
  }

  const items = changes(envelope);
  const groups = groupChanges(items);
  const review = items.filter((c) => c.needsReview);
  const s = diff.summary;
  const base = envelope.baseline;
  const head = r.repository.head_commit;

  return (
    <div>
      <RiskTabs current="drift" />
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Drift</h1>
        <div className="caption">What changed in each agent's reach since the baseline.</div>
      </div>

      <div className="mt-4 panel p-4 grid gap-3 md:grid-cols-[1fr_auto_1fr] items-center">
        <div>
          <div className="caption uppercase tracking-wide text-[11px]">Baseline</div>
          <div className="text-[16px] font-semibold text-navy">{base?.git_ref ?? diff.base.commit ?? "unknown ref"}</div>
          <div className="caption">{base?.head_commit ? `committed ${formatDate(base.head_commit.date)}` : "commit date unavailable"}{base?.name ? ` · ${base.name}` : ""}</div>
        </div>
        <div className="text-gold text-[20px] text-center" aria-hidden="true">→</div>
        <div>
          <div className="caption uppercase tracking-wide text-[11px]">Current</div>
          <div className="text-[16px] font-semibold text-navy">{r.repository.git_ref ?? diff.head.commit ?? "working tree"}</div>
          <div className="caption">{head ? `committed ${formatDate(head.date)}` : "commit date unavailable"} · {r.repository.name}</div>
        </div>
      </div>

      <div className="mt-4 grid gap-3 grid-cols-3">
        <StatCard icon="flag" label="Needs review" value={review.length} detail="unapproved authority increases" tone={review.length ? "warn" : "neutral"} />
        <StatCard icon="inventory" label="Agents changed" value={s.agents_changed + s.agents_added + s.agents_removed} detail={`${s.agents_added} added · ${s.agents_removed} removed`} />
        <StatCard icon="risk" label="New high-risk findings" value={s.findings_delta.new_critical + s.findings_delta.new_high} detail={`${s.findings_delta.resolved} resolved`} />
      </div>

      {review.length ? (
        <Section title="Needs review" caption="Authority increases nobody has approved yet. Approve intentional ones with stoa approve.">
          <ul className="m-0 p-0 list-none panel divide-y divide-line">
            {review.map((c, i) => <ChangeRow key={i} change={c} emphasize />)}
          </ul>
        </Section>
      ) : (
        <Section title="Needs review">
          <p className="caption m-0">No unapproved authority increases between these two scans.</p>
        </Section>
      )}

      <Section title="All changes" caption={pluralize(items.length, "change")}>
        {groups.length === 0 ? (
          <p className="caption m-0">No change in any agent's reach between these two scans.</p>
        ) : (
          <div className="flex flex-col gap-4">
            {groups.map((g) => (
              <div key={g.kind}>
                <h3 className="text-[14px] m-0 mb-1.5">{g.label} <span className="caption font-sans font-normal">{g.items.length}</span></h3>
                <ul className="m-0 p-0 list-none panel divide-y divide-line">
                  {g.items.map((c, i) => <ChangeRow key={i} change={c} />)}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Section>

      {diff.approvals.stale.length ? (
        <Section title="Stale approvals" caption="Approvals whose evidence fingerprint no longer matches the code. They no longer apply.">
          <ul className="m-0 p-0 list-none panel divide-y divide-line text-[13px]">
            {diff.approvals.stale.map((a, i) => <li key={i} className="p-3 mono">{JSON.stringify(a)}</li>)}
          </ul>
        </Section>
      ) : null}
    </div>
  );
}

function ChangeRow({ change, emphasize }: { change: Change; emphasize?: boolean }) {
  const { envelope } = useApp();
  const agentExists = envelope.registry.agents.some((a) => a.id === change.agentId);
  const findingExists = change.fingerprint ? envelope.registry.agents.some((a) => a.findings.some((f) => f.fingerprint === change.fingerprint)) : false;
  return (
    <li className={`p-3 grid gap-x-3 gap-y-1 md:grid-cols-[minmax(150px,1fr)_minmax(180px,1.4fr)_minmax(160px,1.2fr)_auto] items-start text-[13px] ${emphasize ? "border-l-2 border-sev-high" : ""}`}>
      <div>
        <div className="caption text-[11px] uppercase tracking-wide">{change.population ? (change.kind === "agent_added" ? "New agent" : "Removed agent") : "Agent"}</div>
        <span className="flex items-center gap-2"><AgentMark />{agentExists ? <a href={buildHash("inventory", change.agentId)} className="link font-medium">{change.agentName}</a> : <span className="font-medium">{change.agentName}</span>}</span>
        <div className="caption mono truncate">{change.agentPath}</div>
      </div>
      <div>
        <div className="caption text-[11px] uppercase tracking-wide">{change.population ? "Reason" : change.kind.replace(/_/g, " ")}</div>
        {change.fingerprint && findingExists ? <a href={buildHash("findings", change.fingerprint)} className="link mono">{change.label}</a> : <span className={change.kind.endsWith("_added") || change.kind === "finding_new" ? "mono" : ""}>{change.label}</span>}
      </div>
      <div className="caption">{change.detail}</div>
      <div className="flex flex-wrap gap-1 md:justify-end">
        <SeverityBadge severity={DRIFT_BADGE[change.severity]} />
        {change.needsReview ? <Pill tone="warn">needs review</Pill> : change.authorityIncrease && change.approved ? <Pill tone="neutral">approved</Pill> : null}
      </div>
    </li>
  );
}
