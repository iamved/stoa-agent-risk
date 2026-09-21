import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { Envelope } from "../data/types";
import type { FrameworkId } from "../data/frameworks";
import type { SchemaProblem } from "../data/schema";

export { FRAMEWORKS } from "../data/frameworks";
export type { FrameworkId } from "../data/frameworks";

/** Opening a scan from the viewer's disk. `opened` is that file's name, or null for the embedded scan. */
export interface ScanSource {
  opened: string | null;
  openScan: (file: File) => void;
  openError: SchemaProblem | null;
  clearOpenError: () => void;
}

interface AppState extends ScanSource {
  envelope: Envelope;
  framework: FrameworkId;
  setFramework: (id: FrameworkId) => void;
}

const Ctx = createContext<AppState | null>(null);

const PREF_KEY = "stoa.dashboard.framework";

/** Labels are fixed to OWASP LLM Top 10 (2025); the selector was removed as confusing. The EU AI Act article still shows on each finding. */
function readPref(): FrameworkId {
  return "owasp";
}

function writePref(id: FrameworkId): void {
  try {
    window.localStorage.setItem(PREF_KEY, id);
  } catch {
    /* storage unavailable */
  }
}

export function AppProvider({ envelope, source, children }: { envelope: Envelope; source: ScanSource; children: ReactNode }) {
  const [framework, setFrameworkState] = useState<FrameworkId>(readPref);
  const value = useMemo<AppState>(
    () => ({
      ...source,
      envelope,
      framework,
      setFramework: (id) => {
        writePref(id);
        setFrameworkState(id);
      },
    }),
    [envelope, framework, source],
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
