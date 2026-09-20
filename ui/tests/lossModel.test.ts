import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { EVENTS, FIXTURES, indicate, whatIfs } from "../src/data/lossModel";
import { agentToModel, candidateAgents, intakeFromEnvelope, intakeToToml } from "../src/data/lossInputs";
import type { Envelope } from "../src/data/types";

const require = createRequire(import.meta.url);
// The model exactly as published on the Stoa AI loss outlook page.
const reference = require("./reference/loss-outlook.cjs");
const env = JSON.parse(readFileSync(new URL("../fixtures/meridian-pay.envelope.json", import.meta.url), "utf8")) as Envelope;

const OPTS = { years: 20000, noBoot: true };

describe("loss model port matches the published reference", () => {
  for (const key of ["F1", "F2", "F3"] as const) {
    it(`reproduces fixture ${key} exactly`, () => {
      const fx = FIXTURES[key]!;
      const ours = indicate(EVENTS, fx.scan.agents[0]!, fx.intake, 42, {}, OPTS);
      const theirs = reference.indicate(reference.EVENTS, fx.scan, fx.intake, 42, {}, OPTS);
      expect(ours.summary.pMid).toBeCloseTo(theirs.summary.pMid, 6);
      expect(ours.summary.eal).toBeCloseTo(theirs.summary.eal, 6);
      expect(ours.summary.pLow).toBeCloseTo(theirs.summary.pLow, 6);
      expect(ours.summary.pHigh).toBeCloseTo(theirs.summary.pHigh, 6);
      expect(ours.limits).toEqual(theirs.limits);
      expect(ours.retention).toBe(theirs.retention);
      expect(ours.confidence).toBe(theirs.confidence);
      expect(ours.gaps.map((g) => g.status)).toEqual(theirs.gaps.map((g: { status: string }) => g.status));
      expect(ours.summary.perCat.map((c) => c.tailShare)).toEqual(theirs.summary.perCat.map((c: { tailShare: number }) => c.tailShare));
      for (const cat of Object.keys(ours.comparables)) {
        expect(ours.comparables[cat]!.map((c) => c.id)).toEqual(theirs.comparables[cat].map((c: { id: string }) => c.id));
      }
      expect(ours.summary.curve.length).toBe(theirs.summary.curve.length);
    });
  }

  it("is deterministic for a seed and produces what-if levers", () => {
    const fx = FIXTURES.F2!;
    const a = indicate(EVENTS, fx.scan.agents[0]!, fx.intake, 42, {}, OPTS);
    const b = indicate(EVENTS, fx.scan.agents[0]!, fx.intake, 42, {}, OPTS);
    expect(a.summary.pMid).toBe(b.summary.pMid);
    const levers = whatIfs(fx.scan.agents[0]!, fx.intake, 42, a);
    expect(levers.length).toBeGreaterThan(0);
    expect(levers.some((l) => l.label.startsWith("Require human approval"))).toBe(true);
    expect(a.disclaimer).toContain("Not a quote");
  });
});

describe("scan to model inputs", () => {
  it("reads the intake block and maps the refund agent", () => {
    const { intake, monthlyVolume, declared } = intakeFromEnvelope(env);
    expect(declared).toBe(true);
    expect(intake.sector).toBe("fintech");
    expect(intake.existing_coverage[0]?.ai_exclusion).toBe(true);
    const agents = candidateAgents(env);
    expect(agents.length).toBeGreaterThan(0);
    const refund = agents.find((a) => a.id === "b8f0111742fc")!;
    const { model, notes } = agentToModel(env, refund, monthlyVolume);
    expect(model.capabilities.financial_authority.enabled).toBe(true);
    expect(model.capabilities.financial_authority.max_per_action_usd).toBe(500);
    expect(model.capabilities.autonomy_level).toBe("high");
    expect(model.capabilities.human_in_loop).toBe("none");
    expect(model.dimension_scores.mandate_overreach).toBe(refund.dimension_assessment!.dimensions.find((d) => d.id === "mandate-overreach")!.score);
    expect(Object.keys(model.dimension_scores).length).toBe(8);
    expect(notes.some((n) => n.input === "Max per action" && n.from.includes("declared"))).toBe(true);
    const out = indicate(EVENTS, model, intake, 42, {}, OPTS);
    expect(out.summary.pMid).toBeGreaterThan(0);
    expect(intakeToToml(intake, monthlyVolume)).toContain('sector                = "fintech"');
  });

  it("falls back to defaults without an intake block", () => {
    const { intake, declared } = intakeFromEnvelope({ ...env, intake: null });
    expect(declared).toBe(false);
    expect(intake.revenue).toBe(10e6);
  });
});
