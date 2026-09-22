/**
 * Pure read-only views over the envelope. Nothing here recomputes a score:
 * every number is copied from the registry, the diff, or the history entries
 * the scanner wrote. Tested in `tests/selectors.test.ts`.
 */
import { uniqueAgentOf, uniqueAgents, type UniqueAgent } from "./agents";
import { PLAIN_TITLE, prose } from "./labels";
import type {
  Agent,
  DimensionEntry,
  DimensionSummaryEntry,
  Envelope,
  Exposure,
  Finding,
  HistoryEntry,
  Registry,
  Severity,
  TaxonomyDimension,
} from "./types";
import { EU_AI_ACT_ARTICLES, OWASP_LLM_2025, euArticleDescription, euArticleName, owaspDescription, owaspName, type FrameworkId } from "./frameworks";

export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];

/** The dashboard shows three risk levels; the scanner's five severities map onto them. */
export type RiskLevel = "high" | "medium" | "low";
export const RISK_LEVELS: RiskLevel[] = ["high", "medium", "low"];
export const RISK_LABEL: Record<RiskLevel, string> = { high: "High", medium: "Medium", low: "Low" };
export const RISK_SEVERITIES: Record<RiskLevel, Severity[]> = { high: ["critical", "high"], medium: ["medium"], low: ["low", "info"] };
export function riskLevel(severity: Severity): RiskLevel {
  return severity === "critical" || severity === "high" ? "high" : severity === "medium" ? "medium" : "low";
}
export function countByLevel(refs: FindingRef[]): Record<RiskLevel, number> {
  const out: Record<RiskLevel, number> = { high: 0, medium: 0, low: 0 };
  for (const ref of refs) out[riskLevel(ref.finding.severity)] += 1;
  return out;
}
export const SEVERITY_RANK: Record<Severity, number> = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
export const CONFIDENCE_RANK: Record<string, number> = { high: 2, medium: 1, low: 0 };
export const EXPOSURE_RANK: Record<Exposure, number> = {
  "not-assessable": -1,
  "none-observed": 0,
  low: 1,
  moderate: 2,
  elevated: 3,
};
export const EXPOSURE_LABEL: Record<Exposure, string> = {
  "not-assessable": "Not assessable",
  "none-observed": "None observed",
  low: "Low",
  moderate: "Moderate",
  elevated: "Elevated",
};
export const ASSESSABILITY_LABEL: Record<string, string> = {
  strong: "Strong",
  partial: "Partial",
  proxy: "Proxy",
  runtime: "Runtime",
  "runtime-required": "Runtime required",
};
export const ASSESSABILITY_HINT: Record<string, string> = {
  strong: "Static analysis observes the mechanism directly.",
  partial: "Static analysis observes part of the mechanism.",
  proxy: "Configuration signals only; capped at moderate.",
  runtime: "Assessed from runtime traces in an observed window.",
  "runtime-required": "Cannot be assessed from code alone.",
};

export interface FindingRef {
  /** The record the finding is read from: the highest severity of its evidence, code before infrastructure. */
  finding: Finding;
  /**
   * Every scanner record behind this finding, `finding` first. The same rule
   * firing on two records of one agent (its code and its Terraform) is one
   * finding with two evidence locations. The records themselves are unchanged.
   */
  evidence: Finding[];
  /** The first scanned record carrying this finding; null for a repository-level finding. */
  agent: Agent | null;
  /** Every scanned record carrying any of the evidence (agents in one file share that file's findings). */
  agents: Agent[];
  /** The unique agents those records belong to. */
  uniqueAgents: UniqueAgent[];
}

// --- findings -------------------------------------------------------------------

/** Every scanner record once. A file-level finding is repeated on each agent in that file; the registry summary counts it once, so this does too. */
function recordRefs(env: Envelope): FindingRef[] {
  const registry = env.registry;
  const byFingerprint = new Map<string, FindingRef>();
  for (const agent of registry.agents) {
    for (const finding of agent.findings) {
      const existing = byFingerprint.get(finding.fingerprint);
      if (existing) existing.agents.push(agent);
      else byFingerprint.set(finding.fingerprint, { finding, evidence: [finding], agent, agents: [agent], uniqueAgents: [] });
    }
  }
  for (const finding of registry.repository_findings) {
    if (!byFingerprint.has(finding.fingerprint)) byFingerprint.set(finding.fingerprint, { finding, evidence: [finding], agent: null, agents: [], uniqueAgents: [] });
  }
  const refs = [...byFingerprint.values()];
  for (const ref of refs) ref.uniqueAgents = [...new Set(ref.agents.map((a) => uniqueAgentOf(env, a.id)).filter((u): u is UniqueAgent => u !== null))];
  return refs;
}

const byLocation = (a: Finding, b: Finding) => a.path.localeCompare(b.path) || a.line - b.line || a.rule_id.localeCompare(b.rule_id) || a.fingerprint.localeCompare(b.fingerprint);

function merge(refs: FindingRef[]): FindingRef {
  if (refs.length === 1) return refs[0]!;
  const isCode = (r: FindingRef) => (r.agents.some((a) => a.source !== "iac") ? 0 : 1);
  const ordered = [...refs].sort((a, b) => SEVERITY_RANK[b.finding.severity] - SEVERITY_RANK[a.finding.severity] || isCode(a) - isCode(b) || byLocation(a.finding, b.finding));
  const first = ordered[0]!;
  return { finding: first.finding, evidence: ordered.map((r) => r.finding), agent: first.agent, agents: [...new Set(ordered.flatMap((r) => r.agents))], uniqueAgents: first.uniqueAgents };
}

const findingsCache = new WeakMap<Envelope, FindingRef[]>();

/**
 * Every finding once. Records of the same rule on the same unique agent are
 * merged when they come from different scanned records of that agent; two
 * hits inside one record stay two findings. With no identity block every
 * record is its own agent, so nothing merges.
 */
export function allFindings(env: Envelope): FindingRef[] {
  const hit = findingsCache.get(env);
  if (hit) return hit;
  const groups = new Map<string, FindingRef[]>();
  for (const ref of recordRefs(env)) {
    const owners = ref.uniqueAgents.map((u) => u.id).sort().join(",");
    const key = owners ? `${ref.finding.rule_id}|${ref.finding.suppressed ? 1 : 0}|${owners}` : `record|${ref.finding.fingerprint}`;
    const list = groups.get(key);
    if (list) list.push(ref);
    else groups.set(key, [ref]);
  }
  const out: FindingRef[] = [];
  for (const group of groups.values()) {
    // One bucket per set of scanned records; the i-th hit of each bucket is the same problem seen again.
    const buckets = new Map<string, FindingRef[]>();
    for (const ref of group) {
      const records = ref.agents.map((a) => a.id).sort().join(",");
      const bucket = buckets.get(records);
      if (bucket) bucket.push(ref);
      else buckets.set(records, [ref]);
    }
    const lists = [...buckets.values()].map((list) => list.sort((a, b) => byLocation(a.finding, b.finding)));
    const depth = Math.max(...lists.map((list) => list.length));
    for (let i = 0; i < depth; i++) out.push(merge(lists.map((list) => list[i]).filter((r): r is FindingRef => r !== undefined)));
  }
  out.sort((a, b) => byLocation(a.finding, b.finding));
  findingsCache.set(env, out);
  return out;
}

export function activeFindings(env: Envelope): FindingRef[] {
  return allFindings(env).filter((r) => !r.finding.suppressed);
}

/** How many scanner records sit behind a list of findings. The registry, the CLI and SARIF count these. */
export function recordCount(refs: FindingRef[]): number {
  return refs.reduce((n, r) => n + r.evidence.length, 0);
}

export function countBySeverity(refs: FindingRef[]): Record<Severity, number> {
  const out: Record<Severity, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
  for (const ref of refs) out[ref.finding.severity] += 1;
  return out;
}

/**
 * The finding's title, the same on every screen: the plain-English consequence
 * from the crosswalk. The rule's own name is a label for the check, and lives
 * in the detail drawer beside the rule id.
 */
export function findingTitle(env: Envelope, finding: Finding): string {
  return PLAIN_TITLE[finding.rule_id] ?? prose(finding.crosswalk?.so_what || env.rules[finding.rule_id]?.crosswalk?.so_what || finding.title);
}

/** Any of a finding's evidence fingerprints resolves to it, so links made before a merge still open. */
export function findingByFingerprint(env: Envelope, fingerprint: string): FindingRef | null {
  return allFindings(env).find((r) => r.evidence.some((f) => f.fingerprint === fingerprint)) ?? null;
}

/** Fingerprints the baseline diff reports as new. Empty without a baseline. */
export function newFingerprints(env: Envelope): Set<string> {
  return new Set((env.diff?.agents.changed ?? []).flatMap((c) => c.findings_delta.new.map((f) => f.fingerprint)));
}

/** New since the baseline: every piece of its evidence is new. A known finding that gained a location is not new. */
export function isNewFinding(ref: FindingRef, fresh: Set<string>): boolean {
  return ref.evidence.every((f) => fresh.has(f.fingerprint));
}

export function agentById(registry: Registry, id: string): Agent | null {
  return registry.agents.find((a) => a.id === id) ?? null;
}

export function agentLabel(agent: Agent): string {
  return agent.display_name || agent.name;
}

/** The framework tag a finding carries under the selected framework. */
export function findingTag(finding: Finding, framework: FrameworkId): string {
  const cw = finding.crosswalk;
  if (!cw) return "";
  if (framework === "owasp") return cw.owasp_llm_2025;
  if (framework === "eu") return cw.eu_ai_act;
  return "";
}

export function tagLabel(tag: string, framework: FrameworkId): string {
  if (!tag) return "No class";
  if (framework === "owasp") return `${tag}: ${owaspName(tag)}. ${owaspDescription(tag)}`.trim();
  if (framework === "eu") return `${tag}: ${euArticleName(tag)}. ${euArticleDescription(tag)}`.trim();
  return tag;
}

// --- dimensions -----------------------------------------------------------------

export interface MatrixAgent {
  agent: Agent;
  entry: DimensionEntry;
}

export interface MatrixCell {
  dimension: TaxonomyDimension;
  summary: DimensionSummaryEntry | null;
  maxExposure: Exposure;
  agentsElevated: number;
  agentsModerate: number;
  findingCount: number;
  agents: MatrixAgent[];
  tags: string[];
}

export interface MatrixGroup {
  id: string;
  label: string;
  cells: MatrixCell[];
}

const GROUP_ORDER = ["A", "B", "C", "D", "E", "F", "G", ""];

export function dimensionMatrix(env: Envelope, framework: FrameworkId): MatrixGroup[] {
  const registry = env.registry;
  const summaries = new Map((registry.dimension_summary?.dimensions ?? []).map((d) => [d.id, d]));
  const active = activeFindings(env);
  const groups = new Map<string, MatrixGroup>();
  for (const dimension of env.taxonomy.dimensions) {
    const summary = summaries.get(dimension.id) ?? null;
    const agents: MatrixAgent[] = [];
    for (const agent of registry.agents) {
      const entry = agent.dimension_assessment?.dimensions.find((d) => d.id === dimension.id);
      if (entry && entry.exposure !== "none-observed") agents.push({ agent, entry });
    }
    agents.sort((a, b) => b.entry.score - a.entry.score || agentLabel(a.agent).localeCompare(agentLabel(b.agent)));
    const tags = framework === "owasp" ? (summary?.crosswalk?.owasp_llm_2025 ?? []) : framework === "eu" ? (summary?.crosswalk?.eu_ai_act ?? []) : [];
    const cell: MatrixCell = {
      dimension,
      summary,
      maxExposure: summary?.max_exposure ?? "none-observed",
      agentsElevated: summary?.agents_elevated ?? 0,
      agentsModerate: summary?.agents_moderate ?? 0,
      findingCount: active.filter((r) => r.finding.dimensions?.includes(dimension.id)).length,
      agents,
      tags,
    };
    const groupId = dimension.group ?? "";
    let group = groups.get(groupId);
    if (!group) {
      group = { id: groupId, label: env.taxonomy.groups[groupId] ?? (groupId ? `Group ${groupId}` : "Other"), cells: [] };
      groups.set(groupId, group);
    }
    group.cells.push(cell);
  }
  return [...groups.values()].sort((a, b) => GROUP_ORDER.indexOf(a.id) - GROUP_ORDER.indexOf(b.id));
}

export function dimensionName(env: Envelope, id: string): string {
  return env.taxonomy.dimensions.find((d) => d.id === id)?.name ?? id;
}

/** Agents that carry at least one elevated dimension, with those dimensions. */
export function elevatedAgents(env: Envelope): { agent: Agent; entries: DimensionEntry[] }[] {
  const out: { agent: Agent; entries: DimensionEntry[] }[] = [];
  for (const agent of env.registry.agents) {
    const entries = (agent.dimension_assessment?.dimensions ?? []).filter((d) => d.exposure === "elevated");
    if (entries.length) out.push({ agent, entries });
  }
  out.sort((a, b) => b.entries.length - a.entries.length || agentLabel(a.agent).localeCompare(agentLabel(b.agent)));
  return out;
}

// --- overview stats ----------------------------------------------------------------

export interface Stats {
  agents: number;
  /** Scanned records behind those agents. */
  records: number;
  highConfidence: number;
  authorityAgents: number;
  unreviewedHighImpact: number;
  contradictions: number;
  findings: Record<Severity, number>;
  newFindings: Record<Severity, number>;
  suppressed: number;
  drift: { changed: number; added: number; removed: number; escalationsHigh: number; unapproved: string } | null;
}

export function hasAuthority(env: Envelope, agent: Agent): boolean {
  const highImpact = new Set(env.vocabulary.high_impact_capabilities);
  if (agent.capabilities.some((c) => highImpact.has(c))) return true;
  return (agent.tools ?? []).some((t) => t.high_impact || t.money_action);
}

export function stats(env: Envelope): Stats {
  const registry = env.registry;
  const active = activeFindings(env);
  const diff = env.diff;
  return {
    // Unique agents, and findings as shown: the same numbers every screen reports.
    agents: uniqueAgents(env).length,
    records: registry.agents.length,
    highConfidence: registry.agents.filter((a) => a.confidence === "high").length,
    authorityAgents: uniqueAgents(env).filter((u) => u.records.some((a) => hasAuthority(env, a))).length,
    unreviewedHighImpact: active.filter((r) => r.finding.rule_id === "AI003").length,
    contradictions: active.filter((r) => r.finding.rule_id.startsWith("DECL")).length,
    findings: countBySeverity(active),
    newFindings: registry.summary.new_findings,
    suppressed: registry.summary.suppressed_findings,
    drift: diff
      ? {
          changed: diff.summary.agents_changed,
          added: diff.summary.agents_added,
          removed: diff.summary.agents_removed,
          escalationsHigh: diff.summary.escalations.high,
          unapproved: diff.summary.unapproved_max_drift_severity,
        }
      : null,
  };
}

// --- top risks ----------------------------------------------------------------------

export interface TopRisk {
  ref: FindingRef;
  soWhat: string;
}

function riskRank(f: Finding): number {
  return SEVERITY_RANK[f.severity] * 10 + (CONFIDENCE_RANK[f.confidence] ?? 0) * 2 + (f.gate_eligible ? 1 : 0);
}

/** Highest-severity findings, one per rule first so the list reads as five different risks. */
export function topRisks(env: Envelope, n = 5): TopRisk[] {
  const ranked = activeFindings(env).sort((a, b) => riskRank(b.finding) - riskRank(a.finding) || a.finding.path.localeCompare(b.finding.path) || a.finding.line - b.finding.line);
  const chosen: FindingRef[] = [];
  const seenRules = new Set<string>();
  for (const ref of ranked) {
    if (chosen.length >= n) break;
    if (seenRules.has(ref.finding.rule_id)) continue;
    seenRules.add(ref.finding.rule_id);
    chosen.push(ref);
  }
  for (const ref of ranked) {
    if (chosen.length >= n) break;
    if (!chosen.includes(ref)) chosen.push(ref);
  }
  return chosen.map((ref) => ({ ref, soWhat: findingTitle(env, ref.finding) }));
}

// --- framework classes -----------------------------------------------------------------

export type ClassState = "observed" | "assessable" | "gap" | "aligned" | "outside";

export interface FrameworkClass {
  id: string;
  name: string;
  state: ClassState;
  count: number;
}

/** Which classes of the selected framework this scan touched, kept honest: a class with no detector is a gap. */
export function frameworkClasses(env: Envelope, framework: FrameworkId): FrameworkClass[] {
  const active = activeFindings(env);
  if (framework === "nist") {
    return env.frameworks.nist_ai_rmf.map((f) => ({ id: f.function, name: f.stoa, state: f.function === "GOVERN" ? "outside" : "aligned", count: 0 }));
  }
  const detectable = new Set<string>();
  for (const rule of Object.values(env.rules)) {
    const tag = framework === "owasp" ? rule.crosswalk?.owasp_llm_2025 : rule.crosswalk?.eu_ai_act;
    if (tag) detectable.add(tag);
  }
  const counts = new Map<string, number>();
  for (const ref of active) {
    const tag = findingTag(ref.finding, framework);
    if (tag) counts.set(tag, (counts.get(tag) ?? 0) + 1);
  }
  if (framework === "owasp") {
    return OWASP_LLM_2025.map((c) => {
      const count = counts.get(c.code) ?? 0;
      const state: ClassState = count > 0 ? "observed" : detectable.has(c.code) ? "assessable" : "gap";
      return { id: c.code, name: c.name, state, count };
    });
  }
  const ids = new Set<string>([...Object.keys(EU_AI_ACT_ARTICLES), ...detectable, ...counts.keys()]);
  return [...ids]
    .sort((a, b) => articleNumber(a) - articleNumber(b))
    .map((id) => {
      const count = counts.get(id) ?? 0;
      const state: ClassState = count > 0 ? "observed" : detectable.has(id) ? "assessable" : "gap";
      return { id, name: euArticleName(id), state, count };
    });
}

function articleNumber(article: string): number {
  const match = /(\d+)/.exec(article);
  return match && match[1] ? Number.parseInt(match[1], 10) : 9999;
}

// --- history ------------------------------------------------------------------------------

export interface TrendPoint {
  hash: string;
  date: string;
  value: number;
  label: string;
}

/** Exposure rank of a dimension's org-level maximum across history, oldest first. */
export function dimensionTrend(history: HistoryEntry[], dimensionId: string): TrendPoint[] {
  return history.map((h) => {
    const d = h.dimensions.find((x) => x.id === dimensionId);
    const exposure = d?.max_exposure ?? "none-observed";
    return { hash: h.head_commit.hash, date: h.head_commit.date, value: Math.max(0, EXPOSURE_RANK[exposure]), label: EXPOSURE_LABEL[exposure] };
  });
}

export function findingsTrend(history: HistoryEntry[], severity: Severity): TrendPoint[] {
  return history.map((h) => ({ hash: h.head_commit.hash, date: h.head_commit.date, value: h.findings[severity] ?? 0, label: `${h.findings[severity] ?? 0} ${severity}` }));
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "no date";
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!match) return iso;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[Number.parseInt(match[2] ?? "1", 10) - 1] ?? match[2];
  return `${Number.parseInt(match[3] ?? "1", 10)} ${month} ${match[1]}`;
}

export function pluralize(n: number, singular: string, plural = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : plural}`;
}


// --- overview: deltas against the baseline and findings by dimension -------------------

export interface Delta { value: number; label: string }

/** Changes since the baseline for the four headline figures; null without a diff. */
export function overviewDeltas(env: Envelope): { agents: Delta | null; findings: Delta | null; authority: Delta | null; elevated: Delta | null } {
  const diff = env.diff;
  if (!diff) return { agents: null, findings: null, authority: null, elevated: null };
  const highImpact = new Set(env.vocabulary.high_impact_capabilities);
  const sensitive = new Set(env.vocabulary.sensitive_integrations);
  let authority = 0;
  let elevated = 0;
  for (const c of diff.agents.changed) {
    if (c.capabilities.added.some((x) => x.high_impact ?? highImpact.has(x.id)) || c.integrations.added.some((x) => x.sensitive ?? sensitive.has(x.id))) authority += 1;
    if (c.dimension_delta.some((d) => d.direction === "increased" && d.to === "elevated")) elevated += 1;
  }
  for (const a of diff.agents.added) if (a.capabilities.some((x) => highImpact.has(x)) || a.integrations.some((x) => sensitive.has(x))) authority += 1;
  // Counted on findings as shown. A known finding that gained a second location is not a new finding,
  // so this can be lower than the diff's count of new records.
  const fresh = newFingerprints(env);
  const newHigh = activeFindings(env).filter((r) => riskLevel(r.finding.severity) === "high" && isNewFinding(r, fresh)).length;
  return {
    agents: { value: diff.summary.agents_added - diff.summary.agents_removed, label: `${diff.summary.agents_added} added, ${diff.summary.agents_removed} removed` },
    findings: { value: newHigh - diff.summary.findings_delta.resolved, label: `${newHigh} new, ${diff.summary.findings_delta.resolved} resolved` },
    authority: { value: authority, label: authority ? "gained money or write reach" : "no change in reach" },
    elevated: { value: elevated, label: elevated ? "rose to elevated" : "none rose to elevated" },
  };
}

export interface DimensionBar {
  dimension: TaxonomyDimension;
  counts: Record<RiskLevel, number>;
  total: number;
  maxExposure: Exposure;
  agents: MatrixAgent[];
}

/** Active findings per dimension by risk level, in taxonomy order, with the org-level exposure and the agents behind it. */
export function findingsByDimension(env: Envelope): DimensionBar[] {
  const cells = dimensionMatrix(env, "owasp").flatMap((g) => g.cells);
  const active = activeFindings(env);
  return cells.map((cell) => {
    const counts: Record<RiskLevel, number> = { high: 0, medium: 0, low: 0 };
    for (const ref of active) if (ref.finding.dimensions?.includes(cell.dimension.id)) counts[riskLevel(ref.finding.severity)] += 1;
    return { dimension: cell.dimension, counts, total: counts.high + counts.medium + counts.low, maxExposure: cell.maxExposure, agents: cell.agents };
  });
}

export function initials(name: string): string {
  const clean = name.replace(/[·_-]+/g, " ").trim();
  const parts = clean.split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}
