import type { Envelope } from "./types";
import type { SchemaProblem } from "./schema";

/**
 * Every screen reads through this interface and nothing else. Phase 1 has one
 * implementation (`EmbeddedProvider`, the script tag); a hosted deployment
 * adds an `ApiProvider` without touching a screen.
 */
export interface DataProvider {
  /** Resolve the envelope, or a schema problem the shell renders as an error screen. */
  load(): Promise<{ envelope: Envelope } | { problem: SchemaProblem }>;
}
