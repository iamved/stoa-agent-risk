import { useCallback, useEffect, useMemo, useState } from "react";
import type { DataProvider } from "../data/provider";
import type { Envelope } from "../data/types";
import type { SchemaProblem } from "../data/schema";
import { envelopeFromText } from "../data/file";
import { OpenScanButton } from "../components/OpenScan";
import { AppProvider, type ScanSource } from "./context";
import { buildHash, useRoute } from "./router";
import { Shell } from "../components/Shell";
import { Overview } from "../screens/Overview";
import { Inventory } from "../screens/Inventory";
import { Findings } from "../screens/Findings";
import { Drift } from "../screens/Drift";
import { Register } from "../screens/Register";
import { Evidence } from "../screens/Evidence";
import { Scope } from "../screens/Scope";
import { Controls } from "../screens/Controls";
import { Loss } from "../screens/Loss";

type State = { status: "loading" } | { status: "ready"; envelope: Envelope } | { status: "problem"; problem: SchemaProblem };

/** Far above any real scan (the 5,000-finding fixture is 7 MB); stops a stray video from freezing the tab. */
const MAX_SCAN_BYTES = 256 * 1024 * 1024;

export function App({ provider }: { provider: DataProvider }) {
  const [state, setState] = useState<State>({ status: "loading" });
  // A scan opened from disk replaces the embedded one. `generation` remounts
  // the screens so their filters and edits never carry across scans.
  const [opened, setOpened] = useState<string | null>(null);
  const [generation, setGeneration] = useState(0);
  const [openError, setOpenError] = useState<SchemaProblem | null>(null);

  const openScan = useCallback((file: File) => {
    const fail = (message: string) => setOpenError({ kind: "malformed", message, found: file.name, expected: "stoa-dashboard/1.x" });
    if (file.size > MAX_SCAN_BYTES) return fail("That file is too large to be a Stoa scan.");
    file.text().then((text) => {
      const result = envelopeFromText(text);
      if ("problem" in result) return setOpenError({ ...result.problem, found: result.problem.found ?? file.name });
      setOpenError(null);
      setOpened(file.name);
      setGeneration((n) => n + 1);
      // Deep links name findings and agents of the scan being replaced.
      window.location.hash = buildHash("overview");
      setState({ status: "ready", envelope: result.envelope });
    }, () => fail("That file could not be read."));
  }, []);

  // Dropping a scan anywhere on the page opens it.
  useEffect(() => {
    const hasFile = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");
    const onOver = (event: DragEvent) => { if (hasFile(event)) event.preventDefault(); };
    const onDrop = (event: DragEvent) => {
      if (!hasFile(event)) return;
      event.preventDefault();
      const file = event.dataTransfer?.files[0];
      if (file) openScan(file);
    };
    window.addEventListener("dragover", onOver);
    window.addEventListener("drop", onDrop);
    return () => { window.removeEventListener("dragover", onOver); window.removeEventListener("drop", onDrop); };
  }, [openScan]);

  const source = useMemo<ScanSource>(() => ({ opened, openScan, openError, clearOpenError: () => setOpenError(null) }), [opened, openScan, openError]);

  useEffect(() => {
    let cancelled = false;
    provider.load().then((result) => {
      if (cancelled) return;
      setState("envelope" in result ? { status: "ready", envelope: result.envelope } : { status: "problem", problem: result.problem });
    });
    return () => {
      cancelled = true;
    };
  }, [provider]);

  if (state.status === "loading") return <main className="p-8 caption">Loading scan data…</main>;
  if (state.status === "problem") return <ProblemScreen problem={state.problem} openError={openError} onOpen={openScan} />;
  return (
    <AppProvider key={generation} envelope={state.envelope} source={source}>
      <Routed />
    </AppProvider>
  );
}

function Routed() {
  const route = useRoute();
  const screen =
    route.screen === "inventory" ? <Inventory /> :
    route.screen === "findings" ? <Findings /> :
    route.screen === "drift" ? <Drift /> :
    route.screen === "register" ? <Register /> :
    route.screen === "evidence" ? <Evidence /> :
    route.screen === "scope" ? <Scope /> :
    route.screen === "controls" ? <Controls /> :
    route.screen === "loss" ? <Loss /> :
    <Overview />;
  return <Shell screen={route.screen}>{screen}</Shell>;
}

function ProblemScreen({ problem, openError, onOpen }: { problem: SchemaProblem; openError: SchemaProblem | null; onOpen: (file: File) => void }) {
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="panel max-w-lg p-6">
        <h1 className="text-[20px] m-0">This dashboard cannot read its data</h1>
        <p className="mt-3 mb-0">{problem.message}</p>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 caption">
          <dt>Found</dt>
          <dd className="m-0 mono">{problem.found ?? "nothing"}</dd>
          <dt>Expected</dt>
          <dd className="m-0 mono">{problem.expected}</dd>
        </dl>
        <p className="caption mt-3 mb-0">Regenerate the file with a matching Stoa release: <code>stoa dashboard stoa-registry.json</code>.</p>
        <div className="mt-4 pt-4 border-t border-line">
          <p className="caption mt-0 mb-2">Or open a scan you already have. It is read in this browser and never uploaded.</p>
          <OpenScanButton onOpen={onOpen} className="btn btn-primary">Open a scan file</OpenScanButton>
          {openError ? <p role="alert" className="caption mt-2 mb-0 text-sev-critical">{openError.message}</p> : null}
        </div>
      </div>
    </main>
  );
}
