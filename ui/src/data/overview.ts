/**
 * Everything the Overview says, derived from the envelope. Each figure is a
 * count of something the scanner reported; nothing here scores or re-ranks.
 * Where the scan gives no basis for a statement (no baseline, no declared
 * business context, no agents), the function returns null or an empty list
 * and the screen says so instead of filling the gap.
 */
import type { Envelope, RegisterRow, Severity } from "./types";
import { canMoveMoney, exposureOf, providersOf, toolsOf, uniqueAgentOf, uniqueAgents, type UniqueAgent } from "./agents";
import { safeguardRows } from "./controls";
import { agentToModel, candidateAgents, intakeFromEnvelope } from "./lossInputs";
import { EVENTS, indicate, money } from "./lossModel";
import { dimensionSubtitle, prose } from "./labels";
import { summarize as summarizeRegister } from "./register";
import { SEVERITY_RANK, activeFindings, agentLabel, countByLevel, findingTitle, findingsByDimension, isNewFinding, newFingerprints, overviewDeltas, pluralize, riskLevel, type FindingRef, type RiskLevel } from "./selectors";

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
    // A tool seen in an agent's code and again in its infrastructure is one tool.
    tools: agents.reduce((n, a) => n + toolsOf(a).length, 0),
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

// --- what it could cost ---------------------------------------------------------------

export interface CostOutlook {
  /** The agent the figures are modelled for: the loss model runs per agent, and bad years do not add up across agents. */
  agent: string;
  badYear: number;
  averageYear: number;
  /** Declared policy limits that do not exclude AI losses. */
  covered: number;
  /** Declared policy types that exclude AI, e.g. ["cyber"]. */
  excluding: string[];
  policies: number;
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
    badYear: r.summary.pMid,
    averageYear: r.summary.eal,
    covered: policies.filter((p) => !p.ai_exclusion).reduce((n, p) => n + p.limit, 0),
    excluding: policies.filter((p) => p.ai_exclusion).map((p) => POLICY_LABEL[p.type] ?? p.type),
    policies: policies.length,
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
}

/** Active findings, one item per rule, so the same problem on several agents is read once. Highest severity first. */
export function attention(env: Envelope, n = 4): AttentionItem[] {
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
      title: first.crosswalk?.so_what || env.rules[ruleId]?.crosswalk?.so_what || first.title,
      agents: [...new Set(refs.flatMap((r) => r.uniqueAgents.map((u) => u.name)))].sort(),
      dimension: dimensionId ? dimensionNames.get(dimensionId) ?? null : null,
      findings: refs.length,
      fingerprint: first.fingerprint,
      register: env.register.filter((row) => row.contributing_findings.some((fp) => fingerprints.has(fp))),
      remediation: env.rules[ruleId]?.remediation || first.remediation || "",
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

/** Sentences that set the scene rather than say what to do. */
const CONTEXT_OPENER = /^(this|these|an?|the|traces|reported|observability|stoa-declared\.toml)\b/i;

/**
 * One sentence of the rule's remediation guidance, in the scanner's words. A
 * one-sentence remediation is already an instruction. A longer one explains
 * first and instructs last, so this takes the last sentence that is not
 * scene-setting.
 */
export function nextAction(item: AttentionItem): string {
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

const NUMBER_WORD = ["No", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine"];
const count = (n: number) => NUMBER_WORD[n] ?? String(n);
const CAPABILITY_PHRASE: Record<string, string> = { payment_access: "payment access", database_write: "database write access", shell_execution: "shell access", file_write: "file write access", email_send: "the ability to send email" };

/** Null without a baseline. Otherwise always the same four lines, so an unchanged scan reads as unchanged. */
export function whatChanged(env: Envelope): ChangeLine[] | null {
  const diff = env.diff;
  if (!diff) return null;
  const deltas = overviewDeltas(env);
  const highImpact = new Set(env.vocabulary.high_impact_capabilities);
  const lines: ChangeLine[] = [];

  const gained = diff.agents.changed.flatMap((c) => c.capabilities.added.filter((x) => x.high_impact ?? highImpact.has(x.id)).map((x) => ({ change: c, capability: x.id })));
  // Counted in unique agents: a capability gained by an agent's code and by its Terraform is one agent gaining it.
  const gainers = new Set(gained.map((g) => uniqueAgentOf(env, g.change.agent_id)?.id ?? g.change.agent_id));
  const authority = gainers.size || (deltas.authority?.value ?? 0);
  if (authority > 0) {
    const money = gained.some((g) => g.capability === "payment_access");
    const first = gained[0];
    let detail = "";
    if (first) {
      const agent = env.registry.agents.find((a) => a.id === first.change.agent_id);
      const name = uniqueAgentOf(env, first.change.agent_id)?.name ?? (agent ? agentLabel(agent) : first.change.name);
      detail = `${name} gained ${CAPABILITY_PHRASE[first.capability] ?? first.capability.replace(/_/g, " ")}`;
      // Commit and author exist only when the scan ran inside git.
      if (agent?.last_commit) detail += ` in ${agent.last_commit.hash.slice(0, 7)}`;
      if (agent?.last_touched_by) detail += `, last changed by ${agent.last_touched_by}`;
      detail += gained.length > 1 ? `, and ${pluralize(gained.length - 1, "other capability change")}.` : ".";
    }
    lines.push({ direction: "up", title: `${count(authority)} more ${authority === 1 ? "agent" : "agents"} can now ${money ? "move money" : "change systems"}.`, detail });
  } else {
    lines.push({ direction: "same", title: "No agent gained new reach.", detail: "No new money or system access." });
  }

  // Findings as shown. A known finding that gained a location (the same rule now also fires on the
  // agent's other record) is said as that, not counted as new.
  const fd = diff.summary.findings_delta;
  const fresh = newFingerprints(env);
  const highNow = activeFindings(env).filter((r) => riskLevel(r.finding.severity) === "high");
  const newHighRefs = highNow.filter((r) => isNewFinding(r, fresh));
  const widened = highNow.filter((r) => !isNewFinding(r, fresh) && r.evidence.some((f) => fresh.has(f.fingerprint)));
  const newHigh = newHighRefs.length;
  if (newHigh > 0 || widened.length > 0 || fd.resolved > 0) {
    const titles = [...new Set(newHighRefs.map((r) => findingTitle(env, r.finding)))];
    const detail = [
      titles.length ? `${titles[0]}${titles.length > 1 ? ` And ${pluralize(titles.length - 1, "other")}.` : ""}` : "",
      widened.length ? `${pluralize(widened.length, "known high-severity finding")} now ${widened.length === 1 ? "has" : "have"} a second evidence location.` : "",
      fd.resolved ? `${pluralize(fd.resolved, "finding")} resolved.` : "",
    ].filter(Boolean).join(" ");
    lines.push({ direction: newHigh > 0 || widened.length > 0 ? "up" : "down", title: newHigh > 0 ? `${newHigh} new high-severity ${newHigh === 1 ? "finding" : "findings"}.` : widened.length ? "No new high-severity findings." : `${pluralize(fd.resolved, "finding")} resolved.`, detail });
  } else {
    lines.push({ direction: "same", title: "No new high-severity findings.", detail: "None resolved either." });
  }

  const risers = new Set(diff.agents.changed.filter((c) => c.dimension_delta.some((d) => d.direction === "increased" && d.to === "elevated")).map((c) => uniqueAgentOf(env, c.agent_id)?.id ?? c.agent_id));
  const agents = uniqueAgents(env);
  const elevatedNow = agents.filter((u) => exposureOf(u) === "elevated").length;
  lines.push(risers.size > 0
    ? { direction: "up", title: `${count(risers.size)} more ${risers.size === 1 ? "agent" : "agents"} at elevated exposure.`, detail: `${elevatedNow} of ${pluralize(agents.length, "agent")} ${elevatedNow === 1 ? "is" : "are"} now elevated.` }
    : { direction: "same", title: "No agent rose to elevated exposure.", detail: `${elevatedNow} of ${pluralize(agents.length, "agent")} ${elevatedNow === 1 ? "is" : "are"} elevated.` });

  // The diff counts scanned records, so that is what this line says.
  const { agents_added: added, agents_removed: removed } = diff.summary;
  lines.push(added || removed
    ? { direction: added > removed ? "up" : removed > added ? "down" : "same", title: `${pluralize(added, "discovered record")} added, ${removed} removed.`, detail: "The change log shows which agents they belong to." }
    : { direction: "same", title: "No agents added or removed.", detail: "" });
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

/**
 * The opening sentences. Each clause is one of the facts above, and a clause
 * with no fact behind it is left out rather than softened.
 */
export function standing(env: Envelope, cost: CostOutlook | null): Sentence[] {
  const agents = uniqueAgents(env).length;
  if (agents === 0) return [["No AI agents were found in this scan, so there is nothing to report on yet."]];
  const out: Sentence[] = [];
  const p = protection(env);
  if (p.moneyMovers > 0) {
    // A detection result, not a claim about the business process: "was detected", never "has".
    const approval = p.approved === 0 ? `and no human approval was detected for ${p.moneyMovers === 1 ? "it" : p.moneyMovers === 2 ? "either" : "any of them"}`
      : p.approved === p.moneyMovers ? `and human approval was detected for ${p.moneyMovers === 1 ? "it" : p.moneyMovers === 2 ? "both" : "all of them"}`
      : `and human approval was detected for ${p.approved} of them`;
    out.push([`${pluralize(p.moneyMovers, "agent")} can move money on ${p.moneyMovers === 1 ? "its" : "their"} own, ${approval}.`]);
  } else {
    const high = countByLevel(activeFindings(env)).high;
    out.push([`${pluralize(agents, "AI agent")} found, and none can move money. ${high ? `${pluralize(high, "high-severity finding")} ${high === 1 ? "needs" : "need"} attention.` : "No high-severity findings."}`]);
  }
  if (cost) out.push(["Modeled loss in a bad year is ", { strong: money(cost.badYear) }, "."]);
  const changed = (whatChanged(env) ?? []).filter((line) => line.direction === "up").length;
  if (changed) out.push([`${pluralize(changed, "thing")} changed since the last scan.`]);
  return out;
}
