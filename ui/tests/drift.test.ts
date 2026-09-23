import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { Envelope } from "../src/data/types";
import { changes, groupChanges } from "../src/data/drift";

// two-stacks: account actions on AWS gained its action group, a real authority increase in the diff.
const env = JSON.parse(readFileSync(new URL("../fixtures/two-stacks.envelope.json", import.meta.url), "utf8")) as Envelope;

describe("drift grouping copies the diff", () => {
  it("surfaces the payment authority increase first and flags it for review", () => {
    const items = changes(env);
    expect(items.length).toBeGreaterThan(0);
    const first = items[0]!;
    expect(first.needsReview).toBe(true);
    // The AWS account-actions record got its tools: high-impact capabilities, unapproved.
    const cap = items.find((c) => c.kind === "capability_added" && c.label === "database_write")!;
    expect(cap.severity).toBe("high");
    expect(cap.authorityIncrease).toBe(true);
    expect(cap.approved).toBe(false);
    expect(items.some((c) => c.kind === "finding_new" && c.fingerprint)).toBe(true);
  });

  it("groups in reviewer order", () => {
    const groups = groupChanges(changes(env));
    expect(groups[0]!.kind).toBe("capability_added");
    expect(groups.every((g) => g.items.length > 0)).toBe(true);
  });

  it("is empty without a diff", () => {
    expect(changes({ ...env, diff: null })).toEqual([]);
  });
});
