/**
 * Rules for UI copy: no em dashes, and never the bare word "guard". Stoa says
 * "safeguard" for an agent-level control and "guardrail" for a tool-level check.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { DIMENSION_SUBTITLE } from "../src/data/labels";

const SRC = new URL("../src", import.meta.url).pathname;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? files(path) : /\.(tsx?|css)$/.test(name) ? [path] : [];
  });
}

/** Source with comments removed: what can reach the screen. */
function copy(path: string): string {
  return readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/.*$/gm, "$1");
}

describe("UI copy", () => {
  it("has no em dashes", () => {
    const hits = files(SRC).flatMap((path) => copy(path).split("\n").map((line, i) => (line.includes("—") ? `${path.replace(SRC, "src")}:${i + 1}` : "")).filter(Boolean));
    expect(hits).toEqual([]);
  });

  it("never says the bare word guard", () => {
    // `guards` as a data field (tool.guards, toolsWithGuardrail) is code, not copy.
    const bare = /(?<![.\w])[Gg]uards?(?![\w(:.=\[])/;
    const hits = files(SRC).flatMap((path) => copy(path).split("\n").map((line, i) => (bare.test(line) && !/^\s*(import|export (interface|type)|const|let|if|for|return [a-z]+\.)/.test(line) ? `${path.replace(SRC, "src")}:${i + 1}: ${line.trim().slice(0, 90)}` : "")).filter(Boolean));
    expect(hits).toEqual([]);
  });

  it("keeps all eight dimension names from the taxonomy and gives each a subtitle", () => {
    const env = JSON.parse(readFileSync(new URL("../fixtures/meridian-pay.envelope.json", import.meta.url), "utf8"));
    const names = env.taxonomy.dimensions.map((d: { name: string }) => d.name).sort();
    expect(names).toEqual(["Boundary leakage", "Conduct variability", "Control coverage gap", "Dependency drift", "Injection & tamper surface", "Mandate overreach", "Output fidelity", "Unreviewed high-impact action"]);
    for (const d of env.taxonomy.dimensions) expect(DIMENSION_SUBTITLE[d.id], d.id).toBeTruthy();
  });
});
