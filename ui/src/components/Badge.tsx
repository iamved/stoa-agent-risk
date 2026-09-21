import type { ReactNode } from "react";
import type { Confidence, Exposure, Severity } from "../data/types";
import { EXPOSURE_METHOD, STATE_HINT, STATE_LABEL, type DimensionState } from "../data/exposure";
import { ASSESSABILITY_HINT, ASSESSABILITY_LABEL, EXPOSURE_LABEL, RISK_LABEL, riskLevel } from "../data/selectors";

/* Status chips: a colored dot plus a text label, so nothing relies on color alone. */

/** Shown as one of three risk levels; the scanner's severity is in the tooltip. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const level = riskLevel(severity);
  return <span className={`chip chip-${level}`} title={`Severity: ${RISK_LABEL[level]} (scanner severity: ${severity})`}>{RISK_LABEL[level]}</span>;
}

const EXPOSURE_CLASS: Record<Exposure, string> = {
  elevated: "chip-high",
  moderate: "chip-medium",
  low: "chip-low",
  "none-observed": "chip-muted",
  "not-assessable": "chip-muted chip-dashed",
};

export function ExposureBadge({ exposure }: { exposure: Exposure }) {
  return <span className={`chip ${EXPOSURE_CLASS[exposure]}`} title={`Exposure: ${EXPOSURE_LABEL[exposure]}. ${EXPOSURE_METHOD}`}>{EXPOSURE_LABEL[exposure]}</span>;
}

/** A dimension's exposure, or, when it has no findings, what the scanner knows about its own coverage there. */
export function DimensionStateBadge({ state }: { state: DimensionState }) {
  if (state.kind === "exposure") return <ExposureBadge exposure={state.exposure} />;
  return <span className={`chip chip-muted ${state.kind === "no_findings" ? "" : "chip-dashed"}`} title={STATE_HINT[state.kind]}>{STATE_LABEL[state.kind]}</span>;
}

const CONFIDENCE_CLASS: Record<Confidence, string> = { high: "chip-ok", medium: "chip-medium", low: "chip-muted" };

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <span className={`chip ${CONFIDENCE_CLASS[confidence]}`}>{confidence} confidence</span>;
}

/** Dimension assessability, labeled "confidence" for the reader. */
export function AssessabilityBadge({ assessability }: { assessability: string }) {
  const label = ASSESSABILITY_LABEL[assessability] ?? assessability;
  const cls = assessability === "strong" ? "chip-ok" : assessability === "partial" ? "chip-medium" : "chip-muted chip-dashed";
  return (
    <span className={`chip ${cls}`} title={ASSESSABILITY_HINT[assessability] ?? ""}>
      {label}
    </span>
  );
}

export function Pill({ children, tone = "neutral", title }: { children: ReactNode; tone?: "neutral" | "gold" | "navy" | "warn"; title?: string }) {
  const cls = tone === "gold" ? "chip-gold" : tone === "navy" ? "chip-navy" : tone === "warn" ? "chip-high" : "";
  return (
    <span className={`chip chip-plain ${cls}`} title={title}>
      {children}
    </span>
  );
}
