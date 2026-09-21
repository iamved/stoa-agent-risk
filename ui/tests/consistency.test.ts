/**
 * Numbers tie out. A figure on the Overview is the same function, or the same
 * count, as the figure on the screen it links to; and what is shown always
 * reconciles with the scanner's own records. Runs on every fixture, because a
 * count that only works on the demo is a hardcoded count.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { uniqueAgents } from "../src/data/agents";
import { gapGroups, safeguardRows, safeguardTotals } from "../src/data/controls";
import { applyFilters, EMPTY_FILTERS } from "../src/data/filters";
import { categories, uniqueAgentFindingCount } from "../src/data/inventory";
import { attention, elevatedDimensions, holdings, protection, registerCard } from "../src/data/overview";
import { summarize } from "../src/data/register";
import { activeFindings, allFindings, countByLevel, countBySeverity, findingsByDimension, recordCount, stats } from "../src/data/selectors";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const FIXTURES = ["meridian-pay", "first-run", "no-agents", "hostile"] as const;

describe.each(FIXTURES)("%s", (name) => {
  const env = load(name);
  const active = activeFindings(env);

  it("findings by severity sum to the total, and the three levels do too", () => {
    const bySeverity = countBySeverity(active);
    expect(Object.values(bySeverity).reduce((a, b) => a + b, 0)).toBe(active.length);
    const byLevel = countByLevel(active);
    expect(byLevel.high + byLevel.medium + byLevel.low).toBe(active.length);
    expect(byLevel.high).toBe(bySeverity.critical + bySeverity.high);
  });

  it("the findings shown reconcile with the scanner's records", () => {
    const summary = env.registry.summary.findings;
    expect(recordCount(active)).toBe(Object.values(summary).reduce((a, b) => a + b, 0));
    expect(active.length).toBeLessThanOrEqual(recordCount(active));
    // Merging never invents, drops or duplicates a record.
    const fingerprints = allFindings(env).flatMap((r) => r.evidence.map((f) => f.fingerprint));
    expect(new Set(fingerprints).size).toBe(fingerprints.length);
  });

  it("the Findings table, unfiltered, holds exactly the findings counted", () => {
    expect(applyFilters(env, EMPTY_FILTERS, "owasp").length).toBe(allFindings(env).length);
    const high = applyFilters(env, { ...EMPTY_FILTERS, severity: ["critical", "high"] }, "owasp").filter((r) => !r.finding.suppressed);
    expect(high.length).toBe(countByLevel(active).high);
  });

  it("Overview agent figures equal the Agent Inventory's", () => {
    const h = holdings(env);
    expect(h.agents).toBe(uniqueAgents(env).length);
    expect(h.agents).toBe(categories(env).find((c) => c.id === "agents")!.count);
    expect(h.records).toBe(env.registry.agents.length);
    expect(h.records).toBe(categories(env).filter((c) => c.id === "agents_code" || c.id === "agents_iac").reduce((n, c) => n + c.count, 0));
    expect(stats(env).agents).toBe(h.agents);
    // Every record belongs to exactly one agent.
    expect(uniqueAgents(env).reduce((n, u) => n + u.records.length, 0)).toBe(h.records);
  });

  it("Overview safeguard figures equal Controls & Safeguards'", () => {
    const p = protection(env);
    const totals = safeguardTotals(env);
    expect(p.moneyTools).toBe(totals.moneyTools);
    expect(p.moneyToolsWithoutGuardrail).toBe(totals.moneyToolsWithoutGuardrail);
    expect(p.doublePost).toBe(totals.doublePayment.length);
    expect(totals.gaps).toBe(gapGroups(env).reduce((n, g) => n + g.refs.length, 0));
    expect(safeguardRows(env).length).toBe(uniqueAgents(env).length);
    expect(p.approved).toBeLessThanOrEqual(p.moneyMovers);
  });

  it("Overview finding figures equal the Findings screen's", () => {
    expect(attention(env, 999).reduce((n, item) => n + item.findings, 0)).toBe(active.length);
    expect(stats(env).findings).toEqual(countBySeverity(active));
    for (const d of elevatedDimensions(env)) {
      const bar = findingsByDimension(env).find((b) => b.dimension.id === d.id)!;
      expect(d.findings).toBe(bar.total);
      expect(applyFilters(env, { ...EMPTY_FILTERS, dimension: d.id }, "owasp").filter((r) => !r.finding.suppressed).length).toBe(d.findings);
    }
  });

  it("per-agent finding counts cover every finding that names an agent", () => {
    const owned = active.filter((r) => r.uniqueAgents.length > 0);
    const perAgent = uniqueAgents(env).reduce((n, u) => n + uniqueAgentFindingCount(env, u), 0);
    expect(perAgent).toBe(owned.reduce((n, r) => n + r.uniqueAgents.length, 0));
  });

  it("the Overview register card equals the register", () => {
    const card = registerCard(env);
    expect(card.risks + card.stale).toBe(env.register.length);
    expect(card.stale).toBe(summarize(env).unmatched);
    expect(card.decided + card.awaiting).toBe(card.risks);
  });
});
