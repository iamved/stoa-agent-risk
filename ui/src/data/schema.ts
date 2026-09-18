/**
 * Startup compatibility check. The envelope and the registry each carry a
 * version; a major we do not understand gets a friendly error screen, never a
 * half-rendered page. Minor bumps are additive by policy (SCHEMA.md) and are
 * accepted.
 */

export const SUPPORTED_ENVELOPE_MAJOR = 1;
export const SUPPORTED_REGISTRY_MAJOR = 1;

export interface SchemaProblem {
  kind: "missing" | "malformed" | "unsupported";
  message: string;
  found: string | null;
  expected: string;
}

export function parseMajor(version: unknown, prefix?: string): number | null {
  if (typeof version !== "string") return null;
  const bare = prefix && version.startsWith(prefix) ? version.slice(prefix.length) : version;
  const match = /^(\d+)\.(\d+)/.exec(bare);
  if (!match || match[1] === undefined) return null;
  return Number.parseInt(match[1], 10);
}

export function checkEnvelope(data: unknown): SchemaProblem | null {
  if (data === null || typeof data !== "object") {
    return { kind: "missing", message: "No scan data was embedded in this page.", found: null, expected: "stoa-dashboard/1.x" };
  }
  const env = data as { schema?: unknown; registry?: { schema_version?: unknown } };
  const envMajor = parseMajor(env.schema, "stoa-dashboard/");
  if (envMajor === null) {
    return { kind: "malformed", message: "The embedded data does not declare a dashboard schema.", found: typeof env.schema === "string" ? env.schema : null, expected: "stoa-dashboard/1.x" };
  }
  if (envMajor !== SUPPORTED_ENVELOPE_MAJOR) {
    return { kind: "unsupported", message: `This page was generated for dashboard schema major ${envMajor}; this build understands ${SUPPORTED_ENVELOPE_MAJOR}.`, found: String(env.schema), expected: "stoa-dashboard/1.x" };
  }
  const regMajor = parseMajor(env.registry?.schema_version);
  if (regMajor === null) {
    return { kind: "malformed", message: "The embedded registry does not declare a schema version.", found: null, expected: "1.x" };
  }
  if (regMajor !== SUPPORTED_REGISTRY_MAJOR) {
    return { kind: "unsupported", message: `The embedded registry is schema major ${regMajor}; this build understands ${SUPPORTED_REGISTRY_MAJOR}.`, found: String(env.registry?.schema_version), expected: "1.x" };
  }
  return null;
}
