import { readFileSync } from "node:fs";
import { uniqueAgentOf } from "../src/data/agents";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { EMPTY_FILTERS, applyFilters, filtersFromQuery, filtersToQuery, sortFromQuery } from "../src/data/filters";
import { categories, codeAgents, iacAgents, integrationRows, toolRows } from "../src/data/inventory";
import { activeFindings, allFindings } from "../src/data/selectors";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const env = load("meridian-pay");
// account-actions defined in code and on AWS: one agent, two records.
const twoStacks = load("two-stacks");

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
    const all = allFindings(env);
    expect(applyFilters(env, EMPTY_FILTERS, "owasp").length).toBe(all.length);
    const crit = applyFilters(env, { ...EMPTY_FILTERS, severity: ["critical"] }, "owasp");
    expect(crit.length).toBe(all.filter((r) => !r.finding.suppressed && r.finding.severity === "critical").length);
    expect(crit.reduce((n, r) => n + r.evidence.length, 0)).toBe(env.registry.summary.findings.critical);
    const dim = applyFilters(env, { ...EMPTY_FILTERS, dimension: "mandate-overreach" }, "owasp");
    expect(dim.every((r) => r.finding.dimensions?.includes("mandate-overreach"))).toBe(true);
    const cls = applyFilters(env, { ...EMPTY_FILTERS, cls: "LLM06" }, "owasp");
    expect(cls.length).toBeGreaterThan(0);
    expect(cls.every((r) => r.finding.crosswalk?.owasp_llm_2025 === "LLM06")).toBe(true);
    const agent = twoStacks.registry.agents.find((a) => a.id === "b8f0111742fc")!;
    const byAgent = applyFilters(twoStacks, { ...EMPTY_FILTERS, agent: agent.id }, "owasp");
    // The filter means the whole agent: the same findings whichever of its records the link names.
    const whole = uniqueAgentOf(twoStacks, agent.id)!;
    expect(whole.records.length).toBe(2);
    expect(byAgent.length).toBeGreaterThan(0);
    expect(byAgent.every((r) => r.uniqueAgents.includes(whole))).toBe(true);
    for (const record of whole.records) expect(applyFilters(twoStacks, { ...EMPTY_FILTERS, agent: record.id }, "owasp")).toEqual(byAgent);
    expect(applyFilters(env, { ...EMPTY_FILTERS, agent: "no-such-agent" }, "owasp")).toEqual([]);
    expect(applyFilters(env, { ...EMPTY_FILTERS, rule: "DECL" }, "owasp").every((r) => r.finding.rule_id.startsWith("DECL"))).toBe(true);
    expect(applyFilters(env, { ...EMPTY_FILTERS, q: "idempotency" }, "owasp").some((r) => r.finding.rule_id === "AI008")).toBe(true);
    expect(applyFilters(env, { ...EMPTY_FILTERS, status: "suppressed" }, "owasp").length).toBe(all.length - activeFindings(env).length);
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
    expect(cats.map((c) => c.id)).toEqual(["agents", "agents_code", "agents_iac", "tools", "providers", "integrations", "declarations"]);
    expect(cats[0]!.count).toBe(5);
    expect([cats[1]!.count, cats[2]!.count]).toEqual([3, 2]);
    expect(cats.find((c) => c.id === "declarations")?.count).toBe(env.registry.agents.filter((a) => a.declared).length);
    expect(integrationRows(env).every((r) => r.agents.length > 0)).toBe(true);
  });
});
