import type { Confidence, Exposure, Severity } from "../data/types";
import { ASSESSABILITY_HINT, ASSESSABILITY_LABEL, EXPOSURE_LABEL } from "../data/selectors";

/* Every badge pairs its color with a label and a glyph, so nothing relies on color alone. */

const SEVERITY_GLYPH: Record<Severity, string> = { critical: "▲▲", high: "▲", medium: "■", low: "●", info: "○" };
const SEVERITY_CLASS: Record<Severity, string> = {
  critical: "bg-sev-critical-bg text-sev-critical border-sev-critical/30",
  high: "bg-sev-high-bg text-sev-high border-sev-high/30",
  medium: "bg-sev-medium-bg text-sev-medium border-sev-medium/30",
  low: "bg-sev-low-bg text-sev-low border-sev-low/30",
  info: "bg-sev-info-bg text-sev-info border-sev-info/30",
};

const base = "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[11.5px] font-medium leading-none whitespace-nowrap";

export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={`${base} ${SEVERITY_CLASS[severity]}`}>
      <span aria-hidden="true">{SEVERITY_GLYPH[severity]}</span>
      {severity}
    </span>
  );
}

const EXPOSURE_CLASS: Record<Exposure, string> = {
  elevated: "bg-sev-high-bg text-sev-high border-sev-high/30",
  moderate: "bg-sev-medium-bg text-sev-medium border-sev-medium/30",
  low: "bg-sev-low-bg text-sev-low border-sev-low/30",
  "none-observed": "bg-paper text-ink-muted border-line",
  "not-assessable": "bg-paper text-ink-muted border-line border-dashed",
};
const EXPOSURE_GLYPH: Record<Exposure, string> = { elevated: "▲", moderate: "■", low: "●", "none-observed": "○", "not-assessable": "–" };

export function ExposureBadge({ exposure }: { exposure: Exposure }) {
  return (
    <span className={`${base} ${EXPOSURE_CLASS[exposure]}`}>
      <span aria-hidden="true">{EXPOSURE_GLYPH[exposure]}</span>
      {EXPOSURE_LABEL[exposure]}
    </span>
  );
}

const CONFIDENCE_CLASS: Record<Confidence, string> = {
  high: "bg-ok-bg text-ok border-ok/30",
  medium: "bg-sev-medium-bg text-sev-medium border-sev-medium/30",
  low: "bg-paper text-ink-muted border-line",
};

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return <span className={`${base} ${CONFIDENCE_CLASS[confidence]}`}>{confidence} confidence</span>;
}

/** Dimension assessability, labeled "confidence" for the reader. */
export function AssessabilityBadge({ assessability }: { assessability: string }) {
  const label = ASSESSABILITY_LABEL[assessability] ?? assessability;
  const cls = assessability === "strong" ? "bg-ok-bg text-ok border-ok/30" : assessability === "partial" ? "bg-sev-medium-bg text-sev-medium border-sev-medium/30" : "bg-paper text-ink-muted border-line border-dashed";
  return (
    <span className={`${base} ${cls}`} title={ASSESSABILITY_HINT[assessability] ?? ""}>
      {label}
    </span>
  );
}

export function Pill({ children, tone = "neutral", title }: { children: React.ReactNode; tone?: "neutral" | "gold" | "navy" | "warn"; title?: string }) {
  const cls = tone === "gold" ? "bg-gold-100 text-navy border-gold/50" : tone === "navy" ? "bg-navy text-white border-navy" : tone === "warn" ? "bg-sev-high-bg text-sev-high border-sev-high/30" : "bg-paper text-ink border-line";
  return (
    <span className={`${base} ${cls}`} title={title}>
      {children}
    </span>
  );
}
