/**
 * The Overview states facts in sentences, so each one is pinned to the scan
 * it came from: a figure the fixture does not support must never appear.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { SPECTRUM_BANDS, agentSpectrum, attention, attentionStatus, attentionTitle, audienceLine, costOutlook, elevatedDimensions, highLines, holdings, joinWords, moneyMovers, newHighLine, newestAgent, nextAction, otherDimensionsLine, protection, registerCard, scanSaw, scanSources, sentenceText, spanWords, standing, whatChanged, whyItMatters } from "../src/data/overview";
import { PLAIN_ACTION, PLAIN_TITLE, PLAIN_WHY } from "../src/data/labels";
import { toolRows } from "../src/data/inventory";
import { activeFindings, countByLevel } from "../src/data/selectors";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const demo = load("meridian-pay");
const twoStacks = load("two-stacks");
const firstRun = load("first-run");
const empty = load("no-agents");

describe("what we have and whether it is protected", () => {
  it("counts what the registry holds", () => {
    const h = holdings(demo);
    // Five agents from five records: three in code, one on AWS, one on Databricks. Tools are the inventory's count.
    expect(h).toEqual({ agents: 5, records: 5, moneyMovers: 2, tools: toolRows(demo).length, providers: 4 });
    expect(moneyMovers(demo).every((u) => u.records.some((a) => (a.tools ?? []).some((t) => t.money_action) || a.capabilities.includes("payment_access")))).toBe(true);
    expect(scanSources(demo)).toEqual(["application code", "AWS and Databricks definitions"]);
    // Account actions in code and on AWS is one money mover, not two.
    expect(holdings(twoStacks)).toMatchObject({ agents: 5, records: 6, moneyMovers: 2 });
    expect(holdings(empty)).toEqual({ agents: 0, records: 0, moneyMovers: 0, tools: 0, providers: 0 });
    expect(scanSources(empty)).toEqual([]);
  });

  it("says who the agents serve and which one is newest, from the declaration and the history", () => {
    expect(audienceLine(demo)).toBe("3 customer-facing, 2 internal");
    // Nothing declared: nothing said.
    expect(audienceLine(firstRun)).toBe("");
    const newest = newestAgent(demo)!;
    expect(newest).toMatchObject({ name: "meridian-support", note: "moves money with no approval detected" });
    expect(newest.date).toMatch(/^2026-09-15/);
    expect(newestAgent(firstRun)).toBeNull();
  });

  it("reports approval only where the scanner observed it", () => {
    const p = protection(demo);
    expect(p).toMatchObject({ moneyMovers: 2, approved: 0, moneyTools: 8, moneyToolsWithoutGuardrail: 8, doublePost: 1 });
    // Human approval detected on any record of a money mover is credited to that agent.
    const credited = structuredClone(demo);
    const mover = moneyMovers(credited)[0]!;
    mover.records[0]!.dimension_assessment!.dimensions[0]!.controls_observed.push("approval");
    expect(protection(credited).approved).toBe(1);
    // A guardrail detected on a money tool, in either record, counts.
    const guarded = structuredClone(demo);
    moneyMovers(guarded)[0]!.records.flatMap((a) => a.tools ?? []).find((t) => t.money_action)!.guards.push("approval_check");
    expect(protection(guarded).moneyToolsWithoutGuardrail).toBe(7);
  });

});

describe("risk mapping", () => {
  it("places every agent on the spectrum by its highest dimension score, the new one marked", () => {
    const rows = agentSpectrum(demo);
    expect(rows.map((r) => [r.name, r.score, r.level, r.isNew])).toEqual([
      ["meridian-support", 58, "elevated", true],
      ["account-actions", 58, "elevated", false],
      ["meridian-escalation", 18, "low", false],
      ["meridian-front", 18, "low", false],
      ["meridian-knowledge", 18, "low", false],
    ]);
    // The scanner's own buckets, so the bands on the line are where its levels change.
    expect(SPECTRUM_BANDS).toEqual({ moderate: 25, elevated: 55 });
    for (const r of rows) expect(r.score).toBe(Math.max(...demo.registry.agents.filter((a) => a.id === r.id).flatMap((a) => a.dimension_assessment!.dimensions.map((d) => d.score))));
    expect(agentSpectrum(firstRun).every((r) => !r.isNew)).toBe(true);
    expect(agentSpectrum(empty)).toEqual([]);
  });

  it("lists each high-severity finding once, naming its agents", () => {
    const lines = highLines(demo);
    expect(lines).toHaveLength(countByLevel(activeFindings(demo)).high);
    expect(lines.map((l) => [l.agents.join(","), l.isNew])).toEqual([["account-actions", false], ["meridian-support", true], ["account-actions,meridian-support", false]]);
    expect(lines.map((l) => l.title)).toEqual([PLAIN_TITLE["DECL001"], PLAIN_TITLE["DECL001"], PLAIN_TITLE["AI008"]]);
    expect(newHighLine(demo)).toBe("+1 high since last scan (meridian-support)");
    expect(newHighLine(firstRun)).toBe("");
    expect(highLines(empty)).toEqual([]);
  });
});

describe("what it could cost", () => {
  it("gives a figure only when the business context is declared", () => {
    expect(costOutlook(firstRun)).toBeNull();
    expect(costOutlook(empty)).toBeNull();
    const cost = costOutlook(demo, 4000)!;
    expect(cost.badYear).toBeGreaterThan(cost.averageYear);
    expect(cost.averageYear).toBeGreaterThan(0);
    expect(cost).toMatchObject({ covered: 0, excluding: ["cyber"], policies: 1, limits: [{ label: "cyber policy limit", limit: 5e6, aiExcluded: true }], capacity: 4e6 });
    // At the full simulation length (what the screens run) the bad year now sits above the declared risk capacity; the earlier scans did not.
    const full = costOutlook(demo)!;
    expect(full.trend[0]!.badYear).toBeLessThan(full.capacity!);
    expect(full.badYear).toBeGreaterThan(full.capacity!);
    const undeclared = structuredClone(demo);
    delete undeclared.intake!.risk_capacity;
    expect(costOutlook(undeclared, 2000)!.capacity).toBeNull();
    expect(cost.agent).toBe("account-actions");
    // The trend: one point per past scan, ending at today's figure, and it rose when the cap came off and the chatbot arrived.
    expect(cost.trend.map((p) => p.ref)).toEqual(["a1b2c3d", "b7c8d9e", "e4f5a6b"]);
    expect(cost.trend[2]!.badYear).toBe(cost.badYear);
    expect(cost.trend[0]!.badYear).toBeLessThan(cost.badYear);
    expect(cost.trend[2]!.added).toEqual(["meridian-support"]);
  });

  it("is deterministic", () => {
    expect(costOutlook(demo, 2000)).toEqual(costOutlook(demo, 2000));
  });

  it("counts only policies that do not exclude AI as cover", () => {
    const covered = structuredClone(demo);
    covered.intake!.existing_coverage = [{ type: "cyber", limit: 5e6, ai_exclusion: true }, { type: "tech_eo", limit: 2e6, ai_exclusion: false }];
    expect(costOutlook(covered, 2000)).toMatchObject({ covered: 2e6, excluding: ["cyber"], policies: 2, limits: [{ limit: 5e6 }, { limit: 2e6 }] });
  });
});

describe("needs your attention", () => {
  it("shows each problem once, highest severity first", () => {
    const items = attention(demo, 99);
    expect(new Set(items.map((i) => i.ruleId)).size).toBe(items.length);
    expect(items.reduce((n, i) => n + i.findings, 0)).toBe(activeFindings(demo).length);
    const rank = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
    for (let i = 1; i < items.length; i++) expect(rank[items[i - 1]!.severity]).toBeGreaterThanOrEqual(rank[items[i]!.severity]);
    expect(attention(demo)).toHaveLength(3);
    expect(attention(empty)).toEqual([]);
  });

  it("names the agents in the title, a dimension the finding sits in, and the register decision", () => {
    const [first, second] = attention(demo);
    expect(first!.title).toBe("Declared autonomy does not match what the code does.");
    expect(first!.agents).toEqual(["account-actions", "meridian-support"]);
    expect(attentionTitle(first!)).toBe("account-actions and meridian-support: declared autonomy does not match what the code does.");
    expect(first!.findings).toBe(2);
    expect(attentionStatus(first!)).toContain("1 marked for transfer");
    expect(second!.ruleId).toBe("AI008");
    expect(second!.refs[0]!.finding.dimensions).toContain(second!.dimension === "Control coverage gap" ? "control-coverage-gap" : "unreviewed-high-impact-action");
    expect(elevatedDimensions(demo).map((d) => d.name)).toContain(first!.dimension);
    // Account actions in code and on AWS: one agent in the title, two records behind it.
    const twin = attention(twoStacks)[0]!;
    expect(twin.ruleId).toBe("DECL001");
    expect(twin.agents).toEqual(["account-actions", "meridian-support"]);
    expect(twin.findings).toBe(2);
  });

  it("says what the scan saw, why it matters, and the fix, in plain words", () => {
    const items = attention(demo);
    const by = (rule: string) => items.find((i) => i.ruleId === rule)!;
    expect(scanSaw(by("DECL001"))).toBe("Declared: acts after human approval. In the code: acts on its own, with 4 tools that can move money and no approval step detected.");
    expect(scanSaw(by("AI008"))).toBe("issue_refund is retried on failure with no unique reference per request, in tools/account_tools.py, line 17. Both agents call it.");
    expect(scanSaw(by("DECL005"))).toBe("Both agents are declared production, but no logging or tracing was found in their code.");
    for (const item of attention(demo, 99)) {
      expect(whyItMatters(item)).toBe(PLAIN_WHY[item.ruleId]);
      expect(scanSaw(item)).not.toContain("`");
      expect(scanSaw(item)).not.toContain("—");
    }
    // A rule with no template falls back to the scanner's first sentence.
    const other = { ...by("AI008"), ruleId: "XX999" };
    expect(scanSaw(other)).toBe("issue_refund posts a money action and is retried on failure (retry (via _post_refund)); no idempotency key or dedupe check was observed.");
  });

  it("says what the register says, and nothing when it says nothing", () => {
    for (const item of attention(demo, 99)) {
      const decided = item.register.filter((row) => row.declared?.treatment).length;
      if (decided) expect(attentionStatus(item)).toMatch(/^\d+ /);
      else expect(attentionStatus(item)).toBe("");
      for (const row of item.register) expect(demo.register).toContain(row);
    }
  });

  it("takes the next action from the rule's own remediation: the instruction, not the scene-setting", () => {
    const items = [...attention(demo, 99), ...attention(firstRun, 99)];
    for (const item of items) {
      const action = nextAction(item);
      expect(action.length).toBeGreaterThan(0);
      expect(action).not.toContain("—");
      // Plain words where they exist; otherwise verbatim from the scanner's guidance.
      if (!PLAIN_ACTION[item.ruleId]) expect((demo.rules[item.ruleId]?.remediation ?? "").replace(/\s*(?:—|\s--\s)\s*/g, ": ")).toContain(action);
    }
    const by = (rule: string) => nextAction(items.find((i) => i.ruleId === rule)!);
    expect(by("DECL001")).toBe("Add the approval step, or correct the declaration.");
    expect(by("CTRL007")).toMatch(/^Add a setting or feature flag/);
    expect(by("AI008")).toBe("Give each payment request a unique reference so a retry cannot charge it again, and apply limits per request rather than per attempt.");
  });
});

describe("what changed", () => {
  it("is null without a baseline", () => {
    expect(whatChanged(firstRun)).toBeNull();
    expect(whatChanged(empty)).toBeNull();
  });

  it("tells the September push in three lines: who arrived, what an existing agent lost, what it did to the loss", () => {
    const cost = costOutlook(demo, 4000);
    const lines = whatChanged(demo, cost)!;
    expect(lines.map((l) => l.direction)).toEqual(["up", "up", "up"]);
    expect(lines[0]).toEqual({ direction: "up", title: "1 agent added: meridian-support.", detail: "meridian-support can move money." });
    // From the history: bounded in August, unrestricted in September. The declared limit rose in the same push, so it is not a second line.
    expect(lines[1]!.title).toBe("account-actions lost its amount cap.");
    expect(lines[1]!.detail).toBe("Every action was limited in code; now the only limit is the $500 written in the system prompt.");
    expect(lines[2]!.title).toMatch(/^Modeled loss in a bad year: \$[\d.]+[kM] to \$[\d.]+[kM]\.$/);
    expect(lines[2]!.detail).toBe("1 new high-severity finding. 2 of 5 agents are elevated.");
    // Without the cost outlook the third line still says what the findings say.
    expect(whatChanged(demo)![2]).toEqual({ direction: "up", title: "1 new high-severity finding.", detail: "2 of 5 agents are elevated." });
    const joined = lines.map((l) => `${l.title} ${l.detail}`).join(" ");
    expect(joined).not.toMatch(/follow from|because|caused/i);
  });

  it("reads a capability gained from the diff when the history says nothing", () => {
    // Account actions on AWS got its action group: database and email reach on an agent already there.
    const lines = whatChanged(twoStacks)!;
    expect(lines[0]!.title).toBe("No agents added or removed.");
    expect(lines[1]!.direction).toBe("up");
    expect(`${lines[1]!.title} ${lines[1]!.detail}`).toContain("account-actions gained database write access");
  });

  it("reads as unchanged when nothing changed", () => {
    const quiet = structuredClone(demo);
    quiet.diff!.agents.changed = [];
    quiet.diff!.agents.added = [];
    quiet.diff!.summary = { ...quiet.diff!.summary, agents_added: 0, agents_changed: 0, findings_delta: { new_critical: 0, new_high: 0, resolved: 0 } };
    quiet.history = [quiet.history[quiet.history.length - 1]!];
    const lines = whatChanged(quiet)!;
    expect(lines.map((l) => l.direction)).toEqual(["same", "same", "same"]);
    expect(lines.map((l) => l.title)).toEqual(["No agents added or removed.", "No existing agent gained reach.", "No new high-severity findings."]);
  });
});

describe("where you stand", () => {
  const text = (env: Envelope, years?: number) => standing(env, costOutlook(env, years)).map(sentenceText).join(" ");

  it("is one sentence: the rise, the push and what went live", () => {
    const t = text(demo, 4000);
    expect(t).toMatch(/^Modeled loss in a bad year has risen from \$[\d.]+[kM] to \$[\d.]+[kM] in two months, driven by one push in September: meridian-support went live\.$/);
  });

  it("says less when the line did not move, or nothing went live", () => {
    const flat = structuredClone(demo);
    flat.history = flat.history.slice(-1);
    expect(text(flat, 2000)).toMatch(/^Modeled loss in a bad year is \$[\d.]+[kM]\.$/);
    // Two-stacks: the line rose but nothing went live and no cap came off, so no cause is named.
    expect(text(twoStacks, 2000)).toMatch(/^Modeled loss in a bad year has risen from \$[\d.]+[kM] to \$[\d.]+[kM] in four weeks, driven by one push in September\.$/);
    // Nothing went live but a cap came off: that is the cause.
    const capOnly = structuredClone(demo);
    capOnly.diff!.agents.added = [];
    for (const h of capOnly.history) h.agents = h.agents!.filter((a) => a.id !== "bc3db1f17013");
    capOnly.registry.agents = capOnly.registry.agents.filter((a) => a.id !== "bc3db1f17013");
    capOnly.unique_agents = capOnly.unique_agents!.filter((u) => u.name !== "meridian-support");
    expect(text(capOnly, 2000)).toMatch(/driven by one push in September: the amount cap on account-actions came off\.$/);
  });

  it("leaves out every clause it has no fact for", () => {
    const t = text(firstRun);
    expect(t).toBe("2 agents can move money on their own, and no human approval was detected on either.");
    expect(text(empty)).toContain("No AI agents were found");
  });

  it("agrees in number", () => {
    const one = structuredClone(firstRun);
    const keep = moneyMovers(one)[0]!.id;
    for (const a of one.registry.agents) if (a.id !== keep) { a.tools = []; a.capabilities = a.capabilities.filter((c) => c !== "payment_access"); }
    expect(text(one)).toBe("1 agent can move money on its own, and no human approval was detected on it.");
    const none = structuredClone(one);
    for (const a of none.registry.agents) { a.tools = []; a.capabilities = []; }
    expect(text(none)).toMatch(/^5 AI agents found, none of which can move money\. 1 high-severity finding needs attention\.$/);
  });

  it("counts a span in the unit that reads well", () => {
    expect(spanWords("2026-07-21T09:12:44+00:00", "2026-09-15T16:45:02+00:00")).toBe("two months");
    expect(spanWords("2026-09-01T00:00:00+00:00", "2026-09-22T00:00:00+00:00")).toBe("three weeks");
    expect(spanWords("2026-09-20T00:00:00+00:00", "2026-09-22T00:00:00+00:00")).toBe("two days");
  });
});

describe("register and helpers", () => {
  it("counts live risks apart from a stale declaration", () => {
    const r = registerCard(demo);
    expect(r.risks + r.stale).toBe(demo.register.length);
    expect(r.decided + r.awaiting).toBe(r.risks);
    expect(r.stale).toBe(1);
    // Whatever treatments the register holds, as it holds them.
    expect(Object.fromEntries(r.treatments)).toEqual({ transfer: 1, mitigate: 1 });
    expect(otherDimensionsLine(demo)).toBe("The other 7 dimensions are moderate or lower.");
    expect(registerCard(empty)).toMatchObject({ risks: 0, awaiting: 0 });
  });

  it("joins words", () => {
    expect([joinWords([]), joinWords(["a"]), joinWords(["a", "b"]), joinWords(["a", "b", "c"])]).toEqual(["", "a", "a and b", "a, b and c"]);
  });
});
