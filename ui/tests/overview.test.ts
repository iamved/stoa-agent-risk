/**
 * The Overview states facts in sentences, so each one is pinned to the scan
 * it came from: a figure the fixture does not support must never appear.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { attention, attentionRegisterRow, attentionStatus, costOutlook, elevatedDimensions, holdings, joinWords, moneyMovers, protection, registerCard, scanSources, sentenceText, standing, whatChanged } from "../src/data/overview";
import { activeFindings } from "../src/data/selectors";

const load = (name: string) => JSON.parse(readFileSync(new URL(`../fixtures/${name}.envelope.json`, import.meta.url), "utf8")) as Envelope;
const demo = load("meridian-pay");
const firstRun = load("first-run");
const empty = load("no-agents");

describe("what we have and whether it is protected", () => {
  it("counts what the registry holds", () => {
    const h = holdings(demo);
    // 5 agents seen as 11 records; account actions in code and on AWS is one money mover, not two.
    expect(h).toEqual({ agents: 5, records: demo.registry.agents.length, moneyMovers: 2, tools: 13, providers: 4 });
    expect(moneyMovers(demo).every((u) => u.records.some((a) => (a.tools ?? []).some((t) => t.money_action) || a.capabilities.includes("payment_access")))).toBe(true);
    expect(scanSources(demo)).toEqual(["application code", "AWS and Databricks definitions"]);
    expect(holdings(empty)).toEqual({ agents: 0, records: 0, moneyMovers: 0, tools: 0, providers: 0 });
    expect(scanSources(empty)).toEqual([]);
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

describe("what it could cost", () => {
  it("gives a figure only when the business context is declared", () => {
    expect(costOutlook(firstRun)).toBeNull();
    expect(costOutlook(empty)).toBeNull();
    const cost = costOutlook(demo, 4000)!;
    expect(cost.badYear).toBeGreaterThan(cost.averageYear);
    expect(cost.averageYear).toBeGreaterThan(0);
    expect(cost).toMatchObject({ covered: 0, excluding: ["cyber"], policies: 1 });
    expect(demo.registry.agents.map((a) => a.display_name || a.name)).toContain(cost.agent);
  });

  it("is deterministic", () => {
    expect(costOutlook(demo, 2000)).toEqual(costOutlook(demo, 2000));
  });

  it("counts only policies that do not exclude AI as cover", () => {
    const covered = structuredClone(demo);
    covered.intake!.existing_coverage = [{ type: "cyber", limit: 5e6, ai_exclusion: true }, { type: "tech_eo", limit: 2e6, ai_exclusion: false }];
    expect(costOutlook(covered, 2000)).toMatchObject({ covered: 2e6, excluding: ["cyber"], policies: 2 });
  });
});

describe("needs your attention", () => {
  it("shows each problem once, highest severity first", () => {
    const items = attention(demo, 99);
    expect(new Set(items.map((i) => i.ruleId)).size).toBe(items.length);
    expect(items.reduce((n, i) => n + i.findings, 0)).toBe(activeFindings(demo).length);
    const rank = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
    for (let i = 1; i < items.length; i++) expect(rank[items[i - 1]!.severity]).toBeGreaterThanOrEqual(rank[items[i]!.severity]);
    expect(attention(demo)).toHaveLength(4);
    expect(attention(empty)).toEqual([]);
  });

  it("names the elevated dimension and the register decision", () => {
    const [first, second] = attention(demo);
    expect(first!.title).toBe("Declared autonomy does not match what the code does.");
    // DECL001 fired on three records: account actions in code and on AWS (one agent), and the support agent.
    expect(first!.agents).toEqual(["account-actions", "meridian-support (Databricks)"]);
    expect(first!.findings).toBe(2);
    expect(attentionStatus(first!)).toContain("marked for transfer to insurance");
    expect(attentionRegisterRow(first!)?.declared?.owner ?? null).toBeNull();
    expect(second!.ruleId).toBe("AI008");
    expect(second!.dimension).toBe("Unreviewed high-impact action");
    expect(elevatedDimensions(demo).map((d) => d.name)).toContain(second!.dimension);
  });

  it("offers a register row only where the finding feeds one", () => {
    for (const item of attention(demo, 99)) {
      const row = attentionRegisterRow(item);
      if (row) expect(demo.register).toContain(row);
      else expect(attentionStatus(item)).toBe("Open");
    }
  });
});

describe("what changed", () => {
  it("is null without a baseline", () => {
    expect(whatChanged(firstRun)).toBeNull();
    expect(whatChanged(empty)).toBeNull();
  });

  it("states the diff, and nothing the diff does not say", () => {
    const lines = whatChanged(demo)!;
    expect(lines.map((l) => l.direction)).toEqual(["up", "up", "up", "same"]);
    expect(lines[0]!.title).toBe("One more agent can now move money.");
    expect(lines[0]!.detail).toContain("gained payment access");
    // The fixture was scanned without git: no commit or author is invented.
    expect(lines[0]!.detail).not.toMatch(/ in [0-9a-f]{7}|changed by/);
    // The diff reports two new records. One is a new finding; the other is a second location on a known one.
    expect(lines[1]!.title).toBe("1 new high-severity finding.");
    expect(lines[1]!.detail).toContain("1 known high-severity finding now has a second evidence location.");
    expect(lines[3]!.title).toBe("No agents added or removed.");
    const joined = lines.map((l) => `${l.title} ${l.detail}`).join(" ");
    expect(joined).not.toMatch(/follow from|because|caused/i);
  });

  it("adds the commit and author when the scan had git", () => {
    const withGit = structuredClone(demo);
    const changedId = withGit.diff!.agents.changed[0]!.agent_id;
    const agent = withGit.registry.agents.find((a) => a.id === changedId)!;
    agent.last_commit = { hash: "abcdef1234567", date: "2026-09-14T10:00:00+00:00" };
    agent.last_touched_by = "Sam Lee";
    expect(whatChanged(withGit)![0]!.detail).toContain("in abcdef1, last changed by Sam Lee");
  });

  it("reads as unchanged when nothing changed", () => {
    const quiet = structuredClone(demo);
    quiet.diff!.agents.changed = [];
    quiet.diff!.summary = { ...quiet.diff!.summary, agents_changed: 0, findings_delta: { new_critical: 0, new_high: 0, resolved: 0 } };
    expect(whatChanged(quiet)!.every((l) => l.direction === "same")).toBe(true);
  });
});

describe("where you stand", () => {
  const text = (env: Envelope, years?: number) => standing(env, costOutlook(env, years)).map(sentenceText).join(" ");

  it("builds the demo headline from the facts above", () => {
    const t = text(demo, 4000);
    expect(t).toContain("2 agents can move money on their own, and neither requires human approval.");
    expect(t).toMatch(/A bad year could cost \$[\d.]+[kM], and your cyber policy excludes AI\./);
    expect(t).toContain("3 things changed since the last scan.");
  });

  it("leaves out every clause it has no fact for", () => {
    const t = text(firstRun);
    expect(t).toBe("2 agents can move money on their own, and neither requires human approval.");
    expect(text(empty)).toContain("No AI agents were found");
  });

  it("agrees in number", () => {
    const one = structuredClone(firstRun);
    const keep = moneyMovers(one)[0]!.id;
    for (const a of one.registry.agents) if (a.id !== keep) { a.tools = []; a.capabilities = a.capabilities.filter((c) => c !== "payment_access"); }
    expect(text(one)).toBe("1 agent can move money on its own, and it does not require human approval.");
    const none = structuredClone(one);
    for (const a of none.registry.agents) { a.tools = []; a.capabilities = []; }
    expect(text(none)).toMatch(/^11 AI agents found, and none can move money\. 1 high-severity finding needs attention\.$/);
  });
});

describe("register and helpers", () => {
  it("counts live risks apart from a stale declaration", () => {
    const r = registerCard(demo);
    expect(r.risks + r.stale).toBe(demo.register.length);
    expect(r.decided + r.awaiting).toBe(r.risks);
    expect(r).toMatchObject({ transfer: 1, stale: 1 });
    expect(registerCard(empty)).toMatchObject({ risks: 0, awaiting: 0 });
  });

  it("joins words", () => {
    expect([joinWords([]), joinWords(["a"]), joinWords(["a", "b"]), joinWords(["a", "b", "c"])]).toEqual(["", "a", "a and b", "a, b and c"]);
  });
});
