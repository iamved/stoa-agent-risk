/**
 * The loss model is deterministic (one seed, the same inputs), so every
 * figure is computed once per loaded scan and kept. Keyed by the envelope
 * object, so opening another scan starts clean, and by the inputs that
 * change the answer. `warmLoss` runs the heavy computations after the first
 * paint, so the Financial Exposure screen opens with its figures ready.
 */
import type { Envelope } from "./types";
import { agentToModel, candidateAgents, intakeFromEnvelope } from "./lossInputs";
import { EVENTS, indicate, whatIfs, type Indication, type Intake, type ModelAgent, type WhatIf } from "./lossModel";

const store = new WeakMap<Envelope, Map<string, unknown>>();

export function cached<T>(env: Envelope, key: string, compute: () => T): T {
  let bucket = store.get(env);
  if (!bucket) { bucket = new Map(); store.set(env, bucket); }
  if (bucket.has(key)) return bucket.get(key) as T;
  const value = compute();
  bucket.set(key, value);
  return value;
}

/** The full indication (with its bootstrap band) and the levers for one model and intake, as the Financial Exposure screen shows them. */
export function indicationFor(env: Envelope, model: ModelAgent, intake: Intake, seed: number): { r: Indication; levers: WhatIf[] } {
  return cached(env, `indication:${seed}:${JSON.stringify(model)}:${JSON.stringify(intake)}`, () => {
    const r = indicate(EVENTS, model, intake, seed);
    return { r, levers: whatIfs(model, intake, seed, r) };
  });
}

/**
 * Compute what the Financial Exposure screen will ask for first, in idle time.
 * Safe to call more than once; each piece is computed at most once per scan.
 */
export function warmLoss(env: Envelope, seed: number, trend: () => unknown): void {
  const idle = (fn: () => void) => (typeof window !== "undefined" && "requestIdleCallback" in window ? (window as Window & { requestIdleCallback: (cb: () => void) => void }).requestIdleCallback(fn) : setTimeout(fn, 200));
  idle(() => {
    const { intake, monthlyVolume } = intakeFromEnvelope(env);
    const agents = candidateAgents(env);
    const first = agents[0];
    if (first) indicationFor(env, agentToModel(env, first, monthlyVolume).model, intake, seed);
    idle(() => {
      trend();
      // The other agents, one per idle slot, so switching the agent on the screen is instant too.
      const rest = agents.slice(1);
      const next = () => { const a = rest.shift(); if (!a) return; indicationFor(env, agentToModel(env, a, monthlyVolume).model, intake, seed); idle(next); };
      idle(next);
    });
  });
}
