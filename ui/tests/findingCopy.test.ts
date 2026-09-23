/**
 * The finding panel's copy: static per rule, generated per finding, and the
 * agent named the way the "Affected agent" field names it.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { evidenceLines, howToFix, locationText, ruleName, whatThisCheckDoes, whatWeFound, whyItMatters } from "../src/data/findingCopy";
import { DIMENSION_LABEL, dimensionLabel, relabelDimensions } from "../src/data/labels";
import { activeFindings, dimensionName, findingTitle } from "../src/data/selectors";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const demo = load("meridian-pay");
const decl001 = activeFindings(demo).find((r) => r.finding.rule_id === "DECL001" && r.uniqueAgents[0]!.name === "account-actions")!;
const ai008 = activeFindings(demo).find((r) => r.finding.rule_id === "AI008")!;

describe("the finding panel for DECL001", () => {
  it("names the agent as the panel does, not as the scanner's symbol", () => {
    // The scanner writes the code symbol (`graph`, the LangGraph variable); the panel uses the agent's name.
    expect(decl001.finding.message).toContain("`graph`");
    expect(whatWeFound(decl001)).toBe("account-actions is declared as needing human approval, but its code can take actions with no approval step. Either the declaration is out of date, or the approval step is missing.");
    const recommend = { ...decl001, uniqueAgents: decl001.uniqueAgents.map((u) => ({ ...u, records: u.records.map((r) => ({ ...r, declared: { ...r.declared!, autonomy_intent: "recommend_only" } })) })) };
    expect(whatWeFound(recommend)).toMatch(/^account-actions is declared as recommend-only, but/);
  });

  it("splits the static copy from the generated copy", () => {
    expect(findingTitle(demo, decl001.finding)).toBe("Agent has more autonomy than declared.");
    expect(ruleName(demo, "DECL001", decl001.finding.title)).toBe("Declared autonomy doesn't match the code");
    expect(whatThisCheckDoes(demo, "DECL001")).toBe("Compares the autonomy an agent is declared to have with what its code actually allows. Can fail a build when confidence is high.");
    expect(whyItMatters(demo, decl001, "x")).toBe("An agent you think is supervised can act on its own.");
    expect(howToFix(decl001)).toBe("Add an approval step before this action. If the agent is meant to act on its own, update autonomy_intent for this agent in stoa-declared.toml instead.");
    expect(decl001.finding.declared_ref?.key).toBe('agents."b8f0111742fc".autonomy_intent');
    expect(evidenceLines(decl001)).toEqual([{ label: "Declared", value: "human_approved" }, { label: "Found", value: "unrestricted_autonomous" }]);
  });

  it("falls back to the scanner's words, without backticks, for a rule with no plain copy", () => {
    expect(evidenceLines(ai008)).toBeNull();
    expect(whatWeFound(ai008)).toMatch(/^issue_refund posts a money action/);
    expect(whatWeFound(ai008)).not.toContain("`");
    expect(ruleName(demo, "AI008", ai008.finding.title)).toBe(demo.rules["AI008"]!.title);
    expect(whatThisCheckDoes(demo, "AI008")).toMatch(new RegExp(`^${demo.rules["AI008"]!.title}\\.`));
  });

  it("drops a column number that says nothing", () => {
    expect(locationText("a.py", 17, 1)).toBe("a.py:17");
    expect(locationText("a.py", 17, 9)).toBe("a.py:17:9");
    expect(locationText("a.py", 17)).toBe("a.py:17");
  });
});

describe("dimension display names", () => {
  it("relabel the taxonomy and register rows, and nothing else", () => {
    expect(Object.keys(DIMENSION_LABEL)).toHaveLength(8);
    const shown = relabelDimensions(demo);
    expect(shown.taxonomy.dimensions.map((d) => d.name).sort()).toEqual(Object.values(DIMENSION_LABEL).sort());
    expect(shown.taxonomy.dimensions.map((d) => d.id)).toEqual(demo.taxonomy.dimensions.map((d) => d.id));
    expect(shown.register.find((r) => r.risk_id.startsWith("mandate-overreach/"))?.dimension_name).toBe("Excess access");
    expect(shown.registry).toBe(demo.registry);
    expect(dimensionName(demo, "mandate-overreach")).toBe("Excess access");
    expect(dimensionLabel("custom-dimension", "Custom")).toBe("Custom");
    for (const name of Object.values(DIMENSION_LABEL)) expect(name).not.toContain("\u2014");
  });
});
