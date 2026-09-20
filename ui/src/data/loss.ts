/**
 * Declared financial exposure. Stoa does not estimate losses: every figure
 * here was written by a person in stoa-declared.toml (`economic_authority`),
 * and the scanner only checks whether the code enforces it (DECL003) and
 * which agents can move money at all.
 */
import type { Agent, Envelope } from "./types";
import { activeFindings, agentLabel, hasAuthority, type FindingRef } from "./selectors";

export interface Money {
  amount: number;
  currency: string;
}

export interface LossRow {
  agent: Agent;
  name: string;
  authority: boolean;
  moneyTools: string[];
  maxPerAction: Money | null;
  dailyAggregate: Money | null;
  worstCase: Money | null;
  enforcementGaps: FindingRef[];
  worstExposure: string;
}

export function lossRows(env: Envelope): LossRow[] {
  const active = activeFindings(env.registry);
  return env.registry.agents
    .map((agent) => {
      const ea = agent.declared?.economic_authority;
      const dims = agent.dimension_assessment?.dimensions ?? [];
      const worst = dims.some((d) => d.exposure === "elevated") ? "elevated" : dims.some((d) => d.exposure === "moderate") ? "moderate" : dims.some((d) => d.exposure === "low") ? "low" : "none-observed";
      return {
        agent,
        name: agentLabel(agent),
        authority: hasAuthority(env, agent),
        moneyTools: (agent.tools ?? []).filter((t) => t.money_action).map((t) => t.name),
        maxPerAction: ea?.max_per_action ?? null,
        dailyAggregate: ea?.daily_aggregate ?? null,
        worstCase: ea?.worst_case_customer_loss ?? null,
        enforcementGaps: active.filter((r) => (r.finding.rule_id === "DECL003" || r.finding.rule_id === "AI008") && r.agents.some((a) => a.id === agent.id)),
        worstExposure: worst,
      };
    })
    .filter((r) => r.authority || r.maxPerAction || r.dailyAggregate || r.worstCase)
    .sort((a, b) => (b.worstCase?.amount ?? 0) - (a.worstCase?.amount ?? 0) || (b.dailyAggregate?.amount ?? 0) - (a.dailyAggregate?.amount ?? 0) || Number(b.authority) - Number(a.authority) || a.name.localeCompare(b.name));
}

export interface LossTotals {
  currency: string | null;
  worstCase: number;
  dailyAggregate: number;
  declaredAgents: number;
  authorityAgents: number;
  undeclaredAuthority: number;
  mixedCurrencies: boolean;
}

export function lossTotals(rows: LossRow[]): LossTotals {
  const currencies = new Set<string>();
  let worst = 0;
  let daily = 0;
  let declared = 0;
  for (const r of rows) {
    if (r.maxPerAction || r.dailyAggregate || r.worstCase) declared += 1;
    for (const m of [r.maxPerAction, r.dailyAggregate, r.worstCase]) if (m) currencies.add(m.currency);
    worst += r.worstCase?.amount ?? 0;
    daily += r.dailyAggregate?.amount ?? 0;
  }
  return {
    currency: currencies.size === 1 ? [...currencies][0] ?? null : null,
    worstCase: worst,
    dailyAggregate: daily,
    declaredAgents: declared,
    authorityAgents: rows.filter((r) => r.authority).length,
    undeclaredAuthority: rows.filter((r) => r.authority && !r.maxPerAction && !r.dailyAggregate && !r.worstCase).length,
    mixedCurrencies: currencies.size > 1,
  };
}

export function money(m: Money | null): string {
  return m ? `${m.amount.toLocaleString()} ${m.currency}` : "not declared";
}
