/**
 * Risk register helpers. Rows come from the envelope (derived by the
 * scanner from its own dimension levels); this module only formats the
 * declared side as TOML for stoa-declared.toml and summarizes.
 */
import type { Envelope, RegisterRow, RiskRegisterDeclaration, Treatment } from "./types";

export const TREATMENTS: Treatment[] = ["accept", "mitigate", "avoid", "transfer"];
export const STATUSES = ["open", "in_progress", "closed"] as const;

export interface Declared {
  owner: string;
  treatment: Treatment | "";
  rationale: string;
  review_by: string;
  status: (typeof STATUSES)[number] | "";
}

export function declaredOf(row: RegisterRow): Declared {
  const d = row.declared;
  return {
    owner: d?.owner ?? "",
    treatment: d?.treatment ?? "",
    rationale: d?.rationale ?? "",
    review_by: d?.review_by ?? "",
    status: d?.status ?? "",
  };
}

function tomlString(value: string): string {
  return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n").replace(/\r/g, "").replace(/\t/g, "\\t")}"`;
}

/** The [[risk_register]] block to paste into stoa-declared.toml. */
export function toToml(riskId: string, d: Declared): string {
  const lines = ["[[risk_register]]", `risk_id   = ${tomlString(riskId)}`];
  if (d.owner) lines.push(`owner     = ${tomlString(d.owner)}`);
  if (d.treatment) lines.push(`treatment = ${tomlString(d.treatment)}   # ${TREATMENTS.join(" | ")}`);
  if (d.rationale) lines.push(`rationale = ${tomlString(d.rationale)}`);
  if (d.review_by) lines.push(`review_by = ${tomlString(d.review_by)}`);
  if (d.status) lines.push(`status    = ${tomlString(d.status)}   # ${STATUSES.join(" | ")}`);
  return lines.join("\n") + "\n";
}

export function isDeclaredEqual(a: Declared, b: Declared): boolean {
  return a.owner === b.owner && a.treatment === b.treatment && a.rationale === b.rationale && a.review_by === b.review_by && a.status === b.status;
}

/** "Due" is judged against the scan's own commit date, never the wall clock. */
export function reviewDue(row: RegisterRow, asOf: string | null | undefined): boolean {
  const date = row.declared?.review_by;
  if (!date || !asOf) return false;
  return date.slice(0, 10) < asOf.slice(0, 10);
}

export interface RegisterSummary {
  rows: number;
  declared: number;
  unmatched: number;
  due: number;
  byTreatment: Record<Treatment | "undeclared", number>;
}

export function summarize(env: Envelope): RegisterSummary {
  const asOf = env.registry.repository.head_commit?.date ?? null;
  const byTreatment: RegisterSummary["byTreatment"] = { accept: 0, mitigate: 0, avoid: 0, transfer: 0, undeclared: 0 };
  let declared = 0;
  let unmatched = 0;
  let due = 0;
  for (const row of env.register) {
    if (row.declared) declared += 1;
    if (row.unmatched) unmatched += 1;
    if (reviewDue(row, asOf)) due += 1;
    const t = row.declared?.treatment;
    if (t) byTreatment[t] += 1;
    else byTreatment.undeclared += 1;
  }
  return { rows: env.register.length, declared, unmatched, due, byTreatment };
}

export function riskName(row: RegisterRow): string {
  return `${row.dimension_name} · ${row.agent_name ?? row.agent_id}`;
}

export function declarationFromRow(row: RegisterRow): RiskRegisterDeclaration | null {
  return row.declared;
}
