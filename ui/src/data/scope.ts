/**
 * Declared Scope: the business context a person supplies, edited on the page
 * and saved back as the two files the scanner already reads
 * (stoa-declared.toml and .stoa/underwriting.toml). The page never writes to
 * the repository; it generates the files to commit.
 */
import type { Agent, Envelope } from "./types";
import { hasAuthority } from "./selectors";

export const USERS = ["internal", "customers", "public"] as const;
export const PRODUCTION_STATUSES = ["dev", "staging", "production", "deprecated"] as const;
export const AUTONOMY_INTENTS = ["recommend_only", "human_approved", "bounded_autonomous", "unrestricted_autonomous"] as const;
export const DATA_CLASSES = ["personal", "financial", "health", "confidential", "ip", "authentication"] as const;
export const DEPENDENCY_LEVELS = ["low", "medium", "high", "critical"] as const;
export const SOCIETAL_FLAGS = ["critical_infrastructure", "biosecurity_adjacent", "mass_influence"] as const;
export const SECTORS = ["fintech", "healthtech", "edtech", "software", "retail", "legal"] as const;
export const POLICY_TYPES = ["cyber", "tech_eo", "crime"] as const;
export const EVIDENCE_CATEGORIES = ["testing", "safety_testing", "monitoring", "contracts", "historical", "vendor"] as const;

export interface OrgState { industries: string; regulated_activities: string; max_customer_dependency: string; societal_risk_flags: string[] }
export interface GovState { release_approval: string; incident_response: string; harmful_output_policy: string; risk_acceptance_owner: string; risk_acceptance_date: string }
export interface AgentState {
  id: string; label: string; path: string; inferredAutonomy: string | null; moneyMover: boolean; wasDeclared: boolean;
  name: string; owner: string; purpose: string; users: string; geography: string; production_status: string; autonomy_intent: string; data_classes: string[];
  max_per_action: string; daily_aggregate: string; worst_case: string; currency: string;
}
export interface EvidenceState { category: string; kind: string; ref: string; date: string }
export interface PolicyState { type: string; limit: string; ai_exclusion: boolean }
export interface IntakeState { revenue: string; sector: string; jurisdictions: string; records: string; regulated: boolean; minors: boolean; monthly_action_volume: string }
export interface IdentityState { company: string; contact_name: string; contact_title: string; contact_email: string; address: string; home_state: string; model_name: string; model_version: string; deployment: string; currency: string }
export interface ScopeState { org: OrgState; gov: GovState; agents: AgentState[]; evidence: EvidenceState[]; policies: PolicyState[]; intake: IntakeState; identity: IdentityState }

const list = (v: unknown): string => (Array.isArray(v) ? v.map(String).join(", ") : typeof v === "string" ? v : "");
const amount = (m?: { amount: number; currency: string }) => (m ? String(m.amount) : "");

export function scopeFromEnvelope(env: Envelope): ScopeState {
  const r = env.registry;
  const business = (r.business ?? {}) as Record<string, unknown>;
  const gov = (r.governance ?? {}) as Record<string, unknown>;
  const ra = (gov.risk_acceptance ?? {}) as Record<string, unknown>;
  const intake = env.intake;
  const identity = env.assessment.identity;
  const agents: AgentState[] = r.agents.map((a: Agent) => {
    const d = a.declared;
    const ea = d?.economic_authority;
    return {
      id: a.id, label: a.display_name || a.name, path: a.path, inferredAutonomy: a.autonomy_level?.level ?? null, moneyMover: hasAuthority(env, a), wasDeclared: Boolean(d),
      name: d?.name ?? a.name, owner: d?.owner ?? "", purpose: d?.purpose ?? "", users: d?.users ?? "", geography: list(d?.geography), production_status: d?.production_status ?? "", autonomy_intent: d?.autonomy_intent ?? "", data_classes: [...(d?.data_classes ?? [])],
      max_per_action: amount(ea?.max_per_action), daily_aggregate: amount(ea?.daily_aggregate), worst_case: amount(ea?.worst_case_customer_loss), currency: ea?.max_per_action?.currency ?? ea?.daily_aggregate?.currency ?? ea?.worst_case_customer_loss?.currency ?? "USD",
    };
  });
  const evidence: EvidenceState[] = Object.entries(r.evidence ?? {}).flatMap(([category, items]) => items.map((e) => ({ category, kind: e.kind, ref: e.ref, date: e.date ?? "" })));
  return {
    org: { industries: list(business.industries), regulated_activities: list(business.regulated_activities), max_customer_dependency: typeof business.max_customer_dependency === "string" ? business.max_customer_dependency : "", societal_risk_flags: Array.isArray(business.societal_risk_flags) ? business.societal_risk_flags.map(String) : [] },
    gov: { release_approval: String(gov.release_approval ?? ""), incident_response: String(gov.incident_response ?? ""), harmful_output_policy: String(gov.harmful_output_policy ?? ""), risk_acceptance_owner: String(ra.owner ?? ""), risk_acceptance_date: String(ra.date ?? "") },
    agents,
    evidence,
    policies: (intake?.existing_coverage ?? []).map((p) => ({ type: p.type, limit: String(p.limit), ai_exclusion: p.ai_exclusion })),
    intake: { revenue: intake?.revenue != null ? String(intake.revenue) : "", sector: intake?.sector ?? "", jurisdictions: list(intake?.jurisdictions), records: intake?.records != null ? String(intake.records) : "", regulated: intake?.regulated ?? false, minors: intake?.minors ?? false, monthly_action_volume: intake?.monthly_action_volume != null ? String(intake.monthly_action_volume) : "" },
    identity: { ...identity },
  };
}

// --- completeness ------------------------------------------------------------------

export interface Gap { section: string; label: string; why: string }
export interface Completeness { filled: number; total: number; pct: number; gaps: Gap[] }

/** The fields that change what the scanner, the outlook and the assessment can say. */
export function completeness(s: ScopeState): Completeness {
  const checks: { ok: boolean; section: string; label: string; why: string }[] = [
    { ok: Boolean(s.org.industries.trim()), section: "Organization", label: "Industries", why: "sets the sector for comparable loss events" },
    { ok: Boolean(s.org.max_customer_dependency), section: "Organization", label: "Customer dependency", why: "assurance packet business exposure" },
    { ok: Boolean(s.gov.release_approval.trim()), section: "Governance", label: "Release approval", why: "questionnaire: update and rollback readiness" },
    { ok: Boolean(s.gov.incident_response.trim()), section: "Governance", label: "Incident response", why: "questionnaire: post-deployment" },
    { ok: Boolean(s.intake.revenue.trim()), section: "Business context", label: "Annual revenue", why: "scales every loss figure in the outlook" },
    { ok: Boolean(s.intake.records.trim()), section: "Business context", label: "Personal records held", why: "drives data-leakage severity" },
    { ok: s.policies.length > 0, section: "Existing insurance", label: "Current policies", why: "the outlook's gap analysis" },
    { ok: Boolean(s.identity.contact_name.trim() && s.identity.contact_email.trim()), section: "Applicant", label: "Contact", why: "the assessment's signatory" },
  ];
  for (const a of s.agents) {
    checks.push({ ok: Boolean(a.owner.trim()), section: a.label, label: "Owner", why: "who answers for this agent" });
    checks.push({ ok: Boolean(a.autonomy_intent), section: a.label, label: "Intended autonomy", why: "cross-checked against inferred autonomy (DECL001)" });
    checks.push({ ok: Boolean(a.users), section: a.label, label: "Users", why: "customer facing or internal in the outlook" });
    checks.push({ ok: a.data_classes.length > 0, section: a.label, label: "Data classes", why: "cross-checked against observed data access (DECL004)" });
    if (a.moneyMover) checks.push({ ok: Boolean(a.max_per_action.trim()), section: a.label, label: "Max per action", why: "this agent moves money; the scan checks the limit is enforced (DECL003)" });
  }
  const filled = checks.filter((c) => c.ok).length;
  return { filled, total: checks.length, pct: checks.length ? Math.round((filled / checks.length) * 100) : 100, gaps: checks.filter((c) => !c.ok).map(({ section, label, why }) => ({ section, label, why })) };
}

// --- TOML generation ---------------------------------------------------------------

const q = (v: string) => `"${v.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n").replace(/\r/g, "").replace(/\t/g, "\\t")}"`;
const arr = (csv: string) => `[${csv.split(",").map((x) => x.trim()).filter(Boolean).map(q).join(", ")}]`;
const num = (v: string): number | null => { const n = Number(v.replace(/[,\s]/g, "")); return v.trim() && Number.isFinite(n) ? n : null; };

/** stoa-declared.toml, complete: business, agents, governance, evidence, and the register rows already in the registry. */
export function toDeclaredToml(s: ScopeState, register: { risk_id: string; owner: string; treatment: string | null; rationale: string; review_by?: string; status?: string }[]): string {
  const out: string[] = ["# stoa-declared.toml — declared facts, cross-checked by the scanner. Generated from the dashboard's Declared Scope.", "version = 1", ""];
  const biz: string[] = [];
  if (s.org.industries.trim()) biz.push(`industries = ${arr(s.org.industries)}`);
  if (s.org.regulated_activities.trim()) biz.push(`regulated_activities = ${arr(s.org.regulated_activities)}`);
  if (s.org.max_customer_dependency) biz.push(`max_customer_dependency = ${q(s.org.max_customer_dependency)}`);
  if (s.org.societal_risk_flags.length) biz.push(`societal_risk_flags = [${s.org.societal_risk_flags.map(q).join(", ")}]`);
  if (biz.length) out.push("[business]", ...biz, "");
  for (const a of s.agents) {
    const has = [a.owner, a.purpose, a.users, a.geography, a.production_status, a.autonomy_intent, a.max_per_action, a.daily_aggregate, a.worst_case].some((v) => v.trim()) || a.data_classes.length > 0 || a.wasDeclared;
    if (!has) continue;
    out.push(`[agents.${q(a.id)}]      # ${a.path}`, `name = ${q(a.name || a.label)}`);
    if (a.owner.trim()) out.push(`owner = ${q(a.owner.trim())}`);
    if (a.purpose.trim()) out.push(`purpose = ${q(a.purpose.trim())}`);
    if (a.users) out.push(`users = ${q(a.users)}`);
    if (a.geography.trim()) out.push(`geography = ${arr(a.geography)}`);
    if (a.production_status) out.push(`production_status = ${q(a.production_status)}`);
    if (a.autonomy_intent) out.push(`autonomy_intent = ${q(a.autonomy_intent)}`);
    if (a.data_classes.length) out.push(`data_classes = [${a.data_classes.map(q).join(", ")}]`);
    const ea: string[] = [];
    const cur = a.currency.trim() || "USD";
    for (const [key, v] of [["max_per_action", a.max_per_action], ["daily_aggregate", a.daily_aggregate], ["worst_case_customer_loss", a.worst_case]] as const) {
      const n = num(v);
      if (n !== null) ea.push(`${key} = { amount = ${n}, currency = ${q(cur)} }`);
    }
    if (ea.length) out.push(`[agents.${q(a.id)}.economic_authority]`, ...ea);
    out.push("");
  }
  const gov: string[] = [];
  if (s.gov.release_approval.trim()) gov.push(`release_approval = ${q(s.gov.release_approval.trim())}`);
  if (s.gov.incident_response.trim()) gov.push(`incident_response = ${q(s.gov.incident_response.trim())}`);
  if (s.gov.harmful_output_policy.trim()) gov.push(`harmful_output_policy = ${q(s.gov.harmful_output_policy.trim())}`);
  if (gov.length || s.gov.risk_acceptance_owner.trim()) {
    out.push("[governance]", ...gov);
    if (s.gov.risk_acceptance_owner.trim()) out.push("[governance.risk_acceptance]", `owner = ${q(s.gov.risk_acceptance_owner.trim())}`, ...(s.gov.risk_acceptance_date.trim() ? [`date = ${q(s.gov.risk_acceptance_date.trim())}`] : []));
    out.push("");
  }
  for (const e of s.evidence) {
    if (!e.category.trim() || !e.kind.trim() || !e.ref.trim()) continue;
    out.push(`[[evidence.${e.category.trim()}]]`, `kind = ${q(e.kind.trim())}`, `ref = ${q(e.ref.trim())}`, ...(e.date.trim() ? [`date = ${q(e.date.trim())}`] : []), "");
  }
  for (const row of register) {
    out.push("[[risk_register]]", `risk_id = ${q(row.risk_id)}`);
    if (row.owner) out.push(`owner = ${q(row.owner)}`);
    if (row.treatment) out.push(`treatment = ${q(row.treatment)}`);
    if (row.rationale) out.push(`rationale = ${q(row.rationale)}`);
    if (row.review_by) out.push(`review_by = ${q(row.review_by)}`);
    if (row.status) out.push(`status = ${q(row.status)}`);
    out.push("");
  }
  return out.join("\n").replace(/\n+$/, "\n");
}

/** .stoa/underwriting.toml: identity, intake, existing policies; performance rows carried from the assessment. */
export function toUnderwritingToml(s: ScopeState, performance: { metric: string; value: string; cadence: string }[]): string {
  const out: string[] = ["# .stoa/underwriting.toml — applicant identity and business context. Generated from the dashboard's Declared Scope.", "", "[identity]"];
  for (const key of ["company", "contact_name", "contact_title", "contact_email", "address", "home_state", "model_name", "model_version", "deployment", "currency"] as const) {
    if (s.identity[key].trim()) out.push(`${key.padEnd(14)} = ${q(s.identity[key].trim())}`);
  }
  for (const p of performance) out.push("", "[[performance]]", `metric  = ${q(p.metric)}`, `value   = ${q(p.value)}`, `cadence = ${q(p.cadence)}`);
  const intake: string[] = [];
  const rev = num(s.intake.revenue); if (rev !== null) intake.push(`revenue               = ${rev}`);
  if (s.intake.sector) intake.push(`sector                = ${q(s.intake.sector)}`);
  if (s.intake.jurisdictions.trim()) intake.push(`jurisdictions         = ${arr(s.intake.jurisdictions.toUpperCase())}`);
  const rec = num(s.intake.records); if (rec !== null) intake.push(`records               = ${rec}`);
  intake.push(`regulated             = ${s.intake.regulated}`, `minors                = ${s.intake.minors}`);
  const vol = num(s.intake.monthly_action_volume); if (vol !== null) intake.push(`monthly_action_volume = ${vol}`);
  out.push("", "[intake]", ...intake);
  for (const p of s.policies) {
    const lim = num(p.limit);
    if (!p.type || lim === null) continue;
    out.push("", "[[intake.existing_coverage]]", `type         = ${q(p.type)}`, `limit        = ${lim}`, `ai_exclusion = ${p.ai_exclusion}`);
  }
  return out.join("\n") + "\n";
}

export function isEqualScope(a: ScopeState, b: ScopeState): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}
