import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { DimensionMatrix } from "../components/DimensionMatrix";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { TopRisks } from "../components/TopRisks";
import { SeverityBadge } from "../components/Badge";
import { SEVERITIES, elevatedAgents, pluralize, stats } from "../data/selectors";

export function Overview() {
  const { envelope } = useApp();
  const s = stats(envelope);
  const elevated = elevatedAgents(envelope);
  const activeTotal = SEVERITIES.reduce((n, sev) => n + s.findings[sev], 0);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-[24px] m-0">Overview</h1>
        <div className="caption">Exposure is what the code makes possible, not what has happened. Every level below is decomposable.</div>
      </div>

      <div className="mt-4 grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        <StatCard label="Agent candidates" value={s.agents} detail={`${s.highConfidence} high confidence`} href={buildHash("inventory")} />
        <StatCard label="With financial or write authority" value={s.authorityAgents} detail="high-impact capability or money-moving tool" href={buildHash("inventory", null, { authority: "1" })} tone={s.authorityAgents ? "warn" : "neutral"} />
        <StatCard label="Unreviewed high-impact actions" value={s.unreviewedHighImpact} detail="AI003: no approval control observed" href={buildHash("findings", null, { rule: "AI003" })} tone={s.unreviewedHighImpact ? "warn" : "neutral"} />
        <StatCard label="Declared vs scanned contradictions" value={s.contradictions} detail="DECL rules" href={buildHash("findings", null, { rule: "DECL" })} tone={s.contradictions ? "warn" : "neutral"} />
        <StatCard
          label="Open findings"
          value={activeTotal}
          detail={
            <span className="flex flex-wrap gap-1">
              {SEVERITIES.filter((sev) => s.findings[sev]).map((sev) => (
                <span key={sev} className="inline-flex items-center gap-1">
                  <SeverityBadge severity={sev} />
                  <span className="tabular-nums">{s.findings[sev]}</span>
                </span>
              ))}
              {s.suppressed ? <span>· {s.suppressed} suppressed</span> : null}
            </span>
          }
          href={buildHash("findings")}
        />
        <StatCard
          label="Changes since baseline"
          value={s.drift ? s.drift.changed + s.drift.added + s.drift.removed : "–"}
          detail={s.drift ? `${pluralize(s.drift.changed, "agent")} changed · ${s.drift.added} added · ${s.drift.removed} removed · unapproved drift ${s.drift.unapproved}` : "no baseline in this scan"}
          href={buildHash("drift")}
          tone={s.drift && s.drift.escalationsHigh ? "warn" : "neutral"}
        />
      </div>

      <Section title="Where the exposure sits" caption="Eight dimensions, four categories. Click a dimension to see which agents produce its level.">
        {elevated.length ? (
          <p className="m-0 mb-3 text-[13.5px]">
            <span className="font-serif text-gold text-[22px] align-middle mr-2">{elevated.length}</span>
            {elevated.length === 1 ? "agent carries" : "agents carry"} elevated exposure:{" "}
            {elevated.map(({ agent, entries }, i) => (
              <span key={agent.id}>
                <a href={buildHash("inventory", agent.id)} className="link">
                  {agent.display_name || agent.name}
                </a>
                <span className="caption"> ({entries.map((e) => e.id).join(", ")})</span>
                {i < elevated.length - 1 ? ", " : "."}
              </span>
            ))}
          </p>
        ) : (
          <p className="m-0 mb-3 caption">No agent carries elevated exposure in this scan.</p>
        )}
        <DimensionMatrix />
      </Section>

      <Section title="Read these first" caption="Highest severity, one per rule where possible. Each links to its finding.">
        <TopRisks />
      </Section>

    </div>
  );
}
