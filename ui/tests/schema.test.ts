import { describe, expect, it } from "vitest";
import { checkEnvelope, parseMajor } from "../src/data/schema";
import { EmbeddedProvider } from "../src/data/embedded";

describe("schema check", () => {
  it("parses majors with and without a prefix", () => {
    expect(parseMajor("1.8")).toBe(1);
    expect(parseMajor("stoa-dashboard/1.0", "stoa-dashboard/")).toBe(1);
    expect(parseMajor("stoa-dashboard/2.3", "stoa-dashboard/")).toBe(2);
    expect(parseMajor(12)).toBeNull();
    expect(parseMajor("v1")).toBeNull();
  });

  it("accepts a 1.x envelope over a 1.x registry", () => {
    expect(checkEnvelope({ schema: "stoa-dashboard/1.0", registry: { schema_version: "1.8" } })).toBeNull();
    expect(checkEnvelope({ schema: "stoa-dashboard/1.4", registry: { schema_version: "1.12" } })).toBeNull();
  });

  it("rejects other majors and malformed input", () => {
    expect(checkEnvelope({ schema: "stoa-dashboard/2.0", registry: { schema_version: "1.8" } })?.kind).toBe("unsupported");
    expect(checkEnvelope({ schema: "stoa-dashboard/1.0", registry: { schema_version: "2.0" } })?.kind).toBe("unsupported");
    expect(checkEnvelope({ registry: {} })?.kind).toBe("malformed");
    expect(checkEnvelope(null)?.kind).toBe("missing");
    expect(checkEnvelope("x")?.kind).toBe("missing");
  });
});

describe("EmbeddedProvider", () => {
  it("returns the envelope when the tag holds a supported document", async () => {
    const provider = new EmbeddedProvider(() => JSON.stringify({ schema: "stoa-dashboard/1.0", registry: { schema_version: "1.8", agents: [] } }));
    const result = await provider.load();
    expect("envelope" in result && result.envelope.registry.schema_version).toBe("1.8");
  });

  it("reports a missing or broken tag as a problem, never a throw", async () => {
    expect(await new EmbeddedProvider(() => null).load()).toMatchObject({ problem: { kind: "missing" } });
    expect(await new EmbeddedProvider(() => "   ").load()).toMatchObject({ problem: { kind: "missing" } });
    expect(await new EmbeddedProvider(() => "{not json").load()).toMatchObject({ problem: { kind: "malformed" } });
    expect(await new EmbeddedProvider(() => JSON.stringify({ schema: "stoa-dashboard/3.0", registry: { schema_version: "1.8" } })).load()).toMatchObject({ problem: { kind: "unsupported" } });
  });

  it("survives escaped separators and closing tags inside the JSON", async () => {
    const hostile = JSON.stringify({ schema: "stoa-dashboard/1.0", registry: { schema_version: "1.8", warnings: ["</script><script>alert(1)</script>\u2028\u2029"] } })
      .replace(/</g, "\\u003c").replace(/>/g, "\\u003e").replace(/\u2028/g, "\\u2028").replace(/\u2029/g, "\\u2029");
    const result = await new EmbeddedProvider(() => hostile).load();
    expect("envelope" in result && (result.envelope.registry.warnings as string[])[0]).toBe("</script><script>alert(1)</script>\u2028\u2029");
  });
});
