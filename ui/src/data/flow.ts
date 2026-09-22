/**
 * One agent's risk path: request, agent, approval gate, tools, reach. Built
 * for a unique agent from the same helpers every other screen uses (its
 * merged tools, the safeguard states of the Controls screen, the merged
 * findings of the Findings screen, the graph's reach edges), so the diagram
 * cannot disagree with the tiles above it. Layout is a fixed reading order:
 * a static scan knows what sits at each step, not the order things run in.
 */
import type { Envelope, Evidence, Severity, ToolRecord } from "./types";
import { autonomyOf, capabilitiesOf, declaredOf, frameworksOf, integrationsOf, providersOf, toolsOf, uniqueAgents, type UniqueAgent } from "./agents";
import { COVERAGE_CONTROLS, controlLabel, safeguardRows, type SafeguardRow, type SafeguardState } from "./controls";
import { prose } from "./labels";
import { SEVERITY_RANK, activeFindings, riskLevel, type FindingRef, type RiskLevel } from "./selectors";

export type LaneId = "entry" | "agent" | "gate" | "tools" | "reach";
export type NodeKind = "request" | "agent" | "gate" | "safeguard" | "tool" | "resource" | "service" | "empty";
/** How a box reads: a finding that needs attention, a lower one, a safeguard detected, one not detected, or nothing to say. */
export type Tone = "risk" | "warn" | "ok" | "missing" | "neutral";

export interface Lane { id: LaneId; title: string; sub: string; cx: number; w: number }

export const LANES: Lane[] = [
  { id: "entry", title: "Request arrives", sub: "Who can reach the agent", cx: 100, w: 176 },
  { id: "agent", title: "Agent decides", sub: "Model, harness, autonomy", cx: 378, w: 212 },
  { id: "gate", title: "Approval gate", sub: "Before a high-impact action", cx: 632, w: 156 },
  { id: "tools", title: "Tools it can call", sub: "Each with its own guardrails", cx: 886, w: 212 },
  { id: "reach", title: "What it can touch", sub: "Data, resources, services", cx: 1150, w: 212 },
];
export const FLOW_WIDTH = 1268;

/** Which step a rule's finding belongs to. Unlisted rules sit on the agent. */
const RULE_LANE: Record<string, LaneId> = {
  CTRL001: "entry", CTRL002: "entry", CTRL003: "entry", AI001: "entry",
  AI003: "gate", DECL001: "gate", RT001: "gate", RT005: "gate", CTRL005: "gate",
  AI002: "tools", AI008: "tools", CTRL006: "tools", DECL002: "tools", DECL003: "tools", RT002: "tools",
  AI006: "reach", NET001: "reach", NET002: "reach", SEC002: "reach", SEC003: "reach", DECL004: "reach", RT003: "reach",
};
/** Rules that report a safeguard not detected, by safeguard. */
const RULE_CONTROL: Record<string, string> = {
  CTRL001: "authentication", CTRL002: "validation", CTRL003: "rate_limit", CTRL005: "rate_limit",
  CTRL004: "observability", DECL005: "observability", RT004: "observability", CTRL006: "sandbox",
  CTRL007: "kill_switch", AI003: "approval", RT001: "approval", RT005: "approval", AI007: "deterministic_sampling",
};
const ENTRY_CONTROLS = ["authentication", "validation", "rate_limit"];
// Kept to the two safeguards a risk officer asks about first; the rest are on the Controls screen.
const AGENT_CONTROLS = ["kill_switch", "observability"];
const VERB: Record<string, string> = { reads: "reads", writes: "writes", network: "sends to" };

export interface Reach { cap: string; label: string; kind: string; runtime: boolean; hot: boolean; findings: FindingRef[] }

export interface FlowNode {
  id: string;
  lane: LaneId;
  kind: NodeKind;
  /** A safeguard chip hangs below its step, smaller than a main box. */
  small: boolean;
  label: string;
  cap: string;
  own: Tone;
  tone: Tone;
  findings: FindingRef[];
  control?: string;
  state?: SafeguardState;
  tool?: ToolRecord;
  exposed?: boolean;
  unsafeRetry?: boolean;
  reach?: Reach;
  sensitive?: boolean;
  harness?: string;
  mismatch?: boolean;
  /** Money-moving or high-impact tools behind the gate. */
  heavy?: number;
}

export interface FlowEdge { from: string; to: string; label?: string; tone?: "risk"; loose?: boolean }

export interface Flow {
  agent: UniqueAgent;
  nodes: FlowNode[];
  edges: FlowEdge[];
  findings: FindingRef[];
  row: SafeguardRow;
  providers: string[];
  harness: string;
  inferred: string | null;
  declared: string | null;
  /** IAM and grant lines the infrastructure scan read, verbatim. */
  permissions: string[];
  /** Everything else the scan read about the agent. */
  evidence: string[];
}

export function worstOf(refs: FindingRef[]): Severity | null {
  let worst: Severity | null = null;
  for (const r of refs) if (worst === null || SEVERITY_RANK[r.finding.severity] > SEVERITY_RANK[worst]) worst = r.finding.severity;
  return worst;
}

export function worstLevel(refs: FindingRef[]): RiskLevel | null {
  const w = worstOf(refs);
  return w ? riskLevel(w) : null;
}

function toneFor(own: Tone, refs: FindingRef[]): Tone {
  const level = worstLevel(refs);
  if (own === "risk" || level === "high") return "risk";
  return level ? "warn" : own;
}

export function laneOf(ruleId: string): LaneId {
  return RULE_LANE[ruleId] ?? "agent";
}

export function laneTitle(id: LaneId): string {
  return LANES.find((l) => l.id === id)!.title;
}

/** Agents worth drawing first: the ones with the most on their path. */
export function flowAgents(env: Envelope): UniqueAgent[] {
  const active = activeFindings(env);
  const weight = (u: UniqueAgent) => toolsOf(u).length + capabilitiesOf(u).length + active.filter((r) => r.uniqueAgents.includes(u)).length;
  return [...uniqueAgents(env)].sort((a, b) => weight(b) - weight(a) || a.name.localeCompare(b.name));
}

export function agentWorstLevel(env: Envelope, agent: UniqueAgent): RiskLevel | null {
  return worstLevel(activeFindings(env).filter((r) => r.uniqueAgents.includes(agent)));
}

function reachOf(env: Envelope, agent: UniqueAgent, findings: FindingRef[]): Reach[] {
  const ids = new Set(agent.records.map((a) => a.id));
  const hot = new Set(env.vocabulary.high_impact_capabilities);
  const nodes = new Map(env.graph.nodes.map((n) => [n.id, n]));
  const byCap = new Map<string, Reach>();
  for (const e of env.graph.edges) {
    if (!ids.has(e.source) || !(e.kind === "reads" || e.kind === "writes" || e.kind === "network")) continue;
    const node = nodes.get(e.target);
    if (!node || node.type !== "resource") continue;
    const cap = e.target.replace(/^resource_/, "");
    const matched = findings.filter((r) => e.findings.some((f) => r.evidence.some((x) => x.rule_id === f.rule_id && x.path === f.path && x.line === f.line)));
    const seen = byCap.get(cap);
    if (seen) {
      seen.runtime &&= e.provenance === "observed";
      for (const r of matched) if (!seen.findings.includes(r)) seen.findings.push(r);
    } else byCap.set(cap, { cap, label: node.label, kind: e.kind, runtime: e.provenance === "observed", hot: hot.has(cap), findings: matched });
  }
  // A capability the records carry but no graph edge names still counts as reach.
  for (const cap of capabilitiesOf(agent)) {
    if (byCap.has(cap) || cap === "tool_calling" || cap === "function_calling") continue;
    const node = nodes.get(`resource_${cap}`);
    if (node) byCap.set(cap, { cap, label: node.label, kind: "reads", runtime: false, hot: hot.has(cap), findings: [] });
  }
  return [...byCap.values()].sort((a, b) => Number(b.hot) - Number(a.hot) || a.label.localeCompare(b.label));
}

export function buildFlow(env: Envelope, agent: UniqueAgent): Flow {
  const findings = activeFindings(env).filter((r) => r.uniqueAgents.includes(agent));
  const row = safeguardRows(env).find((r) => r.agent === agent)!;
  const nodes: FlowNode[] = [];
  const edges: FlowEdge[] = [];
  const gaps = (control: string) => findings.filter((r) => RULE_CONTROL[r.finding.rule_id] === control);
  const add = (n: Omit<FlowNode, "tone" | "own" | "findings" | "small"> & Partial<Pick<FlowNode, "own" | "findings" | "small">>): FlowNode => {
    const node: FlowNode = { small: false, own: "neutral", findings: [], ...n, tone: "neutral" };
    node.tone = toneFor(node.own, node.findings);
    nodes.push(node);
    return node;
  };
  const safeguard = (lane: LaneId, control: string) => {
    const g = gaps(control);
    const state = row.states[control] ?? "not_detected";
    const on = state === "detected";
    add({ id: `control:${control}`, lane, kind: "safeguard", small: true, label: controlLabel(control), control, state,
      cap: state === "not_applicable" ? "not applicable" : g.length ? (on ? "detected, with a gap" : "gap reported") : on ? "detected" : "not detected",
      own: on ? "ok" : state === "not_applicable" ? "neutral" : "missing", findings: g });
  };

  const providers = providersOf(agent);
  const frameworks = frameworksOf(agent);
  const platform = agent.info.find((i) => i.platform)?.platform;
  const harness = frameworks.length ? frameworks.join(" + ") : platform ? `${platform} (managed)` : "raw provider calls";
  const inferred = autonomyOf(agent);
  const declared = declaredOf(agent)?.autonomy_intent ?? null;
  const mismatch = Boolean(inferred && declared && inferred !== declared);

  add({ id: "request", lane: "entry", kind: "request", label: "Incoming request", cap: "a user, system or another agent" });
  for (const c of ENTRY_CONTROLS) safeguard("entry", c);
  add({ id: "agent", lane: "agent", kind: "agent", label: agent.name, cap: `${harness} · ${providers.join(" + ") || "provider not detected"}`, own: mismatch ? "risk" : "neutral", harness, mismatch,
    findings: findings.filter((r) => laneOf(r.finding.rule_id) === "agent" && !RULE_CONTROL[r.finding.rule_id]) });
  for (const c of AGENT_CONTROLS) safeguard("agent", c);

  const tools = toolsOf(agent);
  const heavy = tools.filter((t) => t.money_action || t.high_impact);
  const approved = row.states["approval"] === "detected";
  add({ id: "gate", lane: "gate", kind: "gate", label: "Human approval", control: "approval", state: row.states["approval"], heavy: heavy.length,
    cap: approved ? "detected" : "no human approval detected", own: approved ? "ok" : heavy.length ? "missing" : "neutral",
    findings: findings.filter((r) => laneOf(r.finding.rule_id) === "gate") });

  const retryFindings = findings.filter((r) => r.finding.rule_id === "AI008");
  tools.forEach((t, i) => {
    const exposed = (t.money_action || t.high_impact) && t.guards.length === 0;
    const unsafeRetry = t.retry && !t.idempotency_key;
    const kind = t.money_action ? "money action" : t.high_impact ? "high impact" : t.kind.replace(/_/g, " ");
    add({ id: `tool:${i}`, lane: "tools", kind: "tool", label: t.name, tool: t, exposed, unsafeRetry,
      cap: t.guards.length ? `${kind} · guardrail detected` : exposed ? `${kind} · no guardrail detected` : kind,
      own: exposed || unsafeRetry ? "risk" : t.guards.length ? "ok" : "neutral",
      findings: unsafeRetry && t.money_action ? retryFindings.filter((r) => r.evidence.some((f) => f.path === t.path)) : [] });
  });
  if (!tools.length) add({ id: "no-tools", lane: "tools", kind: "empty", label: "", cap: "No tool definitions detected" });

  const sensitive = new Set(env.vocabulary.sensitive_integrations);
  for (const r of reachOf(env, agent, findings)) {
    add({ id: `reach:${r.cap}`, lane: "reach", kind: "resource", label: r.label, reach: r,
      cap: `${VERB[r.kind] ?? r.kind}${r.hot ? " · high impact" : ""}${r.runtime ? " · runtime only" : ""}`, own: r.hot || r.runtime ? "risk" : "neutral", findings: r.findings });
  }
  for (const name of integrationsOf(agent)) {
    if (providers.includes(name)) continue;
    add({ id: `service:${name}`, lane: "reach", kind: "service", label: name, sensitive: sensitive.has(name), cap: sensitive.has(name) ? "sensitive integration" : "integration", own: sensitive.has(name) ? "risk" : "neutral" });
  }
  if (!nodes.some((n) => n.lane === "reach")) add({ id: "no-reach", lane: "reach", kind: "empty", label: "", cap: "No data or service reach detected" });

  // A finding not yet on a box sits on its step's main box; tool and reach findings with no box stay in the list only.
  const placed = new Set(nodes.flatMap((n) => n.findings));
  for (const r of findings) {
    if (placed.has(r)) continue;
    const lane = laneOf(r.finding.rule_id);
    if (lane === "tools" || lane === "reach") continue;
    const host = nodes.find((n) => n.lane === lane && !n.small && n.kind !== "empty");
    if (host) { host.findings.push(r); host.tone = toneFor(host.own, host.findings); }
  }

  edges.push({ from: "request", to: "agent", label: "sends request" });
  edges.push({ from: "agent", to: "gate", label: "proposes action" });
  const resources = nodes.filter((n) => n.kind === "resource");
  nodes.filter((n) => n.kind === "tool").forEach((n, i) => {
    edges.push({ from: "gate", to: n.id, label: i === 0 ? "calls" : undefined, tone: n.exposed && !approved ? "risk" : undefined });
    for (const r of resources) if (n.tool!.capabilities.includes(r.reach!.cap)) edges.push({ from: n.id, to: r.id, tone: n.exposed && r.reach!.hot && !approved ? "risk" : undefined });
  });
  for (const r of nodes.filter((n) => n.lane === "reach" && n.kind !== "empty")) {
    if (!edges.some((e) => e.to === r.id)) edges.push({ from: "agent", to: r.id, loose: true });
  }

  const evidence: Evidence[] = agent.records.flatMap((a) => a.evidence);
  const isPermission = (e: Evidence) => e.rule_id === "IAC_IAM_POLICY" || e.rule_id === "IAC_GRANT";
  return {
    agent, nodes, edges, findings, row, providers, harness, inferred, declared,
    permissions: [...new Set(evidence.filter(isPermission).map((e) => prose(e.description)))],
    evidence: [...new Set(evidence.filter((e) => !isPermission(e) && e.rule_id !== "IAC_TOOL_BINDING").map((e) => prose(e.description)))],
  };
}

/** The sentence under the diagram. */
export function flowCaption(flow: Flow): string {
  const tools = toolsOf(flow.agent);
  const open = tools.filter((t) => (t.money_action || t.high_impact) && t.guards.length === 0).length;
  const detected = COVERAGE_CONTROLS.filter((c) => flow.row.states[c] === "detected").length;
  const n = (v: number, one: string, many = `${one}s`) => `${v} ${v === 1 ? one : many}`;
  return `${flow.agent.name}: ${n(tools.length, "tool")}${tools.length ? `, ${open} of them money-moving or high impact with no guardrail detected` : ""}; ${n(detected, "safeguard")} detected; ${n(flow.findings.length, "finding")}. The five steps are a fixed reading order. Stoa reads code and infrastructure, so it knows what sits at each step, not the order things run in.`;
}
