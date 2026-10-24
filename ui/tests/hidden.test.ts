import { describe, expect, it } from "vitest";
import { hiddenNav, screenHidden } from "../src/data/hidden";
import type { Envelope } from "../src/data/types";

const base = {} as Envelope;

describe("hidden screens", () => {
  it("is empty when the page hides nothing", () => {
    expect(hiddenNav(base).size).toBe(0);
    expect(screenHidden(base, "evidence")).toBe(false);
  });
  it("maps a sidebar id to every screen behind it", () => {
    const env = { ...base, hidden_screens: ["insurance", "risk"] } as Envelope;
    expect(screenHidden(env, "evidence")).toBe(true);
    expect(screenHidden(env, "drift")).toBe(true);
    expect(screenHidden(env, "loss")).toBe(false);
  });
  it("never hides Overview and ignores junk", () => {
    const env = { ...base, hidden_screens: ["overview", 3, null] } as unknown as Envelope;
    expect(screenHidden(env, "overview")).toBe(false);
    expect(hiddenNav(env).size).toBe(0);
  });
});
