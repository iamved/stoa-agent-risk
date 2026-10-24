/**
 * Policies (stoa-policy/0.1) as the dashboard shows them: the document the
 * repository carries, the outcomes the traces recorded per policy, and which
 * money-moving or high-impact tools have no policy scoped to them. Read
 * from the runtime slot; absent it, everything here is empty.
 */
import type { Envelope, PolicyCounts, PolicyEvent, PolicySpecRecord } from "./types";
import { toolsOf, uniqueAgents, type UniqueAgent } from "./agents";
import { runtimeSlot } from "./runtime";

export interface PolicyRow extends PolicySpecRecord {
  counts: PolicyCounts | null;
  /** Agents the scope resolves to. */
  agents: UniqueAgent[];
}

const EMPTY: PolicyCounts = { evaluated: 0, allowed: 0, blocked: 0, would_block: 0, escalated: 0, masked: 0, logged: 0, error: 0 };

export function policyMode(env: Envelope): "observe" | "enforce" | null {
  return runtimeSlot(env)?.policies?.document?.mode ?? null;
}

export function hasPolicies(env: Envelope): boolean {
  const block = runtimeSlot(env)?.policies;
  return Boolean(block && (block.document?.policies.length || Object.keys(block.summary).length));
}

/** The agents a scope names: every agent for "*", else the one whose name or id matches. */
export function scopedAgents(env: Envelope, scope: { agent: string }): UniqueAgent[] {
  const agents = uniqueAgents(env);
  if (!scope.agent || scope.agent === "*") return agents;
  return agents.filter((u) => u.name === scope.agent || u.id === scope.agent || u.records.some((r) => r.id === scope.agent));
}

export function policyRows(env: Envelope): PolicyRow[] {
  const block = runtimeSlot(env)?.policies;
  if (!block) return [];
  const rows: PolicyRow[] = (block.document?.policies ?? []).map((p) => ({ ...p, counts: block.summary[p.id] ?? null, agents: scopedAgents(env, p.scope) }));
  // Outcomes for a policy the document no longer lists still show, as a row with no spec.
  for (const [id, counts] of Object.entries(block.summary)) {
    if (!rows.some((r) => r.id === id)) rows.push({ id, title: "(not in the current policy file)", scope: { agent: "*" }, trigger: "any", condition: {}, condition_text: "", action: "log", fail: "open", enforced: false, counts, agents: [] });
  }
  const order = { block: 0, escalate: 1, mask: 2, log: 3, allow: 4 };
  return rows.sort((a, b) => (b.counts?.blocked ?? 0) - (a.counts?.blocked ?? 0) || (b.counts?.would_block ?? 0) - (a.counts?.would_block ?? 0) || (b.counts?.escalated ?? 0) - (a.counts?.escalated ?? 0) || order[a.action] - order[b.action] || a.id.localeCompare(b.id));
}

const COUNT_KEYS = ["evaluated", "allowed", "blocked", "would_block", "escalated", "masked", "logged", "error"] as const;

export function policyTotals(env: Envelope): PolicyCounts & { policies: number; enforced: number } {
  const rows = policyRows(env);
  const total: Record<(typeof COUNT_KEYS)[number], number> = { ...EMPTY };
  for (const r of rows) for (const k of COUNT_KEYS) total[k] += Number(r.counts?.[k] ?? 0);
  return { ...total, policies: rows.length, enforced: rows.filter((r) => r.enforced).length };
}

export interface PolicyEventLine extends PolicyEvent { agent: string }

/** Outcomes that changed or would have changed a call, newest first. */
export function policyEvents(env: Envelope, limit = 50): PolicyEventLine[] {
  const slot = runtimeSlot(env);
  if (!slot) return [];
  const out: PolicyEventLine[] = [];
  for (const [agentId, summary] of Object.entries(slot.analysis.agents)) {
    const name = uniqueAgents(env).find((u) => u.records.some((r) => r.id === agentId))?.name ?? agentId;
    for (const e of summary.policy_events ?? []) out.push({ ...e, agent: name });
  }
  return out.sort((a, b) => (b.ts ?? "").localeCompare(a.ts ?? "")).slice(0, limit);
}

/** The policies whose scope covers an agent and, when it names one, the tool. */
export function policiesFor(env: Envelope, agent: UniqueAgent, tool?: string): PolicySpecRecord[] {
  const doc = runtimeSlot(env)?.policies?.document;
  if (!doc) return [];
  return doc.policies.filter((p) => {
    if (!(p.scope.agent === "*" || p.scope.agent === agent.name || p.scope.agent === agent.id || agent.records.some((r) => r.id === p.scope.agent))) return false;
    if (tool !== undefined && p.scope.tool && p.scope.tool !== tool) return false;
    return p.trigger === "tool_call" || p.trigger === "any";
  });
}

export interface UnprotectedEdge { agent: UniqueAgent; tool: string; why: "money" | "high impact" }

/** Money-moving or high-impact tools with no block or escalate policy scoped to them. Empty without a policy document. */
export function unprotectedEdges(env: Envelope): UnprotectedEdge[] {
  if (!runtimeSlot(env)?.policies?.document) return [];
  const out: UnprotectedEdge[] = [];
  for (const u of uniqueAgents(env)) {
    for (const t of toolsOf(u)) {
      if (!(t.money_action || t.high_impact)) continue;
      const guarded = policiesFor(env, u, t.name).some((p) => p.action === "block" || p.action === "escalate");
      if (!guarded) out.push({ agent: u, tool: t.name, why: t.money_action ? "money" : "high impact" });
    }
  }
  return out.sort((a, b) => a.agent.name.localeCompare(b.agent.name) || a.tool.localeCompare(b.tool));
}

export const ACTION_LABEL: Record<string, string> = { block: "Block", escalate: "Escalate", mask: "Mask", log: "Log", allow: "Allow" };
export const OUTCOME_LABEL: Record<string, string> = { blocked: "blocked", would_block: "would block", escalated: "escalated", masked: "masked", logged: "logged", allowed: "allowed", error: "error" };
