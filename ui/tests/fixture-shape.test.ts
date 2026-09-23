/**
 * The hand-written types are validated against the generated fixture: every
 * field a screen consumes must be present with the expected runtime type.
 * When the Python producer changes shape, this fails before any page does.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { checkEnvelope } from "../src/data/schema";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const envelope = load("meridian-pay");

describe("meridian-pay fixture matches the consumed contract", () => {
  it("passes the schema check", () => {
    expect(checkEnvelope(envelope)).toBeNull();
    expect(envelope.schema).toBe("stoa-dashboard/1.0");
  });

  it("carries the registry fields screens read", () => {
    const r = envelope.registry;
    expect(r.repository.head_commit?.hash).toMatch(/^[0-9a-f]{7,}$/);
    expect(r.repository.head_commit?.date).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(r.agents.length).toBeGreaterThan(3);
    for (const agent of r.agents) {
      expect(typeof agent.display_name).toBe("string");
      expect(Array.isArray(agent.findings)).toBe(true);
      expect(agent.dimension_assessment?.dimensions.length).toBeGreaterThan(0);
      for (const d of agent.dimension_assessment!.dimensions) {
        expect(typeof d.score).toBe("number");
        expect(typeof d.score_before_controls).toBe("number");
        expect(d.score_before_controls!).toBeGreaterThanOrEqual(d.score);
        expect(["strong", "partial", "proxy"]).toContain(d.assessability);
      }
      for (const f of agent.findings) {
        expect(f.crosswalk?.so_what).toBeTypeOf("string");
        expect(typeof f.fingerprint).toBe("string");
      }
    }
    expect(r.dimension_summary?.dimensions.length).toBe(8);
    expect(r.risk_register?.length).toBe(3);
  });

  it("carries a diff with an added agent; two-stacks carries one with a real authority increase", () => {
    const diff = envelope.diff!;
    expect(diff.schema).toBe("stoa-diff/1.0");
    expect(diff.agents.added.map((a) => a.name)).toEqual(["support_agent"]);
    const twoStacks = load("two-stacks");
    expect(checkEnvelope(twoStacks)).toBeNull();
    const added = twoStacks.diff!.agents.changed.flatMap((c) => c.capabilities.added);
    expect(added.some((c) => c.high_impact && c.drift_severity === "high")).toBe(true);
    expect(twoStacks.unique_agents!.find((u) => u.name === "account-actions")!.records).toHaveLength(2);
  });

  it("carries history, register rows, rules, and taxonomy", () => {
    expect(envelope.history.length).toBe(3);
    expect(envelope.register.some((row) => row.declared?.treatment === "transfer")).toBe(true);
    expect(envelope.register.some((row) => row.unmatched)).toBe(true);
    expect(envelope.rules["AI002"]?.crosswalk?.owasp_llm_2025).toBeTruthy();
    expect(envelope.taxonomy.dimensions.map((d) => d.id)).toContain("unreviewed-high-impact-action");
    expect(envelope.taxonomy.groups["A"]).toBe("Data & Privacy");
    expect(envelope.assurance.header.scan_timestamp).toBe(envelope.registry.repository.head_commit?.date);
    expect(envelope.frameworks.nist_ai_rmf.map((f) => f.function)).toEqual(["MAP", "MEASURE", "MANAGE", "GOVERN"]);
    expect(envelope.graph.nodes.some((n) => n.type === "agent")).toBe(true);
    expect(envelope.graph.edges.length).toBeGreaterThan(0);
    expect(envelope.vocabulary.high_impact_capabilities).toContain("payment_access");
    expect(envelope.assessment.sections.length).toBe(3);
    expect(envelope.assessment.schedule.some((f) => f.key === "policy_limit")).toBe(true);
    expect(envelope.assessment.counts.prefilled).toBeGreaterThan(0);
  });
});


describe("first-run and no-agents fixtures", () => {
  it("pass the schema check with every optional block absent", () => {
    for (const name of ["first-run", "no-agents"]) {
      const env = load(name);
      expect(checkEnvelope(env), name).toBeNull();
      expect(env.diff, name).toBeNull();
      expect(env.intake, name).toBeNull();
      expect(env.history, name).toEqual([]);
      expect(env.assessment.identity_source, name).toBe("sample");
    }
  });

  it("first-run has agents but nothing declared; no-agents has neither", () => {
    const first = load("first-run");
    expect(first.registry.agents.length).toBeGreaterThan(0);
    expect(first.registry.agents.some((a) => a.declared)).toBe(false);
    expect(load("no-agents").registry.agents).toEqual([]);
  });
});
