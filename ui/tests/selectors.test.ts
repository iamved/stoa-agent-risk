import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { activeFindings, countBySeverity, dimensionMatrix, dimensionTrend, elevatedAgents, findingByFingerprint, frameworkClasses, hasAuthority, stats, topRisks } from "../src/data/selectors";
import { buildHash, parseHash } from "../src/app/router";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const env = load("meridian-pay");
// account-actions defined in code and on AWS: the same rule on both records is one finding with two locations.
const twoStacks = load("two-stacks");

describe("selectors copy scanner numbers without recomputing", () => {
  it("the scanner records behind the findings tie to the registry summary exactly", () => {
    // Findings are shown merged; the records they are made of are the scanner's, untouched.
    const records = activeFindings(env).flatMap((r) => r.evidence);
    const bySeverity = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    for (const f of records) bySeverity[f.severity] += 1;
    expect(bySeverity).toEqual(env.registry.summary.findings);
    expect(new Set(records.map((f) => f.fingerprint)).size).toBe(records.length);
  });

  it("the same rule on two records of one agent is one finding with two locations", () => {
    expect(countBySeverity(activeFindings(env))).toEqual({ critical: 2, high: 1, medium: 2, low: 3, info: 5 });
    expect(activeFindings(env).every((r) => r.evidence.length === 1)).toBe(true);
    const active = activeFindings(twoStacks);
    expect(countBySeverity(active)).toEqual({ critical: 2, high: 1, medium: 2, low: 3, info: 5 });
    const merged = active.filter((r) => r.evidence.length > 1);
    expect(merged.map((r) => r.finding.rule_id)).toEqual(["DECL001"]);
    // The refund tool is bound by two agents: its AI008 is one finding, one location, two agents.
    const shared = active.find((r) => r.finding.rule_id === "AI008")!;
    expect(shared.evidence).toHaveLength(1);
    expect(shared.uniqueAgents.map((u) => u.name).sort()).toEqual(["account-actions", "meridian-support"]);
    for (const ref of merged) {
      expect(ref.uniqueAgents).toHaveLength(1);
      expect(new Set(ref.evidence.map((f) => f.rule_id)).size).toBe(1);
      // One location per scanned record of that agent: its code and its infrastructure.
      expect(new Set(ref.evidence.map((f) => f.path)).size).toBe(ref.evidence.length);
      expect(ref.evidence[0]).toBe(ref.finding);
    }
    // A link made to either location still opens the finding.
    const both = merged[0]!;
    for (const f of both.evidence) expect(findingByFingerprint(twoStacks, f.fingerprint)).toBe(both);
  });

  it("nothing merges without an identity block", () => {
    const old = { ...twoStacks, unique_agents: undefined };
    expect(activeFindings(old).every((r) => r.evidence.length === 1)).toBe(true);
    expect(countBySeverity(activeFindings(old))).toEqual(twoStacks.registry.summary.findings);
  });

  it("matrix cells mirror dimension_summary", () => {
    const groups = dimensionMatrix(env, "owasp");
    const cells = groups.flatMap((g) => g.cells);
    expect(cells.length).toBe(8);
    for (const cell of cells) {
      const summary = env.registry.dimension_summary!.dimensions.find((d) => d.id === cell.dimension.id)!;
      expect(cell.maxExposure).toBe(summary.max_exposure);
      expect(cell.agentsElevated).toBe(summary.agents_elevated);
      for (const { entry } of cell.agents) expect(entry.exposure).not.toBe("none-observed");
    }
    expect(groups.map((g) => g.id)).toEqual(["A", "B", "C", "D"]);
    expect(dimensionMatrix(env, "eu").flatMap((g) => g.cells).some((c) => c.tags.some((t) => t.startsWith("Art.")))).toBe(true);
  });

  it("stats and authority follow the scanner vocabulary", () => {
    const s = stats(env);
    expect(s.agents).toBe(5);
    expect(s.records).toBe(env.registry.agents.length);
    expect(s.authorityAgents).toBeGreaterThan(0);
    expect(s.drift?.changed).toBe(env.diff!.summary.agents_changed);
    const withPayment = env.registry.agents.find((a) => a.capabilities.includes("payment_access"))!;
    expect(hasAuthority(env, withPayment)).toBe(true);
  });

  it("top risks are unique by rule first and link to real findings", () => {
    const risks = topRisks(env, 5);
    expect(risks.length).toBe(5);
    const rules = risks.map((r) => r.ref.finding.rule_id);
    expect(new Set(rules).size).toBe(rules.length);
    for (const r of risks) {
      expect(findingByFingerprint(env, r.ref.finding.fingerprint)).not.toBeNull();
      expect(r.soWhat.length).toBeGreaterThan(10);
    }
    expect(risks[0]!.ref.finding.severity).toBe("critical");
  });

  it("framework classes keep gaps visible", () => {
    const owasp = frameworkClasses(env, "owasp");
    expect(owasp.map((c) => c.id)).toEqual(["LLM01", "LLM02", "LLM03", "LLM04", "LLM05", "LLM06", "LLM07", "LLM08", "LLM09", "LLM10"]);
    expect(owasp.some((c) => c.state === "observed")).toBe(true);
    expect(owasp.some((c) => c.state === "gap")).toBe(true);
    const nist = frameworkClasses(env, "nist");
    expect(nist.find((c) => c.id === "GOVERN")?.state).toBe("outside");
  });

  it("trends read history in order", () => {
    const points = dimensionTrend(env.history, "unreviewed-high-impact-action");
    expect(points.length).toBe(3);
    expect(points.map((p) => p.hash)).toEqual(env.history.map((h) => h.head_commit.hash));
    expect(elevatedAgents(env).length).toBeGreaterThan(0);
  });
});

describe("hash router", () => {
  it("parses and builds routes with ids and queries", () => {
    expect(parseHash("")).toMatchObject({ screen: "overview", id: null });
    expect(parseHash("#/findings/abc%2F1?severity=high").id).toBe("abc/1");
    expect(parseHash("#/findings?severity=high").query.get("severity")).toBe("high");
    expect(parseHash("#/nonsense").screen).toBe("overview");
    expect(buildHash("findings", "a b", { severity: "high" })).toBe("#/findings/a%20b?severity=high");
    expect(buildHash("overview")).toBe("#/overview");
  });
});
