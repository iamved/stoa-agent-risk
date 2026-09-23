/**
 * The Safety Audit: every agent with the people who answer for it and where
 * to take the next step. Names and links are declared in stoa-declared.toml
 * (`owner`, `engineer`, `slack_thread`, `[integrations]`); nothing here is
 * inferred, and a row with nothing declared says so.
 */
import type { Envelope } from "./types";
import { declaredOf, exposureOf, uniqueAgents, type UniqueAgent } from "./agents";
import { activeFindings, countByLevel, riskLevel } from "./selectors";

export interface AuditRow {
  agent: UniqueAgent;
  owner: string;
  engineer: string;
  /** Exposure the scanner reports, for the row's badge. */
  exposure: ReturnType<typeof exposureOf>;
  high: number;
  slack: string | null;
  /** A prefilled "create issue" link, when `[integrations].jira_create_url` is declared. */
  jira: string | null;
  /** mailto: to the owner, when the owner is an address. */
  email: string | null;
}

export function auditRows(env: Envelope): AuditRow[] {
  const jiraBase = env.registry.integrations?.jira_create_url?.trim() || null;
  const company = env.assessment.identity.company.trim() || env.registry.repository.name;
  return uniqueAgents(env)
    .map((agent) => {
      const d = declaredOf(agent);
      const owner = d?.owner?.trim() ?? "";
      const mine = activeFindings(env).filter((r) => r.uniqueAgents.includes(agent));
      const high = countByLevel(mine).high;
      const summary = `${agent.name}: ${high ? `${high} high-severity finding${high === 1 ? "" : "s"}` : "safety audit"} (Stoa)`;
      const description = mine.filter((r) => riskLevel(r.finding.severity) === "high").map((r) => `- ${r.finding.title} (${r.finding.rule_id}, ${r.finding.path}:${r.finding.line})`).join("\n");
      const jira = jiraBase ? `${jiraBase}${jiraBase.includes("?") ? "&" : "?"}summary=${encodeURIComponent(summary)}&description=${encodeURIComponent(`${company} agent ${agent.name}\n${description}`)}` : null;
      return {
        agent,
        owner,
        engineer: d?.engineer?.trim() ?? "",
        exposure: exposureOf(agent),
        high,
        slack: d?.slack_thread?.trim() || null,
        jira,
        email: /^[^\s@]+@[^\s@]+$/.test(owner) ? `mailto:${owner}?subject=${encodeURIComponent(summary)}` : null,
      };
    })
    .sort((a, b) => b.high - a.high || a.agent.name.localeCompare(b.agent.name));
}
