import { readFileSync } from "node:fs";
import { parse } from "smol-toml";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { completeness, scopeFromEnvelope, toDeclaredToml, toUnderwritingToml } from "../src/data/scope";
import { declaredContext } from "../src/data/lossInputs";

const env = JSON.parse(readFileSync(new URL("../fixtures/meridian-pay.envelope.json", import.meta.url), "utf8")) as Envelope;

describe("declared scope", () => {
  it("loads what the registry declared and lists every scanned agent", () => {
    const s = scopeFromEnvelope(env);
    expect(s.agents.length).toBe(env.registry.agents.length);
    const refund = s.agents.find((a) => a.id === "b8f0111742fc")!;
    expect(refund.wasDeclared).toBe(true);
    expect(refund.owner).toContain("meridian.example");
    expect(refund.max_per_action).toBe("500");
    expect(refund.moneyMover).toBe(true);
    expect(s.org.industries).toBe("financial_services");
    expect(s.intake.sector).toBe("fintech");
    expect(s.policies[0]?.type).toBe("cyber");
    expect(s.identity.company).toBe("Meridian Pay");
  });

  it("scores completeness and names the gaps that matter", () => {
    const s = scopeFromEnvelope(env);
    const c = completeness(s);
    expect(c.total).toBeGreaterThan(10);
    expect(c.filled).toBeLessThan(c.total);
    // Every agent is declared with an owner; the chatbot moves money with no limit declared.
    expect(c.gaps.some((g) => g.label === "Owner")).toBe(false);
    expect(c.gaps.some((g) => g.label === "Max per action")).toBe(true);
  });

  it("generates valid stoa-declared.toml that round-trips", () => {
    const s = scopeFromEnvelope(env);
    s.agents[0]!.owner = 'Team "Payments" \\ ops';
    s.agents[0]!.purpose = "Line one\nline two";
    s.org.industries = "financial_services, payments";
    const doc = parse(toDeclaredToml(s, env.registry.risk_register ?? [])) as Record<string, unknown>;
    expect(doc.version).toBe(1);
    expect((doc.business as Record<string, unknown>).industries).toEqual(["financial_services", "payments"]);
    const agents = doc.agents as Record<string, Record<string, unknown>>;
    expect(agents[s.agents[0]!.id]!.owner).toBe('Team "Payments" \\ ops');
    expect(agents[s.agents[0]!.id]!.purpose).toBe("Line one\nline two");
    const refund = agents["b8f0111742fc"] as { economic_authority: { max_per_action: { amount: number; currency: string } } };
    expect(refund.economic_authority.max_per_action).toEqual({ amount: 500, currency: "USD" });
    expect(Array.isArray(doc.risk_register)).toBe(true);
    expect((doc.risk_register as unknown[]).length).toBe(env.registry.risk_register!.length);
  });

  it("generates valid .stoa/underwriting.toml", () => {
    const s = scopeFromEnvelope(env);
    s.intake.revenue = "45,000,000";
    s.policies.push({ type: "tech_eo", limit: "10000000", ai_exclusion: false });
    const doc = parse(toUnderwritingToml(s, env.assessment.performance)) as { identity: Record<string, string>; intake: { revenue: number; existing_coverage: { type: string }[] }; performance: unknown[] };
    expect(doc.identity.company).toBe("Meridian Pay");
    expect(doc.intake.revenue).toBe(45000000);
    expect(doc.intake.existing_coverage.map((p) => p.type)).toEqual(["cyber", "tech_eo"]);
    expect(doc.performance.length).toBe(env.assessment.performance.length);
  });

  it("derives outlook context from declared facts", () => {
    const ctx = declaredContext(env);
    expect(ctx.sector).toBe("fintech");
    expect(ctx.regulated).toBe(true);
  });
});
