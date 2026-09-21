/**
 * Opening a scan from disk: the one path where the envelope does not come
 * straight from the Python builder, so it is the one path that is validated.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { embeddedJson, envelopeFromText, shapeProblem } from "../src/data/file";

const read = (name: string) => readFileSync(new URL(`../fixtures/${name}`, import.meta.url), "utf8");
const FIXTURES = ["meridian-pay", "hostile", "first-run", "no-agents"];

describe("envelopeFromText", () => {
  it("opens every fixture the scanner produces", () => {
    for (const name of FIXTURES) {
      const result = envelopeFromText(read(`${name}.envelope.json`));
      expect("envelope" in result, name).toBe(true);
    }
  });

  it("lifts the data out of a stoa-dashboard.html", () => {
    const json = read("first-run.envelope.json").replace(/</g, "\\u003c");
    const html = `<!doctype html><html><head><script>boot()</script></head><body><script id="stoa-data" type="application/json">${json}</script><script type="module">app()</script></body></html>`;
    const result = envelopeFromText(html);
    expect("envelope" in result && result.envelope.registry.repository.name).toBe("acme-support");
  });

  it("tells a raw registry apart and says how to build the data", () => {
    const result = envelopeFromText(read("meridian-pay.baseline.json"));
    expect("problem" in result && result.problem.message).toContain("stoa-registry.json");
    expect("problem" in result && result.problem.message).toContain("--json-out");
  });

  it("rejects what it cannot read without throwing", () => {
    for (const text of ["", "   ", "not json", "[1,2]", "null", '"text"', "<html><body>hi</body></html>", '{"schema":"stoa-dashboard/9.0","registry":{"schema_version":"1.0"}}']) {
      expect("problem" in envelopeFromText(text), JSON.stringify(text)).toBe(true);
    }
  });

  it("rejects an envelope with a part missing, naming the part", () => {
    const full = JSON.parse(read("first-run.envelope.json")) as Record<string, unknown>;
    for (const key of ["registry", "register", "graph", "assessment", "rules", "taxonomy", "history"]) {
      const { [key]: _dropped, ...rest } = full;
      const result = envelopeFromText(JSON.stringify(rest));
      expect("problem" in result, key).toBe(true);
    }
    const broken = { ...full, registry: { ...(full["registry"] as object), agents: "nope" } };
    expect(shapeProblem(broken)).toBe("registry.agents");
  });
});

describe("embeddedJson", () => {
  it("returns null for html without a data block", () => {
    expect(embeddedJson("<html></html>")).toBeNull();
    expect(embeddedJson('<script id="stoa-data" type="application/json">{"unterminated":1}')).toBeNull();
  });
});
