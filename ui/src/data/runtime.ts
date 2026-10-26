/**
 * What the traces showed (the envelope's `runtime` slot, dashboard-runtime/1.0).
 * Everything here reads the slot and the enriched registry; nothing is
 * scored again. Absent the slot, every function says so (null, [], "") and
 * the screens fall back to the static view.
 */
import type { DetectrBlock, DetectrFinding, Envelope, FlagEvent, ReconcileRow, RuntimeAgentSummary, RuntimeDriftEvent, RuntimeSlot } from "./types";
import { uniqueAgentOf, uniqueAgents, type UniqueAgent } from "./agents";
import { SEVERITY_RANK, runtimeFindingRefs, type FindingRef } from "./selectors";

export function runtimeSlot(env: Envelope): RuntimeSlot | null {
  return env.runtime ?? null;
}

export function hasRuntime(env: Envelope): boolean {
  return Boolean(env.runtime && env.runtime.analysis.window.span_count > 0);
}

export interface RuntimeWindow { start: string | null; end: string | null; spans: number; days: number }

export function runtimeWindow(env: Envelope): RuntimeWindow | null {
  const slot = runtimeSlot(env);
  if (!slot) return null;
  const { start, end, span_count } = slot.analysis.window;
  const days = start && end ? Math.max(1, Math.round((Date.parse(end) - Date.parse(start)) / 86_400_000)) : 0;
  return { start, end, spans: span_count, days };
}

export interface ChainStatus { ok: boolean; records: number; grade: string; broken: string[]; unchained: number }

export function chainStatus(env: Envelope): ChainStatus | null {
  const slot = runtimeSlot(env);
  if (!slot) return null;
  const files = slot.chain.files;
  const grades = [...new Set(files.map((f) => f.key_grade))].filter((g) => g !== "none");
  return { ok: slot.chain.ok, records: slot.chain.records, grade: grades.length === 1 ? grades[0]! : grades.length ? "mixed" : "none", broken: files.filter((f) => !f.ok).map((f) => `${f.file}: line ${f.first_break}, ${f.break_reason}`), unchained: files.filter((f) => f.unchained).length };
}

/** "active" when any record of the agent has spans in the window, "idle" when the slot is present and none do, null without traces. */
export function liveness(env: Envelope, agent: UniqueAgent): "active" | "idle" | null {
  if (!hasRuntime(env)) return null;
  return agent.records.some((r) => r.liveness_state === "active") ? "active" : "idle";
}

/** The agent's runtime summary from the analysis, merged across its records (the first record with evidence). */
export function summaryOf(env: Envelope, agent: UniqueAgent): RuntimeAgentSummary | null {
  const slot = runtimeSlot(env);
  if (!slot) return null;
  for (const r of agent.records) {
    const s = slot.analysis.agents[r.id];
    if (s) return s;
  }
  return null;
}

export interface ReconcileLine extends ReconcileRow { agent: UniqueAgent | null }

export function reconcileRows(env: Envelope): ReconcileLine[] {
  const slot = runtimeSlot(env);
  if (!slot) return [];
  // One row per unique agent: the first record's row carries the name, the others fold in.
  const byUnique = new Map<string, ReconcileLine>();
  for (const row of slot.reconcile.agents) {
    const agent = uniqueAgentOf(env, row.agent_id);
    const key = agent?.id ?? row.agent_id;
    const existing = byUnique.get(key);
    if (!existing) byUnique.set(key, { ...row, name: agent?.name ?? row.name, agent });
    else {
      existing.has_runtime_evidence = existing.has_runtime_evidence || row.has_runtime_evidence;
      for (const k of ["declared_and_used", "used_but_undeclared", "declared_but_dormant"] as const) existing[k] = [...existing[k], ...row[k].filter((t) => !existing[k].some((x) => x.tool === t.tool))];
    }
  }
  return [...byUnique.values()].sort((a, b) => b.used_but_undeclared.length - a.used_but_undeclared.length || Number(b.has_runtime_evidence) - Number(a.has_runtime_evidence) || a.name.localeCompare(b.name));
}

/** RT-family findings as shown, highest severity first. */
/** Hallucination DetectR rows: per agent, then the findings, most severe first. */
export function detectr(env: Envelope): { block: DetectrBlock; agents: { id: string; name: string; agentId: string | null; row: DetectrBlock["by_agent"][string] }[]; findings: DetectrFinding[] } | null {
  const block = runtimeSlot(env)?.detectr;
  if (!block || !block.with_content) return null;
  const agents = Object.entries(block.by_agent).map(([id, row]) => {
    const unique = uniqueAgents(env).find((u) => u.records.some((r) => r.agent_id === id) || u.id === id);
    return { id, name: unique?.name ?? id, agentId: unique?.id ?? null, row };
  }).sort((a, b) => b.row.findings - a.row.findings || a.name.localeCompare(b.name));
  const findings = [...block.findings].sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || a.rule_id.localeCompare(b.rule_id));
  return { block, agents, findings };
}

export function runtimeFindings(env: Envelope): FindingRef[] {
  return runtimeFindingRefs(env).sort((a, b) => SEVERITY_RANK[b.finding.severity] - SEVERITY_RANK[a.finding.severity] || a.finding.rule_id.localeCompare(b.finding.rule_id));
}

export const FLAG_LABEL: Record<string, string> = {
  approval_bypassed: "Money moved with no approval",
  over_declared_limit: "Over the declared limit",
  undeclared_tool: "Tool the scan never listed",
  new_counterparty: "New counterparty",
  burst: "Burst of calls",
  repeat_failure: "Repeated failures",
  model_changed: "Model changed",
  integration_changed: "Integration changed",
  no_registry: "No registry found",
};

export function flagLabel(flag: string): string {
  return FLAG_LABEL[flag] ?? flag.replace(/_/g, " ");
}

export interface FlagDay { day: string; counts: Record<string, number>; total: number }

/** Flagged spans by day across all agents, oldest first, and the totals per flag. */
export function flagTimeline(env: Envelope): { days: FlagDay[]; totals: Record<string, number>; events: (FlagEvent & { agent: string })[] } {
  const slot = runtimeSlot(env);
  const days = new Map<string, FlagDay>();
  const totals: Record<string, number> = {};
  const events: (FlagEvent & { agent: string })[] = [];
  if (!slot) return { days: [], totals, events };
  for (const [agentId, summary] of Object.entries(slot.analysis.agents)) {
    const name = uniqueAgentOf(env, agentId)?.name ?? agentId;
    for (const event of summary.flag_events ?? []) {
      events.push({ ...event, agent: name });
      const day = (event.ts ?? "").slice(0, 10) || "unknown";
      const entry = days.get(day) ?? { day, counts: {}, total: 0 };
      for (const flag of event.flags) {
        if (flag === "no_registry") continue;
        entry.counts[flag] = (entry.counts[flag] ?? 0) + 1;
        entry.total += 1;
        totals[flag] = (totals[flag] ?? 0) + 1;
      }
      days.set(day, entry);
    }
  }
  events.sort((a, b) => (a.ts ?? "").localeCompare(b.ts ?? ""));
  return { days: [...days.values()].sort((a, b) => a.day.localeCompare(b.day)), totals, events };
}

const DRIFT_KIND_LABEL: Record<string, string> = {
  approval_rate_drop: "Approval rate fell",
  amount_exceeds_declared_max_per_action: "Amount over the declared limit",
  new_high_impact_capability: "New high-impact capability",
  new_capability: "New capability",
  new_integration: "New integration",
  frequency_shift: "Frequency shifted",
  capability_no_longer_observed: "Capability no longer observed",
};

function driftValue(v: unknown): string {
  if (v && typeof v === "object" && "amount" in (v as Record<string, unknown>)) {
    const a = v as { amount: number; currency?: string };
    return `${a.currency === "USD" || !a.currency ? "$" : ""}${a.amount.toLocaleString("en-US")}${a.currency && a.currency !== "USD" ? ` ${a.currency}` : ""}`;
  }
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export interface DriftLine { cls: "info" | "medium" | "high"; label: string; agent: string; detail: string }

export function driftLines(env: Envelope): DriftLine[] {
  const slot = runtimeSlot(env);
  if (!slot?.drift) return [];
  const order = { high: 0, medium: 1, info: 2 };
  return (slot.drift.events ?? []).map((e: RuntimeDriftEvent) => ({
    cls: e.class,
    label: DRIFT_KIND_LABEL[e.kind] ?? e.kind.replace(/_/g, " "),
    agent: uniqueAgentOf(env, e.agent_id)?.name ?? e.agent_id,
    detail: Object.entries(e).filter(([k]) => !["class", "kind", "agent_id"].includes(k)).map(([k, v]) => `${k.replace(/_/g, " ")} ${driftValue(v)}`).join(" · "),
  })).sort((a, b) => order[a.cls] - order[b.cls] || a.agent.localeCompare(b.agent));
}

export interface ObservedApproval { approved: number; total: number; rate: number | null }

/** Approval on money actions across every money-moving agent in the window. Null without traces or money actions. */
export function observedApproval(env: Envelope): ObservedApproval | null {
  if (!hasRuntime(env)) return null;
  let approved = 0, total = 0;
  for (const u of uniqueAgents(env)) {
    const s = summaryOf(env, u);
    if (!s) continue;
    total += s.money_actions ?? 0;
    approved += s.money_actions_approved ?? 0;
  }
  if (!total) return null;
  return { approved, total, rate: approved / total };
}

/** Tool and action calls in the window scaled to 30 days, for the loss model's monthly volume. Null without traces. */
export function observedMonthlyVolume(env: Envelope): number | null {
  const slot = runtimeSlot(env);
  const window = runtimeWindow(env);
  if (!slot || !window || !window.days) return null;
  let actions = 0;
  for (const s of Object.values(slot.analysis.agents)) actions += (s.spans_by_kind["action"] ?? 0) + (s.spans_by_kind["tool_call"] ?? 0);
  if (!actions) return null;
  return Math.round((actions / window.days) * 30);
}

/** The agents with evidence, idle, and unmatched, for the Runtime screen's header line. */
export function coverage(env: Envelope): { active: number; idle: number; unmatched: number; total: number } | null {
  const slot = runtimeSlot(env);
  if (!slot) return null;
  const agents = uniqueAgents(env);
  const active = agents.filter((u) => liveness(env, u) === "active").length;
  return { active, idle: agents.length - active, unmatched: slot.analysis.unmatched_agents.length, total: agents.length };
}
