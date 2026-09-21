import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useApp } from "../app/context";
import { printAs } from "../app/print";
import { buildHash } from "../app/router";
import { SeverityBadge } from "../components/Badge";
import { ExposureTip } from "../components/InfoTip";
import { money } from "../data/lossModel";
import { attention, attentionStatus, costOutlook, elevatedDimensions, holdings, nextAction, otherDimensionsLine, protection, registerCard, standing, whatChanged, type AttentionItem, type ChangeLine, type CostOutlook } from "../data/overview";
import { activeFindings, countByLevel, overviewDeltas, pluralize, RISK_LEVELS, type RiskLevel } from "../data/selectors";

/** The loss model takes about a tenth of a second, so it runs after first paint. `undefined` is "not yet". */
function useCostOutlook(): CostOutlook | null | undefined {
  const { envelope } = useApp();
  const [cost, setCost] = useState<CostOutlook | null | undefined>(undefined);
  useEffect(() => {
    const timer = window.setTimeout(() => setCost(costOutlook(envelope)), 0);
    return () => window.clearTimeout(timer);
  }, [envelope]);
  return cost;
}

export function Overview() {
  const { envelope } = useApp();
  const cost = useCostOutlook();
  const hasAgents = envelope.registry.agents.length > 0;

  // Scope strip (in the shell), verdict band, four tiles, two panels, three footer cards. Nothing else.
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Overview</h1>
        <div className="caption">What the code makes possible, not what has happened.</div>
      </div>

      <Standing cost={cost ?? null} />

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <HoldingsTile />
        <FindingsTile />
        <ProtectionTile />
        <CostTile cost={cost} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)] items-start">
        <Attention />
        <Changed />
      </div>

      {hasAgents ? (
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3 items-stretch">
          <ElevatedCard />
          <RegisterCardPanel />
          <AssessmentCard />
        </div>
      ) : null}
    </div>
  );
}

// --- where you stand ---------------------------------------------------------------------------

function Standing({ cost }: { cost: CostOutlook | null }) {
  const { envelope } = useApp();
  const sentences = useMemo(() => standing(envelope, cost), [envelope, cost]);
  return (
    <section aria-label="Where you stand" className="mt-4 rounded-xl bg-navy text-white px-6 py-5 flex flex-wrap items-center gap-x-8 gap-y-4">
      <div className="min-w-0 flex-1 basis-[36ch]">
        <div aria-hidden="true" className="text-[11px] font-semibold tracking-[0.08em] uppercase text-[#d9bd7e]">Where you stand</div>
        <p className="mt-2 mb-0 text-[17px] leading-[1.55] text-white max-w-[62ch]">
          {sentences.map((sentence, i) => (
            <span key={i}>
              {i ? " " : ""}
              {sentence.map((part, j) => (typeof part === "string" ? <span key={j}>{part}</span> : <strong key={j} className="font-semibold text-[#e3c88a]">{part.strong}</strong>))}
            </span>
          ))}
        </p>
      </div>
      <div className="no-print w-full sm:w-auto">
        <button type="button" onClick={() => printAs("summary")} className="w-full rounded-md px-4 py-2 text-[13px] font-semibold bg-[#d9bd7e] text-navy hover:bg-[#e3c88a] cursor-pointer border-0">Export board report</button>
      </div>
    </section>
  );
}

// --- the four tiles ------------------------------------------------------------------------------

function Tile({ question, children, href, action }: { question: string; children: ReactNode; href: string; action: string }) {
  return (
    <section className="panel p-4 flex flex-col">
      <h2 className="eyebrow m-0">{question}</h2>
      <div className="mt-2 flex-1">{children}</div>
      <a href={href} className="mt-4 pt-3 border-t border-line text-[13px] font-medium text-navy no-underline hover:underline">{action} <span aria-hidden="true">→</span></a>
    </section>
  );
}

function Figure({ value, unit, tone = "neutral" }: { value: string; unit: string; tone?: "neutral" | "warn" }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2">
      <span className={`num text-[34px] leading-none ${tone === "warn" ? "text-sev-high" : "text-navy"}`}>{value}</span>
      <span className="text-[13.5px] text-ink-soft">{unit}</span>
    </div>
  );
}

function HoldingsTile() {
  const { envelope } = useApp();
  const h = holdings(envelope);
  const delta = overviewDeltas(envelope).agents;
  return (
    <Tile question="What we have" href={buildHash("inventory")} action="View agents">
      <Figure value={String(h.agents)} unit={h.agents === 1 ? "AI agent" : "AI agents"} />
      <p className="mt-2 mb-0 text-[13px] text-ink-soft">{h.agents ? `${h.moneyMovers} with payment capability · ${pluralize(h.tools, "tool")} · ${pluralize(h.providers, "model provider")}` : "No agents were found in the scanned files."}</p>
      {h.records !== h.agents ? <p className="caption mt-1 mb-0">{h.records} discovered records</p> : null}
      <p className="caption mt-2 mb-0">{delta === null ? "No baseline to compare against" : delta.value === 0 ? "No change since last scan" : `${delta.label} since last scan`}</p>
    </Tile>
  );
}

const LEVEL_BAR: Record<RiskLevel, string> = { high: "bg-sev-high", medium: "bg-sev-medium", low: "bg-sev-low" };

function FindingsTile() {
  const { envelope } = useApp();
  const counts = countByLevel(activeFindings(envelope));
  const total = counts.high + counts.medium + counts.low;
  const delta = overviewDeltas(envelope).findings;
  return (
    <Tile question="What is wrong" href={buildHash("findings")} action="View findings">
      <Figure value={String(counts.high)} unit={counts.high === 1 ? "high-severity finding" : "high-severity findings"} tone={counts.high ? "warn" : "neutral"} />
      {total ? (
        <div className="mt-3 flex gap-1" role="img" aria-label={`${counts.high} high, ${counts.medium} medium, ${counts.low} low`}>
          {RISK_LEVELS.filter((level) => counts[level] > 0).map((level) => <span key={level} className={`h-1.5 rounded-full ${LEVEL_BAR[level]}`} style={{ flexGrow: counts[level], flexBasis: 0, minWidth: 6 }} />)}
        </div>
      ) : null}
      <p className="mt-2 mb-0 text-[13px] text-ink-soft">{total ? `${counts.medium} medium · ${counts.low} low · ${total} in total` : "No open findings."}</p>
      {delta ? <p className={`mt-2 mb-0 text-[12px] ${delta.value > 0 ? "text-sev-high font-medium" : "text-ink-muted"}`}>{delta.value > 0 ? `+${delta.value} high since last scan` : delta.value < 0 ? `${delta.value} high since last scan` : "No new high since last scan"}</p> : null}
    </Tile>
  );
}

function ProtectionTile() {
  const { envelope } = useApp();
  const p = protection(envelope);
  const exposed = p.moneyMovers > 0 && p.approved < p.moneyMovers;
  return (
    <Tile question="Are we protected" href={buildHash("controls")} action="View safeguards">
      {p.moneyMovers ? (
        <>
          <Figure value={`${p.approved} of ${p.moneyMovers}`} unit="" tone={exposed ? "warn" : "neutral"} />
          <p className="mt-1 mb-0 text-[13.5px] text-ink-soft">Human approval detected on {p.approved} of {pluralize(p.moneyMovers, "agent")} that can move money</p>
        </>
      ) : (
        <>
          <Figure value="0" unit="agents can move money" />
          <p className="mt-1 mb-0 text-[13.5px] text-ink-soft">No payment tools or payment access were detected.</p>
        </>
      )}
      {p.moneyTools ? <p className="mt-2 mb-0 text-[13px] text-ink-soft">{p.moneyToolsWithoutGuardrail} of {pluralize(p.moneyTools, "tool")} that can move money {p.moneyToolsWithoutGuardrail === 1 ? "has" : "have"} no guardrail detected</p> : null}
    </Tile>
  );
}

function CostTile({ cost }: { cost: CostOutlook | null | undefined }) {
  const { envelope } = useApp();
  const hasAgents = envelope.registry.agents.length > 0;
  return (
    <Tile question="What it could cost" href={buildHash("loss")} action="View financial exposure">
      {cost === undefined ? (
        <p className="caption m-0">Estimating…</p>
      ) : cost ? (
        <>
          <Figure value={money(cost.badYear)} unit="in a bad year" />
          <p className="mt-2 mb-0 text-[13px] text-ink-soft">Modeled. An average year is about {money(cost.averageYear)}.</p>
          {/* The model runs per agent and a 1 in 100 year does not add across agents, so this is the largest one, named. */}
          <p className="caption mt-1 mb-0">1 year in 100, for {cost.agent}, the agent with the largest figure.</p>
          {cost.excluding.length ? <p className="mt-2 mb-0 text-[12.5px] text-ink-soft flex flex-wrap items-center gap-1.5">Declared cover for AI losses: <strong className={cost.covered === 0 ? "text-sev-high" : "text-navy"}>{money(cost.covered)}</strong><span className="chip chip-muted" title="From your declared insurance details. Not a reviewed policy.">declared</span></p> : null}
        </>
      ) : (
        <>
          <div className="text-[20px] leading-tight text-navy font-medium">Not estimated yet</div>
          <p className="mt-2 mb-0 text-[13px] text-ink-soft">{hasAgents ? "A modeled figure needs your revenue, sector and records held. You can try your numbers on the next screen." : "There are no agents to model."}</p>
        </>
      )}
    </Tile>
  );
}

// --- needs your attention ------------------------------------------------------------------------

function Attention() {
  const { envelope } = useApp();
  const items = useMemo(() => attention(envelope), [envelope]);
  const total = activeFindings(envelope).length;
  return (
    <section className="panel" aria-labelledby="attention-title">
      <div className="px-5 pt-4 pb-3">
        <h2 id="attention-title" className="m-0">Needs your attention</h2>
        <div className="caption">Highest severity first. The same problem on several agents is shown once.</div>
      </div>
      {!items.length ? <p className="caption px-5 pb-4 m-0">No open findings.</p> : (
        <ol className="m-0 p-0 list-none divide-y divide-line/70 border-t border-line/70">
          {items.map((item) => <AttentionRow key={item.ruleId} item={item} />)}
        </ol>
      )}
      {total ? <div className="px-5 py-3 border-t border-line/70"><a href={buildHash("findings")} className="text-[13px] font-medium text-navy no-underline hover:underline">View all {pluralize(total, "finding")} <span aria-hidden="true">→</span></a></div> : null}
    </section>
  );
}

function AttentionRow({ item }: { item: AttentionItem }) {
  const who = item.agents.length === 0 ? "Repository" : item.agents.length === 1 ? item.agents[0]! : pluralize(item.agents.length, "agent");
  const action = nextAction(item);
  return (
    <li className="grid grid-cols-[72px_minmax(0,1fr)] gap-x-3 items-start px-5 py-3">
      <span className="pt-0.5"><SeverityBadge severity={item.severity} /></span>
      <div className="min-w-0">
        <a href={buildHash("findings", item.fingerprint)} className="block text-[14px] font-medium leading-snug text-navy no-underline hover:underline">{item.title}</a>
        <div className="caption mt-0.5" title={item.agents.join(", ")}>{[who, item.dimension, attentionStatus(item)].filter(Boolean).join(" · ")}</div>
        {action ? <div className="text-[12.5px] text-ink-soft mt-1"><span className="font-medium text-navy">Next action.</span> {action}</div> : null}
      </div>
    </li>
  );
}

// --- what changed ----------------------------------------------------------------------------------

const ARROW: Record<ChangeLine["direction"], { glyph: string; label: string; className: string }> = {
  up: { glyph: "↑", label: "Increased", className: "text-sev-high" },
  down: { glyph: "↓", label: "Decreased", className: "text-ok" },
  same: { glyph: "–", label: "Unchanged", className: "text-ink-muted" },
};

function Changed() {
  const { envelope } = useApp();
  const lines = useMemo(() => whatChanged(envelope), [envelope]);
  return (
    <section className="panel" aria-labelledby="changed-title">
      <div className="px-5 pt-4 pb-3">
        <h2 id="changed-title" className="m-0">What changed</h2>
        <div className="caption">{lines ? "Since the previous scan." : "Nothing to compare against yet."}</div>
      </div>
      {lines ? (
        <>
          <ul className="m-0 p-0 list-none divide-y divide-line/70 border-t border-line/70">
            {lines.map((line) => {
              const arrow = ARROW[line.direction];
              return (
                <li key={line.title} className="grid grid-cols-[18px_minmax(0,1fr)] gap-x-2 px-5 py-3">
                  <span className={`text-[15px] leading-5 ${arrow.className}`} role="img" aria-label={arrow.label}>{arrow.glyph}</span>
                  <div className="min-w-0">
                    <div className="text-[13.5px] font-medium text-navy leading-snug">{line.title}</div>
                    {line.detail ? <div className="caption mt-0.5 break-words">{line.detail}</div> : null}
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="px-5 py-3 border-t border-line/70"><a href={buildHash("drift")} className="text-[13px] font-medium text-navy no-underline hover:underline">Open the change log <span aria-hidden="true">→</span></a></div>
        </>
      ) : (
        <div className="px-5 pb-4 border-t border-line/70 pt-3">
          <p className="m-0 text-[13px] text-ink-soft">This is a single scan. Compare it with a baseline to see which agents gained reach and which findings are new:</p>
          <p className="mono text-[12px] mt-2 mb-0 break-words">stoa scan . --diff-against origin/main</p>
          <a href={buildHash("drift")} className="inline-block mt-3 text-[13px] font-medium text-navy no-underline hover:underline">How baselines work <span aria-hidden="true">→</span></a>
        </div>
      )}
    </section>
  );
}

// --- the bottom row ---------------------------------------------------------------------------------

function ElevatedCard() {
  const { envelope } = useApp();
  const dims = elevatedDimensions(envelope);
  const others = otherDimensionsLine(envelope);
  return (
    <section className="panel p-5 flex flex-col" aria-labelledby="elevated-title">
      <div className="flex items-center gap-1.5"><h2 id="elevated-title" className="m-0">Where exposure is elevated</h2><ExposureTip align="left" /></div>
      {!dims.length ? <p className="caption mt-2 mb-0">No dimension is at elevated exposure in this scan.</p> : (
        <ul className="mt-3 mb-0 p-0 list-none space-y-3">
          {dims.map((d) => (
            <li key={d.id} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-3 items-center">
              <a href={buildHash("findings", null, { dimension: d.id })} className="min-w-0 no-underline text-ink hover:underline">
                <span className="block text-[13.5px] font-medium text-navy leading-snug">{d.name}</span>
                <span className="caption block mt-0.5">{d.definition}</span>
              </a>
              <span className="text-[12.5px] text-ink-soft whitespace-nowrap">{pluralize(d.findings, "finding")}</span>
              <span className="chip chip-high">Elevated</span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex-1" />
      <p className="caption mt-4 mb-0 pt-3 border-t border-line">{dims.length ? `${others} ` : ""}A finding can affect more than one dimension. <a href={buildHash("findings")} className="link">See all {envelope.taxonomy.dimensions.length}</a></p>
    </section>
  );
}

const TREATMENT_WORD: Record<string, string> = { transfer: "marked for transfer", mitigate: "being mitigated", accept: "accepted", avoid: "being avoided" };

function RegisterCardPanel() {
  const { envelope } = useApp();
  const r = registerCard(envelope);
  // Whatever treatments the register holds, as it holds them. No owners, dates or overdue counts: Stoa has no such workflow.
  const parts = [...r.treatments.map(([t, n]) => `${n} ${TREATMENT_WORD[t] ?? t}`), r.awaiting ? `${r.awaiting} with no treatment recorded` : ""].filter(Boolean);
  return (
    <section className="panel p-5 flex flex-col" aria-labelledby="register-title">
      <h2 id="register-title" className="m-0">Risk register</h2>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="num text-[34px] leading-none text-navy">{r.risks}</span>
        <span className="text-[13.5px] text-ink-soft">{r.risks === 1 ? "risk recorded" : "risks recorded"}</span>
      </div>
      <p className="mt-2 mb-0 text-[13px] text-ink-soft flex-1">{r.risks ? parts.join(" · ") : "The scan reported no risks above low exposure."}</p>
      {r.stale ? <p className="caption mt-2 mb-0">{pluralize(r.stale, "declared risk")} no longer {r.stale === 1 ? "matches" : "match"} the scan.</p> : null}
      <a href={buildHash("register")} className="mt-4 pt-3 border-t border-line text-[13px] font-medium text-navy no-underline hover:underline">Open the register <span aria-hidden="true">→</span></a>
    </section>
  );
}

function AssessmentCard() {
  const { envelope } = useApp();
  const c = envelope.assessment.counts;
  const segments: { key: string; n: number; className: string; label: string }[] = [
    { key: "code", n: c.prefilled, className: "bg-navy", label: "From your code" },
    { key: "you", n: c.to_confirm, className: "bg-gold", label: "Needs you" },
    { key: "carrier", n: c.indicative, className: "bg-line-strong", label: "Agreed with the carrier later" },
  ];
  return (
    <section className="panel p-5 flex flex-col md:col-span-2 xl:col-span-1" aria-labelledby="assessment-title">
      <h2 id="assessment-title" className="m-0">Insurance assessment</h2>
      <p className="mt-3 mb-0 text-[13.5px] text-ink-soft"><strong className="text-navy font-semibold">{c.prefilled} of {c.total}</strong> answers came from your code. <strong className="text-navy font-semibold">{c.to_confirm}</strong> need your confirmation.</p>
      <div className="mt-3 flex gap-1" role="img" aria-label={segments.map((s) => `${s.n} ${s.label.toLowerCase()}`).join(", ")}>
        {segments.filter((s) => s.n > 0).map((s) => <span key={s.key} className={`h-1.5 rounded-full ${s.className}`} style={{ flexGrow: s.n, flexBasis: 0 }} />)}
      </div>
      <ul className="mt-2 mb-0 p-0 list-none flex flex-wrap gap-x-3 gap-y-1 caption">
        {segments.map((s) => <li key={s.key} className="flex items-center gap-1.5"><span aria-hidden="true" className={`inline-block w-2 h-2 rounded-full ${s.className}`} />{s.label}</li>)}
      </ul>
      <div className="flex-1" />
      <a href={buildHash("evidence")} className="btn btn-primary no-underline mt-4 justify-center text-center">Continue the assessment</a>
    </section>
  );
}
