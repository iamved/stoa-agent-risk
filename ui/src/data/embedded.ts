import type { DataProvider } from "./provider";
import type { Envelope } from "./types";
import { checkEnvelope } from "./schema";

export const DATA_ELEMENT_ID = "stoa-data";

/**
 * Reads the envelope the Python injector placed in
 * `<script id="stoa-data" type="application/json">`. This is the only module
 * allowed to touch that element or `document` for data.
 *
 * A JSON script tag never executes, and the injector escapes `<`, `>`, `&`,
 * U+2028 and U+2029 as `\uXXXX` so no snippet can close the tag early.
 */
export class EmbeddedProvider implements DataProvider {
  constructor(private readonly readText: () => string | null = defaultReader) {}

  async load(): Promise<{ envelope: Envelope } | { problem: import("./schema").SchemaProblem }> {
    const text = this.readText();
    if (text === null || text.trim() === "") {
      return { problem: { kind: "missing", message: "No scan data was embedded in this page.", found: null, expected: "stoa-dashboard/1.x" } };
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch {
      return { problem: { kind: "malformed", message: "The embedded scan data is not valid JSON.", found: null, expected: "stoa-dashboard/1.x" } };
    }
    const problem = checkEnvelope(parsed);
    if (problem) return { problem };
    return { envelope: parsed as Envelope };
  }
}

function defaultReader(): string | null {
  if (typeof document === "undefined") return null;
  const element = document.getElementById(DATA_ELEMENT_ID);
  return element ? element.textContent : null;
}
