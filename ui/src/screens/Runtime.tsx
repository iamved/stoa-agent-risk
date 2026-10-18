import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { Pill, SeverityBadge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { RiskTabs } from "../components/RiskTabs";
import { Section } from "../components/Section";
import { chainStatus, coverage, driftLines, flagLabel, flagTimeline, reconcileRows, runtimeFindings, runtimeWindow } from "../data/runtime";
import { findingTitle, formatDate, pluralize } from "../data/selectors";

/** What the traces showed: tools declared against used, runtime findings, flags by day, drift since the baseline. */
export function Runtime() {
  const { envelope } = useApp();
  const window = runtimeWindow(envelope);
  const chain = chainStatus(envelope);
  const cover = coverage(envelope);
  if (!window || !cover || !window.spans) {
    return (
      <div>
        <RiskTabs current="runtime" />
        <h1 className="m-0 mb-3">Runtime</h1>
        <EmptyState title="No traces in this scan"><span>Instrument an agent with <span className="mono">stoa.runtime</span>, then build the page with <span className="mono">stoa dashboard stoa-registry.json --runtime stoa-traces</span> or scan with <span className="mono">--with-runtime</span>.</span></EmptyState>
      </div>
    );
  }
  const rows = reconcileRows(envelope);
  const findings = runtimeFindings(envelope);
  const timeline = flagTimeline(envelope);
  const drift = driftLines(envelope);
  const flags = Object.entries(timeline.totals).sort((a, b) => b[1] - a[1]);
  return (
    <div>
      <RiskTabs current="runtime" />
      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
        <h1 className="m-0">Runtime</h1>
        <div className="caption">Observed {formatDate(window.start)} to {formatDate(window.end)} · {pluralize(window.spans, "span")} · {cover.active} of {pluralize(cover.total, "agent")} active{cover.unmatched ? ` · ${pluralize(cover.unmatched, "unmatched record")}` : ""}</div>
      </div>
      {chain ? (
        <p className="m-0 mb-4 text-[12.5px] flex flex-wrap items-center gap-2">
          <span className={`chip ${chain.ok ? "chip-ok" : "chip-critical"}`}>{chain.ok ? "Chain intact" : "Chain broken"}</span>
          <span className="text-ink-soft">{pluralize(chain.records, "record")}, {chain.grade === "none" ? "unsigned" : `signed (${chain.grade})`}{chain.unchained ? `, ${pluralize(chain.unchained, "older file")} unchained` : ""}.</span>
          {chain.broken.map((b) => <span key={b} className="text-sev-critical">{b}</span>)}
        </p>
      ) : null}

      <Section title="Tools: declared and used" caption={`A declared tool unseen for ${pluralize(envelope.runtime!.reconcile.dormant_days, "day")} is dormant.`}>
        <div className="panel overflow-x-auto" tabIndex={0}>
          <table className="tbl w-full">
            <thead><tr><th>Agent</th><th>Declared and used</th><th>Used but undeclared</th><th>Declared but dormant</th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.agent_id}>
                  <td>{row.agent ? <a href={buildHash("inventory", row.agent.id)} className="link font-medium">{row.name}</a> : <span className="font-medium">{row.name}</span>}{row.has_runtime_evidence ? null : <div className="caption">no runtime evidence</div>}</td>
                  <td>{row.declared_and_used.length ? row.declared_and_used.map((t) => <span key={t.tool} className="chip chip-plain mr-1 mb-1">{t.tool}{t.calls ? <span className="text-ink-muted"> x{t.calls}</span> : null}</span>) : <span className="caption">none</span>}</td>
                  <td>{row.used_but_undeclared.length ? row.used_but_undeclared.map((t) => <span key={t.tool} className="chip chip-high mr-1 mb-1">{t.tool}{t.calls ? <span> x{t.calls}</span> : null}</span>) : <span className="caption">none</span>}</td>
                  <td>{row.declared_but_dormant.length ? row.declared_but_dormant.map((t) => <span key={t.tool} className="chip chip-muted chip-plain mr-1 mb-1">{t.tool}</span>) : <span className="caption">none</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Runtime findings" caption="Declared and scanned facts against what the traces showed. Each one points at a span.">
        {findings.length ? (
          <ol className="panel m-0 p-0 list-none divide-y divide-line/70">
            {findings.map((ref) => {
              const f = ref.finding;
              return (
                <li key={f.fingerprint} className="grid grid-cols-[68px_minmax(0,1fr)] gap-x-3 items-start px-4 py-3">
                  <span className="pt-0.5"><SeverityBadge severity={f.severity} /></span>
                  <div className="min-w-0">
                    <a href={buildHash("findings", f.fingerprint)} className="block text-[13.5px] font-medium leading-snug text-navy no-underline hover:underline">{findingTitle(envelope, f)}</a>
                    <div className="caption mt-0.5">{ref.uniqueAgents.map((u) => u.name).join(", ") || "Repository"}{f.trace_ref?.file ? <span className="mono"> · {f.trace_ref.file}:{f.trace_ref.line}</span> : null}</div>
                  </div>
                </li>
              );
            })}
          </ol>
        ) : <EmptyState title="No runtime findings">What the traces showed matches the declared and scanned facts.</EmptyState>}
      </Section>

      <Section title="Flags by day" caption="Computed by the SDK as each span was written.">
        {timeline.days.length ? (
          <div className="panel overflow-x-auto" tabIndex={0}>
            <table className="tbl w-full">
              <thead><tr><th>Day</th>{flags.map(([flag]) => <th key={flag}>{flagLabel(flag)}</th>)}<th className="text-right">Total</th></tr></thead>
              <tbody>
                {timeline.days.map((d) => (
                  <tr key={d.day}>
                    <td className="tabular-nums">{formatDate(d.day)}</td>
                    {flags.map(([flag]) => <td key={flag} className="tabular-nums">{d.counts[flag] ? <span className={flag === "approval_bypassed" || flag === "over_declared_limit" ? "text-sev-high font-medium" : ""}>{d.counts[flag]}</span> : <span className="text-ink-muted">·</span>}</td>)}
                    <td className="tabular-nums text-right">{d.total}</td>
                  </tr>
                ))}
                <tr>
                  <td className="font-medium">All days</td>
                  {flags.map(([flag, n]) => <td key={flag} className="tabular-nums font-medium">{n}</td>)}
                  <td className="tabular-nums text-right font-medium">{timeline.days.reduce((n, d) => n + d.total, 0)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : <EmptyState title="No flags">No span in the window was flagged.</EmptyState>}
      </Section>

      <Section title="Drift since baseline" caption={envelope.runtime!.baseline_present ? "Observed behavior against the committed runtime baseline." : "No runtime baseline committed."}>
        {drift.length ? (
          <ul className="panel m-0 p-0 list-none divide-y divide-line/70">
            {drift.map((d, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2.5 text-[13px]">
                <Pill tone={d.cls === "high" ? "warn" : d.cls === "medium" ? "gold" : "neutral"}>{d.cls}</Pill>
                <span className="font-medium text-navy">{d.label}</span>
                <span className="text-ink-soft">{d.agent}</span>
                {d.detail ? <span className="caption break-all">{d.detail}</span> : null}
              </li>
            ))}
          </ul>
        ) : <EmptyState title={envelope.runtime!.baseline_present ? "No drift" : "Nothing to compare against"}>envelope.runtime!.baseline_present ? "Observed behavior matches the baseline within the configured thresholds." : <span>Commit one with <span className="mono">stoa runtime baseline stoa-traces --registry stoa-registry.json</span>.</span></EmptyState>}
      </Section>
    </div>
  );
}
