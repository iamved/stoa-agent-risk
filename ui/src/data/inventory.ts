/** Inventory categories derived from what the registry actually holds. */
import type { Agent, Envelope, Exposure, ToolRecord } from "./types";
import { capabilitiesOf, declaredOf, definedIn, integrationsOf, uniqueAgents, type UniqueAgent } from "./agents";
import { amountLabel, businessCapabilities, type CapabilityId } from "./labels";
import { EXPOSURE_RANK, agentLabel, activeFindings, hasAuthority } from "./selectors";

export type CategoryId = "agents" | "agents_code" | "agents_iac" | "tools" | "providers" | "integrations" | "declarations";

export interface Category {
  id: CategoryId;
  label: string;
  count: number;
}

export interface ToolRow {
  key: string;
  tool: ToolRecord;
  agents: Agent[];
}

export interface NameRow {
  name: string;
  agents: Agent[];
  sensitive?: boolean;
}

export function codeAgents(env: Envelope): Agent[] {
  return env.registry.agents.filter((a) => (a.source ?? "code") !== "iac");
}

export function iacAgents(env: Envelope): Agent[] {
  return env.registry.agents.filter((a) => a.source === "iac");
}

export function toolRows(env: Envelope): ToolRow[] {
  const byKey = new Map<string, ToolRow>();
  for (const agent of env.registry.agents) {
    for (const tool of agent.tools ?? []) {
      const key = `${tool.path}:${tool.line}:${tool.name}`;
      const row = byKey.get(key);
      if (row) row.agents.push(agent);
      else byKey.set(key, { key, tool, agents: [agent] });
    }
  }
  return [...byKey.values()].sort((a, b) => Number(b.tool.high_impact) - Number(a.tool.high_impact) || a.tool.name.localeCompare(b.tool.name));
}

function nameRows(agents: Agent[], pick: (a: Agent) => string[], sensitive?: Set<string>): NameRow[] {
  const byName = new Map<string, NameRow>();
  for (const agent of agents) {
    for (const name of pick(agent)) {
      const row = byName.get(name);
      if (row) row.agents.push(agent);
      else byName.set(name, { name, agents: [agent], sensitive: sensitive?.has(name) });
    }
  }
  return [...byName.values()].sort((a, b) => Number(Boolean(b.sensitive)) - Number(Boolean(a.sensitive)) || a.name.localeCompare(b.name));
}

export function providerRows(env: Envelope): NameRow[] {
  return nameRows(env.registry.agents, (a) => a.providers);
}

export function integrationRows(env: Envelope): NameRow[] {
  return nameRows(env.registry.agents, (a) => a.integrations, new Set(env.vocabulary.sensitive_integrations));
}

export function declaredAgents(env: Envelope): Agent[] {
  return env.registry.agents.filter((a) => a.declared);
}

export function categories(env: Envelope): Category[] {
  return [
    // Unique agents first; the two record views below show where each was found.
    { id: "agents", label: "Agents", count: uniqueAgents(env).length },
    { id: "agents_code", label: "Agents in code", count: codeAgents(env).length },
    { id: "agents_iac", label: "Agents in infrastructure", count: iacAgents(env).length },
    { id: "tools", label: "Tools", count: toolRows(env).length },
    { id: "providers", label: "Providers and models", count: providerRows(env).length },
    { id: "integrations", label: "Integrations", count: integrationRows(env).length },
    { id: "declarations", label: "Declarations", count: declaredAgents(env).length },
  ];
}

export function worstExposure(agent: Agent): Exposure {
  let worst: Exposure = "none-observed";
  for (const d of agent.dimension_assessment?.dimensions ?? []) {
    if (EXPOSURE_RANK[d.exposure] > EXPOSURE_RANK[worst]) worst = d.exposure;
  }
  return worst;
}

export function agentSource(agent: Agent): string {
  if (agent.source === "iac") return agent.platform ? `${agent.platform} (infrastructure)` : "infrastructure";
  return agent.frameworks.length ? agent.frameworks.join(", ") : "raw provider calls";
}

export function agentFindingCount(env: Envelope, agent: Agent): number {
  return activeFindings(env).filter((r) => r.agents.some((a) => a.id === agent.id)).length;
}

export function contradictions(env: Envelope, agent: Agent) {
  return activeFindings(env).filter((r) => r.finding.rule_id.startsWith("DECL") && r.agents.some((a) => a.id === agent.id));
}

export function filterAgents(env: Envelope, agents: Agent[], query: URLSearchParams): Agent[] {
  let out = agents;
  if (query.get("authority") === "1") out = out.filter((a) => hasAuthority(env, a));
  const q = (query.get("q") ?? "").trim().toLowerCase();
  if (q) out = out.filter((a) => `${agentLabel(a)} ${a.path} ${a.symbol} ${a.frameworks.join(" ")} ${a.capabilities.join(" ")}`.toLowerCase().includes(q));
  return out;
}

// --- unique agents -----------------------------------------------------------------

export function agentCapabilities(agent: UniqueAgent): CapabilityId[] {
  return businessCapabilities(capabilitiesOf(agent), integrationsOf(agent));
}

/** Findings as shown (merged) that touch any record of this agent. */
export function uniqueAgentFindingCount(env: Envelope, agent: UniqueAgent): number {
  return activeFindings(env).filter((r) => r.uniqueAgents.includes(agent)).length;
}

/** "up to $500 per action", from the declared limit. Empty when nothing is declared: the scan cannot know it. */
export function spendingAuthority(agent: UniqueAgent): string {
  const limit = declaredOf(agent)?.economic_authority?.max_per_action;
  return limit ? `up to ${amountLabel(limit)} per action` : "";
}

/** `capability` holds the selected capability ids, comma separated; an agent must have all of them. */
export function filterUniqueAgents(agents: UniqueAgent[], query: URLSearchParams): UniqueAgent[] {
  const wanted = (query.get("capability") ?? "").split(",").filter(Boolean);
  let out = wanted.length ? agents.filter((a) => wanted.every((c) => agentCapabilities(a).includes(c as CapabilityId))) : agents;
  const q = (query.get("q") ?? "").trim().toLowerCase();
  if (q) out = out.filter((a) => `${a.name} ${definedIn(a)} ${a.records.map((r) => `${agentLabel(r)} ${r.path} ${r.symbol}`).join(" ")}`.toLowerCase().includes(q));
  return out;
}
