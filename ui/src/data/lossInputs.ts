/**
 * Turns a scanned agent plus the applicant's intake into the loss model's
 * inputs. Every mapping is listed on the page so a reader can see which scan
 * fact drove which model input.
 */
import type { Agent, Envelope } from "./types";
import { hasAuthority } from "./selectors";
import type { Autonomy, HumanInLoop, Intake, ModelAgent, Policy } from "./lossModel";

export interface MappingNote { input: string; value: string; from: string }

export const DEFAULT_INTAKE: Intake = { revenue: 10e6, sector: "software", jurisdictions: ["US"], records: 100e3, regulated: false, minors: false, existing_coverage: [] };

const WRITE_CAPS = new Set(["database_write", "filesystem_write", "shell_exec", "payment_access", "email_send", "messaging", "code_execution"]);

const SECTOR_BY_INDUSTRY: [RegExp, string][] = [[/fin|bank|pay|insur/i, "fintech"], [/health|medic|pharma|care/i, "healthtech"], [/edu|school|learn/i, "edtech"], [/retail|commerce|shop/i, "retail"], [/legal|law/i, "legal"]];
const JUR_BY_GEO: Record<string, string> = { us: "US", usa: "US", eu: "EU", de: "EU", fr: "EU", nl: "EU", it: "EU", es: "EU", ie: "EU", ca: "CA", au: "AU", kr: "KR", hk: "HK" };

/** Sector, regulation and jurisdictions the declared facts imply, used when the intake block is silent. */
export function declaredContext(env: Envelope): { sector: string | null; regulated: boolean | null; jurisdictions: string[] } {
  const business = (env.registry.business ?? {}) as { industries?: unknown; regulated_activities?: unknown };
  const industries = Array.isArray(business.industries) ? business.industries.map(String) : [];
  let sector: string | null = null;
  for (const ind of industries) for (const [re, s] of SECTOR_BY_INDUSTRY) if (!sector && re.test(ind)) sector = s;
  if (!sector && industries.length) sector = "software";
  const regulated = Array.isArray(business.regulated_activities) ? business.regulated_activities.length > 0 : null;
  const jur = new Set<string>();
  for (const a of env.registry.agents) for (const g of a.declared?.geography ?? []) { const code = JUR_BY_GEO[g.toLowerCase()] ?? g.toUpperCase(); jur.add(code); }
  return { sector, regulated, jurisdictions: [...jur].sort() };
}

export function intakeFromEnvelope(env: Envelope): { intake: Intake; monthlyVolume: number; declared: boolean } {
  const raw = env.intake;
  const ctx = declaredContext(env);
  const base: Intake = { ...DEFAULT_INTAKE, sector: ctx.sector ?? DEFAULT_INTAKE.sector, regulated: ctx.regulated ?? DEFAULT_INTAKE.regulated, jurisdictions: ctx.jurisdictions.length ? ctx.jurisdictions : DEFAULT_INTAKE.jurisdictions };
  if (!raw) return { intake: base, monthlyVolume: 50_000, declared: false };
  const coverage: Policy[] = (raw.existing_coverage ?? []).filter((p): p is Policy => p.type === "cyber" || p.type === "tech_eo" || p.type === "crime");
  return {
    intake: {
      revenue: raw.revenue ?? base.revenue,
      sector: raw.sector ?? base.sector,
      jurisdictions: raw.jurisdictions?.length ? raw.jurisdictions : base.jurisdictions,
      records: raw.records ?? base.records,
      regulated: raw.regulated ?? base.regulated,
      minors: raw.minors ?? false,
      existing_coverage: coverage,
    },
    monthlyVolume: raw.monthly_action_volume ?? 50_000,
    declared: true,
  };
}

/** Agents the model can be run for: those with a dimension assessment, money movers first. */
export function candidateAgents(env: Envelope): Agent[] {
  return env.registry.agents
    .filter((a) => a.dimension_assessment)
    .sort((a, b) => Number(hasAuthority(env, b)) - Number(hasAuthority(env, a)) || worst(b) - worst(a) || (a.display_name || a.name).localeCompare(b.display_name || b.name));
}
function worst(a: Agent): number {
  return Math.max(0, ...(a.dimension_assessment?.dimensions ?? []).map((d) => d.score));
}

export function agentToModel(env: Envelope, agent: Agent, monthlyVolume: number): { model: ModelAgent; notes: MappingNote[] } {
  const notes: MappingNote[] = [];
  const declared = agent.declared;
  const money = hasAuthority(env, agent);
  const maxUsd = declared?.economic_authority?.max_per_action?.currency === "USD" ? declared.economic_authority.max_per_action.amount : declared?.economic_authority?.max_per_action?.amount ?? 500;
  notes.push({ input: "Can move money", value: money ? "yes" : "no", from: money ? "payment capability or a money-moving tool observed" : "no payment capability or money tool observed" });
  if (money) notes.push({ input: "Max per action", value: `$${maxUsd.toLocaleString()}`, from: declared?.economic_authority?.max_per_action ? "declared economic_authority" : "model default; declare economic_authority to set it" });

  const classes = new Set(declared?.data_classes ?? []);
  const pii = classes.has("personal") || classes.has("financial") || classes.has("health") || agent.capabilities.includes("database_read") || agent.capabilities.includes("vector_search");
  notes.push({ input: "Reads personal data", value: pii ? "yes" : "no", from: classes.size ? "declared data_classes" : "database_read or vector_search capability" });
  const sensitive = classes.has("health") ? "phi" : classes.has("financial") || money ? "payment" : "none";

  const write = agent.capabilities.some((c) => WRITE_CAPS.has(c)) || (agent.tools ?? []).some((t) => t.high_impact);
  notes.push({ input: "Writes to systems", value: write ? "yes" : "no", from: "write, execution, payment or messaging capability observed" });

  const customer = declared?.users ? declared.users !== "internal" : true;
  notes.push({ input: "Customer facing", value: customer ? "yes" : "no", from: declared?.users ? `declared users = ${declared.users}` : "not declared; assumed customer facing" });

  const level = agent.autonomy_level?.level ?? "";
  const autonomy: Autonomy = level === "unrestricted_autonomous" ? "high" : level === "bounded_autonomous" ? "medium" : "low";
  notes.push({ input: "Autonomy", value: autonomy, from: level ? `inferred autonomy ${level}` : "autonomy indeterminate; assumed low" });

  const controls = new Set<string>();
  for (const d of agent.dimension_assessment?.dimensions ?? []) for (const c of d.controls_observed) controls.add(c);
  const hil: HumanInLoop = controls.has("approval") ? "approval_above_threshold" : declared?.autonomy_intent === "human_approved" && autonomy === "low" ? "partial" : "none";
  notes.push({ input: "Human review", value: hil.replace(/_/g, " "), from: controls.has("approval") ? "approval control observed in code" : "no approval control observed" });

  const scores: Record<string, number> = {};
  for (const d of agent.dimension_assessment?.dimensions ?? []) scores[d.id.replace(/-/g, "_")] = d.score;
  for (const key of ["boundary_leakage", "mandate_overreach", "injection_tamper_surface", "control_coverage_gap", "unreviewed_high_impact_action", "output_fidelity", "conduct_variability", "dependency_drift"]) if (scores[key] === undefined) scores[key] = 0;
  notes.push({ input: "Scan scores", value: Object.values(scores).join(" / "), from: "dimension_assessment scores, 0 to 100" });

  return {
    model: {
      name: agent.display_name || agent.name,
      capabilities: { financial_authority: { enabled: money, max_per_action_usd: maxUsd, monthly_action_volume: monthlyVolume }, pii_access: pii, sensitive_data_access: sensitive, write_access_to_systems: write, autonomy_level: autonomy, human_in_loop: hil, customer_facing: customer },
      dimension_scores: scores,
    },
    notes,
  };
}

export function intakeToToml(intake: Intake, monthlyVolume: number): string {
  const q = (s: string) => `"${s.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
  const lines = ["[intake]", `revenue               = ${Math.round(intake.revenue)}`, `sector                = ${q(intake.sector)}`, `jurisdictions         = [${intake.jurisdictions.map(q).join(", ")}]`, `records               = ${Math.round(intake.records)}`, `regulated             = ${intake.regulated}`, `minors                = ${intake.minors}`, `monthly_action_volume = ${Math.round(monthlyVolume)}`];
  for (const p of intake.existing_coverage) lines.push("", "[[intake.existing_coverage]]", `type         = ${q(p.type)}`, `limit        = ${Math.round(p.limit)}`, `ai_exclusion = ${p.ai_exclusion}`);
  return lines.join("\n") + "\n";
}
