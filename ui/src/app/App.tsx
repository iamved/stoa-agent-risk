import { useEffect, useState } from "react";
import type { DataProvider } from "../data/provider";
import type { Envelope } from "../data/types";
import type { SchemaProblem } from "../data/schema";
import { AppProvider } from "./context";
import { useRoute } from "./router";
import { Shell } from "../components/Shell";
import { Overview } from "../screens/Overview";
import { Inventory } from "../screens/Inventory";
import { Findings } from "../screens/Findings";
import { Drift } from "../screens/Drift";
import { Register } from "../screens/Register";
import { Evidence } from "../screens/Evidence";

type State = { status: "loading" } | { status: "ready"; envelope: Envelope } | { status: "problem"; problem: SchemaProblem };

export function App({ provider }: { provider: DataProvider }) {
  const [state, setState] = useState<State>({ status: "loading" });

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
  if (state.status === "problem") return <ProblemScreen problem={state.problem} />;
  return (
    <AppProvider envelope={state.envelope}>
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
    <Overview />;
  return <Shell screen={route.screen}>{screen}</Shell>;
}

function ProblemScreen({ problem }: { problem: SchemaProblem }) {
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
      </div>
    </main>
  );
}
