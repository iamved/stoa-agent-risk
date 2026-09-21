/**
 * Types for the `stoa-dashboard/1.0` envelope and the `stoa-registry.json`
 * document (schema 1.x) it wraps.
 *
 * Hand-written against the Python producers (`stoa.report_json`,
 * `stoa.registry_diff`, `stoa.dashboard.*`) and validated against the
 * generated fixture in `tests/fixture-shape.test.ts`, so a producer change
 * that breaks a consumed field fails the build rather than the page.
 *
 * Everything here is read-only. The UI never recomputes, reweights, or
 * alters a score; the scanner is the source of truth.
 */

export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type Confidence = "low" | "medium" | "high";
export type Exposure = "none-observed" | "low" | "moderate" | "elevated" | "not-assessable";
export type Assessability = "strong" | "partial" | "proxy" | "runtime-required" | "runtime" | string;
export type DimensionGroup = "A" | "B" | "C" | "D" | "E" | "F" | "";
export type Treatment = "accept" | "mitigate" | "avoid" | "transfer";
export type RegisterStatus = "open" | "in_progress" | "closed";

export interface CrosswalkTag {
  owasp_llm_2025: string;
  eu_ai_act: string;
  relation: string;
  so_what: string;
}

export interface FlowStep {
  role: "source" | "propagation" | "sink";
  line: number;
  snippet: string;
}

export interface Finding {
  fingerprint: string;
  rule_id: string;
  title: string;
  category: string;
  severity: Severity;
  confidence: Confidence;
  path: string;
  line: number;
  column: number;
  snippet: string;
  remediation: string;
  suppressed: boolean;
  suppression_reason: string | null;
  is_new: boolean;
  canonical_name?: string | null;
  flow?: FlowStep[];
  gate_eligible?: boolean;
  dimensions?: string[];
  variant?: string | null;
  evidence_tags?: string[];
  message?: string | null;
  declared_ref?: { path: string; key: string } | null;
  crosswalk?: CrosswalkTag;
  [extra: string]: unknown;
}

export interface Evidence {
  rule_id: string;
  line: number;
  description: string;
}

export interface CommitInfo {
  hash: string;
  date: string;
}

export interface DimensionEntry {
  id: string;
  group: DimensionGroup | string;
  assessability: Assessability;
  exposure: Exposure;
  score: number;
  /** Schema 1.8: the score before control credit is subtracted. */
  score_before_controls?: number;
  contributing_findings: string[];
  contributing_capabilities: string[];
  controls_observed: string[];
  statement: string;
}

export interface DimensionAssessment {
  taxonomy: { id: string; version: string };
  dimensions: DimensionEntry[];
}

export interface ToolRecord {
  name: string;
  path: string;
  line: number;
  kind: string;
  params: { name: string; type?: string | null }[];
  capabilities: string[];
  integrations: string[];
  high_impact: boolean;
  money_action: boolean;
  guards: string[];
  retry: boolean;
  idempotency_key: boolean;
  resolved: boolean;
}

export interface EconomicAuthority {
  max_per_action?: { amount: number; currency: string };
  daily_aggregate?: { amount: number; currency: string };
  worst_case_customer_loss?: { amount: number; currency: string };
}

export interface AgentDeclaration {
  name: string;
  owner: string;
  purpose: string;
  users: string | null;
  geography: string[];
  production_status: string | null;
  autonomy_intent: string | null;
  data_classes: string[];
  economic_authority?: EconomicAuthority;
}

export interface AutonomyLevel {
  level: string;
  signals: { kind: string; path: string; line: number }[] | unknown[];
  reason: string | null;
}

export interface Agent {
  id: string;
  name: string;
  display_name: string;
  symbol: string;
  path: string;
  language: string;
  confidence: Confidence;
  detection_score: number;
  evidence: Evidence[];
  providers: string[];
  frameworks: string[];
  integrations: string[];
  capabilities: string[];
  permission_tags: string[];
  call_sites: Record<string, number>;
  last_touched_by: string | null;
  last_commit: CommitInfo | null;
  codeowners: string[];
  findings: Finding[];
  highest_severity: Severity | null;
  dimension_assessment?: DimensionAssessment;
  declared?: AgentDeclaration;
  autonomy_level?: AutonomyLevel;
  tools?: ToolRecord[];
  /** Schema 1.6: only present for agents not discovered in application code. */
  source?: "code" | "iac";
  discovery_tier?: "full" | "recognized" | "inferred";
  platform?: string;
  [extra: string]: unknown;
}

export interface DimensionSummaryEntry {
  id: string;
  name: string;
  group: DimensionGroup | string;
  assessability: Assessability;
  max_exposure: Exposure;
  agents_elevated: number;
  agents_moderate: number;
  crosswalk?: { owasp_llm_2025: string[]; eu_ai_act: string[] };
}

export interface RiskRegisterDeclaration {
  risk_id: string;
  owner: string;
  treatment: Treatment | null;
  rationale: string;
  review_by?: string;
  status?: RegisterStatus;
}

export interface Registry {
  schema_version: string;
  tool: { name: string; version: string };
  repository: {
    name: string;
    root: string;
    git_ref: string | null;
    base_ref: string | null;
    /** Schema 1.8. */
    head_commit?: CommitInfo;
  };
  summary: {
    files_scanned: number;
    agent_candidates: number;
    high_confidence_candidates: number;
    integrations: number;
    findings: Record<Severity, number>;
    new_findings: Record<Severity, number>;
    suppressed_findings: number;
  };
  agents: Agent[];
  repository_findings: Finding[];
  skipped_files: { path: string; reason: string }[];
  warnings: string[];
  degraded_files?: string[];
  dimension_summary?: {
    taxonomy: { id: string; version: string };
    dimensions: DimensionSummaryEntry[];
  };
  business?: Record<string, unknown>;
  governance?: Record<string, unknown>;
  evidence?: Record<string, { kind: string; ref: string; date?: string }[]>;
  crosswalk?: { id: string; version: string; [extra: string]: unknown };
  /** Schema 1.8. */
  risk_register?: RiskRegisterDeclaration[];
  [extra: string]: unknown;
}

// --- stoa-diff/1.0 ---------------------------------------------------------

export type DriftSeverity = "info" | "low" | "medium" | "high";

export interface DiffCapability {
  id: string;
  high_impact?: boolean;
  sensitive?: boolean;
  drift_severity: DriftSeverity;
  approved?: boolean;
}

export interface DiffDimensionDelta {
  id: string;
  from: Exposure;
  to: Exposure;
  direction: "increased" | "decreased";
}

export interface DiffChangedAgent {
  agent_id: string;
  name: string;
  path: string;
  renamed_from?: string;
  confidence: { base: Confidence | null; head: Confidence | null };
  capabilities: { added: DiffCapability[]; removed: DiffCapability[] };
  integrations: { added: DiffCapability[]; removed: DiffCapability[] };
  providers: { added: string[]; removed: string[] };
  findings_delta: {
    new: { fingerprint: string; rule_id: string; severity: Severity; line: number }[];
    resolved: { fingerprint: string; rule_id: string }[];
  };
  dimension_delta: DiffDimensionDelta[];
  drift_severity: DriftSeverity;
}

export interface DiffAddedAgent {
  agent_id: string;
  name: string;
  path: string;
  confidence: Confidence | null;
  capabilities: string[];
  integrations: string[];
  providers: string[];
  drift_severity: DriftSeverity;
  drift_reasons: string[];
  approved: boolean;
}

export interface DiffRemovedAgent {
  agent_id: string;
  name: string;
  path: string;
  drift_severity: DriftSeverity;
}

export interface DiffDocument {
  schema: string;
  scanner_version: string;
  base: { registry_schema: string; commit: string | null; ref: string | null };
  head: { registry_schema: string; commit: string | null; ref: string };
  summary: {
    agents_added: number;
    agents_removed: number;
    agents_changed: number;
    escalations: Record<"high" | "medium" | "low", number>;
    reductions: number;
    findings_delta: { new_critical: number; new_high: number; resolved: number };
    max_drift_severity: DriftSeverity;
    unapproved_max_drift_severity: DriftSeverity;
    approvals_applied: number;
  };
  agents: { added: DiffAddedAgent[]; removed: DiffRemovedAgent[]; changed: DiffChangedAgent[] };
  approvals: { applied: unknown[]; stale: unknown[]; file: string | null };
}

// --- dashboard envelope -----------------------------------------------------

export interface HistoryEntry {
  schema: string;
  git_ref: string | null;
  head_commit: CommitInfo;
  scanner_version: string | null;
  registry_schema_version: string | null;
  agent_candidates: number;
  findings: Partial<Record<Severity, number>>;
  dimensions: { id: string; max_exposure: Exposure; agents_elevated: number; agents_moderate: number }[];
}

export interface RegisterLevel {
  score: number;
  level: Exposure;
}

export interface RegisterRow {
  risk_id: string;
  source: "scanned" | "declared";
  dimension_id: string;
  dimension_name: string;
  group: string;
  assessability: string;
  agent_id: string;
  agent_name: string | null;
  agent_path: string | null;
  inherent: RegisterLevel | null;
  residual: RegisterLevel | null;
  controls_observed: string[];
  contributing_findings: string[];
  contributing_capabilities: string[];
  statement: string;
  declared: RiskRegisterDeclaration | null;
  unmatched: boolean;
}

export interface RuleRecord {
  title: string;
  category: string;
  default_severity: Severity;
  gateable: boolean;
  remediation: string;
  canonical_name: string | null;
  crosswalk?: CrosswalkTag;
}

export interface TaxonomyDimension {
  id: string;
  name: string;
  definition: string;
  assessability: Assessability;
  group: DimensionGroup | string;
}

export interface TaxonomyBlock {
  id: string | null;
  version: string | null;
  dimensions: TaxonomyDimension[];
  groups: Record<string, string>;
}

export interface AssuranceRow {
  field: string;
  status: "scanned" | "declared" | "ingested" | "observed" | "not_provided";
  evidence?: Record<string, unknown> | null;
}

export interface AssuranceArea {
  group: string;
  area_name: string;
  /** Source layers, e.g. "scanned + declared"; a string in assurance-packet/1.2. */
  layers: string | string[];
  rows?: AssuranceRow[];
  agents?: { agent_id: string; name: string; fields: Record<string, AssuranceRow> }[];
  [extra: string]: unknown;
}

export interface AssurancePacket {
  schema: string;
  header: {
    repository: string | null;
    git_sha: string | null;
    scan_timestamp: string | null;
    stoa_version: string | null;
    registry_schema_version: string | null;
    agent_count: number;
    findings_by_severity: Partial<Record<Severity, number>>;
    contradiction_count: number;
  };
  contradictions: Record<string, unknown>[];
  areas: Record<string, AssuranceArea>;
}

export interface UnderwritingDerivation {
  agent_count: number;
  critical_count: number;
  robustness: boolean;
  code_quality: boolean;
  monitoring: boolean;
  drift: boolean;
  has_declarations: boolean;
  econ_findings: string[];
  elevated_dims: string[];
  limit: string;
  deductible: string;
  trigger: string;
}

// --- architecture graph (graph_model.to_json_dict) ------------------------------

export type GraphNodeType = "agent" | "mcp_server" | "tool" | "resource";
export type GraphEdgeKind = "delegates" | "tool_call" | "mcp" | "reads" | "writes" | "network";

export interface GraphFindingRef {
  rule_id: string;
  severity: Severity;
  path: string;
  line: number;
  message?: string;
}

export interface GraphNode {
  id: string;
  type: GraphNodeType;
  label: string;
  dimension_scores: Record<string, number>;
  display_severity: Severity | null;
  path: string | null;
  symbol: string | null;
  autonomy_level: string | null;
  findings: GraphFindingRef[];
}

export interface GraphEdge {
  source: string;
  target: string;
  kind: GraphEdgeKind;
  provenance: "declared" | "observed";
  max_severity: Severity | null;
  weight: number;
  findings: GraphFindingRef[];
  observed?: boolean;
}

export interface GraphDocument {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// --- the pre-filled AI Model Risk Assessment (underwriting.build_assessment) ---

export type AssessmentSource = "scan" | "declared" | "applicant" | "sample" | "indicative";

export interface AssessmentField {
  key: string;
  label: string;
  value: string;
  source: AssessmentSource;
  note: string;
}

export interface AssessmentIdentity {
  company: string;
  contact_name: string;
  contact_title: string;
  contact_email: string;
  address: string;
  home_state: string;
  model_name: string;
  model_version: string;
  deployment: string;
  currency: string;
}

export interface Assessment {
  template: string;
  identity: AssessmentIdentity;
  identity_source: "applicant" | "sample";
  carrier: string;
  product: string;
  advisor: { url: string; email: string; submit_email: string };
  repository: string;
  sections: { id: string; title: string; fields: AssessmentField[] }[];
  performance: { metric: string; value: string; cadence: string; source: "applicant" | "sample" }[];
  performance_source: "applicant" | "sample";
  schedule: AssessmentField[];
  schedule_source: "declared" | "indicative";
  declaration: string;
  signatory: string;
  counts: { prefilled: number; to_confirm: number; indicative: number; performance_rows: number; total: number };
  derived: UnderwritingDerivation;
}

export interface IntakeBlock {
  revenue?: number;
  sector?: string;
  jurisdictions?: string[];
  records?: number;
  regulated?: boolean;
  minors?: boolean;
  monthly_action_volume?: number;
  existing_coverage?: { type: string; limit: number; ai_exclusion: boolean }[];
}

export interface Envelope {
  schema: string;
  /** Set by `stoa dashboard --demo`: the page says so and offers to open a real scan. */
  demo?: boolean;
  generator: { name: string; version: string };
  registry: Registry;
  diff: DiffDocument | null;
  baseline: { name: string | null; git_ref: string | null; head_commit: CommitInfo | null; scanner_version: string | null; schema_version: string | null } | null;
  history: HistoryEntry[];
  register: RegisterRow[];
  graph: GraphDocument;
  assurance: AssurancePacket;
  underwriting: UnderwritingDerivation;
  assessment: Assessment;
  intake: IntakeBlock | null;
  rules: Record<string, RuleRecord>;
  taxonomy: TaxonomyBlock;
  frameworks: { nist_ai_rmf: { function: string; stoa: string }[] };
  vocabulary: { high_impact_capabilities: string[]; sensitive_integrations: string[] };
}
