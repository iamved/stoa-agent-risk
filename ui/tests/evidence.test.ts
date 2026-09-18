import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { areaSummaries, controlsByAgent, fixFirst, packetTotals } from "../src/data/evidence";

const env = JSON.parse(readFileSync(new URL("../fixtures/meridian-pay.envelope.json", import.meta.url), "utf8")) as Envelope;

describe("evidence views", () => {
  it("merges critical and high findings by rule and fix", () => {
    const fixes = fixFirst(env);
    expect(fixes.length).toBeGreaterThan(0);
    expect(fixes[0]!.severity).toBe("critical");
    const total = fixes.reduce((n, f) => n + f.refs.length, 0);
    expect(total).toBe(env.registry.summary.findings.critical + env.registry.summary.findings.high);
    expect(new Set(fixes.map((f) => `${f.rule_id}::${f.remediation}`)).size).toBe(fixes.length);
  });

  it("summarizes the assurance packet without dropping not-provided rows", () => {
    const areas = areaSummaries(env.assurance);
    expect(areas.length).toBe(Object.keys(env.assurance.areas).length);
    const totals = packetTotals(areas);
    expect(totals.not_provided).toBeGreaterThan(0);
    expect(totals.scanned + totals.declared).toBeGreaterThan(0);
  });

  it("lists observed controls per agent", () => {
    const controls = controlsByAgent(env);
    expect(controls.length).toBe(env.registry.agents.length);
    expect(controls.some((c) => c.declaredAutonomy === "human_approved" && c.inferredAutonomy === "unrestricted_autonomous")).toBe(true);
    expect(controls.some((c) => c.maxPerAction === "500 USD")).toBe(true);
  });
});
