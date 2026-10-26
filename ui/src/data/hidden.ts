/**
 * Screens a page leaves out (`stoa dashboard --hide`). The list holds sidebar
 * ids; a route whose screen belongs to a hidden entry falls back to Overview.
 */
import type { ScreenId } from "../app/router";
import type { Envelope } from "./types";

export type NavId = "overview" | "inventory" | "scope" | "scanner" | "risk" | "controls" | "runtime" | "detectr" | "register" | "policies" | "passports" | "audit" | "loss" | "insurance";

export const NAV_SCREENS: Record<NavId, ScreenId[]> = {
  overview: ["overview"],
  inventory: ["inventory"],
  scope: ["scope"],
  scanner: ["findings", "drift"],
  // "risk" was the sidebar id before the Risk Scanner split; kept so older --hide flags still work.
  risk: ["findings", "drift"],
  controls: ["controls"],
  runtime: ["runtime"],
  detectr: ["detectr"],
  register: ["register"],
  policies: ["policies"],
  passports: ["passports"],
  audit: ["audit"],
  loss: ["loss"],
  insurance: ["evidence"],
};

export function hiddenNav(envelope: Envelope): Set<string> {
  const list = Array.isArray(envelope.hidden_screens) ? envelope.hidden_screens : [];
  // Overview is the fallback, so it can never be hidden.
  return new Set(list.filter((id) => typeof id === "string" && id !== "overview"));
}

export function screenHidden(envelope: Envelope, screen: ScreenId): boolean {
  const hidden = hiddenNav(envelope);
  return (Object.keys(NAV_SCREENS) as NavId[]).some((nav) => hidden.has(nav) && NAV_SCREENS[nav].includes(screen));
}
