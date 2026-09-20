import { useApp } from "../app/context";
import { buildHash, navigate, useRoute } from "../app/router";
import { AgentDrawer } from "../components/AgentDrawer";
import { SeverityBadge } from "../components/Badge";
import { Chips, KeyValue } from "../components/KeyValue";
import { Section } from "../components/Section";
import { StatCard } from "../components/StatCard";
import { DeclarationsTable } from "./Inventory";
import { activeFindings, agentById, agentLabel } from "../data/selectors";

/** What the organization says about its agents, next to what the code shows. */
export function Scope() {
  const { envelope } = useApp();
  const route = useRoute();
  const r = envelope.registry;
  const declared = r.agents.filter((a) => a.declared);
  const undeclared = r.agents.filter((a) => !a.declared);
  const contradictions = activeFindings(r).filter((x) => x.finding.rule_id.startsWith("DECL"));
  const stale = r.warnings.filter((w) => /declared agent id|not found in this scan|risk_register entry/.test(w));
  const selected = route.id ? agentById(r, route.id) : null;
  const business = r.business ?? null;
  const governance = r.governance ?? null;
  const evidence = r.evidence ?? null;

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-[24px] m-0">Declared Scope</h1>
        <div className="caption">Facts a person wrote in stoa-declared.toml, cross-checked by the scanner. Declarations are reviewed like code.</div>
      </div>

      <div className="mt-4 grid gap-3 grid-cols-2 md:grid-cols-4">
        <StatCard label="Agents declared" value={declared.length} detail={`${undeclared.length} scanned agents without a declaration`} tone={undeclared.length ? "warn" : "neutral"} />
        <StatCard label="Contradictions" value={contradictions.length} detail="declared versus scanned (DECL rules)" href={buildHash("findings", null, { rule: "DECL" })} tone={contradictions.length ? "warn" : "neutral"} />
        <StatCard label="Stale declarations" value={stale.length} detail="ids that match nothing in this scan" tone={stale.length ? "warn" : "neutral"} />
        <StatCard label="Evidence references" value={evidence ? Object.values(evidence).reduce((n, list) => n + list.length, 0) : 0} detail="external artifacts pointed to, not verified" />
      </div>

      <Section title="Organization" caption="Business context and governance as declared. Attestation only; the scanner never scores these.">
        {!business && !governance ? (
          <div className="panel p-4 caption">No [business] or [governance] block declared. Run <span className="mono">stoa init declarations</span> to generate a stub with the scanned agent ids filled in.</div>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            <div className="panel p-4">
              <h3 className="text-[14px] m-0 mb-2">Business</h3>
              {business ? <KeyValue rows={Object.entries(business).map(([k, v]) => ({ k: k.replace(/_/g, " "), v: Array.isArray(v) ? <Chips items={v.map((x) => ({ label: String(x) }))} empty="none" /> : String(v) }))} /> : <p className="caption m-0">Not declared.</p>}
            </div>
            <div className="panel p-4">
              <h3 className="text-[14px] m-0 mb-2">Governance</h3>
              {governance ? <KeyValue rows={Object.entries(governance).map(([k, v]) => ({ k: k.replace(/_/g, " "), v: typeof v === "object" && v !== null ? Object.entries(v as Record<string, unknown>).map(([a, b]) => `${a}: ${String(b)}`).join(" · ") : String(v) }))} /> : <p className="caption m-0">Not declared.</p>}
            </div>
          </div>
        )}
        {evidence ? (
          <div className="panel p-4 mt-4">
            <h3 className="text-[14px] m-0 mb-2">Evidence references</h3>
            <ul className="m-0 p-0 list-none flex flex-col gap-1 text-[13px]">
              {Object.entries(evidence).flatMap(([category, items]) => items.map((e, i) => (
                <li key={`${category}-${i}`} className="flex flex-wrap gap-2"><span className="caption">{category}</span><span>{e.kind}</span><span className="mono">{e.ref}</span>{e.date ? <span className="caption">{e.date}</span> : null}</li>
              )))}
            </ul>
          </div>
        ) : null}
      </Section>

      <Section title="Agents" caption="Declared autonomy, owner and status next to what the scan inferred. Click a row for the full comparison.">
        <DeclarationsTable agents={declared} onOpen={(a) => navigate("scope", a.id)} />
        {undeclared.length ? (
          <div className="panel p-3 mt-3 text-[13px]">
            <div className="caption uppercase text-[11px] tracking-wide mb-1">Scanned but not declared</div>
            <span className="flex flex-wrap gap-1">{undeclared.map((a) => <a key={a.id} href={buildHash("scope", a.id)} className="link">{agentLabel(a)}</a>)}</span>
          </div>
        ) : null}
      </Section>

      <Section title="Contradictions" caption="Where the declaration and the code disagree. What a self-attested questionnaire cannot catch.">
        {contradictions.length === 0 ? <p className="caption m-0">None in this scan.</p> : (
          <ul className="m-0 p-0 list-none panel divide-y divide-line">
            {contradictions.map((c) => (
              <li key={c.finding.fingerprint} className="p-3 flex flex-wrap items-center gap-2 text-[13px]">
                <SeverityBadge severity={c.finding.severity} />
                <span className="mono">{c.finding.rule_id}</span>
                <a href={buildHash("findings", c.finding.fingerprint)} className="link">{c.finding.title}</a>
                {c.agent ? <span className="caption">{agentLabel(c.agent)}</span> : null}
                <span className="caption mono">{c.finding.path}:{c.finding.line}</span>
              </li>
            ))}
          </ul>
        )}
        {stale.length ? <ul className="m-0 mt-3 p-0 list-none caption flex flex-col gap-1">{stale.map((w, i) => <li key={i}>{w}</li>)}</ul> : null}
      </Section>

      <AgentDrawer agent={selected} onClose={() => navigate("scope")} />
    </div>
  );
}
