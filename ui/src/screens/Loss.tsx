import { useEffect, useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash, useRoute } from "../app/router";
import { Chips } from "../components/KeyValue";
import { Section } from "../components/Section";
import { CATS, EVENTS, STATUS_LABEL, catName, money, pct, type Comparable, type GapStatus, type Indication, type Intake, type ModelAgent, type Policy, type WhatIf } from "../data/lossModel";
import { indicationFor } from "../data/lossCache";
import { agentToModel, candidateAgents, intakeFromEnvelope, intakeToToml } from "../data/lossInputs";
import { uniqueAgentOf } from "../data/agents";
import { LOSS_SEED } from "../data/overview";
import { lossTrendMax } from "../data/lossTrend";
import { activeFindings, dimensionName, formatDate } from "../data/selectors";
import type { MappingNote } from "../data/lossInputs";

const GAP_CHIP: Record<GapStatus, string> = { unprotected: "chip-critical", excluded: "chip-critical", shortfall: "chip-medium", ok: "chip-ok", minor: "chip-muted" };
const SEED = LOSS_SEED;

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
    const id = window.setTimeout(() => setResult(indicationFor(envelope, model, intake, SEED)), 30);
    return () => window.clearTimeout(id);
  }, [envelope, model, intake]);

  const toml = intakeToToml(intake, volume);
  const copy = async () => {
    try { await navigator.clipboard.writeText(toml); setCopied(true); } catch { setCopied(false); }
  };

  if (!agent || !model || !mapped) {
    return (
      <div>
        <h1 className="m-0">Financial Exposure</h1>
        <p className="caption">No agent in this scan has a dimension assessment, so there is nothing to model.</p>
      </div>
    );
  }
  const c = model.capabilities;
  const deployment = [
    intake.sector + (intake.regulated ? ", regulated" : ""),
    money(intake.revenue) + " revenue",
    intake.jurisdictions.join(" and "),
    c.financial_authority.enabled ? "moves money, up to " + money(c.financial_authority.max_per_action_usd) + " per action" : "cannot move money",
    c.human_in_loop === "none" ? "no human review detected" : "human review: " + c.human_in_loop.replace(/_/g, " "),
  ].filter(Boolean);
  const owner = uniqueAgentOf(envelope, agent.id);

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Financial Exposure</h1>
      </div>

      <div className="mt-4 flex flex-wrap items-end justify-between gap-4 pb-3 border-b border-line">
        <div className="max-w-[75ch]">
          <div className="caption">Deployment assessed</div>
          <div className="text-[13.5px] font-medium text-navy">{owner?.name ?? model.name}</div>
          <Chips items={deployment.map((label) => ({ label }))} />
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
        <Outlook r={result.r} levers={result.levers} intake={intake} model={model} notes={mapped.notes} declared={initial.declared} agentId={agent.id} />
      )}


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

function Outlook({ r, levers, intake, model, notes, declared, agentId }: { r: Indication; levers: WhatIf[]; intake: Intake; model: ModelAgent; notes: MappingNote[]; declared: boolean; agentId: string }) {
  const { envelope } = useApp();
  const S = r.summary, L = r.limits;
  const ranked = S.perCat.slice().sort((a, b) => b.tailShare - a.tailShare);
  const gap = (k: string) => r.gaps.find((g) => g.key === k)!;
  const top = ranked[0]!;
  // Two loss types are left off this list on request; they still count in the totals above.
  const shown = ranked.filter((c) => !HIDDEN_CATEGORIES.has(c.key));
  const major = shown.filter((c) => gap(c.key).status !== "minor"), minor = shown.filter((c) => gap(c.key).status === "minor");
  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="m-0 text-[26px] leading-tight tracking-tight">A bad year could cost {money(S.pMid)}</h2>
        <span className="chip chip-muted" title="A simulation from your inputs and public loss data. Not a quote, and not an observed loss.">Modeled</span>
      </div>
      <p className="mt-2 mb-5 max-w-[68ch] text-[14.5px]">An average year costs about <strong>{money(S.eal)}</strong>. {catName(top.key)} accounts for {pct(top.tailShare)} of the bad-year figure.</p>

      <Drivers r={r} intake={intake} notes={notes} declared={declared} top={top.key} agentId={agentId} />

      <LossOverTime />

      <div className="mt-3 flex flex-wrap gap-x-10 gap-y-2 rounded-lg bg-gold-100/70 px-5 py-4">
        <div className="grid"><span className="caption">Suggested coverage limit</span><b className="text-[18px] font-semibold text-navy">{money(L.lean)} to {money(L.conservative)}</b></div>
        <div className="grid"><span className="caption">Most common choice</span><b className="text-[18px] font-semibold text-navy">{money(L.standard)}</b></div>
        <div className="grid"><span className="caption">Suggested retention</span><b className="text-[18px] font-semibold text-navy">{money(r.retention)}</b></div>
        <div className="grid"><span className="caption">Confidence</span><b className="text-[18px] font-semibold text-navy">{r.confidence}</b></div>
        <a href={buildHash("evidence")} className="link self-end text-[12.5px]">Carry into the assessment schedule</a>
      </div>

      <Section title="Where the loss could come from" caption="With the closest public cases, US financial services first, each backed by a court, regulator or press record, scaled to your size.">
        <div className="flex flex-col divide-y divide-line">
          {major.map((c) => {
            const g = gap(c.key);
            const cases = relevantCases(r.comparables[c.key] ?? []).slice(0, 2);
            return (
              <div key={c.key} className="py-5">
                <div className="grid gap-x-8 gap-y-2 md:grid-cols-[minmax(200px,1.3fr)_auto_auto_minmax(220px,2fr)] items-start mb-3">
                  <div><h3 className="m-0 text-[15px]">{catName(c.key)}</h3><span className={`chip chip-plain ${GAP_CHIP[g.status]} mt-1.5`}>{STATUS_LABEL[g.status]}</span></div>
                  <div className="grid"><b className="num text-[22px] text-navy leading-tight">{money(c.p99)}</b><span className="caption">in a bad year</span></div>
                  <div className="grid"><b className="num text-[22px] text-navy leading-tight">{money(c.eal)}</b><span className="caption">average year</span></div>
                  <div><div className="h-2 rounded bg-paper border border-line overflow-hidden"><i className="block h-full bg-navy" style={{ width: `${Math.max(1, c.tailShare * 100)}%` }} /></div><span className="caption">{pct(c.tailShare)} of total bad-year loss. {g.note}</span></div>
                </div>
                {cases.length ? <div className="grid gap-3 md:grid-cols-2 max-w-[900px]">{cases.map((k) => <CaseCard key={k.id} c={k} />)}</div> : <p className="caption m-0">No public case with a court, regulator or press record fits this loss type closely enough to show.</p>}
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
            {CATS.map((cat) => <tr key={cat.key}><td>{cat.name}<div className="caption">{cat.dims.map((d) => dimensionName(envelope, d.replace(/_/g, "-"))).join(", ")}</div></td><td className="tabular-nums">{r.frequency[cat.key]!.lambda.toFixed(3)}</td><td className="caption">{r.frequency[cat.key]!.mods.join("; ")}</td><td className="caption">n = {r.severity[cat.key]!.n}, credibility {r.severity[cat.key]!.Z.toFixed(2)}; {r.severity[cat.key]!.mods.join("; ")}</td></tr>)}
          </tbody></table>
          <p className="caption mt-2 mb-0">Scores used: {Object.entries(model.dimension_scores).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(" · ")}.</p>
        </details>
      </Section>
    </div>
  );
}

/** What the estimate rests on, by where each input came from. */
function Drivers({ r, intake, notes, declared, top, agentId }: { r: Indication; intake: Intake; notes: MappingNote[]; declared: boolean; top: string; agentId: string }) {
  const { envelope } = useApp();
  const isDeclared = (n: MappingNote) => /^declared /.test(n.from);
  const isAssumed = (n: MappingNote) => /assumed|model default/.test(n.from);
  const fromScan = notes.filter((n) => !isDeclared(n) && !isAssumed(n) && n.input !== "Scan scores");
  const fromYou = notes.filter(isDeclared);
  const assumed = notes.filter(isAssumed);
  const cover = intake.existing_coverage.map((p) => `${p.type === "tech_eo" ? "tech E&O" : p.type} ${money(p.limit)}${p.ai_exclusion ? ", AI excluded" : ""}`);
  const business = [`${money(intake.revenue)} revenue`, intake.sector, intake.jurisdictions.join(" and "), intake.regulated ? "regulated" : "not regulated", `${money(intake.records).replace("$", "")} records`, ...cover];
  // Does the biggest driver rest on anything the scan found? Its loss category maps to dimensions; look for findings there on this agent.
  const category = CATS.find((c) => c.key === top);
  const owner = uniqueAgentOf(envelope, agentId);
  const dims = new Set((category?.dims ?? []).map((d) => d.replace(/_/g, "-")));
  const backing = activeFindings(envelope).filter((f) => (!owner || f.uniqueAgents.includes(owner)) && (f.finding.dimensions ?? []).some((d) => dims.has(d))).length;
  const share = r.summary.perCat.find((c) => c.key === top)?.tailShare ?? 0;
  return (
    <section className="panel px-5 py-4 mt-1" aria-labelledby="drivers-title">
      <h3 id="drivers-title" className="m-0 text-[15px]">What drives this estimate</h3>
      <dl className="mt-3 mb-0 grid gap-x-8 gap-y-3 md:grid-cols-3 text-[13px]">
        <div>
          <dt className="eyebrow">From the scan</dt>
          <dd className="m-0 mt-1.5"><ul className="m-0 p-0 list-none flex flex-col gap-1">{fromScan.map((n) => <li key={n.input}>{n.input}: <strong className="font-medium text-navy">{n.input === "Human review" && n.value === "none" ? "none detected" : n.value}</strong></li>)}<li>Exposure scores in all eight dimensions</li></ul></dd>
        </div>
        <div>
          <dt className="eyebrow flex items-center gap-1.5">Declared by you {declared ? <span className="chip chip-muted normal-case tracking-normal" title="From your declared business details. Not verified by the scan.">declared</span> : null}</dt>
          <dd className="m-0 mt-1.5">
            {declared ? <Chips items={business.map((label) => ({ label }))} /> : <span className="caption">Nothing declared yet, so revenue, sector and records are placeholders. Adjust the inputs above.</span>}
            {fromYou.length ? <ul className="m-0 mt-2 p-0 list-none flex flex-col gap-1">{fromYou.map((n) => <li key={n.input}>{n.input}: <strong className="font-medium text-navy">{n.value}</strong></li>)}</ul> : null}
            {assumed.length ? <p className="caption mt-2 mb-0">Assumed, because not declared: {assumed.map((n) => `${n.input.toLowerCase()} (${n.value})`).join(", ")}.</p> : null}
          </dd>
        </div>
        <div>
          <dt className="eyebrow">From Stoa's loss data</dt>
          <dd className="m-0 mt-1.5">{r.dataset.events} public AI and automation loss events, scaled to a company your size. Assumptions version <span className="mono">{r.assumptions_version}</span>, not yet actuarially reviewed.</dd>
        </div>
      </dl>
      {category && backing === 0 ? <p className="mt-3 mb-0 pt-3 border-t border-line text-[13px]"><strong className="font-medium text-navy">{category.name}</strong> is the largest driver at {pct(share)} of a bad year. Driven by your business profile and data handled, not by scan findings.</p> : null}
    </section>
  );
}

/**
 * Cases shown as references, at most two per loss type. US financial services
 * first; then, when that gives fewer than two, other US sectors; then other
 * countries. Always under a few hundred million dollars, and either backed by
 * a graded court, regulator or press record or a documented near miss with no
 * dollar figure. The model's fitting still uses every event; this filters
 * only what is shown.
 */
const FINANCIAL_SECTORS = new Set(["fintech", "insurance", "banking", "payments", "lending"]);
const CASE_CAP = 300e6;
const HIDDEN_CATEGORIES = new Set(["loss", "perf"]);
export function relevantCases(cases: Comparable[], limit = 2): Comparable[] {
  const byId = new Map(EVENTS.map((e) => [e.id, e]));
  const credible = cases.filter((c) => {
    const e = byId.get(c.id);
    if (!e) return false;
    if (c.raw !== null && c.raw > CASE_CAP) return false;
    const recorded = Boolean(c.src) && (c.grade === "A" || c.grade === "B");
    const nearMiss = c.raw === null && c.nearMiss;
    return recorded || nearMiss;
  });
  const tiers = [
    (id: string) => { const e = byId.get(id)!; return e.jur === "US" && FINANCIAL_SECTORS.has(e.sector); },
    (id: string) => byId.get(id)!.jur === "US",
    () => true,
  ];
  // Within a tier, a case with a recorded figure comes before a documented near miss.
  const ordered = [...credible].sort((a, b) => Number(b.raw !== null) - Number(a.raw !== null));
  const out: Comparable[] = [];
  for (const tier of tiers) {
    for (const c of ordered) if (out.length < limit && !out.includes(c) && tier(c.id)) out.push(c);
    if (out.length >= limit) break;
  }
  return out;
}

/** The largest single-agent bad-year loss at each past scan, with today's business inputs: the line moves only when the code did. */
function LossOverTime() {
  const { envelope } = useApp();
  // The largest single-agent figure at each scan: bad years do not add across agents.
  const points = useMemo(() => lossTrendMax(envelope, SEED), [envelope]);
  if (points.length < 2) return null;
  const W = 760, H = 200, L = 64, R = 20, T = 16, B = 40;
  const values = points.map((p) => p.badYear);
  const top = Math.max(...values) * 1.15, bottom = Math.min(0, Math.min(...values));
  const t0 = Date.parse(points[0]!.date), t1 = Date.parse(points[points.length - 1]!.date);
  const X = (d: string) => L + (t1 === t0 ? 0.5 : (Date.parse(d) - t0) / (t1 - t0)) * (W - L - R);
  const Y = (v: number) => T + (1 - (v - bottom) / Math.max(top - bottom, 1)) * (H - T - B);
  const path = points.map((p, i) => `${i ? "L" : "M"}${X(p.date).toFixed(1)},${Y(p.badYear).toFixed(1)}`).join(" ");
  const ticks = [0.25, 0.5, 0.75, 1].map((f) => bottom + (top - bottom) * f);
  const first = points[0]!, last = points[points.length - 1]!;
  const change = last.badYear - first.badYear;
  const label = `Modeled bad-year loss over ${points.length} scans, ${formatDate(first.date)} to ${formatDate(last.date)}: ${money(first.badYear)} to ${money(last.badYear)}`;
  return (
    <section className="panel px-5 py-4 mt-4" aria-labelledby="loss-over-time-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="loss-over-time-title" className="m-0 text-[15px]">How the modeled loss has moved</h3>
        <span className="caption">{money(first.badYear)} on {formatDate(first.date)} to {money(last.badYear)} on {formatDate(last.date)}: <span className={change > 0 ? "text-sev-high" : change < 0 ? "text-ok" : ""}>{change > 0 ? "up" : change < 0 ? "down" : "level"}{change ? ` ${money(Math.abs(change))}` : ""}</span></span>
      </div>
      <p className="caption mt-1 mb-2">Each point is a scanned commit, modeled with today's business inputs, so the line moves only when the code did. It follows whichever agent could cost the most at that scan.</p>
      <div className="overflow-x-auto">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="block w-full h-auto min-w-[520px]">
          <title>{label}</title>
          {ticks.map((v) => <g key={v}><line x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} className="stroke-line" /><text x={L - 8} y={Y(v) + 4} fontSize="11.5" textAnchor="end" className="fill-ink-muted">{money(v)}</text></g>)}
          <path d={path} className="fill-none stroke-navy [stroke-width:2.2] [stroke-linejoin:round] [stroke-linecap:round]" />
          {points.map((p, i) => (
            <g key={p.hash}>
              <circle cx={X(p.date)} cy={Y(p.badYear)} r={i === points.length - 1 ? 5 : 3.5} className={i === points.length - 1 ? "fill-gold stroke-navy [stroke-width:1.5]" : "fill-navy"} />
              <text x={X(p.date)} y={H - B + 18} fontSize="11.5" textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} className="fill-ink-muted">{formatDate(p.date)}{p.ref ? ` · ${p.ref}` : ""}</text>
              <text x={X(p.date)} y={Y(p.badYear) - 24} fontSize="12" fontWeight="600" textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} className="fill-navy">{money(p.badYear)}</text>
              <text x={X(p.date)} y={Y(p.badYear) - 10} fontSize="11" textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"} className="fill-ink-muted">{p.agent}{p.added.length ? ` · ${p.added.join(", ")} added` : ""}</text>
            </g>
          ))}
        </svg>
      </div>
    </section>
  );
}

function CaseCard({ c }: { c: Comparable }) {
  const loss = c.raw ? money(c.raw) : c.nearMiss ? "Near miss" : c.status === "pending" || c.status === "appealed" ? "Still in court" : "Not disclosed";
  return (
    <article className="panel px-4 py-3">
      <div className="flex justify-between items-baseline"><span className="text-[17px] font-semibold text-navy">{loss}</span><span className="caption">{c.year}</span></div>
      <h4 className="m-0 mt-1 text-[13.5px] font-medium leading-snug">{c.title}</h4>
      <div className="text-[12.5px]">{c.org}{c.analog ? " (automation analog)" : ""}</div>
      {c.scaled ? <div className="text-[12.5px] font-semibold text-gold-ink mt-1.5">About {money(c.scaled)} for a company your size</div> : null}
      <div className="caption mt-1">Like your deployment: {c.why.join(", ") || "same type of failure"}</div>
      {c.src ? <div className="caption text-[11.5px] mt-2 pt-2 border-t border-line">{c.src}</div> : null}
    </article>
  );
}

