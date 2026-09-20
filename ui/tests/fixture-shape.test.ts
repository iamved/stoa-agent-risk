/**
 * The hand-written types are validated against the generated fixture: every
 * field a screen consumes must be present with the expected runtime type.
 * When the Python producer changes shape, this fails before any page does.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { checkEnvelope } from "../src/data/schema";

const envelope = JSON.parse(readFileSync(new URL("../fixtures/meridian-pay.envelope.json", import.meta.url), "utf8")) as Envelope;

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

  it("carries a diff with a real authority increase", () => {
    const diff = envelope.diff!;
    expect(diff.schema).toBe("stoa-diff/1.0");
    const added = diff.agents.changed.flatMap((c) => c.capabilities.added);
    expect(added.some((c) => c.high_impact && c.drift_severity === "high")).toBe(true);
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
