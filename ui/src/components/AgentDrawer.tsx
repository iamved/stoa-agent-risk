import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { AssessabilityBadge, ConfidenceBadge, ExposureBadge, Pill, SeverityBadge } from "./Badge";
import { Drawer } from "./Drawer";
import { ExposureTip } from "./InfoTip";
import { Chips, KeyValue } from "./KeyValue";
import { agentFindingCount, agentSource, contradictions } from "../data/inventory";
import { definedIn, uniqueAgentOf } from "../data/agents";
import { CAPABILITY_LABEL, autonomyLabel, businessCapabilities, prose } from "../data/labels";
import { agentLabel, dimensionName, findingTitle } from "../data/selectors";
import type { Agent } from "../data/types";

function money(v?: { amount: number; currency: string }): string {
  return v ? `${v.amount.toLocaleString()} ${v.currency}` : "not declared";
}

/** What it can do, what it can reach, declared versus inferred, and its scored dimensions. */
export function AgentDrawer({ agent, onClose }: { agent: Agent | null; onClose: () => void }) {
  const { envelope } = useApp();
  if (!agent) return null;
  const highImpact = new Set(envelope.vocabulary.high_impact_capabilities);
  const sensitive = new Set(envelope.vocabulary.sensitive_integrations);
  const declared = agent.declared;
  const inferred = agent.autonomy_level?.level ?? null;
  const decl = contradictions(envelope, agent);
  const autonomyMismatch = Boolean(declared?.autonomy_intent && inferred && declared.autonomy_intent !== inferred);
  const findingCount = agentFindingCount(envelope, agent);
  const unique = uniqueAgentOf(envelope, agent.id);
  const business = businessCapabilities(agent.capabilities, agent.integrations);

  return (
    <Drawer open title={unique?.name ?? agentLabel(agent)} onClose={onClose} width={640}>
      {unique && unique.records.length > 1 ? (
        <div className="mb-4 rounded-md border border-line bg-paper px-3 py-2.5">
          <div className="text-[12.5px] text-ink-soft">One agent, found in {unique.records.length} places. {definedIn(unique)}.{unique.linkedBy === "declared" ? " Linked in your declaration file." : unique.linkedBy === "name" ? " Matched by name." : ""}</div>
          <ul className="m-0 mt-2 p-0 list-none flex flex-col gap-1" aria-label="Discovered records">
            {unique.info.map((info, i) => {
              const record = unique.records[i]!;
              const current = record.id === agent.id;
              return (
                <li key={record.id} className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
                  {current ? <span className="font-medium text-navy">{info.label}</span> : <a className="link" href={buildHash("inventory", record.id)}>{info.label}</a>}
                  <span className="mono caption break-all">{record.path}{record.symbol ? ` :: ${record.symbol}` : ""}</span>
                  {current ? <span className="caption">shown below</span> : null}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-1.5 mb-4">
        <ConfidenceBadge confidence={agent.confidence} />
        <Pill title="Detection score from weighted evidence">score {agent.detection_score}</Pill>
        <Pill tone={agent.source === "iac" ? "navy" : "neutral"}>{agentSource(agent)}</Pill>
        {business.map((id) => <Pill key={id} tone={id === "payments" ? "warn" : "neutral"}>{CAPABILITY_LABEL[id]}</Pill>)}
        {agent.highest_severity ? <SeverityBadge severity={agent.highest_severity} /> : null}
      </div>

      <KeyValue
        rows={[
          { k: "Location", v: <span className="mono">{agent.path}{agent.symbol ? ` :: ${agent.symbol}` : ""}</span> },
          { k: "Language", v: agent.language },
          { k: "Providers", v: <Chips items={agent.providers.map((p) => ({ label: p }))} /> },
          { k: "Autonomy (inferred)", v: <span>{autonomyLabel(inferred)} <span className="mono caption">{inferred ?? "indeterminate"}</span>{agent.autonomy_level?.reason ? <span className="caption"> ({agent.autonomy_level.reason})</span> : null}</span> },
          { k: "Last touched", v: agent.last_touched_by ? `${agent.last_touched_by}${agent.last_commit ? ` · ${agent.last_commit.hash}` : ""}` : "no git attribution" },
          { k: "Code owners", v: <Chips items={agent.codeowners.map((c) => ({ label: c }))} empty="none" /> },
        ]}
      />

      <Section title="What it can do">
        <Chips items={agent.capabilities.map((c) => ({ label: c, hot: highImpact.has(c), title: highImpact.has(c) ? "high-impact capability" : "" }))} empty="no capability signals" />
        {agent.tools && agent.tools.length ? (
          <table className="tbl mt-3">
            <thead>
              <tr><th>Tool</th><th>Effects</th><th>Guardrails</th><th>Where</th></tr>
            </thead>
            <tbody>
              {agent.tools.map((t) => (
                <tr key={`${t.path}:${t.line}:${t.name}`}>
                  <td className="mono">{t.name}<div className="caption">{t.kind}</div></td>
                  <td>
                    <Chips items={[...(t.money_action ? [{ label: "money action", hot: true }] : []), ...(t.high_impact && !t.money_action ? [{ label: "high impact", hot: true }] : []), ...t.capabilities.map((c) => ({ label: c }))]} empty="none observed" />
                  </td>
                  <td className="caption">
                    {t.guards.length ? t.guards.join(", ") : "none detected"}
                    {t.retry ? <div>{t.idempotency_key ? "retried with idempotency key" : "retried without idempotency key"}</div> : null}
                  </td>
                  <td className="mono caption">{t.path}:{t.line}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="caption mt-2 mb-0">No tool definitions bound.</p>}
      </Section>

      <Section title="What it can reach">
        <KeyValue
          rows={[
            { k: "Integrations", v: <Chips items={agent.integrations.map((i) => ({ label: i, hot: sensitive.has(i), title: sensitive.has(i) ? "sensitive integration" : "" }))} empty="none observed" /> },
            { k: "Call sites", v: Object.keys(agent.call_sites).length ? <Chips items={Object.entries(agent.call_sites).map(([k, v]) => ({ label: `${k} ×${v}` }))} /> : <span className="caption">none observed</span> },
            { k: "Permission tags", v: <Chips items={agent.permission_tags.map((p) => ({ label: p }))} empty="none" /> },
          ]}
        />
      </Section>

      <Section title="Declared vs scanned">
        {declared ? (
          <KeyValue
            rows={[
              { k: "Owner", v: declared.owner || "not declared" },
              { k: "Purpose", v: declared.purpose || "not declared" },
              { k: "Users", v: declared.users ?? "not declared" },
              { k: "Production status", v: declared.production_status ?? "not declared" },
              { k: "Autonomy", v: <span>declared <strong>{declared.autonomy_intent ?? "not declared"}</strong> · inferred <strong>{inferred ?? "indeterminate"}</strong>{autonomyMismatch ? " · contradiction" : ""}</span>, flag: autonomyMismatch },
              { k: "Data classes", v: <Chips items={declared.data_classes.map((d) => ({ label: d }))} empty="not declared" /> },
              { k: "Max per action", v: money(declared.economic_authority?.max_per_action) },
              { k: "Daily aggregate", v: money(declared.economic_authority?.daily_aggregate) },
            ]}
          />
        ) : (
          <p className="caption m-0">No declaration for this agent in stoa-declared.toml.</p>
        )}
        {decl.length ? (
          <ul className="m-0 mt-3 p-0 list-none flex flex-col gap-1">
            {decl.map((r) => (
              <li key={r.finding.fingerprint} className="flex items-center gap-2 text-[13px]">
                <SeverityBadge severity={r.finding.severity} />
                <a href={buildHash("findings", r.finding.fingerprint)} className="link">{findingTitle(envelope, r.finding)}</a> <span className="mono caption">{r.finding.rule_id}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </Section>

      <Section title="Exposure by dimension" hint={<ExposureTip align="left" />}>
        {agent.dimension_assessment ? (
          <ul className="m-0 p-0 list-none flex flex-col gap-1">
            {agent.dimension_assessment.dimensions.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-2 text-[13px]">
                <span className="flex items-center gap-2 min-w-0">
                  <span className="truncate">{dimensionName(envelope, d.id)}</span>
                  <AssessabilityBadge assessability={d.assessability} />
                </span>
                <span className="flex items-center gap-2 caption whitespace-nowrap">
                  <span className="tabular-nums">score {d.score}{d.score_before_controls !== undefined && d.score_before_controls !== d.score ? ` (${d.score_before_controls} before safeguards)` : ""}</span>
                  <ExposureBadge exposure={d.exposure} />
                </span>
              </li>
            ))}
          </ul>
        ) : <p className="caption m-0">Not assessed.</p>}
      </Section>

      <Section title={`Findings (${findingCount})`}>
        <a href={buildHash("findings", null, { agent: agent.id })} className="link">Open the findings for this agent</a>
        <div className="caption mt-2">Detection evidence:</div>
        <ul className="m-0 p-0 list-none caption">
          {agent.evidence.map((e, i) => (
            <li key={i}><span className="mono">{e.rule_id}</span> line {e.line}: {prose(e.description)}</li>
          ))}
        </ul>
      </Section>
    </Drawer>
  );
}

function Section({ title, hint, children }: { title: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <div className="flex items-center gap-1.5 mb-1.5"><h3 className="text-[14px] m-0">{title}</h3>{hint}</div>
      <div className="text-[13px]">{children}</div>
    </section>
  );
}
