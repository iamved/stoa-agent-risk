import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { ExposureBadge, Pill } from "../components/Badge";
import { Chips } from "../components/KeyValue";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { lossRows, lossTotals, money } from "../data/loss";
import type { Exposure } from "../data/types";

/** Declared financial exposure for the agents that can move money. Stoa checks enforcement; it does not estimate losses. */
export function Loss() {
  const { envelope } = useApp();
  const rows = lossRows(envelope);
  const t = lossTotals(rows);
  const fmt = (n: number) => (t.currency ? `${n.toLocaleString()} ${t.currency}` : t.mixedCurrencies ? "mixed currencies" : "not declared");

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Estimated Financial Loss</h1>
        <div className="caption">Every figure here was declared by a person in stoa-declared.toml. Stoa checks whether the code enforces it; it does not model or price a loss.</div>
      </div>

      <div className="mt-4 grid gap-3 grid-cols-2 md:grid-cols-4">
        <div className="rounded-lg border border-navy bg-navy text-white p-4">
          <div className="text-[11px] uppercase tracking-wide text-white/70">Declared worst-case customer loss</div>
          <div className="mt-1 num text-[22px] leading-none text-gold">{t.worstCase ? fmt(t.worstCase) : "not declared"}</div>
          <div className="mt-2 text-[12.5px] text-white/70">sum across {t.declaredAgents} declared {t.declaredAgents === 1 ? "agent" : "agents"}</div>
        </div>
        <StatCard label="Declared daily aggregate" value={t.dailyAggregate ? fmt(t.dailyAggregate) : "not declared"} detail="sum of declared daily limits" />
        <StatCard label="Agents that can move money" value={t.authorityAgents} detail="payment access or a money-moving tool observed" href={buildHash("inventory", null, { authority: "1" })} tone={t.authorityAgents ? "warn" : "neutral"} />
        <StatCard label="Money authority with no declared limit" value={t.undeclaredAuthority} detail="declare economic_authority for these" tone={t.undeclaredAuthority ? "warn" : "neutral"} />
      </div>

      <Section title="By agent" caption="Declared limits next to the money-moving tools the scanner found and whether the limit is enforced in code (DECL003) or the action can post twice (AI008).">
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl">
            <thead><tr><th>Agent</th><th>Money-moving tools</th><th>Max per action</th><th>Daily aggregate</th><th>Worst-case customer loss</th><th>Enforcement</th><th>Exposure</th></tr></thead>
            <tbody>
              {rows.length === 0 ? <tr><td colSpan={7} className="caption text-center">No agent with money authority or a declared economic limit in this scan.</td></tr> : rows.map((r) => (
                <tr key={r.agent.id}>
                  <td><a href={buildHash("inventory", r.agent.id)} className="link font-medium">{r.name}</a><div className="caption mono">{r.agent.path}</div></td>
                  <td><Chips items={r.moneyTools.map((n) => ({ label: n, hot: true }))} empty={r.authority ? "capability only" : "none observed"} tone="mono" /></td>
                  <td className="tabular-nums">{money(r.maxPerAction)}</td>
                  <td className="tabular-nums">{money(r.dailyAggregate)}</td>
                  <td className="tabular-nums">{money(r.worstCase)}</td>
                  <td>{r.enforcementGaps.length === 0 ? <span className="caption">{r.maxPerAction ? "no gap reported" : "nothing to enforce"}</span> : <span className="flex flex-wrap gap-1">{r.enforcementGaps.map((g) => <a key={g.finding.fingerprint} href={buildHash("findings", g.finding.fingerprint)} className="no-underline"><Pill tone="warn">{g.finding.rule_id}</Pill></a>)}</span>}</td>
                  <td><ExposureBadge exposure={r.worstExposure as Exposure} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="How to declare a limit" caption="Limits written in a system prompt are not enforced. Declare them so the scanner can check the code against them.">
        <pre className="panel p-3 m-0 mono text-[12px] whitespace-pre-wrap">{`[agents."<agent id>".economic_authority]
max_per_action           = { amount = 500,   currency = "USD" }
daily_aggregate          = { amount = 5000,  currency = "USD" }
worst_case_customer_loss = { amount = 50000, currency = "USD" }`}</pre>
        <p className="caption mt-2 mb-0">Register rows for these agents are on the <a href={buildHash("register")} className="link">risk register</a>; treatment transfer prepares the <a href={buildHash("evidence")} className="link">insurance evidence</a>.</p>
      </Section>
    </div>
  );
}
