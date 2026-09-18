/**
 * Groups the scanner's stoa-diff/1.0 document into the changes a reviewer
 * reads. Adds no severity logic: every item's drift severity and approval
 * flag are copied from the diff, and "needs review" is defined as an
 * unapproved authority increase (a high-impact capability, a sensitive
 * integration, a dimension rising, or a new agent that binds either).
 */
import type { DiffDocument, DriftSeverity, Envelope, Exposure } from "./types";
import { EXPOSURE_LABEL } from "./selectors";

export type ChangeKind =
  | "capability_added"
  | "capability_removed"
  | "integration_added"
  | "integration_removed"
  | "provider_added"
  | "provider_removed"
  | "dimension_increased"
  | "dimension_decreased"
  | "confidence_changed"
  | "renamed"
  | "finding_new"
  | "finding_resolved"
  | "agent_added"
  | "agent_removed";

export const KIND_LABEL: Record<ChangeKind, string> = {
  capability_added: "Capability added",
  capability_removed: "Capability removed",
  integration_added: "Integration added",
  integration_removed: "Integration removed",
  provider_added: "Provider added",
  provider_removed: "Provider removed",
  dimension_increased: "Exposure increased",
  dimension_decreased: "Exposure decreased",
  confidence_changed: "Detection confidence changed",
  renamed: "Agent renamed or moved",
  finding_new: "New finding",
  finding_resolved: "Finding resolved",
  agent_added: "Agent added",
  agent_removed: "Agent removed",
};

export interface Change {
  kind: ChangeKind;
  agentId: string;
  agentName: string;
  agentPath: string;
  label: string;
  detail: string;
  severity: DriftSeverity;
  approved: boolean;
  authorityIncrease: boolean;
  needsReview: boolean;
  fingerprint?: string;
  /** The item is a new or removed agent rather than a change to an existing one. */
  population?: boolean;
}

export const DRIFT_RANK: Record<DriftSeverity, number> = { info: 0, low: 1, medium: 2, high: 3 };

export function changes(env: Envelope): Change[] {
  const diff = env.diff;
  if (!diff) return [];
  const highImpact = new Set(env.vocabulary.high_impact_capabilities);
  const sensitive = new Set(env.vocabulary.sensitive_integrations);
  const dimName = (id: string) => env.taxonomy.dimensions.find((d) => d.id === id)?.name ?? id;
  // The diff carries raw names; prefer the registry's disambiguated label.
  const displayName = (id: string, fallback: string) => {
    const agent = env.registry.agents.find((a) => a.id === id);
    return agent ? agent.display_name || agent.name : fallback;
  };
  const out: Change[] = [];

  for (const c of diff.agents.changed) {
    const base = { agentId: c.agent_id, agentName: displayName(c.agent_id, c.name), agentPath: c.path };
    for (const cap of c.capabilities.added) {
      const hi = cap.high_impact ?? highImpact.has(cap.id);
      out.push({ ...base, kind: "capability_added", label: cap.id, detail: hi ? "high-impact capability" : "capability", severity: cap.drift_severity, approved: Boolean(cap.approved), authorityIncrease: hi, needsReview: hi && !cap.approved });
    }
    for (const cap of c.capabilities.removed) {
      out.push({ ...base, kind: "capability_removed", label: cap.id, detail: cap.high_impact ? "high-impact capability no longer bound" : "capability no longer bound", severity: cap.drift_severity, approved: true, authorityIncrease: false, needsReview: false });
    }
    for (const integ of c.integrations.added) {
      const sens = integ.sensitive ?? sensitive.has(integ.id);
      out.push({ ...base, kind: "integration_added", label: integ.id, detail: sens ? "sensitive integration" : "integration", severity: integ.drift_severity, approved: Boolean(integ.approved), authorityIncrease: sens, needsReview: sens && !integ.approved });
    }
    for (const integ of c.integrations.removed) {
      out.push({ ...base, kind: "integration_removed", label: integ.id, detail: "integration no longer reached", severity: integ.drift_severity, approved: true, authorityIncrease: false, needsReview: false });
    }
    for (const p of c.providers.added) out.push({ ...base, kind: "provider_added", label: p, detail: "model provider now called", severity: "medium", approved: false, authorityIncrease: false, needsReview: false });
    for (const p of c.providers.removed) out.push({ ...base, kind: "provider_removed", label: p, detail: "model provider no longer called", severity: "info", approved: true, authorityIncrease: false, needsReview: false });
    for (const d of c.dimension_delta) {
      const up = d.direction === "increased";
      out.push({ ...base, kind: up ? "dimension_increased" : "dimension_decreased", label: dimName(d.id), detail: `${EXPOSURE_LABEL[d.from as Exposure] ?? d.from} to ${EXPOSURE_LABEL[d.to as Exposure] ?? d.to}`, severity: up ? (d.to === "elevated" ? "high" : "medium") : "info", approved: !up, authorityIncrease: up, needsReview: up });
    }
    if (c.confidence.base !== c.confidence.head) {
      out.push({ ...base, kind: "confidence_changed", label: `${c.confidence.base ?? "none"} to ${c.confidence.head ?? "none"}`, detail: "detection confidence", severity: "info", approved: true, authorityIncrease: false, needsReview: false });
    }
    if (c.renamed_from) {
      out.push({ ...base, kind: "renamed", label: `${c.renamed_from} to ${c.name}`, detail: "matched by evidence overlap", severity: "info", approved: true, authorityIncrease: false, needsReview: false });
    }
    for (const f of c.findings_delta.new) {
      out.push({ ...base, kind: "finding_new", label: f.rule_id, detail: `${f.severity} at line ${f.line}`, severity: f.severity === "critical" || f.severity === "high" ? "high" : f.severity === "medium" ? "medium" : "info", approved: false, authorityIncrease: false, needsReview: f.severity === "critical", fingerprint: f.fingerprint });
    }
    for (const f of c.findings_delta.resolved) {
      out.push({ ...base, kind: "finding_resolved", label: f.rule_id, detail: "no longer present", severity: "info", approved: true, authorityIncrease: false, needsReview: false, fingerprint: f.fingerprint });
    }
  }
  for (const a of diff.agents.added) {
    const hi = a.capabilities.some((c) => highImpact.has(c)) || a.integrations.some((i) => sensitive.has(i));
    out.push({ agentId: a.agent_id, agentName: displayName(a.agent_id, a.name), agentPath: a.path, kind: "agent_added", label: a.name, detail: a.drift_reasons.join("; "), severity: a.drift_severity, approved: a.approved, authorityIncrease: hi, needsReview: hi && !a.approved, population: true });
  }
  for (const a of diff.agents.removed) {
    out.push({ agentId: a.agent_id, agentName: a.name, agentPath: a.path, kind: "agent_removed", label: a.name, detail: "no longer detected", severity: a.drift_severity, approved: true, authorityIncrease: false, needsReview: false, population: true });
  }

  out.sort((a, b) => Number(b.needsReview) - Number(a.needsReview) || Number(b.authorityIncrease) - Number(a.authorityIncrease) || DRIFT_RANK[b.severity] - DRIFT_RANK[a.severity] || a.agentName.localeCompare(b.agentName) || a.label.localeCompare(b.label));
  return out;
}

export interface ChangeGroup {
  kind: ChangeKind;
  label: string;
  items: Change[];
}

const GROUP_ORDER: ChangeKind[] = ["capability_added", "integration_added", "dimension_increased", "agent_added", "finding_new", "provider_added", "confidence_changed", "renamed", "capability_removed", "integration_removed", "dimension_decreased", "provider_removed", "finding_resolved", "agent_removed"];

export function groupChanges(items: Change[]): ChangeGroup[] {
  const byKind = new Map<ChangeKind, Change[]>();
  for (const item of items) {
    const list = byKind.get(item.kind) ?? [];
    list.push(item);
    byKind.set(item.kind, list);
  }
  return GROUP_ORDER.filter((k) => byKind.has(k)).map((kind) => ({ kind, label: KIND_LABEL[kind], items: byKind.get(kind) ?? [] }));
}

export function driftSummary(diff: DiffDocument) {
  return diff.summary;
}
