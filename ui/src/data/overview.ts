/**
 * Everything the Overview says, derived from the envelope. Each figure is a
 * count of something the scanner reported; nothing here scores or re-ranks.
 * Where the scan gives no basis for a statement (no baseline, no declared
 * business context, no agents), the function returns null or an empty list
 * and the screen says so instead of filling the gap.
 */
import type { Envelope, RegisterRow, Severity } from "./types";
import { autonomyOf, canMoveMoney, declaredOf, exposureOf, providersOf, toolsOf, uniqueAgentOf, uniqueAgents, type UniqueAgent } from "./agents";
import { safeguardRows } from "./controls";
import { agentToModel, candidateAgents, intakeFromEnvelope } from "./lossInputs";
import { EVENTS, indicate, money } from "./lossModel";
import { agentChanges, largestStep, lossTrendMax, type TrendPoint } from "./lossTrend";
import { PLAIN_ACTION, PLAIN_WHY, autonomyLabel, dimensionSubtitle, prose } from "./labels";
import { toolRows } from "./inventory";
import { summarize as summarizeRegister } from "./register";
import { SEVERITY_RANK, activeFindings, countByLevel, findingTitle, findingsByDimension, isNewFinding, newFingerprints, pluralize, riskLevel, type FindingRef, type RiskLevel } from "./selectors";

// --- what we have ---------------------------------------------------------------

/** Unique agents that can move money: a money-moving tool, or the payment capability, on any of their records. */
export function moneyMovers(env: Envelope): UniqueAgent[] {
  return uniqueAgents(env).filter(canMoveMoney);
}

export interface Holdings {
  /** Unique agents. */
  agents: number;
  /** Scanned records behind them. */
  records: number;
  moneyMovers: number;
  tools: number;
  providers: number;
}

export function holdings(env: Envelope): Holdings {
  const agents = uniqueAgents(env);
  return {
    agents: agents.length,
    records: env.registry.agents.length,
    moneyMovers: moneyMovers(env).length,
    // Distinct tools, the Agent Inventory's count: a tool two agents share is one tool.
    tools: toolRows(env).length,
    providers: new Set(agents.flatMap(providersOf)).size,
  };
}

/** Where the agents were found, in words: application code, and each platform's definitions. */
const PLATFORM_LABEL: Record<string, string> = { bedrock: "AWS", sagemaker: "AWS", databricks: "Databricks", vertex: "Google Cloud", azure: "Azure" };
export function scanSources(env: Envelope): string[] {
  const agents = env.registry.agents;
  const out: string[] = [];
  if (agents.some((a) => a.source !== "iac")) out.push("application code");
  const platforms = [...new Set(agents.filter((a) => a.source === "iac").map((a) => PLATFORM_LABEL[a.platform ?? ""] ?? a.platform ?? "infrastructure"))].sort();
  if (platforms.length) out.push(`${joinWords(platforms)} definitions`);
  return out;
}

export function joinWords(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** "3 customer-facing, 2 internal", from the declared `users` of each agent. Empty when nothing is declared. */
export function audienceLine(env: Envelope): string {
  let customer = 0, internal = 0, undeclared = 0;
  for (const u of uniqueAgents(env)) {
    const users = declaredOf(u)?.users;
    if (!users) undeclared += 1;
    else if (users === "internal") internal += 1;
    else customer += 1;
  }
  if (!customer && !internal) return "";
  return [customer ? `${customer} customer-facing` : "", internal ? `${internal} internal` : "", undeclared ? `${undeclared} not declared` : ""].filter(Boolean).join(", ");
}

export interface NewestAgent {
  name: string;
  id: string;
  /** Date of the first scan that saw it, from history. Null when only the diff says it is new. */
  date: string | null;
  /** "moves money with no approval detected", "moves money, human approval detected", or "does not move money". */
  note: string;
}

/** The agent added most recently: one the diff lists as added, or failing a diff, the last one to appear in history. */
export function newestAgent(env: Envelope): NewestAgent | null {
  const agents = uniqueAgents(env);
  const history = [...env.history].filter((h) => Array.isArray(h.agents)).sort((a, b) => a.head_commit.date.localeCompare(b.head_commit.date));
  const firstSeen = (u: UniqueAgent) => history.find((h) => h.agents!.some((r) => u.records.some((x) => x.id === r.id)))?.head_commit.date ?? null;
  let newest: UniqueAgent | undefined;
  const added = new Set((env.diff?.agents.added ?? []).map((a) => uniqueAgentOf(env, a.agent_id)?.id ?? a.agent_id));
  const candidates = agents.filter((u) => added.has(u.id));
  if (candidates.length) newest = candidates.sort((a, b) => (firstSeen(b) ?? "").localeCompare(firstSeen(a) ?? "") || a.name.localeCompare(b.name))[0];
  else if (history.length > 1) {
    const dated = agents.map((u) => ({ u, date: firstSeen(u) })).filter((x) => x.date && x.date > history[0]!.head_commit.date);
    newest = dated.sort((a, b) => b.date!.localeCompare(a.date!) || a.u.name.localeCompare(b.u.name))[0]?.u;
  }
  if (!newest) return null;
  const row = safeguardRows(env).find((r) => r.agent === newest);
  const note = !canMoveMoney(newest) ? "does not move money" : row?.states["approval"] === "detected" ? "moves money, human approval detected" : "moves money with no approval detected";
  return { name: newest.name, id: newest.id, date: firstSeen(newest), note };
}

// --- risk mapping ------------------------------------------------------------------

export interface HighLine {
  fingerprint: string;
  agents: string[];
  /** The plain title, e.g. "A payment can be charged twice if a request is retried." */
  title: string;
  isNew: boolean;
}

/** One line per high-severity finding as shown, highest severity first, then by agent. */
export function highLines(env: Envelope): HighLine[] {
  const fresh = newFingerprints(env);
  return activeFindings(env)
    .filter((r) => riskLevel(r.finding.severity) === "high")
    .map((r) => ({ fingerprint: r.finding.fingerprint, agents: [...new Set(r.uniqueAgents.map((u) => u.name))].sort(), title: findingTitle(env, r.finding), isNew: isNewFinding(r, fresh), severity: r.finding.severity }))
    .sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || a.agents.join().localeCompare(b.agents.join()) || a.title.localeCompare(b.title))
    .map(({ fingerprint, agents, title, isNew }) => ({ fingerprint, agents, title, isNew }));
}

/** "+1 high since last scan (meridian-support)". Empty without a baseline. */
export function newHighLine(env: Envelope): string {
  if (!env.diff) return "";
  const fresh = newFingerprints(env);
  const refs = activeFindings(env).filter((r) => riskLevel(r.finding.severity) === "high" && isNewFinding(r, fresh));
  const resolved = env.diff.summary.findings_delta.resolved;
  if (!refs.length) return resolved ? `No new high since last scan, ${resolved} resolved` : "No new high since last scan";
  const names = [...new Set(refs.flatMap((r) => r.uniqueAgents.map((u) => u.name)))].sort();
  return `+${refs.length} high since last scan${names.length ? ` (${names.join(", ")})` : ""}`;
}

// --- are we protected -------------------------------------------------------------

export interface Protection {
  moneyMovers: number;
  /** Money movers on which the scanner detected human approval. */
  approved: number;
  /** Tools that can move money, and how many of them have no guardrail detected. */
  moneyTools: number;
  moneyToolsWithoutGuardrail: number;
  /** Findings of a money action that can repeat on retry (AI008). */
  doublePost: number;
}

/** The same rows the Controls & Safeguards screen shows, so the two cannot disagree. */
export function protection(env: Envelope): Protection {
  const movers = new Set(moneyMovers(env));
  const rows = safeguardRows(env);
  return {
    moneyMovers: movers.size,
    approved: rows.filter((r) => movers.has(r.agent) && r.states["approval"] === "detected").length,
    moneyTools: rows.reduce((n, r) => n + r.moneyTools, 0),
    moneyToolsWithoutGuardrail: rows.reduce((n, r) => n + r.moneyToolsWithoutGuardrail, 0),
    doublePost: activeFindings(env).filter((r) => r.finding.rule_id === "AI008").length,
  };
}

// --- risk mapping: agents on a spectrum -------------------------------------------

export interface SpectrumRow {
  id: string;
  name: string;
  /** The agent's highest dimension score, 0 to 100: its position on the spectrum. */
  score: number;
  level: "low" | "moderate" | "elevated" | "none";
  /** Added since the last scan. */
  isNew: boolean;
}

/** The scanner's buckets: 1 to 24 low, 25 to 54 moderate, 55 and up elevated. */
export const SPECTRUM_BANDS = { moderate: 25, elevated: 55 };

/** Every agent, highest score first, with the scanner's exposure level for that score. */
export function agentSpectrum(env: Envelope): SpectrumRow[] {
  const added = new Set((env.diff?.agents.added ?? []).map((a) => uniqueAgentOf(env, a.agent_id)?.id ?? a.agent_id));
  return uniqueAgents(env)
    .map((u) => {
      const score = Math.max(0, ...u.records.flatMap((r) => (r.dimension_assessment?.dimensions ?? []).map((d) => d.score)));
      const level = score >= SPECTRUM_BANDS.elevated ? "elevated" : score >= SPECTRUM_BANDS.moderate ? "moderate" : score > 0 ? "low" : "none";
      return { id: u.id, name: u.name, score, level, isNew: added.has(u.id) } as SpectrumRow;
    })
    .sort((a, b) => b.score - a.score || Number(b.isNew) - Number(a.isNew) || a.name.localeCompare(b.name));
}

// --- what it could cost ---------------------------------------------------------------

export interface CostOutlook {
  /** The agent the figures are modelled for: the loss model runs per agent, and bad years do not add up across agents. */
  agent: string;
  agentId: string;
  /** The largest single-agent bad year at each past scan, oldest first, ending at today's. Empty without history. */
  trend: TrendPoint[];
  badYear: number;
  averageYear: number;
  /** Declared policy limits that do not exclude AI losses. */
  covered: number;
  /** Declared policy types that exclude AI, e.g. ["cyber"]. */
  excluding: string[];
  policies: number;
  /** Each declared policy's limit, largest first. */
  limits: { label: string; limit: number; aiExcluded: boolean }[];
  /** Declared risk capacity: the most the company will carry from one AI failure in a year. Null when not declared. */
  capacity: number | null;
  confidence: "high" | "medium" | "low";
}

/** One seed everywhere the loss model runs, so every screen reports the same simulation. */
export const LOSS_SEED = 42;

const POLICY_LABEL: Record<string, string> = { cyber: "cyber", tech_eo: "tech E&O", crime: "crime" };

/**
 * Null unless the applicant declared their business context: on placeholder
 * revenue and records the figure would be the model's, not theirs, and the
 * Overview is not the place to explain that.
 */
export function costOutlook(env: Envelope, years?: number): CostOutlook | null {
  const { intake, monthlyVolume, declared } = intakeFromEnvelope(env);
  const agent = candidateAgents(env)[0];
  if (!declared || !agent) return null;
  const { model } = agentToModel(env, agent, monthlyVolume);
  // The same seed and the same number of simulated years as the Financial Exposure screen, so the two
  // show the same figure. Skipping the bootstrap changes the confidence band only, not the summary.
  // `years` exists for tests, which do not need the full run.
  const r = indicate(EVENTS, model, intake, LOSS_SEED, {}, { years, noBoot: true });
  const policies = intake.existing_coverage;
  return {
    agent: model.name,
    agentId: agent.id,
    trend: lossTrendMax(env, LOSS_SEED, years),
    badYear: r.summary.pMid,
    averageYear: r.summary.eal,
    covered: policies.filter((p) => !p.ai_exclusion).reduce((n, p) => n + p.limit, 0),
    excluding: policies.filter((p) => p.ai_exclusion).map((p) => POLICY_LABEL[p.type] ?? p.type),
    policies: policies.length,
    limits: [...policies].sort((a, b) => b.limit - a.limit).map((p) => ({ label: `${POLICY_LABEL[p.type] ?? p.type} policy limit`, limit: p.limit, aiExcluded: p.ai_exclusion })),
    capacity: typeof env.intake?.risk_capacity === "number" && env.intake.risk_capacity > 0 ? env.intake.risk_capacity : null,
    confidence: r.confidence,
  };
}

// --- needs your attention ---------------------------------------------------------------

export interface AttentionItem {
  ruleId: string;
  severity: Severity;
  level: RiskLevel;
  /** The plain-English consequence, from the crosswalk. */
  title: string;
  agents: string[];
  dimension: string | null;
  findings: number;
  /** First finding of the group, for the evidence link. */
  fingerprint: string;
  /** Register rows these findings contribute to. */
  register: RegisterRow[];
  /** The rule's remediation guidance, as the scanner wrote it. */
  remediation: string;
  /** The findings behind the item, highest severity first. */
  refs: FindingRef[];
}

/** Active findings, one item per rule, so the same problem on several agents is read once. Highest severity first. */
export function attention(env: Envelope, n = 3): AttentionItem[] {
  const groups = new Map<string, FindingRef[]>();
  for (const ref of activeFindings(env)) {
    const list = groups.get(ref.finding.rule_id);
    if (list) list.push(ref);
    else groups.set(ref.finding.rule_id, [ref]);
  }
  const dimensionNames = new Map(env.taxonomy.dimensions.map((d) => [d.id, d.name]));
  const elevatedIds = new Set(elevatedDimensions(env).map((d) => d.id));
  const items: AttentionItem[] = [];
  for (const [ruleId, refs] of groups) {
    refs.sort((a, b) => SEVERITY_RANK[b.finding.severity] - SEVERITY_RANK[a.finding.severity] || a.finding.path.localeCompare(b.finding.path) || a.finding.line - b.finding.line);
    const first = refs[0]!.finding;
    const fingerprints = new Set(refs.flatMap((r) => r.evidence.map((f) => f.fingerprint)));
    // A finding can sit in several dimensions; name the one that is elevated, since that is why it matters.
    const dimensionIds = [...new Set(refs.flatMap((r) => r.finding.dimensions ?? []))];
    const dimensionId = dimensionIds.find((id) => elevatedIds.has(id)) ?? dimensionIds[0];
    items.push({
      ruleId,
      severity: first.severity,
      level: riskLevel(first.severity),
      title: findingTitle(env, first),
      agents: [...new Set(refs.flatMap((r) => r.uniqueAgents.map((u) => u.name)))].sort(),
      dimension: dimensionId ? dimensionNames.get(dimensionId) ?? null : null,
      findings: refs.length,
      fingerprint: first.fingerprint,
      register: env.register.filter((row) => row.contributing_findings.some((fp) => fingerprints.has(fp))),
      remediation: env.rules[ruleId]?.remediation || first.remediation || "",
      refs,
    });
  }
  items.sort((a, b) => SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] || b.findings - a.findings || a.ruleId.localeCompare(b.ruleId));
  return items.slice(0, n);
}

/** What the register says about the risks this item feeds, e.g. "1 marked for transfer". Empty when it says nothing. */
export function attentionStatus(item: AttentionItem): string {
  const declared = item.register.filter((row) => row.declared?.treatment);
  if (!declared.length) return "";
  const counts = new Map<string, number>();
  for (const row of declared) counts.set(row.declared!.treatment!, (counts.get(row.declared!.treatment!) ?? 0) + 1);
  const phrase: Record<string, string> = { transfer: "marked for transfer", mitigate: "being mitigated", accept: "accepted", avoid: "being avoided" };
  return [...counts].map(([t, c]) => `${c} ${phrase[t] ?? t}`).join(" · ");
}

/** The title with the agents named first: "account-actions and meridian-support: a payment can be charged twice if a request is retried." */
export function attentionTitle(item: AttentionItem): string {
  const who = item.agents.length ? joinWords(item.agents) : "Repository";
  const title = item.title.replace(/^[A-Z](?![A-Z])/, (c) => c.toLowerCase());
  return `${who}: ${title}`;
}

const NUMBER_TEXT = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
const countWord = (n: number) => NUMBER_TEXT[n] ?? String(n);

/**
 * What the scan saw, in one sentence built from the finding: the declared
 * value against the inferred one, the tool and file for a code finding.
 * Falls back to the scanner's first sentence, without its backticks.
 */
export function scanSaw(item: AttentionItem): string {
  const first = item.refs[0]?.finding;
  if (!first) return "";
  const where = `${first.path.split("/").slice(-2).join("/")}, line ${first.line}`;
  const agents = item.refs.flatMap((r) => r.uniqueAgents);
  const named = item.agents.length === 1 ? "The agent" : item.agents.length === 2 ? "Both agents" : `All ${countWord(item.agents.length)} agents`;
  switch (item.ruleId) {
    case "DECL001": {
      const declared = [...new Set(agents.map((u) => declaredOf(u)?.autonomy_intent).filter(Boolean))].map((x) => autonomyLabel(x).toLowerCase());
      const inferred = [...new Set(agents.map((u) => autonomyOf(u)).filter(Boolean))].map((x) => autonomyLabel(x).toLowerCase());
      const tools = new Set(agents.flatMap((u) => toolsOf(u).filter((t) => t.money_action).map((t) => t.name)));
      return `Declared: ${joinWords(declared) || "human approval"}. In the code: ${joinWords(inferred) || "acts on its own"}, with ${tools.size ? `${pluralize(tools.size, "tool")} that can move money and ` : ""}no approval step detected.`;
    }
    case "AI008": {
      const tool = /`([^`]+)`/.exec(first.message ?? "")?.[1] ?? /def\s+(\w+)/.exec(first.snippet ?? "")?.[1] ?? "The payment call";
      return `${tool} is retried on failure with no unique reference per request, in ${where}. ${named} ${item.agents.length === 1 ? "calls" : "call"} it.`;
    }
    case "DECL005":
      return item.agents.length > 1 ? `${named} are declared production, but no logging or tracing was found in their code.` : `Declared production, but no logging or tracing was found in ${where}.`;
    case "CTRL007":
      return `No feature flag or setting that stops the agent was found in ${where}.`;
    case "AI005":
      return `The model is named without a version in ${where}.`;
    default: {
      const sentence = prose(first.message ?? first.title).replace(/`/g, "").split(/(?<=[.!?])\s+/)[0] ?? "";
      return sentence;
    }
  }
}

export function whyItMatters(item: AttentionItem): string {
  return PLAIN_WHY[item.ruleId] ?? "";
}

export interface FixFirst {
  item: AttentionItem;
  /** "account-actions and meridian-support can move money without approval" */
  title: string;
  found: string;
  why: string;
  fix: string;
}

/**
 * The one finding to fix first: the top attention item, said in three short
 * lines. DECL001 on money-moving agents has its own wording; other rules use
 * the item's plain title, what the scan saw, why it matters and the fix.
 */
export function fixFirst(env: Envelope): FixFirst | null {
  const item = attention(env, 1)[0];
  if (!item) return null;
  const agents = item.refs.flatMap((r) => r.uniqueAgents);
  const moneyTools = new Set(agents.flatMap((u) => toolsOf(u).filter((t) => t.money_action).map((t) => t.name)));
  if (item.ruleId === "DECL001" && moneyTools.size) {
    const who = item.agents.length ? joinWords(item.agents) : "This agent";
    const both = item.agents.length === 1 ? "The agent is" : item.agents.length === 2 ? "Both agents are" : `All ${countWord(item.agents.length)} agents are`;
    const its = item.agents.length === 1 ? "its" : "their";
    return {
      item,
      title: `${who} can move money without approval`,
      found: `${both} declared as needing human approval, but ${moneyTools.size} of ${its} tools can move money with no approval step in the code.`,
      why: "Your policy assumes a person signs off on these actions. Right now nobody does, so losses would be uncontrolled.",
      fix: `Add an approval step before these tools run, or update the declaration if the ${item.agents.length === 1 ? "agent is" : "agents are"} meant to act on ${its} own.`,
    };
  }
  return { item, title: attentionTitle(item).replace(/\.$/, ""), found: scanSaw(item), why: whyItMatters(item), fix: nextAction(item) };
}

/** Sentences that set the scene rather than say what to do. */
const CONTEXT_OPENER = /^(this|these|an?|the|traces|reported|observability|stoa-declared\.toml)\b/i;

/**
 * One sentence of the rule's remediation guidance, in the scanner's words. A
 * one-sentence remediation is already an instruction. A longer one explains
 * first and instructs last, so this takes the last sentence that is not
 * scene-setting.
 */
export function nextAction(item: AttentionItem): string {
  const plain = PLAIN_ACTION[item.ruleId];
  if (plain) return plain;
  const sentences = prose(item.remediation).split(/(?<=[.!?])\s+(?=[A-Z[])/).map((x) => x.trim()).filter(Boolean);
  if (!sentences.length) return "";
  return [...sentences].reverse().find((x) => !CONTEXT_OPENER.test(x)) ?? sentences[sentences.length - 1]!;
}

// --- what changed -------------------------------------------------------------------------

export interface ChangeLine {
  direction: "up" | "down" | "same";
  title: string;
  detail: string;
}

const CAPABILITY_PHRASE: Record<string, string> = { payment_access: "payment access", database_write: "database write access", shell_execution: "shell access", file_write: "file write access", email_send: "the ability to send email" };

/** The previous scan and the current one, as history hashes, when the history holds both. */
function lastTwoScans(env: Envelope): [string, string] | null {
  const dated = [...env.history].filter((h) => Array.isArray(h.agents)).sort((a, b) => a.head_commit.date.localeCompare(b.head_commit.date));
  if (dated.length < 2) return null;
  return [dated[dated.length - 2]!.head_commit.hash, dated[dated.length - 1]!.head_commit.hash];
}

/**
 * Null without a baseline. Otherwise three lines: agents added or removed,
 * the biggest change to an agent that was already there, and what those did
 * to the modeled loss and the findings. Pass the cost outlook when it is
 * known, so the third line can quote the modeled loss before and after.
 */
export function whatChanged(env: Envelope, cost?: CostOutlook | null): ChangeLine[] | null {
  const diff = env.diff;
  if (!diff) return null;
  const highImpact = new Set(env.vocabulary.high_impact_capabilities);
  const lines: ChangeLine[] = [];

  // 1. Agents added and removed, named.
  const addedNames = [...new Set(diff.agents.added.map((a) => uniqueAgentOf(env, a.agent_id)?.name ?? a.name))].sort();
  const removedNames = [...new Set(diff.agents.removed.map((a) => a.name))].sort();
  const addedMoney = diff.agents.added.filter((a) => a.capabilities.some((c) => highImpact.has(c))).map((a) => uniqueAgentOf(env, a.agent_id)?.name ?? a.name);
  lines.push(addedNames.length || removedNames.length
    ? {
      direction: addedNames.length >= removedNames.length ? "up" : "down",
      title: `${addedNames.length ? `${pluralize(addedNames.length, "agent")} added` : ""}${addedNames.length && removedNames.length ? ", " : ""}${removedNames.length ? `${pluralize(removedNames.length, "agent")} removed` : ""}: ${joinWords([...addedNames, ...removedNames.map((n) => `${n} (removed)`)])}.`,
      detail: addedMoney.length ? `${joinWords([...new Set(addedMoney)])} can move money.` : "",
    }
    : { direction: "same", title: "No agents added or removed.", detail: "" });

  // 2. The biggest change to an existing agent: an in-code limit that came off, an agent that now acts on
  //    its own, a declared limit raised (all from the history), or a capability gained (from the diff).
  const scans = lastTwoScans(env);
  const changes = scans ? agentChanges(env, scans[0], scans[1]) : [];
  const gained = diff.agents.changed.flatMap((c) => c.capabilities.added.filter((x) => x.high_impact ?? highImpact.has(x.id)).map((x) => ({ name: uniqueAgentOf(env, c.agent_id)?.name ?? c.name, capability: x.id })));
  const phrases: string[] = [];
  // A raised declared limit on an agent that also lost its in-code cap is part of the same story, told in the detail.
  const uncappedIds = new Set(changes.filter((c) => c.kind === "uncapped").map((c) => c.id));
  for (const kind of ["uncapped", "autonomous", "limit"] as const) for (const c of changes.filter((x) => x.kind === kind && !(kind === "limit" && uncappedIds.has(x.id)))) {
    phrases.push(kind === "uncapped" ? `${c.name} lost its amount cap` : kind === "autonomous" ? `${c.name} now acts on its own` : `the declared limit for ${c.name} rose from $${Number(c.from).toLocaleString()} to $${Number(c.to).toLocaleString()}`);
  }
  for (const g of gained) phrases.push(`${g.name} gained ${CAPABILITY_PHRASE[g.capability] ?? g.capability.replace(/_/g, " ")}`);
  const unique = [...new Set(phrases)];
  if (unique.length) {
    const first = unique[0]!;
    const uncapped = changes.find((c) => c.kind === "uncapped" && first.startsWith(c.name));
    const declaredMax = uncapped ? declaredOf(uniqueAgents(env).find((u) => u.id === uncapped.id)!)?.economic_authority?.max_per_action?.amount : undefined;
    const detail = [
      uncapped ? (declaredMax ? `Every action was limited in code; now the only limit is the $${declaredMax.toLocaleString()} written in the system prompt.` : "Every action was limited in code; no limit is enforced now.") : "",
      unique.length > 1 ? `Also: ${joinWords(unique.slice(1))}.` : "",
    ].filter(Boolean).join(" ");
    // Agent names keep their case, so the line is not capitalised when it opens with one.
    lines.push({ direction: "up", title: `${first.startsWith("the ") ? `T${first.slice(1)}` : first}.`, detail });
  } else {
    lines.push({ direction: "same", title: "No existing agent gained reach.", detail: "No new money or system access, and no limit came off." });
  }

  // 3. The consequence: the modeled loss before and after, new high findings, agents at elevated exposure.
  const fresh = newFingerprints(env);
  const newHigh = activeFindings(env).filter((r) => riskLevel(r.finding.severity) === "high" && isNewFinding(r, fresh)).length;
  const agents = uniqueAgents(env);
  const elevatedNow = agents.filter((u) => exposureOf(u) === "elevated").length;
  const trend = cost?.trend ?? [];
  const before = trend.length >= 2 ? trend[trend.length - 2]! : null;
  const now = trend.length ? trend[trend.length - 1]! : null;
  const rose = before && now && now.badYear > before.badYear * 1.005;
  const fell = before && now && now.badYear < before.badYear * 0.995;
  const tail = [newHigh ? `${pluralize(newHigh, "new high-severity finding")}.` : "No new high-severity findings.", `${elevatedNow} of ${pluralize(agents.length, "agent")} ${elevatedNow === 1 ? "is" : "are"} elevated.`].join(" ");
  if (before && now) lines.push({ direction: rose ? "up" : fell ? "down" : "same", title: `Modeled loss in a bad year: ${money(before.badYear)} to ${money(now.badYear)}.`, detail: tail });
  else if (now) lines.push({ direction: newHigh ? "up" : "same", title: `Modeled loss in a bad year: ${money(now.badYear)}.`, detail: tail });
  else lines.push({ direction: newHigh ? "up" : "same", title: newHigh ? `${pluralize(newHigh, "new high-severity finding")}.` : "No new high-severity findings.", detail: `${elevatedNow} of ${pluralize(agents.length, "agent")} ${elevatedNow === 1 ? "is" : "are"} elevated.` });
  return lines;
}

// --- where exposure is elevated -------------------------------------------------------------

export interface ElevatedDimension {
  id: string;
  name: string;
  definition: string;
  findings: number;
}

/** "The other 6 dimensions are low or show no findings." Says moderate when one is. */
export function otherDimensionsLine(env: Envelope): string {
  const bars = findingsByDimension(env);
  const others = bars.filter((b) => b.maxExposure !== "elevated");
  if (!others.length) return "";
  const moderate = others.some((b) => b.maxExposure === "moderate");
  const noun = others.length === 1 ? "dimension is" : "dimensions are";
  return `The other ${others.length} ${noun} ${moderate ? "moderate or lower" : "low or show no findings"}.`;
}

export function elevatedDimensions(env: Envelope): ElevatedDimension[] {
  return findingsByDimension(env)
    .filter((bar) => bar.maxExposure === "elevated")
    .map((bar) => ({ id: bar.dimension.id, name: bar.dimension.name, definition: dimensionSubtitle(bar.dimension.id, bar.dimension.definition), findings: bar.total }));
}

// --- register and assessment -------------------------------------------------------------------

export interface RegisterCard {
  /** Risks the scan reports. A declared risk the scan no longer finds is counted in `stale`, not here. */
  risks: number;
  /** Count per treatment value the register holds, in the order first seen, e.g. [["transfer", 1], ["mitigate", 1]]. */
  treatments: [string, number][];
  decided: number;
  /** Risks with no treatment recorded yet. */
  awaiting: number;
  stale: number;
}

export function registerCard(env: Envelope): RegisterCard {
  const scanned = env.register.filter((row) => !row.unmatched);
  const counts = new Map<string, number>();
  for (const row of scanned) {
    const t = row.declared?.treatment;
    if (t) counts.set(t, (counts.get(t) ?? 0) + 1);
  }
  const decided = [...counts.values()].reduce((a, b) => a + b, 0);
  return { risks: scanned.length, treatments: [...counts], decided, awaiting: scanned.length - decided, stale: summarizeRegister(env).unmatched };
}

// --- where you stand ----------------------------------------------------------------------------

/** A sentence as runs of text; `strong` runs are the figures the screen emphasises. */
export type Sentence = (string | { strong: string })[];

export function sentenceText(sentence: Sentence): string {
  return sentence.map((part) => (typeof part === "string" ? part : part.strong)).join("");
}

/** "two months", "six weeks", "nine days": the span between two dates, in the largest unit that reads well. */
export function spanWords(fromIso: string, toIso: string): string {
  const days = Math.round((Date.parse(toIso) - Date.parse(fromIso)) / 86_400_000);
  if (days >= 55) { const m = Math.round(days / 30.4); return `${countWord(m)} ${m === 1 ? "month" : "months"}`; }
  if (days >= 14) { const w = Math.round(days / 7); return `${countWord(w)} weeks`; }
  return `${countWord(Math.max(days, 1))} ${days === 1 ? "day" : "days"}`;
}

const MONTH_NAME = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const monthOf = (iso: string) => MONTH_NAME[Number.parseInt(iso.slice(5, 7), 10) - 1] ?? "";

/**
 * One sentence. With a trend: how much the modeled loss rose, over what
 * span, and the push that did it, read from the history (the agent that went
 * live, or the cap that came off). Without a trend: the figure. Without a
 * figure: what can move money and whether approval was detected.
 */
export function standing(env: Envelope, cost: CostOutlook | null): Sentence[] {
  const agents = uniqueAgents(env).length;
  if (agents === 0) return [["No AI agents were found in this scan, so there is nothing to report on yet."]];
  if (cost) {
    const trend = cost.trend;
    const first = trend[0], last = trend[trend.length - 1];
    const step = largestStep(env, trend);
    if (first && last && trend.length >= 2 && last.badYear > first.badYear * 1.005) {
      const sentence: Sentence = ["Modeled loss in a bad year has risen from ", { strong: money(first.badYear) }, " to ", { strong: money(last.badYear) }, ` in ${spanWords(first.date, last.date)}`];
      if (step && step.share >= 0.7) {
        const uncapped = step.changes.find((c) => c.kind === "uncapped");
        const cause = step.added.length ? `${joinWords(step.added)} went live` : uncapped ? `the amount cap on ${uncapped.name} came off` : "";
        sentence.push(`, driven by one push in ${monthOf(step.to.date)}${cause ? `: ${cause}` : ""}.`);
      } else sentence.push(` over ${pluralize(trend.length, "scan")}.`);
      return [sentence];
    }
    if (first && last && trend.length >= 2 && last.badYear < first.badYear * 0.995) return [["Modeled loss in a bad year has fallen from ", { strong: money(first.badYear) }, " to ", { strong: money(last.badYear) }, ` in ${spanWords(first.date, last.date)}.`]];
    return [["Modeled loss in a bad year is ", { strong: money(cost.badYear) }, "."]];
  }
  const p = protection(env);
  if (p.moneyMovers > 0) {
    // A detection result, not a claim about the business process: "was detected", never "has".
    const approval = p.approved === 0 ? `no human approval was detected on ${p.moneyMovers === 1 ? "it" : p.moneyMovers === 2 ? "either" : "any of them"}`
      : p.approved === p.moneyMovers ? `human approval was detected on ${p.moneyMovers === 1 ? "it" : p.moneyMovers === 2 ? "both" : "all of them"}`
      : `human approval was detected on ${p.approved} of them`;
    return [[`${pluralize(p.moneyMovers, "agent")} can move money on ${p.moneyMovers === 1 ? "its" : "their"} own, and ${approval}.`]];
  }
  const high = countByLevel(activeFindings(env)).high;
  return [[`${pluralize(agents, "AI agent")} found, none of which can move money. ${high ? `${pluralize(high, "high-severity finding")} ${high === 1 ? "needs" : "need"} attention.` : "No high-severity findings."}`]];
}
