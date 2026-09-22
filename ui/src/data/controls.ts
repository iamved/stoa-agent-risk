/**
 * Controls and safeguards, read from what the scanner observed: the
 * `controls_observed` on each dimension entry, tool guards and idempotency
 * flags, and the control-family findings (CTRL rules, AI003, AI007). No new
 * scoring; grouping and counting only.
 */
import type { Agent, Envelope, Severity, ToolRecord } from "./types";
import { autonomyOf, capabilitiesOf, safeguardsOf, toolsOf, uniqueAgents, type UniqueAgent } from "./agents";
import { SAFEGUARD_SUBTITLE, prose } from "./labels";
import { SEVERITY_RANK, activeFindings, agentLabel, findingTitle, pluralize, type FindingRef } from "./selectors";

export const CONTROL_LABEL: Record<string, string> = {
  approval: "Human approval",
  kill_switch: "Kill switch",
  authentication: "Authentication",
  validation: "Input validation",
  rate_limit: "Rate limiting",
  observability: "Observability",
  deterministic_sampling: "Deterministic sampling",
  sandbox: "Sandboxing",
};
/** Controls shown in the coverage list. Others the scanner may report stay in the per-agent chips. */
export const COVERAGE_CONTROLS = ["approval", "kill_switch", "authentication", "validation", "rate_limit", "observability", "deterministic_sampling", "sandbox"];

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
  const active = activeFindings(env);
  return env.registry.agents
    .map((agent) => {
      const observed = new Set<string>();
      for (const d of agent.dimension_assessment?.dimensions ?? []) for (const c of d.controls_observed) observed.add(c);
      // A kill switch is reported the other way round: CTRL007 fires when none is
      // observed. So an assessed agent (medium or high confidence) with no CTRL007
      // finding showed one.
      const assessed = agent.confidence === "medium" || agent.confidence === "high";
      const noKillSwitch = active.some((r) => r.finding.rule_id === "CTRL007" && r.agents.some((a) => a.id === agent.id));
      if (assessed && !noKillSwitch) observed.add("kill_switch");
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
  const ids = new Set<string>(COVERAGE_CONTROLS);
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
  for (const ref of activeFindings(env)) {
    if (!isControlFinding(ref, env)) continue;
    const g = map.get(ref.finding.rule_id);
    if (g) {
      g.refs.push(ref);
      if (SEVERITY_RANK[ref.finding.severity] > SEVERITY_RANK[g.worst]) g.worst = ref.finding.severity;
    } else map.set(ref.finding.rule_id, { rule_id: ref.finding.rule_id, title: findingTitle(env, ref.finding), worst: ref.finding.severity, refs: [ref] });
  }
  return [...map.values()].sort((a, b) => SEVERITY_RANK[b.worst] - SEVERITY_RANK[a.worst] || b.refs.length - a.refs.length);
}

// --- safeguards by unique agent ------------------------------------------------------------
//
// "Detected" means the scanner saw the safeguard in the scanned sources. "Not
// detected" means it looked and did not; the safeguard may still exist in the
// business process, outside what was scanned. "Verified" is reserved for a
// runtime or attestation source, which does not exist yet, so it is never shown.

export type SafeguardState = "detected" | "not_detected" | "not_applicable";

export const SAFEGUARD_STATE_LABEL: Record<SafeguardState, string> = { detected: "Detected", not_detected: "Not detected", not_applicable: "Not applicable" };

export interface SafeguardRow {
  agent: UniqueAgent;
  states: Record<string, SafeguardState>;
  tools: ToolRecord[];
  toolsWithGuardrail: number;
  moneyTools: number;
  moneyToolsWithoutGuardrail: number;
  retriesWithoutIdempotency: number;
  gaps: FindingRef[];
}

const ACTS_ALONE = new Set(["unrestricted_autonomous", "bounded_autonomous"]);

/** Human approval is expected of an agent that acts on its own and has a high-impact or money-moving tool or capability. */
export function approvalApplies(env: Envelope, agent: UniqueAgent): boolean {
  const highImpact = new Set(env.vocabulary.high_impact_capabilities);
  const reach = toolsOf(agent).some((t) => t.high_impact || t.money_action) || capabilitiesOf(agent).some((c) => highImpact.has(c));
  return reach && ACTS_ALONE.has(autonomyOf(agent) ?? "");
}

export function safeguardRows(env: Envelope): SafeguardRow[] {
  const active = activeFindings(env);
  return uniqueAgents(env)
    .map((agent) => {
      const detected = new Set(safeguardsOf(agent));
      // The kill-switch rule (CTRL007) runs on code and fires when none is seen.
      // So it is detected only for an agent with an assessed code record on which the rule stayed silent.
      const assessedCode = agent.records.some((a) => a.source !== "iac" && (a.confidence === "medium" || a.confidence === "high"));
      const noKillSwitch = active.some((r) => r.finding.rule_id === "CTRL007" && r.uniqueAgents.includes(agent));
      if (assessedCode && !noKillSwitch) detected.add("kill_switch");
      else detected.delete("kill_switch");
      const states: Record<string, SafeguardState> = {};
      for (const id of COVERAGE_CONTROLS) {
        states[id] = id === "approval" && !approvalApplies(env, agent) && !detected.has(id) ? "not_applicable" : detected.has(id) ? "detected" : "not_detected";
      }
      const tools = toolsOf(agent);
      const money = tools.filter((t) => t.money_action);
      return {
        agent,
        states,
        tools,
        toolsWithGuardrail: tools.filter((t) => t.guards.length > 0).length,
        moneyTools: money.length,
        moneyToolsWithoutGuardrail: money.filter((t) => t.guards.length === 0).length,
        retriesWithoutIdempotency: tools.filter((t) => t.retry && !t.idempotency_key).length,
        gaps: active.filter((r) => isControlFinding(r, env) && r.uniqueAgents.includes(agent)),
      };
    })
    .sort((a, b) => b.gaps.length - a.gaps.length || a.agent.name.localeCompare(b.agent.name));
}

export interface SafeguardCoverage {
  id: string;
  label: string;
  subtitle: string;
  detected: number;
  /** Agents the safeguard is relevant to. */
  applicable: number;
  /** "of 2 agents that act on their own with high-impact tools", or "of 5 agents" when applicability cannot be derived. */
  denominator: string;
}

/** Safeguards listed on the Controls screen. Human approval has its own tile and the approval gate on the Overview; sandboxing is left out of the list. */
export const LISTED_CONTROLS = COVERAGE_CONTROLS.filter((id) => id !== "approval" && id !== "sandbox");

export function safeguardCoverage(env: Envelope): SafeguardCoverage[] {
  const rows = safeguardRows(env);
  return LISTED_CONTROLS.map((id) => {
    const relevant = rows.filter((r) => r.states[id] !== "not_applicable");
    const narrowed = id === "approval";
    return {
      id,
      label: controlLabel(id),
      subtitle: SAFEGUARD_SUBTITLE[id] ?? "",
      detected: relevant.filter((r) => r.states[id] === "detected").length,
      applicable: relevant.length,
      denominator: narrowed ? `of ${pluralize(relevant.length, "agent")} that ${relevant.length === 1 ? "acts" : "act"} on ${relevant.length === 1 ? "its" : "their"} own with high-impact tools` : `of ${pluralize(relevant.length, "agent")}`,
    };
  });
}

export interface SafeguardTotals {
  /** Control findings: the scan looked for a safeguard and did not find one. */
  gaps: number;
  moneyTools: number;
  moneyToolsWithoutGuardrail: number;
  /** A money action that can repeat on retry (AI008). */
  doublePayment: FindingRef[];
}

export function safeguardTotals(env: Envelope): SafeguardTotals {
  const rows = safeguardRows(env);
  return {
    gaps: gapGroups(env).reduce((n, g) => n + g.refs.length, 0),
    moneyTools: rows.reduce((n, r) => n + r.moneyTools, 0),
    moneyToolsWithoutGuardrail: rows.reduce((n, r) => n + r.moneyToolsWithoutGuardrail, 0),
    doublePayment: activeFindings(env).filter((r) => r.finding.rule_id === "AI008"),
  };
}

export interface Recommendation {
  /** The rule behind it, for the link to its findings. Never shown as text. */
  ruleId: string;
  severity: Severity;
  /** What is missing, in plain words. */
  title: string;
  /** What to do, one sentence, in the scanner's words. */
  action: string;
  agents: number;
}

const SCENE_SETTING = /^(this|these|an?|the|traces|reported|observability|stoa-declared\.toml)\b/i;

/** The instruction sentence of a remediation: a long one explains first and instructs last. */
export function actionSentence(text: string): string {
  const sentences = prose(text).split(/(?<=[.!?])\s+(?=[A-Z[])/).map((x) => x.trim()).filter(Boolean);
  if (!sentences.length) return "";
  return [...sentences].reverse().find((x) => !SCENE_SETTING.test(x)) ?? sentences[sentences.length - 1]!;
}

/** The safeguards most worth adding: the control gaps by severity, at most `n`, without rule ids or file paths. */
export function recommendations(env: Envelope, n = 3): Recommendation[] {
  return gapGroups(env).slice(0, n).map((g) => ({
    ruleId: g.rule_id,
    severity: g.worst,
    title: g.title,
    action: actionSentence(env.rules[g.rule_id]?.remediation ?? g.refs[0]?.finding.remediation ?? ""),
    agents: new Set(g.refs.flatMap((r) => r.uniqueAgents.map((u) => u.id))).size,
  }));
}
