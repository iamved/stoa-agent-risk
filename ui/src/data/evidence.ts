/**
 * Evidence views over data the scanner already produced: the assurance
 * packet, the underwriting derivation, the register, the diff. Nothing here
 * scores anything; it groups and counts.
 */
import type { AssuranceArea, AssurancePacket, AssuranceRow, Envelope, Finding, Severity } from "./types";
import { SEVERITY_RANK, activeFindings, agentLabel, type FindingRef } from "./selectors";

export interface FixItem {
  rule_id: string;
  title: string;
  severity: Severity;
  remediation: string;
  soWhat: string;
  refs: FindingRef[];
  owners: string[];
}

/** Critical and high findings merged by rule and fix, worst first: the shortest path that clears them. */
export function fixFirst(env: Envelope, minSeverity: Severity = "high"): FixItem[] {
  const byKey = new Map<string, FixItem>();
  for (const ref of activeFindings(env.registry)) {
    const f = ref.finding;
    if (SEVERITY_RANK[f.severity] < SEVERITY_RANK[minSeverity]) continue;
    const key = `${f.rule_id}::${f.remediation}`;
    let item = byKey.get(key);
    if (!item) {
      item = { rule_id: f.rule_id, title: f.title, severity: f.severity, remediation: f.remediation, soWhat: f.crosswalk?.so_what ?? f.title, refs: [], owners: [] };
      byKey.set(key, item);
    }
    item.refs.push(ref);
    if (SEVERITY_RANK[f.severity] > SEVERITY_RANK[item.severity]) item.severity = f.severity;
    for (const a of ref.agents) {
      const owner = a.declared?.owner;
      if (owner && !item.owners.includes(owner)) item.owners.push(owner);
    }
  }
  return [...byKey.values()].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.refs.length - a.refs.length || a.rule_id.localeCompare(b.rule_id));
}

export type Status = AssuranceRow["status"];
export const STATUS_ORDER: Status[] = ["scanned", "declared", "ingested", "observed", "not_provided"];
export const STATUS_LABEL: Record<Status, string> = { scanned: "Scanned", declared: "Declared", ingested: "Ingested", observed: "Observed", not_provided: "Not provided" };

export interface AreaSummary {
  key: string;
  name: string;
  group: string;
  layers: string;
  counts: Record<Status, number>;
  rows: { field: string; status: Status; agent?: string; evidence?: Record<string, unknown> | null }[];
}

function rowsOf(area: AssuranceArea): AreaSummary["rows"] {
  const out: AreaSummary["rows"] = [];
  for (const r of area.rows ?? []) out.push({ field: r.field, status: r.status, evidence: r.evidence ?? null });
  for (const a of area.agents ?? []) {
    for (const r of Object.values(a.fields)) out.push({ field: r.field, status: r.status, agent: a.name, evidence: r.evidence ?? null });
  }
  return out;
}

export function areaSummaries(packet: AssurancePacket): AreaSummary[] {
  return Object.entries(packet.areas).map(([key, area]) => {
    const rows = rowsOf(area);
    const counts: Record<Status, number> = { scanned: 0, declared: 0, ingested: 0, observed: 0, not_provided: 0 };
    for (const r of rows) counts[r.status] += 1;
    const layers = Array.isArray(area.layers) ? area.layers.join(" + ") : String(area.layers ?? "");
    return { key, name: area.area_name, group: area.group, layers, counts, rows };
  });
}

export function packetTotals(summaries: AreaSummary[]): Record<Status, number> {
  const totals: Record<Status, number> = { scanned: 0, declared: 0, ingested: 0, observed: 0, not_provided: 0 };
  for (const s of summaries) for (const st of STATUS_ORDER) totals[st] += s.counts[st];
  return totals;
}

export interface AgentControls {
  agentId: string;
  name: string;
  observed: string[];
  declaredAutonomy: string | null;
  inferredAutonomy: string | null;
  maxPerAction: string | null;
}

/** Controls the scanner observed per agent (the union across its dimension entries) next to what was declared. */
export function controlsByAgent(env: Envelope): AgentControls[] {
  return env.registry.agents.map((a) => {
    const observed = new Set<string>();
    for (const d of a.dimension_assessment?.dimensions ?? []) for (const c of d.controls_observed) observed.add(c);
    const m = a.declared?.economic_authority?.max_per_action;
    return { agentId: a.id, name: agentLabel(a), observed: [...observed].sort(), declaredAutonomy: a.declared?.autonomy_intent ?? null, inferredAutonomy: a.autonomy_level?.level ?? null, maxPerAction: m ? `${m.amount.toLocaleString()} ${m.currency}` : null };
  });
}

export function findingsByRule(refs: FindingRef[]): { rule_id: string; count: number; worst: Severity; sample: Finding }[] {
  const map = new Map<string, { rule_id: string; count: number; worst: Severity; sample: Finding }>();
  for (const r of refs) {
    const e = map.get(r.finding.rule_id);
    if (e) {
      e.count += 1;
      if (SEVERITY_RANK[r.finding.severity] > SEVERITY_RANK[e.worst]) e.worst = r.finding.severity;
    } else map.set(r.finding.rule_id, { rule_id: r.finding.rule_id, count: 1, worst: r.finding.severity, sample: r.finding });
  }
  return [...map.values()].sort((a, b) => SEVERITY_RANK[b.worst] - SEVERITY_RANK[a.worst] || b.count - a.count);
}
