import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { RiskTabs } from "../components/RiskTabs";
import { buildHash, navigate, useRoute } from "../app/router";
import { Pill, SeverityBadge } from "../components/Badge";
import { DataTable, sortRows, type Column, type SortState } from "../components/DataTable";
import { FindingDrawer } from "../components/FindingDrawer";
import { EMPTY_FILTERS, applyFilters, defaultOrder, filtersFromQuery, filtersToQuery, isFiltered, sortFromQuery, type FindingFilters } from "../data/filters";
import { DimensionChart } from "../components/DimensionChart";
import { SeverityTip } from "../components/InfoTip";
import { uniqueAgents } from "../data/agents";
import { RISK_LABEL, RISK_LEVELS, RISK_SEVERITIES, SEVERITY_RANK, activeFindings, countByLevel, allFindings, findingByFingerprint, findingTag, findingTitle, frameworkClasses, pluralize, recordCount, tagLabel, type FindingRef } from "../data/selectors";
import type { Severity } from "../data/types";

/** A table row: a rule with everything it fired on, or, inside an open rule, one finding. */
type Row = { kind: "group"; key: string; ruleId: string; refs: FindingRef[]; open: boolean } | { kind: "finding"; key: string; ref: FindingRef };

function groupByRule(refs: FindingRef[]): { ruleId: string; refs: FindingRef[] }[] {
  const groups = new Map<string, FindingRef[]>();
  for (const ref of refs) {
    const list = groups.get(ref.finding.rule_id);
    if (list) list.push(ref);
    else groups.set(ref.finding.rule_id, [ref]);
  }
  return [...groups].map(([ruleId, list]) => ({ ruleId, refs: list }));
}

const whoOf = (ref: FindingRef): string => (ref.uniqueAgents.length ? ref.uniqueAgents.map((u) => u.name).join(", ") : "Repository");

export function Findings() {
  const { envelope, framework } = useApp();
  const route = useRoute();
  const filters = useMemo(() => filtersFromQuery(route.query), [route.query]);
  const sort = useMemo(() => sortFromQuery(route.query), [route.query]);
  const [draft, setDraft] = useState<string | null>(null);
  const [openRules, setOpenRules] = useState<Set<string>>(new Set());
  const [shared, setShared] = useState<"idle" | "copied" | "blocked">("idle");

  const filtered = useMemo(() => defaultOrder(applyFilters(envelope, filters, framework)), [envelope, filters, framework]);
  const groups = useMemo(() => groupByRule(filtered), [filtered]);

  const columns = useMemo<Column<Row>[]>(() => {
    const worst = (row: Row) => (row.kind === "group" ? row.refs[0]!.finding : row.ref.finding);
    return [
      { id: "severity", header: "Severity", hint: <SeverityTip align="left" />, width: "118px", cell: (row) => (row.kind === "group" ? <span className="flex items-center gap-1.5"><span aria-hidden="true" className="w-3 text-ink-muted text-[10px]">{row.refs.length > 1 ? (row.open ? "▼" : "▶") : ""}</span><SeverityBadge severity={worst(row).severity} /></span> : null), sortValue: (row) => SEVERITY_RANK[worst(row).severity] },
      { id: "title", header: "Finding", width: "minmax(260px, 2.4fr)", cell: (row) => row.kind === "group"
        ? <span className="block"><span className="font-medium text-navy">{findingTitle(envelope, worst(row))}</span>{row.refs.some((r) => r.finding.suppressed) ? <span className="ml-1.5"><Pill>suppressed</Pill></span> : null}</span>
        : <span className="block pl-4 text-ink-soft">{whoOf(row.ref)}</span>,
        sortValue: (row) => findingTitle(envelope, worst(row)) },
      { id: "affected", header: "Affected", width: "minmax(150px, 1fr)", cell: (row) => {
        if (row.kind === "finding") return <span className="caption">{pluralize(row.ref.evidence.length, "evidence location")}</span>;
        const agents = new Set(row.refs.flatMap((r) => r.uniqueAgents.map((u) => u.id)));
        const names = [...new Set(row.refs.flatMap((r) => r.uniqueAgents.map((u) => u.name)))];
        return <span title={names.join(", ")}>{agents.size === 0 ? "Repository" : agents.size === 1 ? names[0] : pluralize(agents.size, "agent")}{row.refs.length > 1 ? <span className="caption"> · {row.refs.length} findings</span> : null}</span>;
      }, sortValue: (row) => (row.kind === "group" ? row.refs.length : 0) },
      { id: "location", header: "Evidence", width: "minmax(180px, 1.5fr)", cell: (row) => {
        const evidence = row.kind === "group" ? (row.refs.length === 1 ? row.refs[0]!.evidence : []) : row.ref.evidence;
        if (!evidence.length) return <span className="caption">{pluralize((row as Extract<Row, { kind: "group" }>).refs.reduce((n, r) => n + r.evidence.length, 0), "location")}</span>;
        return <span className="block">{evidence.map((f) => <span key={f.fingerprint} className="mono text-[12px] block truncate" title={`${f.path}:${f.line}`}>{f.path}:{f.line}</span>)}</span>;
      } },
      { id: "rule", header: "Rule", width: "92px", cell: (row) => (row.kind === "group" ? <span className="mono text-[12px]" title={envelope.rules[row.ruleId]?.title ?? ""}>{row.ruleId}</span> : null), sortValue: (row) => worst(row).rule_id },
      { id: "class", header: framework === "owasp" ? "OWASP" : framework === "eu" ? "EU AI Act" : "Class", width: "88px", cell: (row) => { if (row.kind !== "group") return null; const t = findingTag(worst(row), framework); return t ? <Pill title={tagLabel(t, framework)}>{t}</Pill> : null; }, sortValue: (row) => findingTag(worst(row), framework) },
    ];
  }, [envelope, framework]);

  const rows = useMemo<Row[]>(() => {
    const heads: Row[] = groups.map((g) => ({ kind: "group", key: `rule:${g.ruleId}`, ruleId: g.ruleId, refs: g.refs, open: openRules.has(g.ruleId) }));
    const out: Row[] = [];
    for (const head of sortRows(heads, columns, sort)) {
      out.push(head);
      if (head.kind === "group" && head.open && head.refs.length > 1) for (const ref of head.refs) out.push({ kind: "finding", key: ref.finding.fingerprint, ref });
    }
    return out;
  }, [groups, openRules, columns, sort]);

  const selected = route.id ? findingByFingerprint(envelope, route.id) : null;
  const backQuery = filtersToQuery(filters, sort);

  const update = (next: FindingFilters, nextSort: SortState | null = sort) => navigate("findings", null, filtersToQuery(next, nextSort));
  const onSort = (column: string) => update(filters, sort?.column === column ? (sort.dir === "desc" ? { column, dir: "asc" } : null) : { column, dir: "desc" });
  const openRow = (row: Row) => {
    // A rule that fired once opens its finding; one that fired several times opens its list.
    if (row.kind === "finding") return navigate("findings", row.ref.finding.fingerprint, backQuery);
    if (row.refs.length === 1) return navigate("findings", row.refs[0]!.finding.fingerprint, backQuery);
    setOpenRules((current) => {
      const next = new Set(current);
      if (next.has(row.ruleId)) next.delete(row.ruleId);
      else next.add(row.ruleId);
      return next;
    });
  };
  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setShared("copied");
    } catch {
      setShared("blocked");
    }
  };

  const all = allFindings(envelope);
  const active = activeFindings(envelope);
  const byLevel = countByLevel(active);
  const agents = uniqueAgents(envelope);
  const classes = frameworkClasses(envelope, framework).filter((c) => c.count > 0);
  const records = recordCount(active);
  const expandable = groups.filter((g) => g.refs.length > 1);
  const allOpen = expandable.length > 0 && expandable.every((g) => openRules.has(g.ruleId));

  return (
    <div>
      <RiskTabs current="findings" />
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="m-0">Findings</h1>
        <div className="flex flex-wrap items-center gap-3">
          <span className="caption">{filtered.length} of {all.length} shown{isFiltered(filters) ? " (filtered)" : ""}</span>
          <button type="button" onClick={share} className="btn btn-sm no-print">{shared === "copied" ? "Link copied" : "Share view"}</button>
        </div>
      </div>
      <p className="caption mt-1 mb-0">
        {pluralize(active.length, "finding")}{records !== active.length ? `, from ${records} scanner records. The same rule on an agent's code and on its infrastructure is one finding with two evidence locations.` : "."}
        {shared === "blocked" ? " Clipboard access was blocked in this viewer; copy the address from the browser instead." : ""}
      </p>

      <div className="mt-4">
        <DimensionChart selected={filters.dimension} onSelect={(id) => update({ ...filters, dimension: id })} />
      </div>

      <div className="mt-4 panel p-3 flex flex-wrap items-end gap-x-4 gap-y-3 text-[13px] no-print sticky top-2 z-20">
        <div role="group" aria-label="Filter by severity" className="flex flex-col gap-1">
          <span className="caption">Severity</span>
          <div className="flex flex-wrap gap-1.5">
            {RISK_LEVELS.map((level) => {
              const members = RISK_SEVERITIES[level];
              const on = members.every((s) => filters.severity.includes(s));
              return (
                <button key={level} type="button" onClick={() => update({ ...filters, severity: on ? filters.severity.filter((s) => !members.includes(s)) : [...filters.severity.filter((s) => !members.includes(s)), ...members] })} aria-pressed={on} className={`flex items-center gap-1.5 rounded border px-2 py-1 cursor-pointer ${on ? "border-gold bg-gold-100" : "border-line bg-panel"}`}>
                  <span className={`chip chip-${level}`}>{RISK_LABEL[level]}</span>
                  <span className="tabular-nums text-[13px]">{byLevel[level]}</span>
                </button>
              );
            })}
          </div>
        </div>
        <label className="flex flex-col gap-1">
          <span className="caption">Search</span>
          <input value={draft ?? filters.q} onChange={(e) => setDraft(e.target.value)} onBlur={() => { if (draft !== null) { update({ ...filters, q: draft }); setDraft(null); } }} onKeyDown={(e) => { if (e.key === "Enter" && draft !== null) { update({ ...filters, q: draft }); setDraft(null); } }} placeholder="finding, rule, path, agent" className="field w-56" />
        </label>
        <Select label="Agent" value={filters.agent ?? ""} onChange={(v) => update({ ...filters, agent: v || null })} options={[{ value: "", label: "All agents" }, ...agents.map((a) => ({ value: a.id, label: a.name }))]} />
        {framework !== "nist" ? <Select label={framework === "owasp" ? "OWASP class" : "EU AI Act article"} value={filters.cls ?? ""} onChange={(v) => update({ ...filters, cls: v || null })} options={[{ value: "", label: "Any" }, ...classes.map((c) => ({ value: c.id, label: `${c.id} ${c.name}` }))]} /> : null}
        {expandable.length ? <button type="button" onClick={() => setOpenRules(allOpen ? new Set() : new Set(expandable.map((g) => g.ruleId)))} className="btn btn-sm">{allOpen ? "Collapse all" : "Expand all"}</button> : null}
        {isFiltered(filters) || sort ? (
          <button type="button" onClick={() => update(EMPTY_FILTERS, null)} className="btn btn-sm">Clear filters</button>
        ) : null}
      </div>

      <div className="mt-4">
        <DataTable rows={rows} columns={columns} rowKey={(row) => row.key} onRowClick={openRow} sort={sort} onSort={onSort} ariaLabel="Findings" />
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
