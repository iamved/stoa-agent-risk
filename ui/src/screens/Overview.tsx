import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { DimensionBars } from "../components/DimensionBars";
import { KpiTile } from "../components/KpiTile";
import { TopRisks } from "../components/TopRisks";
import { elevatedAgents, overviewDeltas, stats } from "../data/selectors";

export function Overview() {
  const { envelope } = useApp();
  const s = stats(envelope);
  const d = overviewDeltas(envelope);
  const elevated = elevatedAgents(envelope);
  const urgent = s.findings.critical + s.findings.high;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Overview</h1>
        <div className="caption">What the code makes possible, not what has happened.</div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiTile icon="inventory" label="AI agents found" value={s.agents} delta={d.agents} href={buildHash("inventory")} upIsBad={false} />
        <KpiTile icon="risk" label="High-risk findings" value={urgent} delta={d.findings} detail={`${s.findings.medium} medium · ${s.findings.low + s.findings.info} low`} href={buildHash("findings", null, { severity: "critical,high" })} tone={urgent ? "warn" : "neutral"} />
        <KpiTile icon="loss" label="Can move money or write to systems" value={s.authorityAgents} delta={d.authority} href={buildHash("inventory", null, { authority: "1" })} tone={s.authorityAgents ? "warn" : "neutral"} />
        <KpiTile icon="controls" label="Agents at elevated exposure" value={elevated.length} delta={d.elevated} href={elevated[0] ? buildHash("inventory", elevated[0].agent.id) : buildHash("inventory")} tone={elevated.length ? "warn" : "neutral"} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(320px,2fr)] items-start">
        <DimensionBars />
        <TopRisks />
      </div>
    </div>
  );
}
