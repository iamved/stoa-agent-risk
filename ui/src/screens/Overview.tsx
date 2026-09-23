import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useApp } from "../app/context";
import { printAs } from "../app/print";
import { buildHash } from "../app/router";
import { AgentFlow } from "../components/AgentFlow";
import { SeverityBadge } from "../components/Badge";
import { money } from "../data/lossModel";
import type { TrendPoint } from "../data/lossTrend";
import { attention, attentionStatus, attentionTitle, audienceLine, costOutlook, highLines, holdings, newHighLine, newestAgent, nextAction, protectionCard, scanSaw, standing, whatChanged, whyItMatters, type AttentionItem, type ChangeLine, type CostOutlook } from "../data/overview";
import { activeFindings, countByLevel, formatDate, overviewDeltas, pluralize, RISK_LEVELS, RISK_SEVERITIES, type RiskLevel } from "../data/selectors";

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

      <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <HoldingsTile />
        <FindingsTile />
        <ProtectionTile />
        <CostTile cost={cost} />
      </div>

      <div className="mt-3 grid gap-3 xl:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)] items-start">
        <Attention />
        <Changed cost={cost} />
      </div>

      {hasAgents ? <div className="mt-3"><AssessmentCard /></div> : null}

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

const LEVEL_BAR: Record<RiskLevel, string> = { high: "bg-sev-high", medium: "bg-sev-medium", low: "bg-sev-low" };

function FindingsTile() {
  const { envelope } = useApp();
  const active = activeFindings(envelope);
  const counts = countByLevel(active);
  const total = counts.high + counts.medium + counts.low;
  const high = highLines(envelope);
  const fresh = newHighLine(envelope);
  return (
    <Tile question="Risk Mapping" href={buildHash("findings", null, { severity: RISK_SEVERITIES.high.join(",") })} action="View high-severity findings">
      <Figure value={String(counts.high)} unit={counts.high === 1 ? "high-severity finding" : "high-severity findings"} tone={counts.high ? "warn" : "neutral"} />
      {high.length ? (
        <ul className="mt-1.5 mb-0 p-0 list-none flex flex-col gap-1">
          {high.slice(0, 4).map((line) => (
            <li key={line.fingerprint} className="text-[12px] leading-snug text-ink-soft flex gap-1.5 items-baseline">
              <span aria-hidden="true" className="inline-block w-1.5 h-1.5 rounded-full bg-sev-high flex-none translate-y-[-1px]" />
              <a href={buildHash("findings", line.fingerprint)} className="no-underline text-ink-soft hover:underline"><span className="font-medium text-navy">{line.agents.join(", ")}</span>: {line.title.replace(/^[A-Z](?![A-Z])/, (c) => c.toLowerCase())}</a>
            </li>
          ))}
          {high.length > 4 ? <li className="caption">and {pluralize(high.length - 4, "more")}</li> : null}
        </ul>
      ) : null}
      {total ? (
        <div className="mt-2 flex gap-1" role="img" aria-label={`${counts.high} high, ${counts.medium} medium, ${counts.low} low`}>
          {RISK_LEVELS.filter((level) => counts[level] > 0).map((level) => <span key={level} className={`h-1 rounded-full ${LEVEL_BAR[level]}`} style={{ flexGrow: counts[level], flexBasis: 0, minWidth: 6 }} />)}
        </div>
      ) : null}
      <p className="caption mt-1.5 mb-0">{total ? `${counts.high} high · ${counts.medium} medium · ${counts.low} low · ${total} in total` : "No open findings."}</p>
      {fresh ? <p className={`mt-0.5 mb-0 text-[12px] ${fresh.startsWith("+") ? "text-sev-high font-medium" : "text-ink-muted"}`}>{fresh}</p> : null}
    </Tile>
  );
}

function ProtectionTile() {
  const { envelope } = useApp();
  const p = protectionCard(envelope);
  const exposed = p.moneyMovers > 0 && p.approved < p.moneyMovers;
  return (
    <Tile question="Protection Level" href={buildHash("controls")} action="View safeguards">
      {p.moneyMovers ? (
        <>
          <Figure value={`${p.approved} of ${p.moneyMovers}`} unit="" tone={exposed ? "warn" : "neutral"} />
          <p className="mt-0.5 mb-0 text-[12.5px] text-ink-soft">Human approval detected on {p.approved} of {pluralize(p.moneyMovers, "agent")} that can move money</p>
        </>
      ) : (
        <>
          <Figure value="0" unit="agents can move money" />
          <p className="mt-0.5 mb-0 text-[12.5px] text-ink-soft">No payment tools or payment access were detected.</p>
        </>
      )}
      {p.scorecard.length ? (
        <dl className="mt-2 mb-0 grid grid-cols-[1fr_auto] gap-x-3 gap-y-0.5 text-[12px] leading-snug">
          {p.scorecard.map((c) => (
            <div key={c.id} className="contents">
              <dt className="text-ink-soft">{c.short}</dt>
              <dd className={`m-0 tabular-nums text-right ${c.detected === 0 && c.applicable ? "text-sev-high font-medium" : "text-navy"}`}>{c.detected} of {c.applicable}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {p.least ? <p className="mt-1.5 mb-0 text-[12px] text-ink-soft leading-snug">Least protected: <span className="font-medium text-navy">{p.least.agents.join(", ")}</span>, {p.least.detected} of {pluralize(p.least.of, "safeguard")} detected{p.least.agents.length > 1 ? " each" : ""}.</p> : null}
      {p.moneyTools ? <p className="mt-1 mb-0 text-[12px] text-ink-soft leading-snug">{p.moneyToolsWithoutGuardrail} of {pluralize(p.moneyTools, "tool")} that can move money {p.moneyToolsWithoutGuardrail === 1 ? "has" : "have"} no guardrail detected{p.doublePostFingerprint ? <>; <a href={buildHash("findings", p.doublePostFingerprint)} className="link">one can charge twice on retry</a></> : null}.</p> : null}
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
        <>
          <CostTrend cost={cost} />
          <p className="caption mt-1.5 mb-0">Modeled. An average year is about {money(cost.averageYear)}.</p>
        </>
      ) : (
        <>
          <div className="text-[18px] leading-tight text-navy font-medium">Not estimated yet</div>
          <p className="mt-1.5 mb-0 text-[12.5px] text-ink-soft">{hasAgents ? "A modeled figure needs your revenue, sector and records held. You can try your numbers on the next screen." : "There are no agents to model."}</p>
        </>
      )}
    </Tile>
  );
}

/** Reference lines for the trend: each declared policy limit, and the cover that applies to AI losses. */
function boundaryLines(cost: CostOutlook): { label: string; value: number; tone: "limit" | "cover" }[] {
  const lines: { label: string; value: number; tone: "limit" | "cover" }[] = [];
  const top = cost.limits[0];
  if (top) lines.push({ label: `${top.label.charAt(0).toUpperCase()}${top.label.slice(1)} ${money(top.limit)}${top.aiExcluded ? ", AI losses excluded" : ""}`, value: top.limit, tone: "limit" });
  if (cost.policies) lines.push({ label: `Cover that applies to AI losses ${money(cost.covered)}`, value: cost.covered, tone: "cover" });
  return lines;
}

/**
 * The bad-year figure over past scans, as a small line ending at today's
 * figure, against the declared policy limit and the cover that applies to AI
 * losses. The gap between the line and the cover is what the company would
 * carry itself. One scan alone shows the figure.
 */
function CostTrend({ cost }: { cost: CostOutlook }) {
  const points: TrendPoint[] = cost.trend.length ? cost.trend : [{ hash: "", ref: null, date: "", agent: cost.agent, added: [], badYear: cost.badYear, averageYear: cost.averageYear }];
  const last = points[points.length - 1]!;
  const first = points[0]!;
  const bounds = boundaryLines(cost);
  if (points.length < 2 && !bounds.length) return <Figure value={money(last.badYear)} unit="in a bad year" />;
  const W = 160, H = 56, padX = 4, padY = 5;
  const top = Math.max(...points.map((p) => p.badYear), ...bounds.map((b) => b.value)) * 1.06;
  const bottom = 0;
  const x = (i: number) => padX + (i * (W - padX * 2)) / Math.max(points.length - 1, 1);
  const y = (v: number) => H - padY - ((v - bottom) / Math.max(top - bottom, 1)) * (H - padY * 2);
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.badYear).toFixed(1)}`).join(" ");
  const up = last.badYear > first.badYear * 1.005, down = last.badYear < first.badYear * 0.995;
  const label = `Modeled bad-year loss over ${pluralize(points.length, "scan")}: ${money(first.badYear)} (${formatDate(first.date)}) to ${money(last.badYear)} (${formatDate(last.date)})${bounds.map((b) => `. ${b.label}`).join("")}`;
  const share = cost.limits[0] && cost.limits[0].limit > 0 ? Math.round((last.badYear / cost.limits[0].limit) * 100) : null;
  return (
    <div>
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="num text-[28px] leading-none text-navy">{money(last.badYear)}</span>
        <span className="text-[12.5px] text-ink-soft">in a bad year</span>
      </div>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={label} className="block mt-1.5 max-w-[240px] overflow-visible">
        <title>{label}</title>
        {bounds.map((b) => <line key={b.tone} x1={0} x2={W} y1={y(b.value)} y2={y(b.value)} className={b.tone === "limit" ? "stroke-sev-high" : "stroke-ok"} strokeDasharray={b.tone === "limit" ? "4 3" : "2 2"} strokeWidth={1} vectorEffect="non-scaling-stroke" />)}
        {points.length > 1 ? <path d={path} className="fill-none stroke-navy [stroke-width:1.75] [stroke-linejoin:round] [stroke-linecap:round]" vectorEffect="non-scaling-stroke" /> : null}
        {points.map((p, i) => <circle key={p.hash || i} cx={x(i)} cy={y(p.badYear)} r={i === points.length - 1 ? 3.5 : 2} className={i === points.length - 1 ? "fill-gold" : "fill-navy"} />)}
      </svg>
      {points.length > 1 ? <div className="text-[12px] mt-1 leading-snug"><span className={up ? "text-sev-high font-medium" : down ? "text-ok font-medium" : "text-ink-muted"}>{up ? "Up" : down ? "Down" : "Level"} from {money(first.badYear)}</span><span className="text-ink-muted"> since {formatDate(first.date)}{share !== null ? `, now ${share}% of the ${cost.limits[0]!.label}` : ""}.</span></div> : null}
      {bounds.length ? (
        <ul className="m-0 mt-1 p-0 list-none flex flex-col gap-0.5 text-[11.5px] text-ink-muted leading-snug">
          {bounds.map((b) => <li key={b.tone} className="flex items-center gap-1.5"><span aria-hidden="true" className={`inline-block w-3 border-t ${b.tone === "limit" ? "border-sev-high border-dashed" : "border-ok border-dotted"}`} />{b.label}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

// --- needs your attention ------------------------------------------------------------------------

function Attention() {
  const { envelope } = useApp();
  const items = useMemo(() => attention(envelope), [envelope]);
  const total = activeFindings(envelope).length;
  return (
    <section className="panel" aria-labelledby="attention-title">
      <div className="px-4 pt-3 pb-2.5">
        <h2 id="attention-title" className="m-0">Needs your attention</h2>
        <div className="caption">Highest severity first. The same problem on several agents is one item.</div>
      </div>
      {!items.length ? <p className="caption px-4 pb-3 m-0">No open findings.</p> : (
        <ol className="m-0 p-0 list-none divide-y divide-line/70 border-t border-line/70">
          {items.map((item) => <AttentionRow key={item.ruleId} item={item} />)}
        </ol>
      )}
      {total ? <div className="px-4 py-2.5 border-t border-line/70"><a href={buildHash("findings")} className="text-[12.5px] font-medium text-navy no-underline hover:underline">View all {pluralize(total, "finding")} <span aria-hidden="true">→</span></a></div> : null}
    </section>
  );
}

function AttentionRow({ item }: { item: AttentionItem }) {
  const status = attentionStatus(item);
  const parts: [string, ReactNode][] = [
    ["What the scan saw", scanSaw(item)],
    ["Why it matters", whyItMatters(item)],
    ["Fix", <>{nextAction(item)}{status ? <span className="text-ink-muted"> · {status}</span> : null}</>],
  ];
  return (
    <li className="grid grid-cols-[68px_minmax(0,1fr)] gap-x-3 items-start px-4 py-3">
      <span className="pt-0.5"><SeverityBadge severity={item.severity} /></span>
      <div className="min-w-0">
        <a href={buildHash("findings", item.fingerprint)} className="block text-[13.5px] font-medium leading-snug text-navy no-underline hover:underline">{attentionTitle(item)}</a>
        <dl className="m-0 mt-1.5 grid grid-cols-[112px_minmax(0,1fr)] gap-x-3 gap-y-1 text-[12.5px] leading-snug">
          {parts.filter(([, v]) => v).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-ink-muted">{k}</dt>
              <dd className="m-0 text-ink-soft">{v}</dd>
            </div>
          ))}
        </dl>
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
        <div className="mt-3 flex gap-1 max-w-[520px]" role="img" aria-label={segments.map((s) => `${s.n} ${s.label.toLowerCase()}`).join(", ")}>
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
