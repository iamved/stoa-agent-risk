import { useEffect, useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash, useRoute } from "../app/router";
import { ExposureBadge, Pill } from "../components/Badge";
import { Chips } from "../components/KeyValue";
import { LossCurve } from "../components/LossCurve";
import { Section } from "../components/Section";
import { CATS, DIMS, EVENTS, STATUS_LABEL, catName, indicate, money, pct, whatIfs, type Comparable, type GapStatus, type Indication, type Intake, type ModelAgent, type Policy, type WhatIf } from "../data/lossModel";
import { agentToModel, candidateAgents, intakeFromEnvelope, intakeToToml } from "../data/lossInputs";
import { lossRows, money as declaredMoney } from "../data/loss";
import { initials } from "../data/selectors";
import type { Exposure } from "../data/types";

const GAP_CHIP: Record<GapStatus, string> = { unprotected: "chip-critical", excluded: "chip-critical", shortfall: "chip-medium", ok: "chip-ok", minor: "chip-muted" };
const SEED = 42;

/** The AI loss outlook for one scanned agent, plus the declared limits the scan checks. */
export function Loss() {
  const { envelope } = useApp();
  const route = useRoute();
  const agents = useMemo(() => candidateAgents(envelope), [envelope]);
  const initial = useMemo(() => intakeFromEnvelope(envelope), [envelope]);
  const [agentId, setAgentId] = useState<string>(route.query.get("agent") ?? agents[0]?.id ?? "");
  const [intake, setIntake] = useState<Intake>(initial.intake);
  const [volume, setVolume] = useState(initial.monthlyVolume);
  const [overrides, setOverrides] = useState<Partial<ModelAgent["capabilities"]>>({});
  const [adjusting, setAdjusting] = useState(!initial.declared);
  const [copied, setCopied] = useState(false);
  const agent = agents.find((a) => a.id === agentId) ?? agents[0] ?? null;

  const mapped = useMemo(() => (agent ? agentToModel(envelope, agent, volume) : null), [envelope, agent, volume]);
  const model: ModelAgent | null = useMemo(() => (mapped ? { ...mapped.model, capabilities: { ...mapped.model.capabilities, ...overrides, financial_authority: { ...mapped.model.capabilities.financial_authority, ...(overrides.financial_authority ?? {}) } } } : null), [mapped, overrides]);

  // The simulation runs on the main thread; keep it off the first paint so the shell shows immediately.
  const [result, setResult] = useState<{ r: Indication; levers: WhatIf[] } | null>(null);
  useEffect(() => {
    if (!model) return;
    setResult(null);
    const id = window.setTimeout(() => {
      const r = indicate(EVENTS, model, intake, SEED);
      setResult({ r, levers: whatIfs(model, intake, SEED, r) });
    }, 30);
    return () => window.clearTimeout(id);
  }, [model, intake]);

  const toml = intakeToToml(intake, volume);
  const copy = async () => {
    try { await navigator.clipboard.writeText(toml); setCopied(true); } catch { setCopied(false); }
  };

  if (!agent || !model || !mapped) {
    return (
      <div>
        <h1 className="m-0">Estimated Financial Loss</h1>
        <p className="caption">No agent in this scan has a dimension assessment, so there is nothing to model.</p>
        <DeclaredLimits />
      </div>
    );
  }
  const c = model.capabilities;
  const deployment = [model.name, intake.sector + (intake.regulated ? ", regulated" : ""), money(intake.revenue) + " revenue", intake.jurisdictions.join(" and "), c.financial_authority.enabled ? "moves money, up to " + money(c.financial_authority.max_per_action_usd) + " per action" : "cannot move money", c.human_in_loop === "none" ? "no human review" : "human review: " + c.human_in_loop.replace(/_/g, " ")].join("; ");

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Estimated Financial Loss</h1>
        <div className="caption">An indication for a broker conversation. Not a quote.</div>
      </div>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4 pb-3 border-b border-line">
        <div className="max-w-[75ch]">
          <div className="caption">Deployment assessed</div>
          <div className="text-[13.5px] font-medium">{deployment}</div>
        </div>
        <label className="flex flex-col gap-1 text-[12.5px] min-w-[260px] no-print">
          <span className="caption">Agent</span>
          <select value={agent.id} onChange={(e) => { setAgentId(e.target.value); setOverrides({}); }} className="field" aria-label="Agent to model">
            {agents.map((a) => <option key={a.id} value={a.id}>{a.display_name || a.name}</option>)}
          </select>
        </label>
      </div>

      {!initial.declared ? (
        <div className="mt-3 rounded-md border border-sev-medium/40 bg-sev-medium-bg px-4 py-3 text-[13px] text-sev-medium">
          No business context declared. The figures below use placeholder revenue, sector and records; adjust them and save the snippet to <span className="mono">.stoa/underwriting.toml</span> so the next scan carries them.
        </div>
      ) : null}

      <details className="mt-3 no-print" open={adjusting} onToggle={(e) => setAdjusting((e.target as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer caption">Adjust the inputs</summary>
        <div className="panel mt-3 p-4 grid gap-x-8 gap-y-3 md:grid-cols-3 text-[13px]">
          <div className="flex flex-col gap-2">
            <div className="eyebrow">The business</div>
            <Num label="Annual revenue ($M)" value={intake.revenue / 1e6} step={1} onChange={(v) => setIntake({ ...intake, revenue: Math.max(v, 0.1) * 1e6 })} />
            <label className="flex flex-col gap-1"><span className="caption">Sector</span>
              <select value={intake.sector} onChange={(e) => setIntake({ ...intake, sector: e.target.value })} className="field" aria-label="Sector">
                {[["fintech", "Fintech"], ["healthtech", "Health tech"], ["edtech", "EdTech"], ["software", "Software"], ["retail", "Retail"], ["legal", "Legal"]].map(([v, t]) => <option key={v} value={v}>{t}</option>)}
              </select>
            </label>
            <Num label="Personal records held (M)" value={intake.records / 1e6} step={0.1} onChange={(v) => setIntake({ ...intake, records: v * 1e6 })} />
            <Check label="Operates in the EU" checked={intake.jurisdictions.includes("EU")} onChange={(on) => setIntake({ ...intake, jurisdictions: on ? [...intake.jurisdictions.filter((j) => j !== "EU"), "EU"] : intake.jurisdictions.filter((j) => j !== "EU") })} />
            <Check label="Regulated sector" checked={intake.regulated} onChange={(v) => setIntake({ ...intake, regulated: v })} />
            <Check label="Serves minors" checked={intake.minors} onChange={(v) => setIntake({ ...intake, minors: v })} />
          </div>
          <div className="flex flex-col gap-2">
            <div className="eyebrow">The agent</div>
            <Check label="Can move money" checked={c.financial_authority.enabled} onChange={(v) => setOverrides({ ...overrides, financial_authority: { ...c.financial_authority, enabled: v } })} />
            {c.financial_authority.enabled ? (
              <>
                <Num label="Max per action ($)" value={c.financial_authority.max_per_action_usd} step={50} onChange={(v) => setOverrides({ ...overrides, financial_authority: { ...c.financial_authority, max_per_action_usd: v } })} />
                <Num label="Actions per month (k)" value={volume / 1e3} step={10} onChange={(v) => setVolume(v * 1e3)} />
              </>
            ) : null}
            <Check label="Reads personal data" checked={c.pii_access} onChange={(v) => setOverrides({ ...overrides, pii_access: v })} />
            <Check label="Writes to production systems" checked={c.write_access_to_systems} onChange={(v) => setOverrides({ ...overrides, write_access_to_systems: v })} />
            <Check label="Customer facing" checked={c.customer_facing} onChange={(v) => setOverrides({ ...overrides, customer_facing: v })} />
            <label className="flex flex-col gap-1"><span className="caption">Autonomy</span>
              <select value={c.autonomy_level} onChange={(e) => setOverrides({ ...overrides, autonomy_level: e.target.value as ModelAgent["capabilities"]["autonomy_level"] })} className="field" aria-label="Autonomy">
                <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
              </select>
            </label>
            <label className="flex flex-col gap-1"><span className="caption">Human review</span>
              <select value={c.human_in_loop} onChange={(e) => setOverrides({ ...overrides, human_in_loop: e.target.value as ModelAgent["capabilities"]["human_in_loop"] })} className="field" aria-label="Human review">
                <option value="none">None</option><option value="partial">Sampled review</option><option value="approval_above_threshold">Approval above a threshold</option><option value="full">Every action approved</option>
              </select>
            </label>
          </div>
          <div className="flex flex-col gap-2">
            <div className="eyebrow">Current insurance</div>
            {[0, 1].map((i) => {
              const p = intake.existing_coverage[i];
              const setPol = (patch: Partial<Policy> | null) => {
                const next = [...intake.existing_coverage];
                if (patch === null) next.splice(i, 1);
                else next[i] = { type: p?.type ?? "cyber", limit: p?.limit ?? 5e6, ai_exclusion: p?.ai_exclusion ?? false, ...patch };
                setIntake({ ...intake, existing_coverage: next.filter(Boolean) });
              };
              return (
                <div key={i} className="grid grid-cols-[1fr_92px] gap-1.5 items-center">
                  <select value={p?.type ?? ""} onChange={(e) => setPol(e.target.value ? { type: e.target.value as Policy["type"] } : null)} className="field" aria-label={`Policy ${i + 1} type`}>
                    <option value="">No policy</option><option value="cyber">Cyber</option><option value="tech_eo">Tech E&amp;O</option><option value="crime">Crime</option>
                  </select>
                  <input type="number" min={0} step={1} value={p ? p.limit / 1e6 : ""} onChange={(e) => setPol({ limit: (parseFloat(e.target.value) || 0) * 1e6 })} disabled={!p} className="field" aria-label={`Policy ${i + 1} limit ($M)`} placeholder="$M" />
                  <label className="col-span-2 flex items-center gap-2 caption"><input type="checkbox" checked={p?.ai_exclusion ?? false} disabled={!p} onChange={(e) => setPol({ ai_exclusion: e.target.checked })} />AI exclusion</label>
                </div>
              );
            })}
            <div className="mt-2 flex items-center justify-between gap-2"><span className="caption">Save the business context</span><button type="button" onClick={copy} className="btn btn-sm">{copied ? "Copied" : "Copy [intake] snippet"}</button></div>
            <textarea readOnly value={toml} rows={6} className="w-full rounded-md border border-line bg-paper p-2 mono text-[11.5px]" aria-label="Intake config snippet" onFocus={(e) => e.currentTarget.select()} />
          </div>
        </div>
        <details className="mt-2">
          <summary className="cursor-pointer caption">How the scan fed the model</summary>
          <table className="tbl mt-2 max-w-[760px]"><thead><tr><th>Model input</th><th>Value</th><th>From</th></tr></thead><tbody>{mapped.notes.map((n) => <tr key={n.input}><td>{n.input}</td><td className="mono">{n.value}</td><td className="caption">{n.from}</td></tr>)}</tbody></table>
        </details>
      </details>

      {!result ? (
        <div className="mt-6 panel p-6 caption" aria-live="polite">Simulating 100,000 years of losses for this deployment…</div>
      ) : (
        <Outlook r={result.r} levers={result.levers} intake={intake} model={model} />
      )}

      <DeclaredLimits />

      <p className="caption mt-8 pt-4 border-t border-line max-w-[90ch]">Indication for discussion with a licensed broker and carrier. Not a quote, not a premium, not advice. Past cases are public events with approximate amounts; the assumptions (version {result?.r.assumptions_version ?? "demo-0.1"}, seed {SEED}) need actuarial review.</p>
    </div>
  );
}

function Num({ label, value, step, onChange }: { label: string; value: number; step: number; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col gap-1"><span className="caption">{label}</span>
      <input type="number" min={0} step={step} value={+value.toFixed(3)} onChange={(e) => onChange(Math.max(0, parseFloat(e.target.value) || 0))} className="field" aria-label={label} />
    </label>
  );
}
function Check({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return <label className="flex items-center gap-2"><input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />{label}</label>;
}

function Outlook({ r, levers, intake, model }: { r: Indication; levers: WhatIf[]; intake: Intake; model: ModelAgent }) {
  const S = r.summary, L = r.limits;
  const ranked = S.perCat.slice().sort((a, b) => b.tailShare - a.tailShare);
  const gap = (k: string) => r.gaps.find((g) => g.key === k)!;
  const top = ranked[0]!;
  const major = ranked.filter((c) => gap(c.key).status !== "minor"), minor = ranked.filter((c) => gap(c.key).status === "minor");
  return (
    <div className="mt-6">
      <h2 className="m-0 text-[26px] leading-tight tracking-tight">A bad year could cost {money(S.pMid)}</h2>
      <p className="mt-2 mb-5 max-w-[68ch] text-[14.5px]">That is the insurable loss this AI deployment could cause in a year seen once in a hundred. An average year costs about <strong>{money(S.eal)}</strong>. {catName(top.key)} accounts for {pct(top.tailShare)} of the bad-year figure.</p>

      <figure className="m-0 panel p-3 overflow-x-auto" tabIndex={0}>
        <LossCurve r={r} coverage={intake.existing_coverage} />
      </figure>

      <div className="mt-3 grid gap-3 grid-cols-2 md:grid-cols-4">
        {([["Average year", S.eal, "expected annual loss"], ["1 in 20 year", S.pLow, "a rough year"], ["1 in 100 year", S.pMid, "a bad year"], ["1 in 250 year", S.pHigh, "a severe year"]] as const).map(([n, v, d], i) => (
          <div key={n} className={`panel px-4 py-3.5 ${i === 2 ? "ring-2 ring-gold/60" : ""}`}>
            <div className="text-[12.5px] text-ink-muted">{n}</div>
            <div className="num text-[26px] text-navy leading-tight mt-1">{money(v)}</div>
            <div className="caption">{d}</div>
          </div>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-x-10 gap-y-2 rounded-xl bg-gold-100/70 px-5 py-4">
        <div className="grid"><span className="caption">Suggested coverage limit</span><b className="text-[18px] font-semibold text-navy">{money(L.lean)} to {money(L.conservative)}</b></div>
        <div className="grid"><span className="caption">Most common choice</span><b className="text-[18px] font-semibold text-navy">{money(L.standard)}</b></div>
        <div className="grid"><span className="caption">Suggested retention</span><b className="text-[18px] font-semibold text-navy">{money(r.retention)}</b></div>
        <div className="grid"><span className="caption">Confidence</span><b className="text-[18px] font-semibold text-navy">{r.confidence}</b></div>
        <a href={buildHash("evidence")} className="link self-end text-[12.5px]">Carry into the assessment schedule</a>
      </div>

      <Section title="Where the loss could come from" caption="With the closest public cases, scaled to your size.">
        <div className="flex flex-col divide-y divide-line">
          {major.map((c, i) => {
            const g = gap(c.key);
            const cases = (r.comparables[c.key] ?? []).slice(0, i < 3 ? 3 : 2);
            return (
              <div key={c.key} className="py-5">
                <div className="grid gap-x-8 gap-y-2 md:grid-cols-[minmax(200px,1.3fr)_auto_auto_minmax(220px,2fr)] items-start mb-3">
                  <div><h3 className="m-0 text-[15px]">{catName(c.key)}</h3><span className={`chip chip-plain ${GAP_CHIP[g.status]} mt-1.5`}>{STATUS_LABEL[g.status]}</span></div>
                  <div className="grid"><b className="num text-[22px] text-navy leading-tight">{money(c.p99)}</b><span className="caption">in a bad year</span></div>
                  <div className="grid"><b className="num text-[22px] text-navy leading-tight">{money(c.eal)}</b><span className="caption">average year</span></div>
                  <div><div className="h-2 rounded bg-paper border border-line overflow-hidden"><i className="block h-full bg-navy" style={{ width: `${Math.max(1, c.tailShare * 100)}%` }} /></div><span className="caption">{pct(c.tailShare)} of total bad-year loss. {g.note}</span></div>
                </div>
                <div className="grid gap-3 md:grid-cols-3">{cases.map((k) => <CaseCard key={k.id} c={k} />)}</div>
              </div>
            );
          })}
        </div>
        {minor.length ? <p className="caption mt-3 mb-0">Small for this deployment: {minor.map((c) => catName(c.key)).join(", ")}.</p> : null}
      </Section>

      <Section title="What would lower it">
        {levers.length ? (
          <table className="tbl max-w-[760px]">
            <thead><tr><th>Change</th><th className="text-right">Bad-year loss</th><th className="text-right">Effect</th></tr></thead>
            <tbody>{levers.map((w) => { const d = (w.to - w.from) / (w.from || 1); return <tr key={w.label}><td>{w.label}</td><td className="text-right tabular-nums whitespace-nowrap">{money(w.from)} to {money(w.to)}</td><td className={`text-right tabular-nums ${d < -0.005 ? "text-ok font-semibold" : ""}`}>{Math.abs(d) < 0.005 ? "no material change" : (d < 0 ? "down " : "up ") + pct(Math.abs(d))}</td></tr>; })}</tbody>
          </table>
        ) : <p className="caption m-0">The main controls are already in place.</p>}
        <details className="mt-3">
          <summary className="cursor-pointer caption">Model parameters for this run</summary>
          <table className="tbl mt-2 max-w-[900px]"><thead><tr><th>Category</th><th>Events per year</th><th>Frequency drivers</th><th>Severity drivers</th></tr></thead><tbody>
            {CATS.map((cat) => <tr key={cat.key}><td>{cat.name}<div className="caption">{cat.dims.map((d) => DIMS.find((x) => x[0] === d)?.[1] ?? d).join(", ")}</div></td><td className="tabular-nums">{r.frequency[cat.key]!.lambda.toFixed(3)}</td><td className="caption">{r.frequency[cat.key]!.mods.join("; ")}</td><td className="caption">n = {r.severity[cat.key]!.n}, credibility {r.severity[cat.key]!.Z.toFixed(2)}; {r.severity[cat.key]!.mods.join("; ")}</td></tr>)}
          </tbody></table>
          <p className="caption mt-2 mb-0">Scores used: {Object.entries(model.dimension_scores).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}.</p>
        </details>
      </Section>
    </div>
  );
}

function CaseCard({ c }: { c: Comparable }) {
  const loss = c.raw ? money(c.raw) : c.nearMiss ? "Near miss" : c.status === "pending" || c.status === "appealed" ? "Still in court" : "Not disclosed";
  return (
    <article className="panel border-l-2 border-l-gold px-4 py-3">
      <div className="flex justify-between items-baseline"><span className="text-[17px] font-semibold text-navy">{loss}</span><span className="caption">{c.year}</span></div>
      <h4 className="m-0 mt-1 text-[13.5px] font-medium leading-snug">{c.title}</h4>
      <div className="text-[12.5px]">{c.org}{c.analog ? " (automation analog)" : ""}</div>
      {c.scaled ? <div className="text-[12.5px] font-semibold text-gold-ink mt-1.5">About {money(c.scaled)} for a company your size</div> : null}
      <div className="caption mt-1">Like your deployment: {c.why.join(", ") || "same type of failure"}</div>
      {c.src ? <div className="caption text-[11.5px] mt-2 pt-2 border-t border-line">{c.src}</div> : null}
    </article>
  );
}

/** The declared limits the scanner checks, unchanged from before the outlook. */
function DeclaredLimits() {
  const { envelope } = useApp();
  const rows = lossRows(envelope);
  return (
    <Section title="Declared limits" caption="Limits you declared, and whether the code enforces them.">
      <div className="panel overflow-x-auto" tabIndex={0}>
        <table className="tbl">
          <thead><tr><th>Agent</th><th>Money-moving tools</th><th>Max per action</th><th>Daily aggregate</th><th>Worst-case customer loss</th><th>Enforcement</th><th>Exposure</th></tr></thead>
          <tbody>
            {rows.length === 0 ? <tr><td colSpan={7} className="caption text-center">No agent with money authority or a declared economic limit in this scan.</td></tr> : rows.map((r) => (
              <tr key={r.agent.id}>
                <td><span className="flex items-center gap-2.5"><span className="avatar" aria-hidden="true">{initials(r.name)}</span><span><a href={buildHash("inventory", r.agent.id)} className="link font-medium">{r.name}</a><div className="caption mono">{r.agent.path}</div></span></span></td>
                <td><Chips items={r.moneyTools.map((n) => ({ label: n, hot: true }))} empty={r.authority ? "capability only" : "none observed"} tone="mono" /></td>
                <td className="tabular-nums">{declaredMoney(r.maxPerAction)}</td>
                <td className="tabular-nums">{declaredMoney(r.dailyAggregate)}</td>
                <td className="tabular-nums">{declaredMoney(r.worstCase)}</td>
                <td>{r.enforcementGaps.length === 0 ? <span className="caption">{r.maxPerAction ? "no gap reported" : "nothing to enforce"}</span> : <span className="flex flex-wrap gap-1">{r.enforcementGaps.map((g) => <a key={g.finding.fingerprint} href={buildHash("findings", g.finding.fingerprint)} className="no-underline"><Pill tone="warn">{g.finding.rule_id}</Pill></a>)}</span>}</td>
                <td><ExposureBadge exposure={r.worstExposure as Exposure} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
