import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { EMPTY_FILTERS, applyFilters, filtersFromQuery, filtersToQuery, sortFromQuery } from "../src/data/filters";
import { categories, codeAgents, iacAgents, integrationRows, toolRows } from "../src/data/inventory";
import { activeFindings, allFindings } from "../src/data/selectors";

const env = JSON.parse(readFileSync(new URL("../fixtures/meridian-pay.envelope.json", import.meta.url), "utf8")) as Envelope;

describe("finding filters round-trip through the URL", () => {
  it("parses and serializes every filter", () => {
    const q = new URLSearchParams("severity=critical,high&dimension=mandate-overreach&class=LLM06&agent=abc&confidence=high&status=new&rule=AI&q=refund&sort=severity&dir=asc");
    const f = filtersFromQuery(q);
    expect(f).toEqual({ severity: ["critical", "high"], dimension: "mandate-overreach", cls: "LLM06", agent: "abc", confidence: "high", status: "new", rule: "AI", q: "refund" });
    expect(sortFromQuery(q)).toEqual({ column: "severity", dir: "asc" });
    expect(filtersToQuery(f, { column: "severity", dir: "asc" }).toString()).toBe(q.toString());
    expect(filtersToQuery(EMPTY_FILTERS, null).toString()).toBe("");
    expect(filtersFromQuery(new URLSearchParams("severity=bogus&status=weird")).severity).toEqual([]);
  });

  it("filters by severity, dimension, class, agent, rule and text", () => {
    const all = allFindings(env.registry);
    expect(applyFilters(env, EMPTY_FILTERS, "owasp").length).toBe(all.length);
    const crit = applyFilters(env, { ...EMPTY_FILTERS, severity: ["critical"] }, "owasp");
    expect(crit.length).toBe(env.registry.summary.findings.critical);
    const dim = applyFilters(env, { ...EMPTY_FILTERS, dimension: "mandate-overreach" }, "owasp");
    expect(dim.every((r) => r.finding.dimensions?.includes("mandate-overreach"))).toBe(true);
    const cls = applyFilters(env, { ...EMPTY_FILTERS, cls: "LLM06" }, "owasp");
    expect(cls.length).toBeGreaterThan(0);
    expect(cls.every((r) => r.finding.crosswalk?.owasp_llm_2025 === "LLM06")).toBe(true);
    const agent = env.registry.agents.find((a) => a.findings.length > 0)!;
    const byAgent = applyFilters(env, { ...EMPTY_FILTERS, agent: agent.id }, "owasp");
    expect(byAgent.every((r) => r.agents.some((a) => a.id === agent.id))).toBe(true);
    expect(applyFilters(env, { ...EMPTY_FILTERS, rule: "DECL" }, "owasp").every((r) => r.finding.rule_id.startsWith("DECL"))).toBe(true);
    expect(applyFilters(env, { ...EMPTY_FILTERS, q: "idempotency" }, "owasp").some((r) => r.finding.rule_id === "AI008")).toBe(true);
    expect(applyFilters(env, { ...EMPTY_FILTERS, status: "suppressed" }, "owasp").length).toBe(all.length - activeFindings(env.registry).length);
  });
});

describe("inventory categories come from the registry", () => {
  it("splits agents by source and dedupes tools and integrations", () => {
    expect(codeAgents(env).length + iacAgents(env).length).toBe(env.registry.agents.length);
    expect(iacAgents(env).every((a) => a.source === "iac")).toBe(true);
    const tools = toolRows(env);
    expect(tools.some((t) => t.tool.money_action)).toBe(true);
    expect(new Set(tools.map((t) => t.key)).size).toBe(tools.length);
    const cats = categories(env);
    expect(cats.map((c) => c.id)).toEqual(["agents_code", "agents_iac", "tools", "providers", "integrations", "declarations"]);
    expect(cats.find((c) => c.id === "declarations")?.count).toBe(env.registry.agents.filter((a) => a.declared).length);
    expect(integrationRows(env).every((r) => r.agents.length > 0)).toBe(true);
  });
});
