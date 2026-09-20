/**
 * Controls and safeguards, read from what the scanner observed: the
 * `controls_observed` on each dimension entry, tool guards and idempotency
 * flags, and the control-family findings (CTRL rules, AI003, AI007). No new
 * scoring; grouping and counting only.
 */
import type { Agent, Envelope, Severity } from "./types";
import { SEVERITY_RANK, activeFindings, agentLabel, type FindingRef } from "./selectors";

export const CONTROL_LABEL: Record<string, string> = {
  approval: "Human approval",
  authentication: "Authentication",
  validation: "Input validation",
  rate_limit: "Rate limiting",
  observability: "Observability",
  deterministic_sampling: "Deterministic sampling",
  pinned_model: "Pinned model",
  sandbox: "Sandboxing",
  guardrail: "Guardrail",
  ai_gateway: "AI gateway",
};

export function controlLabel(id: string): string {
  return CONTROL_LABEL[id] ?? id.replace(/_/g, " ");
}

export interface AgentControlRow {
  agent: Agent;
  name: string;
  observed: string[];
  toolGuards: number;
  toolsWithoutGuards: number;
  retriesWithoutIdempotency: number;
  gaps: FindingRef[];
}

export function isControlFinding(ref: FindingRef, env: Envelope): boolean {
  const id = ref.finding.rule_id;
  return id.startsWith("CTRL") || id === "AI003" || id === "AI007" || id === "AI008" || env.rules[id]?.category === "control";
}

export function agentControlRows(env: Envelope): AgentControlRow[] {
  const active = activeFindings(env.registry);
  return env.registry.agents
    .map((agent) => {
      const observed = new Set<string>();
      for (const d of agent.dimension_assessment?.dimensions ?? []) for (const c of d.controls_observed) observed.add(c);
      const tools = agent.tools ?? [];
      return {
        agent,
        name: agentLabel(agent),
        observed: [...observed].sort(),
        toolGuards: tools.filter((t) => t.guards.length > 0).length,
        toolsWithoutGuards: tools.filter((t) => (t.high_impact || t.money_action) && t.guards.length === 0).length,
        retriesWithoutIdempotency: tools.filter((t) => t.retry && !t.idempotency_key).length,
        gaps: active.filter((r) => isControlFinding(r, env) && r.agents.some((a) => a.id === agent.id)),
      };
    })
    .sort((a, b) => b.gaps.length - a.gaps.length || a.name.localeCompare(b.name));
}

export interface ControlCoverage {
  id: string;
  label: string;
  agents: number;
  total: number;
}

/** How many agents show each control at least once. */
export function coverage(env: Envelope): ControlCoverage[] {
  const rows = agentControlRows(env);
  const ids = new Set<string>(Object.keys(CONTROL_LABEL));
  for (const r of rows) for (const c of r.observed) ids.add(c);
  return [...ids]
    .map((id) => ({ id, label: controlLabel(id), agents: rows.filter((r) => r.observed.includes(id)).length, total: rows.length }))
    .sort((a, b) => b.agents - a.agents || a.label.localeCompare(b.label));
}

export interface GapGroup {
  rule_id: string;
  title: string;
  worst: Severity;
  refs: FindingRef[];
}

export function gapGroups(env: Envelope): GapGroup[] {
  const map = new Map<string, GapGroup>();
  for (const ref of activeFindings(env.registry)) {
    if (!isControlFinding(ref, env)) continue;
    const g = map.get(ref.finding.rule_id);
    if (g) {
      g.refs.push(ref);
      if (SEVERITY_RANK[ref.finding.severity] > SEVERITY_RANK[g.worst]) g.worst = ref.finding.severity;
    } else map.set(ref.finding.rule_id, { rule_id: ref.finding.rule_id, title: ref.finding.title, worst: ref.finding.severity, refs: [ref] });
  }
  return [...map.values()].sort((a, b) => SEVERITY_RANK[b.worst] - SEVERITY_RANK[a.worst] || b.refs.length - a.refs.length);
}
