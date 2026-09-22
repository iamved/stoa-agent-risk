/**
 * The modeled bad-year loss over past scans. Each history entry (schema 1.1)
 * carries the agent fields the loss model reads; the same model runs over
 * each entry with today's business inputs, so the line moves only when the
 * code did. Entries written before 1.1 carry no agents and are skipped.
 */
import type { Agent, Envelope, HistoryAgent, HistoryEntry } from "./types";
import { mergedRecord, uniqueAgents, type UniqueAgent } from "./agents";
import { agentToModel, intakeFromEnvelope } from "./lossInputs";
import { EVENTS, indicate } from "./lossModel";

export interface TrendPoint {
  hash: string;
  ref: string | null;
  date: string;
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

/**
 * Points oldest first, for the unique agent `agentId` (what the Financial
 * Exposure screen models). Each past scan's records of that agent, by the
 * current identity mapping, are merged the same way as today's. A scan with
 * none of them contributes no point. Same seed and simulation length as the
 * screens, so the last point equals the headline figure.
 */
export function lossTrend(env: Envelope, agentId: string, seed: number, years?: number): TrendPoint[] {
  const unique = uniqueAgents(env).find((u) => u.id === agentId);
  if (!unique) return [];
  const ids = new Set(unique.records.map((r) => r.id));
  const { intake, monthlyVolume } = intakeFromEnvelope(env);
  const entries = [...env.history].filter((h): h is HistoryEntry & { agents: HistoryAgent[] } => Array.isArray(h.agents)).sort((a, b) => a.head_commit.date.localeCompare(b.head_commit.date));
  const out: TrendPoint[] = [];
  for (const h of entries) {
    const records = h.agents.filter((a) => ids.has(a.id)).map(asAgent);
    if (!records.length) continue;
    const then: UniqueAgent = { ...unique, records, info: unique.info.filter((i) => records.some((r) => r.id === i.agent_id)) };
    const { model } = agentToModel(env, mergedRecord(then), monthlyVolume);
    const r = indicate(EVENTS, model, intake, seed, {}, { years, noBoot: true });
    out.push({ hash: h.head_commit.hash, ref: h.git_ref, date: h.head_commit.date, badYear: r.summary.pMid, averageYear: r.summary.eal });
  }
  return out;
}
