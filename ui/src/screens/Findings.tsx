import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { RiskTabs } from "../components/RiskTabs";
import { buildHash, navigate, useRoute } from "../app/router";
import { Pill, SeverityBadge } from "../components/Badge";
import { DataTable, sortRows, type Column, type SortState } from "../components/DataTable";
import { FindingDrawer } from "../components/FindingDrawer";
import { EMPTY_FILTERS, applyFilters, defaultOrder, filtersFromQuery, filtersToQuery, isFiltered, sortFromQuery, type FindingFilters } from "../data/filters";
import { SEVERITIES, SEVERITY_RANK, activeFindings, agentLabel, allFindings, countBySeverity, findingByFingerprint, findingTag, frameworkClasses, tagLabel, type FindingRef } from "../data/selectors";
import type { Severity } from "../data/types";

export function Findings() {
  const { envelope, framework } = useApp();
  const route = useRoute();
  const filters = useMemo(() => filtersFromQuery(route.query), [route.query]);
  const sort = useMemo(() => sortFromQuery(route.query), [route.query]);
  const [draft, setDraft] = useState<string | null>(null);

  const rows = useMemo(() => defaultOrder(applyFilters(envelope, filters, framework)), [envelope, filters, framework]);
  const columns = useMemo<Column<FindingRef>[]>(() => [
    { id: "severity", header: "Severity", width: "110px", cell: (r) => <SeverityBadge severity={r.finding.severity} />, sortValue: (r) => SEVERITY_RANK[r.finding.severity] },
    { id: "rule", header: "Rule", width: "90px", cell: (r) => <span className="mono">{r.finding.rule_id}</span>, sortValue: (r) => r.finding.rule_id },
    { id: "title", header: "Title", width: "minmax(220px, 2fr)", cell: (r) => <span className="line-clamp-2">{r.finding.title}{r.finding.is_new ? <Pill tone="gold">new</Pill> : null}{r.finding.suppressed ? <Pill>suppressed</Pill> : null}</span>, sortValue: (r) => r.finding.title },
    { id: "agent", header: "Agent", width: "minmax(120px, 1fr)", cell: (r) => (r.agent ? <span className="truncate block">{agentLabel(r.agent)}{r.agents.length > 1 ? <span className="caption"> +{r.agents.length - 1}</span> : null}</span> : <span className="caption">repository</span>), sortValue: (r) => (r.agent ? agentLabel(r.agent) : "") },
    { id: "location", header: "Location", width: "minmax(160px, 1.4fr)", cell: (r) => <span className="mono truncate block" title={`${r.finding.path}:${r.finding.line}`}>{r.finding.path}:{r.finding.line}</span>, sortValue: (r) => `${r.finding.path}:${String(r.finding.line).padStart(6, "0")}` },
    { id: "class", header: framework === "owasp" ? "OWASP" : framework === "eu" ? "EU AI Act" : "Class", width: "90px", cell: (r) => { const t = findingTag(r.finding, framework); return t ? <Pill title={tagLabel(t, framework)}>{t}</Pill> : <span className="caption">–</span>; }, sortValue: (r) => findingTag(r.finding, framework) },
  ], [framework]);
  const sorted = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);

  const selected = route.id ? findingByFingerprint(envelope.registry, route.id) : null;
  const backQuery = filtersToQuery(filters, sort);

  const update = (next: FindingFilters, nextSort: SortState | null = sort) => navigate("findings", null, filtersToQuery(next, nextSort));
  const onSort = (column: string) => update(filters, sort?.column === column ? (sort.dir === "desc" ? { column, dir: "asc" } : null) : { column, dir: "desc" });

  const all = allFindings(envelope.registry);
  const active = activeFindings(envelope.registry);
  const bySeverity = countBySeverity(active);
  const byDimension = envelope.taxonomy.dimensions.map((d) => ({ id: d.id, name: d.name, count: active.filter((r) => r.finding.dimensions?.includes(d.id)).length }));
  const agents = envelope.registry.agents;
  const classes = frameworkClasses(envelope, framework).filter((c) => c.count > 0);

  return (
    <div>
      <RiskTabs current="findings" />
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Findings</h1>
        <div className="caption">{sorted.length} of {all.length} shown{isFiltered(filters) ? " (filtered)" : ""}. Filters are in the link, so this view can be shared.</div>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <div className="panel p-3">
          <div className="caption uppercase text-[11px] tracking-wide mb-2">By severity</div>
          <div className="flex flex-wrap gap-2">
            {SEVERITIES.map((sev) => (
              <button key={sev} type="button" onClick={() => update({ ...filters, severity: filters.severity.includes(sev) ? filters.severity.filter((s) => s !== sev) : [...filters.severity, sev] })} aria-pressed={filters.severity.includes(sev)} className={`flex items-center gap-1 rounded border px-2 py-1 ${filters.severity.includes(sev) ? "border-gold bg-gold-100" : "border-line bg-panel"}`}>
                <SeverityBadge severity={sev} />
                <span className="tabular-nums text-[13px]">{bySeverity[sev]}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="panel p-3">
          <div className="caption uppercase text-[11px] tracking-wide mb-2">By dimension</div>
          <div className="flex flex-wrap gap-1.5">
            {byDimension.filter((d) => d.count).map((d) => (
              <button key={d.id} type="button" onClick={() => update({ ...filters, dimension: filters.dimension === d.id ? null : d.id })} aria-pressed={filters.dimension === d.id} className={`rounded border px-2 py-1 text-[12.5px] ${filters.dimension === d.id ? "border-gold bg-gold-100" : "border-line bg-panel"}`}>
                {d.name} <span className="tabular-nums caption">{d.count}</span>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-4 panel p-3 flex flex-wrap items-end gap-3 text-[13px] no-print">
        <label className="flex flex-col gap-1">
          <span className="caption">Search</span>
          <input value={draft ?? filters.q} onChange={(e) => setDraft(e.target.value)} onBlur={() => { if (draft !== null) { update({ ...filters, q: draft }); setDraft(null); } }} onKeyDown={(e) => { if (e.key === "Enter" && draft !== null) { update({ ...filters, q: draft }); setDraft(null); } }} placeholder="rule, title, path, snippet" className="field" />
        </label>
        <Select label="Agent" value={filters.agent ?? ""} onChange={(v) => update({ ...filters, agent: v || null })} options={[{ value: "", label: "All agents" }, ...agents.map((a) => ({ value: a.id, label: agentLabel(a) }))]} />
        {framework !== "nist" ? <Select label={framework === "owasp" ? "OWASP class" : "EU AI Act article"} value={filters.cls ?? ""} onChange={(v) => update({ ...filters, cls: v || null })} options={[{ value: "", label: "Any" }, ...classes.map((c) => ({ value: c.id, label: `${c.id} ${c.name}` }))]} /> : null}
        {isFiltered(filters) || sort ? (
          <button type="button" onClick={() => update(EMPTY_FILTERS, null)} className="btn btn-sm">Clear filters</button>
        ) : null}
      </div>

      <div className="mt-4">
        <DataTable rows={sorted} columns={columns} rowKey={(r) => r.finding.fingerprint} onRowClick={(r) => navigate("findings", r.finding.fingerprint, backQuery)} sort={sort} onSort={onSort} ariaLabel="Findings" />
      </div>

      <FindingDrawer ref={selected} backQuery={backQuery} onClose={() => navigate("findings", null, backQuery)} />
      {route.id && !selected ? <p className="caption mt-3">No finding with fingerprint <span className="mono">{route.id}</span> in this scan. <a className="link" href={buildHash("findings")}>Show all findings</a>.</p> : null}
    </div>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="caption">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="field">
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export type { Severity };
