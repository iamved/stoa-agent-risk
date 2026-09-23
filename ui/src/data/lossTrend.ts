/**
 * The modeled bad-year loss over past scans. Each history entry (schema 1.1)
 * carries the agent fields the loss model reads; the same model runs over
 * each entry with today's business inputs, so the line moves only when the
 * code did. Entries written before 1.1 carry no agents and are skipped.
 */
import type { Agent, Envelope, HistoryAgent, HistoryEntry } from "./types";
import { autonomyOf, declaredOf, mergedRecord, uniqueAgents, type UniqueAgent } from "./agents";
import { agentToModel, intakeFromEnvelope } from "./lossInputs";
import { EVENTS, indicate } from "./lossModel";
import { cached } from "./lossCache";

export interface TrendPoint {
  hash: string;
  ref: string | null;
  date: string;
  /** The agent the figure is for. */
  agent: string;
  /** Agents first seen at this scan (names), for the largest-agent line. */
  added: string[];
  /** 1 in 100 year. */
  badYear: number;
  averageYear: number;
}

/** A history agent, shaped as the model's input reader expects. Fields it never reads are left empty. */
function asAgent(a: HistoryAgent): Agent {
  return {
    ...a,
    symbol: "", path: "", language: "", confidence: "high", detection_score: 0, evidence: [], providers: [], frameworks: [], integrations: [], permission_tags: [], call_sites: {}, last_touched_by: null, last_commit: null, codeowners: [], findings: [], highest_severity: null,
    name: a.name ?? a.id, display_name: a.display_name ?? a.name ?? a.id,
    autonomy_level: { level: a.autonomy_level.level ?? "indeterminate", signals: [], reason: null },
    declared: a.declared ? { name: "", owner: "", purpose: "", geography: [], production_status: null, users: null, autonomy_intent: null, data_classes: [], ...Object.fromEntries(Object.entries(a.declared).filter(([, v]) => v !== undefined)) } : undefined,
    tools: a.tools.map((t) => ({ ...t, path: "", line: 0, kind: "", params: [], capabilities: [], integrations: [], guards: [], retry: false, idempotency_key: false, resolved: true })),
    dimension_assessment: { schema: "", dimensions: a.dimension_assessment.dimensions.map((d) => ({ ...d, group: "", assessability: "strong", exposure: "low", contributing_findings: [], contributing_capabilities: [], statement: "" })) },
  } as unknown as Agent;
}

function figure(env: Envelope, scan: string, agent: UniqueAgent, intake: ReturnType<typeof intakeFromEnvelope>["intake"], monthlyVolume: number, seed: number, years?: number): { badYear: number; averageYear: number } | null {
  // One run per scan, agent and simulation length; the inputs are the envelope's, so the key needs no more.
  return cached(env, `figure:${scan}:${agent.id}:${seed}:${years ?? ""}`, () => {
    const merged = mergedRecord(agent);
    if (!merged.dimension_assessment) return null;
    const { model } = agentToModel(env, merged, monthlyVolume);
    const r = indicate(EVENTS, model, intake, seed, {}, { years, noBoot: true });
    return { badYear: r.summary.pMid, averageYear: r.summary.eal };
  });
}

/** A past scan's records grouped as today's identity mapping groups them; a record no current agent claims stands alone. */
function agentsAt(env: Envelope, records: HistoryAgent[]): UniqueAgent[] {
  const out: UniqueAgent[] = [];
  const claimed = new Set<string>();
  for (const u of uniqueAgents(env)) {
    const mine = records.filter((r) => u.records.some((x) => x.id === r.id)).map(asAgent);
    if (!mine.length) continue;
    for (const r of mine) claimed.add(r.id);
    out.push({ ...u, records: mine, info: u.info.filter((i) => mine.some((r) => r.id === i.agent_id)) });
  }
  for (const r of records) {
    if (claimed.has(r.id)) continue;
    const a = asAgent(r);
    out.push({ id: r.id, name: a.display_name, records: [a], info: [{ agent_id: r.id, kind: "code", label: "Defined in code" }], linkedBy: null });
  }
  return out;
}

const entriesOf = (env: Envelope) => [...env.history].filter((h): h is HistoryEntry & { agents: HistoryAgent[] } => Array.isArray(h.agents)).sort((a, b) => a.head_commit.date.localeCompare(b.head_commit.date));

/**
 * Points oldest first, for the unique agent `agentId`. Each past scan's
 * records of that agent are merged the same way as today's; a scan with none
 * of them contributes no point. Same seed and simulation length as the
 * screens, so the last point equals the headline figure.
 */
export function lossTrend(env: Envelope, agentId: string, seed: number, years?: number): TrendPoint[] {
  const { intake, monthlyVolume } = intakeFromEnvelope(env);
  const out: TrendPoint[] = [];
  for (const h of entriesOf(env)) {
    const agent = agentsAt(env, h.agents).find((u) => u.id === agentId);
    const f = agent && figure(env, h.head_commit.hash, agent, intake, monthlyVolume, seed, years);
    if (f) out.push({ hash: h.head_commit.hash, ref: h.git_ref, date: h.head_commit.date, agent: agent.name, added: [], ...f });
  }
  return out;
}

const ACTS_ALONE = new Set(["unrestricted_autonomous", "bounded_autonomous"]);

export interface AgentChange {
  name: string;
  id: string;
  /** "uncapped": an in-code limit came off (bounded to unrestricted). "autonomous": it now acts on its own. "limit": the declared per-action limit rose. */
  kind: "uncapped" | "autonomous" | "limit";
  from: string;
  to: string;
}

/**
 * How the agents present at both of two scans changed between them, from the
 * history slices: the autonomy the scanner inferred, and the declared
 * per-action limit. Empty when either scan is not in the history.
 */
export function agentChanges(env: Envelope, fromHash: string, toHash: string): AgentChange[] {
  const entries = entriesOf(env);
  const from = entries.find((h) => h.head_commit.hash === fromHash);
  const to = entries.find((h) => h.head_commit.hash === toHash);
  if (!from || !to) return [];
  const before = new Map(agentsAt(env, from.agents).map((u) => [u.id, u]));
  const out: AgentChange[] = [];
  for (const u of agentsAt(env, to.agents)) {
    const b = before.get(u.id);
    if (!b) continue;
    const lb = autonomyOf(b) ?? "", la = autonomyOf(u) ?? "";
    if (lb === "bounded_autonomous" && la === "unrestricted_autonomous") out.push({ name: u.name, id: u.id, kind: "uncapped", from: lb, to: la });
    else if (!ACTS_ALONE.has(lb) && ACTS_ALONE.has(la)) out.push({ name: u.name, id: u.id, kind: "autonomous", from: lb, to: la });
    const mb = declaredOf(b)?.economic_authority?.max_per_action?.amount, ma = declaredOf(u)?.economic_authority?.max_per_action?.amount;
    if (mb !== undefined && ma !== undefined && ma > mb) out.push({ name: u.name, id: u.id, kind: "limit", from: String(mb), to: String(ma) });
  }
  return out.sort((a, b) => a.name.localeCompare(b.name) || a.kind.localeCompare(b.kind));
}

export interface TrendStep {
  from: TrendPoint;
  to: TrendPoint;
  /** Agents first seen at `to`. */
  added: string[];
  changes: AgentChange[];
  /** This step's share of the whole rise, 0 to 1. */
  share: number;
}

/** The step between consecutive scans that added the most to the line. Null unless the line rose over at least two scans. */
export function largestStep(env: Envelope, trend: TrendPoint[]): TrendStep | null {
  if (trend.length < 2) return null;
  const first = trend[0]!, last = trend[trend.length - 1]!;
  const rise = last.badYear - first.badYear;
  if (rise <= 0) return null;
  let best = 1;
  for (let i = 2; i < trend.length; i++) if (trend[i]!.badYear - trend[i - 1]!.badYear > trend[best]!.badYear - trend[best - 1]!.badYear) best = i;
  const from = trend[best - 1]!, to = trend[best]!;
  return { from, to, added: to.added, changes: agentChanges(env, from.hash, to.hash), share: (to.badYear - from.badYear) / rise };
}

/**
 * The largest single-agent bad year at each past scan, oldest first, naming
 * the agent. Bad years do not add across agents, so this is the portfolio
 * line: what one agent could cost in a year seen once in a hundred.
 */
export function lossTrendMax(env: Envelope, seed: number, years?: number): TrendPoint[] {
  return cached(env, `trendMax:${seed}:${years ?? ""}`, () => trendMax(env, seed, years));
}

function trendMax(env: Envelope, seed: number, years?: number): TrendPoint[] {
  const { intake, monthlyVolume } = intakeFromEnvelope(env);
  const out: TrendPoint[] = [];
  let seen: Set<string> | null = null;
  for (const h of entriesOf(env)) {
    const agents = agentsAt(env, h.agents);
    const added = seen ? agents.filter((a) => !seen!.has(a.id)).map((a) => a.name) : [];
    seen = new Set(agents.map((a) => a.id));
    let best: TrendPoint | null = null;
    for (const agent of agents) {
      const f = figure(env, h.head_commit.hash, agent, intake, monthlyVolume, seed, years);
      if (f && (!best || f.badYear > best.badYear)) best = { hash: h.head_commit.hash, ref: h.git_ref, date: h.head_commit.date, agent: agent.name, added, ...f };
    }
    if (best) out.push(best);
  }
  return out;
}
