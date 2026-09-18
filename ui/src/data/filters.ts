/**
 * Findings filter and sort state, round-tripped through the URL hash so a
 * filtered view is shareable. Pure functions; tested in tests/filters.test.ts.
 */
import type { Envelope, Severity } from "./types";
import type { FrameworkId } from "./frameworks";
import { CONFIDENCE_RANK, SEVERITY_RANK, activeFindings, allFindings, findingTag, type FindingRef } from "./selectors";
import type { SortState } from "../components/DataTable";

export type StatusFilter = "new" | "existing" | "suppressed";

export interface FindingFilters {
  severity: Severity[];
  dimension: string | null;
  cls: string | null;
  agent: string | null;
  confidence: string | null;
  status: StatusFilter | null;
  rule: string | null;
  q: string;
}

export const EMPTY_FILTERS: FindingFilters = { severity: [], dimension: null, cls: null, agent: null, confidence: null, status: null, rule: null, q: "" };

const SEVERITIES = new Set<string>(["critical", "high", "medium", "low", "info"]);

export function filtersFromQuery(query: URLSearchParams): FindingFilters {
  const sev = (query.get("severity") ?? "").split(",").map((s) => s.trim()).filter((s) => SEVERITIES.has(s)) as Severity[];
  const status = query.get("status");
  return {
    severity: sev,
    dimension: query.get("dimension") || null,
    cls: query.get("class") || null,
    agent: query.get("agent") || null,
    confidence: query.get("confidence") || null,
    status: status === "new" || status === "existing" || status === "suppressed" ? status : null,
    rule: query.get("rule") || null,
    q: query.get("q") ?? "",
  };
}

export function filtersToQuery(filters: FindingFilters, sort: SortState | null): URLSearchParams {
  const query = new URLSearchParams();
  if (filters.severity.length) query.set("severity", filters.severity.join(","));
  if (filters.dimension) query.set("dimension", filters.dimension);
  if (filters.cls) query.set("class", filters.cls);
  if (filters.agent) query.set("agent", filters.agent);
  if (filters.confidence) query.set("confidence", filters.confidence);
  if (filters.status) query.set("status", filters.status);
  if (filters.rule) query.set("rule", filters.rule);
  if (filters.q) query.set("q", filters.q);
  if (sort) {
    query.set("sort", sort.column);
    query.set("dir", sort.dir);
  }
  return query;
}

export function sortFromQuery(query: URLSearchParams): SortState | null {
  const column = query.get("sort");
  if (!column) return null;
  return { column, dir: query.get("dir") === "asc" ? "asc" : "desc" };
}

export function isFiltered(filters: FindingFilters): boolean {
  return filters.severity.length > 0 || Boolean(filters.dimension || filters.cls || filters.agent || filters.confidence || filters.status || filters.rule || filters.q);
}

export function applyFilters(env: Envelope, filters: FindingFilters, framework: FrameworkId): FindingRef[] {
  const source = filters.status === "suppressed" ? allFindings(env.registry).filter((r) => r.finding.suppressed) : filters.status ? activeFindings(env.registry) : allFindings(env.registry);
  const q = filters.q.trim().toLowerCase();
  return source.filter(({ finding, agents }) => {
    if (filters.severity.length && !filters.severity.includes(finding.severity)) return false;
    if (filters.dimension && !(finding.dimensions ?? []).includes(filters.dimension)) return false;
    if (filters.cls) {
      const cw = finding.crosswalk;
      const tag = framework === "nist" ? "" : findingTag(finding, framework);
      const anyTag = cw ? [cw.owasp_llm_2025, cw.eu_ai_act] : [];
      if (tag !== filters.cls && !anyTag.includes(filters.cls)) return false;
    }
    if (filters.agent && !agents.some((a) => a.id === filters.agent)) return false;
    if (filters.confidence && finding.confidence !== filters.confidence) return false;
    if (filters.status === "new" && !finding.is_new) return false;
    if (filters.status === "existing" && (finding.is_new || finding.suppressed)) return false;
    if (filters.rule && !finding.rule_id.startsWith(filters.rule)) return false;
    if (q) {
      const hay = `${finding.rule_id} ${finding.title} ${finding.path} ${finding.snippet} ${finding.remediation} ${finding.crosswalk?.so_what ?? ""} ${finding.canonical_name ?? ""} ${agents.map((a) => a.display_name || a.name).join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

/** Default order: severity, then confidence, then location. */
export function defaultOrder(refs: FindingRef[]): FindingRef[] {
  return [...refs].sort((a, b) => SEVERITY_RANK[b.finding.severity] - SEVERITY_RANK[a.finding.severity] || (CONFIDENCE_RANK[b.finding.confidence] ?? 0) - (CONFIDENCE_RANK[a.finding.confidence] ?? 0) || a.finding.path.localeCompare(b.finding.path) || a.finding.line - b.finding.line);
}
