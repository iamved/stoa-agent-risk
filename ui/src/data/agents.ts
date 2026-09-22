/**
 * Unique agents. The scanner reports one record per place it finds an agent
 * (a graph in code, a Bedrock agent in Terraform, a serving endpoint), and one
 * deployed agent is often two or three of those. The envelope's
 * `unique_agents` block says which records belong together
 * (src/stoa/dashboard/identity.py); this module reads it and rolls the
 * records' facts up. It never rescores: an agent's exposure is the highest
 * level among its records, which is how the scanner already rolls agents up
 * into a dimension.
 */
import type { Agent, AgentDeclaration, Confidence, DimensionEntry, Envelope, Exposure, ToolRecord } from "./types";

export interface AgentRecordInfo {
  agent_id: string;
  kind: "code" | "infrastructure";
  platform?: string | null;
  /** "Defined in code", "Deployed on AWS". */
  label: string;
  path?: string | null;
  symbol?: string | null;
}

export interface UniqueAgent {
  id: string;
  name: string;
  /** Code records first. */
  records: Agent[];
  info: AgentRecordInfo[];
  linkedBy: "declared" | "name" | null;
}

const cache = new WeakMap<Envelope, { list: UniqueAgent[]; byRecord: Map<string, UniqueAgent> }>();

function build(env: Envelope): { list: UniqueAgent[]; byRecord: Map<string, UniqueAgent> } {
  const byId = new Map(env.registry.agents.map((a) => [a.id, a]));
  const list: UniqueAgent[] = [];
  const claimed = new Set<string>();
  for (const block of env.unique_agents ?? []) {
    const info = block.records.filter((r) => byId.has(r.agent_id) && !claimed.has(r.agent_id));
    if (!info.length) continue;
    for (const r of info) claimed.add(r.agent_id);
    list.push({ id: block.id, name: block.name, records: info.map((r) => byId.get(r.agent_id)!), info, linkedBy: block.linked_by ?? null });
  }
  // An envelope written before identity resolution, or a record the block
  // missed: each such record is its own agent, so nothing is ever dropped.
  for (const agent of env.registry.agents) {
    if (claimed.has(agent.id)) continue;
    const kind = agent.source === "iac" ? "infrastructure" : "code";
    list.push({
      id: agent.id,
      name: agent.display_name || agent.name,
      records: [agent],
      info: [{ agent_id: agent.id, kind, platform: agent.platform ?? null, label: kind === "code" ? "Defined in code" : "Defined in infrastructure", path: agent.path, symbol: agent.symbol }],
      linkedBy: null,
    });
  }
  const byRecord = new Map<string, UniqueAgent>();
  for (const u of list) for (const r of u.records) byRecord.set(r.id, u);
  return { list, byRecord };
}

function index(env: Envelope) {
  let hit = cache.get(env);
  if (!hit) {
    hit = build(env);
    cache.set(env, hit);
  }
  return hit;
}

export function uniqueAgents(env: Envelope): UniqueAgent[] {
  return index(env).list;
}

/** The unique agent a scanned record belongs to. */
export function uniqueAgentOf(env: Envelope, recordId: string): UniqueAgent | null {
  return index(env).byRecord.get(recordId) ?? null;
}

/** By unique id, or by the id of any of its records, so old deep links keep working. */
export function uniqueAgentById(env: Envelope, id: string): UniqueAgent | null {
  return index(env).list.find((u) => u.id === id) ?? uniqueAgentOf(env, id);
}

/** "5 agents · 11 discovered records", or just "5 agents" when the two agree. */
export function agentCountLabel(env: Envelope): string {
  const agents = uniqueAgents(env).length;
  const records = env.registry.agents.length;
  const head = `${agents} ${agents === 1 ? "agent" : "agents"}`;
  return records === agents ? head : `${head} · ${records} discovered records`;
}

/** "Defined in code · Deployed on AWS". Repeated labels (two endpoints on one platform) are counted. */
export function definedIn(agent: UniqueAgent): string {
  const counts = new Map<string, number>();
  for (const r of agent.info) counts.set(r.label, (counts.get(r.label) ?? 0) + 1);
  return [...counts].map(([label, n]) => (n > 1 ? `${label} (${n})` : label)).join(" · ");
}

// --- roll-ups ---------------------------------------------------------------------

const union = (agent: UniqueAgent, pick: (a: Agent) => string[]): string[] => [...new Set(agent.records.flatMap(pick))].sort();

export const capabilitiesOf = (agent: UniqueAgent): string[] => union(agent, (a) => a.capabilities);
export const providersOf = (agent: UniqueAgent): string[] => union(agent, (a) => a.providers);
export const integrationsOf = (agent: UniqueAgent): string[] => union(agent, (a) => a.integrations);
export const frameworksOf = (agent: UniqueAgent): string[] => union(agent, (a) => a.frameworks);

/**
 * The agent's tools, one per name. The same tool seen in code and in
 * infrastructure is one tool; it moves money if any record says so, and a
 * guardrail detected on either record counts.
 */
export function toolsOf(agent: UniqueAgent): ToolRecord[] {
  const byName = new Map<string, ToolRecord>();
  for (const record of agent.records) {
    for (const tool of record.tools ?? []) {
      const seen = byName.get(tool.name);
      if (!seen) byName.set(tool.name, { ...tool, guards: [...tool.guards], capabilities: [...tool.capabilities], integrations: [...tool.integrations] });
      else {
        seen.guards = [...new Set([...seen.guards, ...tool.guards])].sort();
        seen.capabilities = [...new Set([...seen.capabilities, ...tool.capabilities])].sort();
        seen.integrations = [...new Set([...seen.integrations, ...tool.integrations])].sort();
        seen.money_action ||= tool.money_action;
        seen.high_impact ||= tool.high_impact;
        seen.retry ||= tool.retry;
        seen.idempotency_key ||= tool.idempotency_key;
      }
    }
  }
  return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function canMoveMoney(agent: UniqueAgent): boolean {
  return agent.records.some((a) => (a.tools ?? []).some((t) => t.money_action) || a.capabilities.includes("payment_access"));
}

export function declaredOf(agent: UniqueAgent): AgentDeclaration | null {
  return agent.records.find((a) => a.declared)?.declared ?? null;
}

const CONFIDENCE_ORDER: Confidence[] = ["low", "medium", "high"];
export function confidenceOf(agent: UniqueAgent): Confidence {
  return agent.records.reduce<Confidence>((best, a) => (CONFIDENCE_ORDER.indexOf(a.confidence) > CONFIDENCE_ORDER.indexOf(best) ? a.confidence : best), "low");
}

/** Most autonomous first: what the agent can do is what its freest record can do. */
const AUTONOMY_ORDER = ["unrestricted_autonomous", "bounded_autonomous", "human_approved", "recommend_only", "indeterminate"];
export function autonomyOf(agent: UniqueAgent): string | null {
  const levels = agent.records.map((a) => a.autonomy_level?.level).filter((l): l is string => Boolean(l));
  if (!levels.length) return null;
  return levels.sort((a, b) => (AUTONOMY_ORDER.indexOf(a) + 1 || 99) - (AUTONOMY_ORDER.indexOf(b) + 1 || 99))[0]!;
}

const EXPOSURE_ORDER: Exposure[] = ["not-assessable", "none-observed", "low", "moderate", "elevated"];
export function higherExposure(a: Exposure, b: Exposure): Exposure {
  return EXPOSURE_ORDER.indexOf(b) > EXPOSURE_ORDER.indexOf(a) ? b : a;
}

/** Per dimension, the entry of the record with the highest exposure (ties: the higher score). No new score is computed. */
export function dimensionsOf(agent: UniqueAgent): DimensionEntry[] {
  const best = new Map<string, DimensionEntry>();
  for (const record of agent.records) {
    for (const entry of record.dimension_assessment?.dimensions ?? []) {
      const seen = best.get(entry.id);
      const rank = (e: DimensionEntry) => EXPOSURE_ORDER.indexOf(e.exposure) * 1000 + e.score;
      if (!seen || rank(entry) > rank(seen)) best.set(entry.id, entry);
    }
  }
  return [...best.values()];
}

/** The agent's highest exposure across all dimensions and records. */
export function exposureOf(agent: UniqueAgent): Exposure {
  return dimensionsOf(agent).reduce<Exposure>((worst, d) => higherExposure(worst, d.exposure), "none-observed");
}

/** Safeguards the scanner detected on any record of the agent. */
export function safeguardsOf(agent: UniqueAgent): string[] {
  return [...new Set(agent.records.flatMap((a) => (a.dimension_assessment?.dimensions ?? []).flatMap((d) => d.controls_observed)))].sort();
}
