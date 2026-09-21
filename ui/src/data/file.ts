import type { Envelope } from "./types";
import { checkEnvelope, type SchemaProblem } from "./schema";
import { DATA_ELEMENT_ID } from "./embedded";

/**
 * Opens a scan the viewer picked from their own disk. The file is read in the
 * browser and nothing else happens to it: the page's CSP is
 * `connect-src 'none'`, so there is no way for it to leave.
 *
 * Accepts the dashboard data as JSON (`stoa dashboard --json-out`) or a whole
 * `stoa-dashboard.html`, from which the embedded data is lifted. Unlike the
 * embedded envelope, this one did not come straight from the Python builder,
 * so its shape is checked before any screen reads it.
 */
export type OpenResult = { envelope: Envelope } | { problem: SchemaProblem };

const EXPECTED = "stoa-dashboard/1.x";
const JSON_OUT_HINT = "stoa dashboard stoa-registry.json --json-out stoa-dashboard.json";

function problem(kind: SchemaProblem["kind"], message: string, found: string | null = null): { problem: SchemaProblem } {
  return { problem: { kind, message, found, expected: EXPECTED } };
}

/** The data block of a stoa-dashboard.html, or null when the text is not one. */
export function embeddedJson(text: string): string | null {
  const open = `<script id="${DATA_ELEMENT_ID}" type="application/json">`;
  const start = text.indexOf(open);
  if (start === -1) return null;
  // The injector escapes `<` inside the data, so the next close tag is the block's own.
  const end = text.indexOf("</script>", start + open.length);
  return end === -1 ? null : text.slice(start + open.length, end);
}

const isObject = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

/** The first part of the envelope a screen would trip over, or null. */
export function shapeProblem(data: Record<string, unknown>): string | null {
  const registry = data["registry"];
  if (!isObject(registry)) return "registry";
  if (!Array.isArray(registry["agents"])) return "registry.agents";
  if (!Array.isArray(registry["repository_findings"])) return "registry.repository_findings";
  if (!isObject(registry["repository"])) return "registry.repository";
  if (!isObject(registry["summary"])) return "registry.summary";
  for (const agent of registry["agents"]) {
    if (!isObject(agent) || !Array.isArray(agent["findings"])) return "registry.agents[].findings";
  }
  for (const key of ["register", "history"]) if (!Array.isArray(data[key])) return key;
  for (const key of ["generator", "rules", "assurance", "frameworks", "vocabulary"]) if (!isObject(data[key])) return key;
  const graph = data["graph"];
  if (!isObject(graph) || !Array.isArray(graph["nodes"]) || !Array.isArray(graph["edges"])) return "graph";
  const taxonomy = data["taxonomy"];
  if (!isObject(taxonomy) || !Array.isArray(taxonomy["dimensions"]) || !isObject(taxonomy["groups"])) return "taxonomy";
  const assessment = data["assessment"];
  if (!isObject(assessment) || !isObject(assessment["identity"]) || !isObject(assessment["counts"])) return "assessment";
  for (const key of ["sections", "performance", "schedule"]) if (!Array.isArray(assessment[key])) return `assessment.${key}`;
  return null;
}

export function envelopeFromText(text: string): OpenResult {
  const trimmed = text.trim();
  if (trimmed === "") return problem("missing", "That file is empty.");
  const source = trimmed.startsWith("<") ? embeddedJson(trimmed) : trimmed;
  if (source === null) return problem("malformed", "That HTML file is not a Stoa dashboard: it carries no scan data.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(source);
  } catch {
    return problem("malformed", "That file is not valid JSON.");
  }
  if (!isObject(parsed)) return problem("malformed", "That file does not hold a Stoa scan.");
  if (typeof parsed["schema"] !== "string" && "schema_version" in parsed && Array.isArray(parsed["agents"])) {
    return problem("malformed", `That is a stoa-registry.json, and the dashboard needs the full scan data. Run "${JSON_OUT_HINT}", then open stoa-dashboard.json.`, `registry ${String(parsed["schema_version"])}`);
  }
  const versionProblem = checkEnvelope(parsed);
  if (versionProblem) return { problem: { ...versionProblem, message: versionProblem.message.replace(/embedded /g, "").replace("This page was generated", "That file was generated") } };
  const missing = shapeProblem(parsed);
  if (missing) return problem("malformed", `That file is missing part of the scan data (${missing}). Rebuild it by running "${JSON_OUT_HINT}".`, String(parsed["schema"]));
  return { envelope: parsed as unknown as Envelope };
}
