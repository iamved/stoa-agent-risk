import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { declaredOf, reviewDue, summarize, toToml } from "../src/data/register";

const env = JSON.parse(readFileSync(new URL("../fixtures/meridian-pay.envelope.json", import.meta.url), "utf8")) as Envelope;

describe("risk register", () => {
  it("summarizes rows from the envelope without recomputing levels", () => {
    const s = summarize(env);
    expect(s.rows).toBe(env.register.length);
    expect(s.byTreatment.transfer).toBe(1);
    expect(s.byTreatment.mitigate).toBe(1);
    expect(s.unmatched).toBe(1);
    expect(s.due).toBe(0);
  });

  it("judges review dates against the scan commit date", () => {
    const row = env.register.find((r) => r.declared?.review_by)!;
    expect(reviewDue(row, "2027-01-01T00:00:00+00:00")).toBe(true);
    expect(reviewDue(row, "2026-01-01T00:00:00+00:00")).toBe(false);
    expect(reviewDue(row, null)).toBe(false);
  });

  it("emits a TOML block with escaping", () => {
    const row = env.register.find((r) => r.declared?.treatment === "transfer")!;
    const toml = toToml(row.risk_id, { ...declaredOf(row), rationale: 'say "hi"\\ done' });
    expect(toml.startsWith("[[risk_register]]\n")).toBe(true);
    expect(toml).toContain(`risk_id   = "${row.risk_id}"`);
    expect(toml).toContain('treatment = "transfer"');
    expect(toml).toContain('rationale = "say \\"hi\\"\\\\ done"');
    expect(toml).toContain('review_by = "2026-11-15"');
    expect(toToml("x/y", { owner: "", treatment: "", rationale: "", review_by: "", status: "" })).toBe('[[risk_register]]\nrisk_id   = "x/y"\n');
  });
});
