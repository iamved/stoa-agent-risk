/**
 * Exposure, as the scanner derives it (src/stoa/dimensions.py), and what to say
 * about a dimension that has no findings. Nothing here computes a level.
 */
import type { Envelope, Exposure, TaxonomyDimension } from "./types";

/**
 * How exposure is derived. Kept next to the scoring rule it describes: per
 * agent and per dimension, score = finding weights (by severity and
 * confidence) + capability weights - credit for controls observed, bucketed
 * at 1, 25 and 55. A dimension reports the highest level among its agents.
 */
export const EXPOSURE_METHOD =
  "Exposure is scored for each agent in each dimension: findings weighted by severity and confidence, plus the agent's capabilities, minus credit for safeguards detected. A dimension shows the highest level any one agent reaches, so many low-severity findings spread across agents can still read Low.";

export const SEVERITY_METHOD = "Severity is set by the rule that fired, for that one finding. It does not depend on how many agents are affected.";

export type DimensionState = { kind: "exposure"; exposure: Exposure } | { kind: "no_findings" } | { kind: "limited_evidence" } | { kind: "not_assessed" };

export const STATE_LABEL: Record<Exclude<DimensionState["kind"], "exposure">, string> = {
  no_findings: "No findings",
  limited_evidence: "Limited evidence",
  not_assessed: "Not assessed",
};

export const STATE_HINT: Record<Exclude<DimensionState["kind"], "exposure">, string> = {
  no_findings: "The rules for this dimension ran and nothing fired.",
  limited_evidence: "A static scan sees only configuration signals for this dimension, so no findings is weak evidence either way.",
  not_assessed: "This scan carried no dimension assessment.",
};

/**
 * What to show for a dimension. With findings, or at Moderate or Elevated
 * (capabilities alone can raise a level), its exposure. With none, what the
 * scanner knows about its own coverage: the taxonomy marks a dimension
 * `proxy` when static analysis sees only configuration signals for it.
 */
export function dimensionState(env: Envelope, dimension: TaxonomyDimension, exposure: Exposure, findings: number): DimensionState {
  if (!env.registry.dimension_summary) return { kind: "not_assessed" };
  if (findings > 0 || exposure === "moderate" || exposure === "elevated") return { kind: "exposure", exposure };
  if (exposure === "not-assessable") return { kind: "not_assessed" };
  return dimension.assessability === "proxy" ? { kind: "limited_evidence" } : { kind: "no_findings" };
}
