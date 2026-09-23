import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useApp } from "../app/context";
import { printAs } from "../app/print";
import { buildHash } from "../app/router";
import { AgentFlow } from "../components/AgentFlow";
import { SeverityBadge } from "../components/Badge";
import { money } from "../data/lossModel";
import type { TrendPoint } from "../data/lossTrend";
import { SPECTRUM_BANDS, agentSpectrum, attentionStatus, audienceLine, costOutlook, fixFirst, holdings, newestAgent, standing, whatChanged, type ChangeLine, type CostOutlook, type SpectrumRow } from "../data/overview";
import { activeFindings, countByLevel, formatDate, overviewDeltas, pluralize } from "../data/selectors";

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
      <h1 className="m-0">Overview</h1>

      <Standing cost={cost ?? null} />

      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <HoldingsTile />
        <FindingsTile />
        <CostTile cost={cost} />
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)] items-start">
        <div className="grid gap-3">
          <Attention />
          {hasAgents ? <AssessmentCard /> : null}
        </div>
        <Changed cost={cost} />
      </div>

      {hasAgents ? <AgentFlow /> : null}
    </div>
  );
}

// --- where you stand ---------------------------------------------------------------------------

function Standing({ cost }: { cost: CostOutlook | null }) {
  const { envelope } = useApp();
  const sentences = useMemo(() => standing(envelope, cost), [envelope, cost]);
  return (
    <section aria-label="Where you stand" className="mt-3 rounded-lg bg-navy text-white px-5 py-4 flex flex-wrap items-center gap-x-8 gap-y-3">
      <div className="min-w-0 flex-1 basis-[36ch]">
        <div aria-hidden="true" className="text-[11px] font-semibold tracking-[0.08em] uppercase text-[#d9bd7e]">Where you stand</div>
        <p className="mt-1.5 mb-0 text-[15.5px] leading-[1.5] text-white max-w-[72ch]">
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
    <section className="panel px-4 pt-3 pb-3 flex flex-col">
      <h2 className="eyebrow m-0">{question}</h2>
      <div className="mt-1.5 flex-1">{children}</div>
      <a href={href} className="mt-2.5 pt-2 border-t border-line text-[12.5px] font-medium text-navy no-underline hover:underline">{action} <span aria-hidden="true">→</span></a>
    </section>
  );
}

function Figure({ value, unit, tone = "neutral" }: { value: string; unit: string; tone?: "neutral" | "warn" }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2">
      <span className={`num text-[28px] leading-none ${tone === "warn" ? "text-sev-high" : "text-navy"}`}>{value}</span>
      <span className="text-[12.5px] text-ink-soft">{unit}</span>
    </div>
  );
}

/** A short, plain date for a tile: "15 Sep". */
function shortDate(iso: string | null): string {
  const text = formatDate(iso);
  return text.replace(/ \d{4}$/, "");
}

function HoldingsTile() {
  const { envelope } = useApp();
  const h = holdings(envelope);
  const audience = audienceLine(envelope);
  const newest = newestAgent(envelope);
  const delta = overviewDeltas(envelope).agents;
  return (
    <Tile question="Agent Inventory" href={buildHash("inventory")} action="View agents">
      <Figure value={String(h.agents)} unit={h.agents === 1 ? "AI agent" : "AI agents"} />
      {audience ? <p className="mt-1.5 mb-0 text-[12.5px] text-navy font-medium">{audience}</p> : null}
      <p className="mt-0.5 mb-0 text-[12.5px] text-ink-soft">{h.agents ? `${h.moneyMovers} can move money · ${pluralize(h.tools, "tool")} · ${pluralize(h.providers, "model provider")}` : "No agents were found in the scanned files."}</p>
      {newest
        ? <p className="mt-1.5 mb-0 text-[12px] text-ink-soft leading-snug">Newest: <a href={buildHash("inventory", newest.id)} className="link font-medium">{newest.name}</a>{newest.date ? `, added ${shortDate(newest.date)}` : ", added since the last scan"}, {newest.note}.</p>
        : <p className="caption mt-1.5 mb-0">{delta === null ? "No baseline to compare against" : delta.value === 0 ? "No change since last scan" : `${delta.label} since last scan`}</p>}
    </Tile>
  );
}

const SPECTRUM_DOT: Record<SpectrumRow["level"], string> = { elevated: "bg-sev-high", moderate: "bg-sev-medium", low: "bg-sev-low", none: "bg-line-strong" };

/** Each agent on one line from low to high, placed by its highest dimension score. */
function FindingsTile() {
  const { envelope } = useApp();
  const rows = agentSpectrum(envelope);
  return (
    <Tile question="Risk Mapping" href={buildHash("findings")} action="View findings">
      {rows.length ? (
        <div className="grid grid-cols-[minmax(0,1.15fr)_minmax(100px,1fr)] gap-x-3 gap-y-1.5 items-center text-[12.5px]">
          <div className="caption text-[11px]" />
          <div className="flex justify-between text-[10.5px] uppercase tracking-[0.06em] text-ink-muted" aria-hidden="true"><span>Low</span><span>Medium</span><span>High</span></div>
          {rows.map((r) => (
            <div key={r.id} className="contents">
              <div className="min-w-0 truncate"><a href={buildHash("inventory", r.id)} className="no-underline text-navy hover:underline">{r.name}</a>{r.isNew ? <span className="ml-1.5 chip chip-plain chip-high text-[10px] leading-4 py-0 px-1.5">new</span> : null}</div>
              <div className="relative h-4">
                <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-line-strong" />
                <div className="absolute top-1/2 h-1.5 w-px -translate-y-1/2 bg-line-strong" style={{ left: `${SPECTRUM_BANDS.moderate}%` }} />
                <div className="absolute top-1/2 h-1.5 w-px -translate-y-1/2 bg-line-strong" style={{ left: `${SPECTRUM_BANDS.elevated}%` }} />
                <span role="img" aria-label={r.level === "none" ? "no findings" : r.level === "elevated" ? "high" : r.level === "moderate" ? "medium" : "low"} className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ${SPECTRUM_DOT[r.level]} ${r.isNew ? "ring-2 ring-gold ring-offset-1 ring-offset-panel" : ""}`} style={{ left: `${Math.min(Math.max(r.score, 2), 98)}%` }} />
              </div>
            </div>
          ))}
        </div>
      ) : <p className="caption m-0">No agents were found in the scanned files.</p>}
    </Tile>
  );
}

function CostTile({ cost }: { cost: CostOutlook | null | undefined }) {
  const { envelope } = useApp();
  const hasAgents = envelope.registry.agents.length > 0;
  return (
    <Tile question="Estimated Failures Cost" href={buildHash("loss")} action="View financial exposure">
      {cost === undefined ? (
        <p className="caption m-0">Estimating…</p>
      ) : cost ? (
        <CostTrend cost={cost} />
      ) : (
        <>
          <div className="text-[18px] leading-tight text-navy font-medium">Not estimated yet</div>
          <p className="mt-1.5 mb-0 text-[12.5px] text-ink-soft">{hasAgents ? "A modeled figure needs your revenue, sector and records held. You can try your numbers on the next screen." : "There are no agents to model."}</p>
        </>
      )}
    </Tile>
  );
}

const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const monthShort = (iso: string) => MONTH[Number.parseInt(iso.slice(5, 7), 10) - 1] ?? "";

/**
 * The bad-year figure by month of scan, against the declared risk capacity
 * as a dotted line. Amounts sit on the points; nothing else is written.
 */
function CostTrend({ cost }: { cost: CostOutlook }) {
  const points: TrendPoint[] = cost.trend.length ? cost.trend : [{ hash: "", ref: null, date: "", agent: cost.agent, added: [], badYear: cost.badYear, averageYear: cost.averageYear }];
  const last = points[points.length - 1]!;
  if (points.length < 2) return <Figure value={money(last.badYear)} unit="in a bad year" />;
  const W = 240, H = 104, left = 8, right = 8, top = 12, bottom = 18;
  const values = [...points.map((p) => p.badYear), ...(cost.capacity !== null ? [cost.capacity] : [])];
  const max = Math.max(...values) * 1.06, min = Math.min(...values) * 0.8;
  const x = (i: number) => left + (i * (W - left - right)) / (points.length - 1);
  const y = (v: number) => top + (1 - (v - min) / (max - min)) * (H - top - bottom);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.badYear).toFixed(1)}`).join(" ");
  const over = cost.capacity !== null && last.badYear > cost.capacity;
  const label = `Modeled bad-year loss by month: ${points.map((p) => `${money(p.badYear)} in ${monthShort(p.date)}`).join(", ")}${cost.capacity !== null ? `. Risk capacity ${money(cost.capacity)}${over ? ", exceeded" : ""}` : ""}`;
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className={`num text-[28px] leading-none ${over ? "text-sev-high" : "text-navy"}`}>{money(last.badYear)}</span>
        <span className="text-[12.5px] text-ink-soft">in a bad year</span>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="block mt-1.5 max-w-[300px] overflow-visible text-[9px]">
        <title>{label}</title>
        {cost.capacity !== null ? (
          <g>
            <line x1={left} x2={W - right} y1={y(cost.capacity)} y2={y(cost.capacity)} className="stroke-sev-high" strokeDasharray="2 3" strokeWidth={1} />
            <text x={left} y={y(cost.capacity) - 3} textAnchor="start" className="fill-sev-high">Risk capacity {money(cost.capacity)}</text>
          </g>
        ) : null}
        <path d={path} className="fill-none stroke-navy [stroke-width:1.75] [stroke-linejoin:round] [stroke-linecap:round]" />
        {points.map((p, i) => {
          const isLast = i === points.length - 1;
          const above = cost.capacity !== null && p.badYear > cost.capacity;
          return (
            <g key={p.hash || i}>
              <circle cx={x(i)} cy={y(p.badYear)} r={isLast ? 3.5 : 2.5} className={above ? "fill-sev-high" : "fill-navy"} />
              <text x={x(i)} y={y(p.badYear) + (above ? -7 : 12)} textAnchor={i === 0 ? "start" : isLast ? "end" : "middle"} className={`num ${above ? "fill-sev-high" : "fill-navy"}`}>{money(p.badYear)}</text>
              <text x={x(i)} y={H - 4} textAnchor={i === 0 ? "start" : isLast ? "end" : "middle"} className="fill-ink-muted">{monthShort(p.date)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// --- needs your attention ------------------------------------------------------------------------

function Attention() {
  const { envelope } = useApp();
  const first = useMemo(() => fixFirst(envelope), [envelope]);
  const counts = countByLevel(activeFindings(envelope));
  const total = counts.high + counts.medium + counts.low;
  return (
    <section className="panel" aria-labelledby="attention-title">
      <div className="px-4 pt-3 pb-2.5">
        <h2 id="attention-title" className="m-0">Fix this first</h2>
        <div className="caption">The highest-risk finding from this scan.</div>
      </div>
      {!first ? <p className="caption px-4 pb-3 m-0 border-t border-line/70 pt-3">No open findings.</p> : (
        <div className="grid grid-cols-[68px_minmax(0,1fr)] gap-x-3 items-start px-4 py-3 border-t border-line/70">
          <span className="pt-0.5"><SeverityBadge severity={first.item.severity} /></span>
          <div className="min-w-0">
            <a href={buildHash("findings", first.item.fingerprint)} className="block text-[13.5px] font-medium leading-snug text-navy no-underline hover:underline">{first.title}</a>
            <dl className="m-0 mt-1.5 grid grid-cols-[112px_minmax(0,1fr)] gap-x-3 gap-y-1 text-[12.5px] leading-snug">
              {([["What we found", first.found], ["Why it matters", first.why], ["Fix", first.fix]] as const).filter(([, v]) => v).map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-ink-muted">{k}</dt>
                  <dd className="m-0 text-ink-soft">{v}{k === "Fix" && attentionStatus(first.item) ? <span className="text-ink-muted"> · {attentionStatus(first.item)}</span> : null}</dd>
                </div>
              ))}
            </dl>
          </div>
        </div>
      )}
      {total ? <div className="px-4 py-2.5 border-t border-line/70 flex flex-wrap items-baseline gap-x-3"><a href={buildHash("findings")} className="text-[12.5px] font-medium text-navy no-underline hover:underline">View all {pluralize(total, "finding")} <span aria-hidden="true">→</span></a><span className="caption">{counts.high} high · {counts.medium} medium · {counts.low} low</span></div> : null}
    </section>
  );
}

// --- what changed ----------------------------------------------------------------------------------

const ARROW: Record<ChangeLine["direction"], { glyph: string; label: string; className: string }> = {
  up: { glyph: "↑", label: "Increased", className: "text-sev-high" },
  down: { glyph: "↓", label: "Decreased", className: "text-ok" },
  same: { glyph: "–", label: "Unchanged", className: "text-ink-muted" },
};

function Changed({ cost }: { cost: CostOutlook | null | undefined }) {
  const { envelope } = useApp();
  const lines = useMemo(() => whatChanged(envelope, cost), [envelope, cost]);
  return (
    <section className="panel" aria-labelledby="changed-title">
      <div className="px-4 pt-3 pb-2.5">
        <h2 id="changed-title" className="m-0">What changed</h2>
        <div className="caption">{lines ? "Since the previous scan." : "Nothing to compare against yet."}</div>
      </div>
      {lines ? (
        <>
          <ul className="m-0 p-0 list-none divide-y divide-line/70 border-t border-line/70">
            {lines.map((line) => {
              const arrow = ARROW[line.direction];
              return (
                <li key={line.title} className="grid grid-cols-[18px_minmax(0,1fr)] gap-x-2 px-4 py-2.5">
                  <span className={`text-[15px] leading-5 ${arrow.className}`} role="img" aria-label={arrow.label}>{arrow.glyph}</span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium text-navy leading-snug">{line.title}</div>
                    {line.detail ? <div className="caption mt-0.5 break-words">{line.detail}</div> : null}
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="px-4 py-2.5 border-t border-line/70"><a href={buildHash("drift")} className="text-[12.5px] font-medium text-navy no-underline hover:underline">Open the change log <span aria-hidden="true">→</span></a></div>
        </>
      ) : (
        <div className="px-4 pb-3 border-t border-line/70 pt-3">
          <p className="m-0 text-[13px] text-ink-soft">This is a single scan. Compare it with a baseline to see which agents gained reach and which findings are new:</p>
          <p className="mono text-[12px] mt-2 mb-0 break-words">stoa scan . --diff-against origin/main</p>
          <a href={buildHash("drift")} className="inline-block mt-3 text-[13px] font-medium text-navy no-underline hover:underline">How baselines work <span aria-hidden="true">→</span></a>
        </div>
      )}
    </section>
  );
}

// --- the bottom row ---------------------------------------------------------------------------------

function AssessmentCard() {
  const { envelope } = useApp();
  const c = envelope.assessment.counts;
  const segments: { key: string; n: number; className: string; label: string }[] = [
    { key: "code", n: c.prefilled, className: "bg-navy", label: "From your code" },
    { key: "you", n: c.to_confirm, className: "bg-gold", label: "Needs you" },
    { key: "carrier", n: c.indicative, className: "bg-line-strong", label: "Agreed with the carrier later" },
  ];
  return (
    <section className="panel px-4 py-3.5 flex flex-wrap items-center gap-x-8 gap-y-3" aria-labelledby="assessment-title">
      <div className="min-w-0 flex-1 basis-[36ch]">
        <h2 id="assessment-title" className="m-0">Insurance assessment</h2>
        <p className="mt-1 mb-0 text-[13px] text-ink-soft"><strong className="text-navy font-semibold">{c.prefilled} of {c.total}</strong> answers came from your code. <strong className="text-navy font-semibold">{c.to_confirm}</strong> need your confirmation.</p>
        <div className="mt-3 flex gap-1" role="img" aria-label={segments.map((s) => `${s.n} ${s.label.toLowerCase()}`).join(", ")}>
          {segments.filter((s) => s.n > 0).map((s) => <span key={s.key} className={`h-1.5 rounded-full ${s.className}`} style={{ flexGrow: s.n, flexBasis: 0 }} />)}
        </div>
        <ul className="mt-2 mb-0 p-0 list-none flex flex-wrap gap-x-3 gap-y-1 caption">
          {segments.map((s) => <li key={s.key} className="flex items-center gap-1.5"><span aria-hidden="true" className={`inline-block w-2 h-2 rounded-full ${s.className}`} />{s.label}</li>)}
        </ul>
      </div>
      <a href={buildHash("evidence")} className="btn btn-primary no-underline justify-center text-center">Continue the assessment</a>
    </section>
  );
}
