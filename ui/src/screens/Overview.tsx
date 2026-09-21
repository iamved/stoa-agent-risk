import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useApp } from "../app/context";
import { printAs } from "../app/print";
import { buildHash } from "../app/router";
import { SeverityBadge } from "../components/Badge";
import { money } from "../data/lossModel";
import { attention, attentionRegisterRow, attentionStatus, costOutlook, elevatedDimensions, holdings, protection, registerCard, standing, whatChanged, type AttentionItem, type ChangeLine, type CostOutlook } from "../data/overview";
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
  const [copied, setCopied] = useState(false);
  // A link only means something to someone else when the page is served; a local file's path does not travel.
  const shareable = typeof window !== "undefined" && window.location.protocol.startsWith("http");
  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
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
      <div className="no-print flex flex-col gap-2 w-full sm:w-auto">
        <button type="button" onClick={() => printAs("summary")} className="rounded-md px-4 py-2 text-[13px] font-semibold bg-[#d9bd7e] text-navy hover:bg-[#e3c88a] cursor-pointer border-0">Export board report</button>
        {shareable ? <button type="button" onClick={share} className="rounded-md px-4 py-2 text-[13px] font-medium bg-transparent text-white border border-white/40 hover:bg-white/10 cursor-pointer">{copied ? "Link copied" : "Share this view"}</button> : null}
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
      <p className="mt-2 mb-0 text-[13px] text-ink-soft">{h.agents ? `${h.moneyMovers} can move money · ${pluralize(h.tools, "tool")} · ${pluralize(h.providers, "model provider")}` : "No agents were found in the scanned files."}</p>
      <p className="caption mt-2 mb-0">{delta === null ? "No baseline to compare against" : delta.value === 0 ? "No change since last scan" : `${delta.label} since last scan`}</p>
    </Tile>
  );
}

const LEVEL_BAR: Record<RiskLevel, string> = { high: "bg-sev-high", medium: "bg-sev-medium", low: "bg-sev-low" };

function FindingsTile() {
  const { envelope } = useApp();
  const counts = countByLevel(activeFindings(envelope.registry));
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
          <p className="mt-1 mb-0 text-[13.5px] text-ink-soft">money-moving {p.moneyMovers === 1 ? "agent requires" : "agents require"} human approval</p>
        </>
      ) : (
        <>
          <Figure value="0" unit="agents can move money" />
          <p className="mt-1 mb-0 text-[13.5px] text-ink-soft">No payment tools or payment access were found.</p>
        </>
      )}
      {p.tools ? <p className="mt-2 mb-0 text-[13px] text-ink-soft">{p.unguardedTools} of {pluralize(p.tools, "tool")} {p.unguardedTools === 1 ? "has" : "have"} no safeguard{p.doublePost ? ` · ${p.doublePost} can post a payment twice` : ""}</p> : null}
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
          <p className="mt-2 mb-0 text-[13px] text-ink-soft">1 year in 100 · an average year costs about {money(cost.averageYear)}</p>
          <p className="caption mt-1 mb-0">Modelled for {cost.agent}, {cost.confidence} confidence. An indication, not a quote.</p>
          <p className={`mt-2 mb-0 text-[12px] ${cost.policies && cost.covered === 0 ? "text-sev-high font-medium" : "text-ink-muted"}`}>{cost.policies ? `AI losses covered today: ${money(cost.covered)}` : "No existing policies declared"}</p>
        </>
      ) : (
        <>
          <div className="text-[20px] leading-tight text-navy font-medium">Not estimated yet</div>
          <p className="mt-2 mb-0 text-[13px] text-ink-soft">{hasAgents ? "A figure needs your revenue, sector and records held. Add an [intake] table to .stoa/underwriting.toml, or try your numbers on the next screen." : "There are no agents to model."}</p>
        </>
      )}
    </Tile>
  );
}

// --- needs your attention ------------------------------------------------------------------------

function Attention() {
  const { envelope } = useApp();
  const items = useMemo(() => attention(envelope), [envelope]);
  const total = activeFindings(envelope.registry).length;
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
  const row = attentionRegisterRow(item);
  const owner = row?.declared?.owner;
  const who = item.agents.length === 0 ? "Repository" : item.agents.length === 1 ? item.agents[0]! : pluralize(item.agents.length, "agent");
  return (
    <li className="grid grid-cols-[64px_minmax(0,1fr)] sm:grid-cols-[64px_minmax(0,1fr)_auto] gap-x-3 gap-y-2 items-center px-5 py-3">
      <span><SeverityBadge severity={item.severity} /></span>
      <div className="min-w-0">
        <a href={buildHash("findings", item.fingerprint)} className="block text-[14px] font-medium leading-snug text-navy no-underline hover:underline">{item.title}</a>
        <div className="caption mt-0.5" title={item.agents.join(", ")}>{[who, item.dimension, attentionStatus(item)].filter(Boolean).join(" · ")}</div>
      </div>
      <div className="col-start-2 sm:col-start-3">
        {row && !owner ? <a href={buildHash("register", row.risk_id)} className="btn btn-sm no-underline">Assign owner</a>
          : row ? <a href={buildHash("register", row.risk_id)} className="btn btn-sm no-underline" title={owner}>Owner assigned</a>
          : <a href={buildHash("findings", item.fingerprint)} className="btn btn-sm no-underline">View evidence</a>}
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
  return (
    <section className="panel p-5" aria-labelledby="elevated-title">
      <h2 id="elevated-title" className="m-0">Where exposure is elevated</h2>
      {!dims.length ? <p className="caption mt-2 mb-0">No dimension is at elevated exposure in this scan.</p> : (
        <ul className="mt-3 mb-0 p-0 list-none space-y-3">
          {dims.map((d) => (
            <li key={d.id} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-x-3 items-center">
              <a href={buildHash("findings", null, { dimension: d.id })} className="min-w-0 no-underline text-ink hover:underline">
                <span className="block text-[13.5px] font-medium text-navy leading-snug">{d.name}</span>
                <span className="caption block mt-0.5">{d.definition}.</span>
              </a>
              <span className="text-[12.5px] text-ink-soft whitespace-nowrap">{pluralize(d.findings, "finding")}</span>
              <span className="chip chip-high">Elevated</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function RegisterCardPanel() {
  const { envelope } = useApp();
  const r = registerCard(envelope);
  const parts = [r.transfer ? `${r.transfer} marked for transfer` : "", r.decided - r.transfer > 0 ? `${r.decided - r.transfer} with another decision` : "", r.awaiting ? `${r.awaiting} awaiting a decision to fix, accept or transfer` : ""].filter(Boolean);
  return (
    <section className="panel p-5 flex flex-col" aria-labelledby="register-title">
      <h2 id="register-title" className="m-0">Risk register</h2>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="num text-[34px] leading-none text-navy">{r.risks}</span>
        <span className="text-[13.5px] text-ink-soft">{r.risks === 1 ? "risk recorded" : "risks recorded"}</span>
      </div>
      <p className="mt-2 mb-0 text-[13px] text-ink-soft flex-1">{r.risks ? parts.join(" · ") : "The scan reported no risks above low exposure."}</p>
      {r.due ? <p className="mt-2 mb-0 text-[12px] text-sev-high font-medium">{pluralize(r.due, "review")} overdue</p> : null}
      {r.stale ? <p className="caption mt-2 mb-0">{pluralize(r.stale, "declared risk")} no longer {r.stale === 1 ? "matches" : "match"} the scan.</p> : null}
      <a href={buildHash("register")} className="mt-4 pt-3 border-t border-line text-[13px] font-medium text-navy no-underline hover:underline">Open the register <span aria-hidden="true">→</span></a>
    </section>
  );
}

function AssessmentCard() {
  const { envelope } = useApp();
  const c = envelope.assessment.counts;
  const segments: { key: string; n: number; className: string; label: string }[] = [
    { key: "code", n: c.prefilled, className: "bg-ok", label: "From your code" },
    { key: "you", n: c.to_confirm, className: "bg-gold", label: "Needs you" },
    { key: "carrier", n: c.indicative, className: "bg-line-strong", label: "Agreed with the carrier later" },
  ];
  return (
    <section className="panel p-5 flex flex-col md:col-span-2 xl:col-span-1" aria-labelledby="assessment-title">
      <h2 id="assessment-title" className="m-0">Insurance assessment</h2>
      <p className="mt-3 mb-0 text-[13.5px] text-ink-soft"><strong className="text-navy font-semibold">{c.prefilled} of {c.total}</strong> answers came from your code. <strong className="text-navy font-semibold">{c.to_confirm}</strong> need you.</p>
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
