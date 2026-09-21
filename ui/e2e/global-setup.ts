import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

export const OUT_DIR = resolve(HERE, "out");
export const FIXTURES = ["meridian-pay", "hostile", "large", "first-run", "no-agents"] as const;

export function dashboardPath(name: string): string {
  return resolve(OUT_DIR, `${name}.html`);
}

/** Generate one dashboard per fixture through the real CLI. */
export default function globalSetup(): void {
  const stoa = process.env.STOA_BIN ?? "stoa";
  mkdirSync(OUT_DIR, { recursive: true });
  const inputs: [string, string][] = FIXTURES.map((name) => [name, resolve(HERE, "..", "fixtures", `${name}.envelope.json`)]);
  // A plain registry (no diff, no history): the empty states.
  inputs.push(["registry-only", resolve(HERE, "..", "fixtures", "meridian-pay.baseline.json")]);
  // The hosted demo is the same fixture marked as demo data; the JSON is what
  // a customer's `--json-out` gives them to open in it.
  const demo = spawnSync(stoa, ["dashboard", resolve(HERE, "..", "fixtures", "meridian-pay.envelope.json"), "--demo", "--out", dashboardPath("demo")], { stdio: "inherit", env: process.env });
  const json = spawnSync(stoa, ["dashboard", resolve(HERE, "..", "fixtures", "first-run.envelope.json"), "--json-out", resolve(OUT_DIR, "first-run.json"), "--out", dashboardPath("first-run-copy")], { stdio: "inherit", env: process.env });
  if (demo.status !== 0 || json.status !== 0) throw new Error(`${stoa} dashboard failed for the demo page`);
  for (const [name, fixture] of inputs) {
    if (!existsSync(fixture)) {
      throw new Error(`fixture missing: ${fixture} (run ui/fixtures/build.py)`);
    }
    const result = spawnSync(stoa, ["dashboard", fixture, "--out", dashboardPath(name), "--root", resolve(HERE, "out")], {
      stdio: "inherit",
      env: process.env,
    });
    if (result.status !== 0) {
      throw new Error(`${stoa} dashboard failed for ${name} (exit ${result.status})`);
    }
  }
}
