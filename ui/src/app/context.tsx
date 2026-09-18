import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { Envelope } from "../data/types";
import type { FrameworkId } from "../data/frameworks";

export { FRAMEWORKS } from "../data/frameworks";
export type { FrameworkId } from "../data/frameworks";

interface AppState {
  envelope: Envelope;
  framework: FrameworkId;
  setFramework: (id: FrameworkId) => void;
}

const Ctx = createContext<AppState | null>(null);

const PREF_KEY = "stoa.dashboard.framework";

/** Per-viewer convenience only; wrapped because storage can throw or be empty. */
function readPref(): FrameworkId {
  try {
    const value = window.localStorage.getItem(PREF_KEY);
    if (value === "owasp" || value === "eu" || value === "nist") return value;
  } catch {
    /* storage unavailable */
  }
  return "owasp";
}

function writePref(id: FrameworkId): void {
  try {
    window.localStorage.setItem(PREF_KEY, id);
  } catch {
    /* storage unavailable */
  }
}

export function AppProvider({ envelope, children }: { envelope: Envelope; children: ReactNode }) {
  const [framework, setFrameworkState] = useState<FrameworkId>(readPref);
  const value = useMemo<AppState>(
    () => ({
      envelope,
      framework,
      setFramework: (id) => {
        writePref(id);
        setFrameworkState(id);
      },
    }),
    [envelope, framework],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const state = useContext(Ctx);
  if (!state) throw new Error("useApp outside AppProvider");
  return state;
}

export function useEnvelope(): Envelope {
  return useApp().envelope;
}
