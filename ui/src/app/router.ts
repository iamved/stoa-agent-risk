/**
 * Hash routing so deep links survive `file://` and email:
 *   #/overview
 *   #/findings?severity=high&dimension=mandate-overreach
 *   #/findings/<fingerprint>
 *   #/inventory/<agent-id>
 */
import { useEffect, useState } from "react";

export type ScreenId = "overview" | "inventory" | "scope" | "findings" | "drift" | "register" | "controls" | "audit" | "loss" | "evidence";
export const SCREENS: ScreenId[] = ["overview", "inventory", "scope", "findings", "drift", "register", "controls", "audit", "loss", "evidence"];
/** Older or friendlier paths that resolve to a screen. */
const ALIASES: Record<string, ScreenId> = { risk: "findings", insurance: "evidence", declarations: "scope" };

export interface Route {
  screen: ScreenId;
  /** Second path segment, e.g. a finding fingerprint or agent id. */
  id: string | null;
  query: URLSearchParams;
}

const DEFAULT: ScreenId = "overview";

function isScreen(value: string): value is ScreenId {
  return (SCREENS as string[]).includes(value);
}

export function parseHash(hash: string): Route {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const [pathPart = "", queryPart = ""] = raw.split("?", 2);
  const segments = pathPart.split("/").filter((s) => s.length > 0);
  const first = segments[0] ?? "";
  const screen = isScreen(first) ? first : (ALIASES[first] ?? DEFAULT);
  const second = segments[1];
  let id: string | null = null;
  if (second !== undefined && second.length > 0) {
    try {
      id = decodeURIComponent(second);
    } catch {
      id = second;
    }
  }
  return { screen, id, query: new URLSearchParams(queryPart) };
}

export function buildHash(screen: ScreenId, id?: string | null, query?: URLSearchParams | Record<string, string>): string {
  let out = `#/${screen}`;
  if (id) out += `/${encodeURIComponent(id)}`;
  const params = query instanceof URLSearchParams ? query : new URLSearchParams(query ?? {});
  const text = params.toString();
  if (text) out += `?${text}`;
  return out;
}

export function navigate(screen: ScreenId, id?: string | null, query?: URLSearchParams | Record<string, string>): void {
  window.location.hash = buildHash(screen, id, query);
}

function currentHash(): string {
  return typeof window === "undefined" ? "" : window.location.hash;
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(currentHash()));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(currentHash()));
    window.addEventListener("hashchange", onChange);
    if (!currentHash()) window.location.replace(buildHash(DEFAULT));
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
