import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { DimensionMatrix } from "../components/DimensionMatrix";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { TopRisks } from "../components/TopRisks";
import { elevatedAgents, pluralize, stats } from "../data/selectors";

export function Overview() {
  const { envelope } = useApp();
  const s = stats(envelope);
  const elevated = elevatedAgents(envelope);
  const urgent = s.findings.critical + s.findings.high;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Overview</h1>
        <div className="caption">What the code makes possible, not what has happened.</div>
      </div>

      <div className="mt-4 grid gap-3 grid-cols-2 xl:grid-cols-4">
        <StatCard label="AI agents found" value={s.agents} href={buildHash("inventory")} />
        <StatCard label="Can move money or write to systems" value={s.authorityAgents} href={buildHash("inventory", null, { authority: "1" })} tone={s.authorityAgents ? "warn" : "neutral"} />
        <StatCard label="High-risk findings" value={urgent} detail={`${s.findings.medium} medium · ${s.findings.low + s.findings.info} low`} href={buildHash("findings", null, { severity: "critical,high" })} tone={urgent ? "warn" : "neutral"} />
        <StatCard label="Changed since last scan" value={s.drift ? s.drift.changed + s.drift.added + s.drift.removed : "–"} detail={s.drift ? (s.drift.escalationsHigh ? `${pluralize(s.drift.escalationsHigh, "high-impact change")} to review` : "nothing to review") : "no baseline"} href={buildHash("drift")} tone={s.drift && s.drift.escalationsHigh ? "warn" : "neutral"} />
      </div>

      <Section title="Risk by dimension" caption="Click a dimension to see which agents drive it.">
        {elevated.length ? (
          <p className="m-0 mb-3 text-[13.5px]">
            <span className="num text-navy text-[18px] align-middle mr-1.5">{elevated.length}</span>
            {elevated.length === 1 ? "agent is at elevated exposure: " : "agents are at elevated exposure: "}
            {elevated.map(({ agent }, i) => (
              <span key={agent.id}>
                <a href={buildHash("inventory", agent.id)} className="link">{agent.display_name || agent.name}</a>
                {i < elevated.length - 1 ? ", " : "."}
              </span>
            ))}
          </p>
        ) : (
          <p className="m-0 mb-3 caption">No agent is at elevated exposure.</p>
        )}
        <DimensionMatrix />
      </Section>

      <Section title="Top findings" caption="Highest severity first. Click one to see the evidence and the fix.">
        <TopRisks />
      </Section>
    </div>
  );
}
