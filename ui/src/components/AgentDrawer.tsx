import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { AssessabilityBadge, ConfidenceBadge, ExposureBadge, Pill, SeverityBadge } from "./Badge";
import { Drawer } from "./Drawer";
import { Chips, KeyValue } from "./KeyValue";
import { agentFindingCount, agentSource, contradictions } from "../data/inventory";
import { agentLabel, dimensionName, hasAuthority } from "../data/selectors";
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

  return (
    <Drawer open title={agentLabel(agent)} onClose={onClose} width={640}>
      <div className="flex flex-wrap items-center gap-1.5 mb-4">
        <ConfidenceBadge confidence={agent.confidence} />
        <Pill title="Detection score from weighted evidence">score {agent.detection_score}</Pill>
        <Pill tone={agent.source === "iac" ? "navy" : "neutral"}>{agentSource(agent)}</Pill>
        {hasAuthority(envelope, agent) ? <Pill tone="warn">financial or write authority</Pill> : null}
        {agent.highest_severity ? <SeverityBadge severity={agent.highest_severity} /> : null}
      </div>

      <KeyValue
        rows={[
          { k: "Location", v: <span className="mono">{agent.path}{agent.symbol ? ` :: ${agent.symbol}` : ""}</span> },
          { k: "Language", v: agent.language },
          { k: "Providers", v: <Chips items={agent.providers.map((p) => ({ label: p }))} /> },
          { k: "Autonomy (inferred)", v: inferred ? <span>{inferred}{agent.autonomy_level?.reason ? <span className="caption"> ({agent.autonomy_level.reason})</span> : null}</span> : "indeterminate" },
          { k: "Last touched", v: agent.last_touched_by ? `${agent.last_touched_by}${agent.last_commit ? ` · ${agent.last_commit.hash}` : ""}` : "no git attribution" },
          { k: "Code owners", v: <Chips items={agent.codeowners.map((c) => ({ label: c }))} empty="none" /> },
        ]}
      />

      <Section title="What it can do">
        <Chips items={agent.capabilities.map((c) => ({ label: c, hot: highImpact.has(c), title: highImpact.has(c) ? "high-impact capability" : "" }))} empty="no capability signals" />
        {agent.tools && agent.tools.length ? (
          <table className="tbl mt-3">
            <thead>
              <tr><th>Tool</th><th>Effects</th><th>Guards</th><th>Where</th></tr>
            </thead>
            <tbody>
              {agent.tools.map((t) => (
                <tr key={`${t.path}:${t.line}:${t.name}`}>
                  <td className="mono">{t.name}<div className="caption">{t.kind}</div></td>
                  <td>
                    <Chips items={[...(t.money_action ? [{ label: "money action", hot: true }] : []), ...(t.high_impact && !t.money_action ? [{ label: "high impact", hot: true }] : []), ...t.capabilities.map((c) => ({ label: c }))]} empty="none observed" />
                  </td>
                  <td className="caption">
                    {t.guards.length ? t.guards.join(", ") : "none observed"}
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
                <a href={buildHash("findings", r.finding.fingerprint)} className="link">{r.finding.rule_id} {r.finding.title}</a>
              </li>
            ))}
          </ul>
        ) : null}
      </Section>

      <Section title="Dimension exposure">
        {agent.dimension_assessment ? (
          <ul className="m-0 p-0 list-none flex flex-col gap-1">
            {agent.dimension_assessment.dimensions.map((d) => (
              <li key={d.id} className="flex items-center justify-between gap-2 text-[13px]">
                <span className="flex items-center gap-2 min-w-0">
                  <span className="truncate">{dimensionName(envelope, d.id)}</span>
                  <AssessabilityBadge assessability={d.assessability} />
                </span>
                <span className="flex items-center gap-2 caption whitespace-nowrap">
                  <span className="tabular-nums">score {d.score}{d.score_before_controls !== undefined && d.score_before_controls !== d.score ? ` (${d.score_before_controls} before controls)` : ""}</span>
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
            <li key={i}><span className="mono">{e.rule_id}</span> line {e.line}: {e.description}</li>
          ))}
        </ul>
      </Section>
    </Drawer>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="text-[14px] m-0 mb-1.5">{title}</h3>
      <div className="text-[13px]">{children}</div>
    </section>
  );
}
