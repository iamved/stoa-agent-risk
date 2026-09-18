import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash, navigate, useRoute } from "../app/router";
import { AgentDrawer } from "../components/AgentDrawer";
import { ConfidenceBadge, ExposureBadge, Pill } from "../components/Badge";
import { DataTable, sortRows, type Column, type SortState } from "../components/DataTable";
import { GraphView } from "../components/GraphView";
import { Chips } from "../components/KeyValue";
import { agentFindingCount, agentSource, categories, codeAgents, contradictions, declaredAgents, filterAgents, iacAgents, integrationRows, providerRows, toolRows, worstExposure, type CategoryId, type NameRow, type ToolRow } from "../data/inventory";
import { EXPOSURE_RANK, agentById, agentLabel, hasAuthority } from "../data/selectors";
import type { Agent } from "../data/types";

export function Inventory() {
  const { envelope } = useApp();
  const route = useRoute();
  const view = route.query.get("view") === "graph" ? "graph" : "table";
  const category = (route.query.get("category") ?? "agents_code") as CategoryId;
  const cats = categories(envelope);
  const [sort, setSort] = useState<SortState | null>(null);
  const selected = route.id ? agentById(envelope.registry, route.id) : null;
  const q = new URLSearchParams(route.query);
  q.delete("view");
  const back = new URLSearchParams(q);

  const setQuery = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(route.query);
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    navigate("inventory", null, next);
  };
  const open = (agent: Agent) => navigate("inventory", agent.id, back);
  const onSort = (column: string) => setSort(sort?.column === column ? (sort.dir === "desc" ? { column, dir: "asc" } : null) : { column, dir: "desc" });

  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-[24px] m-0">AI inventory</h1>
        <div className="flex items-center gap-2 no-print" role="tablist" aria-label="View">
          {(["table", "graph"] as const).map((v) => (
            <a key={v} role="tab" aria-selected={view === v} href={buildHash("inventory", null, (() => { const n = new URLSearchParams(route.query); if (v === "graph") n.set("view", "graph"); else n.delete("view"); return n; })())} className={`rounded border px-3 py-1 text-[13px] no-underline ${view === v ? "border-navy bg-navy text-white" : "border-line bg-panel text-ink"}`}>
              {v === "table" ? "Table" : "Graph"}
            </a>
          ))}
        </div>
      </div>

      {view === "graph" ? (
        <div className="mt-4">
          <p className="caption mt-0 mb-3">Agents, tools, providers, and capability sinks this scan observed, with the findings that explain each connection. The same model as the legacy report's graph.</p>
          <GraphView />
        </div>
      ) : (
        <div className="mt-4 grid gap-4 md:grid-cols-[220px_1fr]">
          <nav aria-label="Categories" className="panel p-2 self-start min-w-0 max-w-full overflow-hidden">
            <ul className="m-0 p-0 list-none flex md:flex-col gap-1 overflow-x-auto">
              {cats.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => setQuery({ category: c.id === "agents_code" ? null : c.id, authority: null, q: null })} aria-current={category === c.id ? "true" : undefined} className={`w-full flex items-center justify-between gap-2 rounded px-2.5 py-1.5 text-left text-[13px] whitespace-nowrap ${category === c.id ? "bg-gold-100 text-navy border-l-2 border-gold" : "hover:bg-paper"}`}>
                    <span>{c.label}</span>
                    <span className="caption tabular-nums">{c.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <div className="min-w-0">
            {category === "agents_code" || category === "agents_iac" ? (
              <AgentsTable agents={category === "agents_code" ? codeAgents(envelope) : iacAgents(envelope)} query={route.query} onQuery={setQuery} onOpen={open} sort={sort} onSort={onSort} />
            ) : category === "tools" ? (
              <ToolsTable rows={toolRows(envelope)} onOpen={open} sort={sort} onSort={onSort} />
            ) : category === "providers" ? (
              <NameTable rows={providerRows(envelope)} label="Provider" onOpen={open} />
            ) : category === "integrations" ? (
              <NameTable rows={integrationRows(envelope)} label="Integration" onOpen={open} />
            ) : (
              <DeclarationsTable agents={declaredAgents(envelope)} onOpen={open} />
            )}
          </div>
        </div>
      )}

      <AgentDrawer agent={selected} onClose={() => navigate("inventory", null, back)} />
      {route.id && !selected ? <p className="caption mt-3">No agent with id <span className="mono">{route.id}</span> in this scan.</p> : null}
    </div>
  );
}

function AgentsTable({ agents, query, onQuery, onOpen, sort, onSort }: { agents: Agent[]; query: URLSearchParams; onQuery: (p: Record<string, string | null>) => void; onOpen: (a: Agent) => void; sort: SortState | null; onSort: (c: string) => void }) {
  const { envelope } = useApp();
  const rows = filterAgents(envelope, agents, query);
  const columns = useMemo<Column<Agent>[]>(() => [
    { id: "name", header: "Name", width: "minmax(160px, 1.4fr)", cell: (a) => <span className="font-medium">{agentLabel(a)}{hasAuthority(envelope, a) ? <span className="caption"> · authority</span> : null}</span>, sortValue: (a) => agentLabel(a) },
    { id: "type", header: "Type", width: "minmax(120px, 1fr)", cell: (a) => <span className="truncate block">{agentSource(a)}</span>, sortValue: (a) => agentSource(a) },
    { id: "location", header: "Location", width: "minmax(180px, 1.5fr)", cell: (a) => <span className="mono truncate block" title={a.path}>{a.path}</span>, sortValue: (a) => a.path },
    { id: "autonomy", header: "Autonomy", width: "150px", cell: (a) => <span className="text-[12.5px]">{a.autonomy_level?.level ?? "indeterminate"}</span>, sortValue: (a) => a.autonomy_level?.level ?? "" },
    { id: "scope", header: "Scope", width: "minmax(140px, 1fr)", cell: (a) => <Chips items={[...a.capabilities.map((c) => ({ label: c, hot: envelope.vocabulary.high_impact_capabilities.includes(c) })), ...a.integrations.map((i) => ({ label: i, hot: envelope.vocabulary.sensitive_integrations.includes(i) }))]} empty="no reach observed" />, sortValue: (a) => a.capabilities.length + a.integrations.length },
    { id: "exposure", header: "Exposure", width: "120px", cell: (a) => <ExposureBadge exposure={worstExposure(a)} />, sortValue: (a) => EXPOSURE_RANK[worstExposure(a)] },
    { id: "confidence", header: "Confidence", width: "120px", cell: (a) => <ConfidenceBadge confidence={a.confidence} />, sortValue: (a) => a.confidence },
    { id: "findings", header: "Findings", width: "80px", align: "right", cell: (a) => <span className="tabular-nums">{agentFindingCount(envelope, a)}</span>, sortValue: (a) => agentFindingCount(envelope, a) },
  ], [envelope]);
  const sorted = sortRows(rows, columns, sort ?? { column: "exposure", dir: "desc" });
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-3 text-[13px] no-print">
        <label className="flex items-center gap-1.5">
          <input type="checkbox" checked={query.get("authority") === "1"} onChange={(e) => onQuery({ authority: e.target.checked ? "1" : null })} />
          Financial or write authority only
        </label>
        <input value={query.get("q") ?? ""} onChange={(e) => onQuery({ q: e.target.value || null })} placeholder="filter by name, path, capability" className="rounded border border-line bg-panel px-2 py-1 w-64" aria-label="Filter agents" />
        <span className="caption">{sorted.length} of {agents.length}</span>
      </div>
      <DataTable rows={sorted} columns={columns} rowKey={(a) => a.id} onRowClick={onOpen} sort={sort} onSort={onSort} ariaLabel="Agents" height={520} />
    </div>
  );
}

function ToolsTable({ rows, onOpen, sort, onSort }: { rows: ToolRow[]; onOpen: (a: Agent) => void; sort: SortState | null; onSort: (c: string) => void }) {
  const columns = useMemo<Column<ToolRow>[]>(() => [
    { id: "name", header: "Tool", width: "minmax(140px, 1.2fr)", cell: (r) => <span className="mono">{r.tool.name}</span>, sortValue: (r) => r.tool.name },
    { id: "kind", header: "Kind", width: "150px", cell: (r) => <span className="caption">{r.tool.kind}</span>, sortValue: (r) => r.tool.kind },
    { id: "effects", header: "Effects", width: "minmax(160px, 1.4fr)", cell: (r) => <Chips items={[...(r.tool.money_action ? [{ label: "money action", hot: true }] : []), ...(r.tool.high_impact && !r.tool.money_action ? [{ label: "high impact", hot: true }] : []), ...r.tool.capabilities.map((c) => ({ label: c })), ...r.tool.integrations.map((i) => ({ label: i }))]} empty="none observed" />, sortValue: (r) => Number(r.tool.high_impact) },
    { id: "guards", header: "Guards", width: "minmax(120px, 1fr)", cell: (r) => <span className="caption">{r.tool.guards.length ? r.tool.guards.join(", ") : "none observed"}{r.tool.retry ? ` · ${r.tool.idempotency_key ? "idempotent retry" : "retry, no idempotency key"}` : ""}</span> },
    { id: "agents", header: "Bound to", width: "minmax(140px, 1fr)", cell: (r) => <span className="flex flex-wrap gap-1">{r.agents.map((a) => <button key={a.id} type="button" onClick={(e) => { e.stopPropagation(); onOpen(a); }} className="link text-left">{agentLabel(a)}</button>)}</span> },
    { id: "where", header: "Where", width: "minmax(160px, 1.2fr)", cell: (r) => <span className="mono caption truncate block">{r.tool.path}:{r.tool.line}</span>, sortValue: (r) => r.tool.path },
  ], [onOpen]);
  return <DataTable rows={sortRows(rows, columns, sort)} columns={columns} rowKey={(r) => r.key} sort={sort} onSort={onSort} ariaLabel="Tools" height={520} />;
}

function NameTable({ rows, label, onOpen }: { rows: NameRow[]; label: string; onOpen: (a: Agent) => void }) {
  return (
    <div className="panel overflow-x-auto">
      <table className="tbl">
        <thead><tr><th>{label}</th><th>Used by</th></tr></thead>
        <tbody>
          {rows.length === 0 ? <tr><td colSpan={2} className="caption text-center">None observed in this scan.</td></tr> : rows.map((r) => (
            <tr key={r.name}>
              <td><span className="mono">{r.name}</span>{r.sensitive ? <span className="ml-2"><Pill tone="warn">sensitive</Pill></span> : null}</td>
              <td className="flex flex-wrap gap-1">{r.agents.map((a) => <button key={a.id} type="button" onClick={() => onOpen(a)} className="link text-left">{agentLabel(a)}</button>)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeclarationsTable({ agents, onOpen }: { agents: Agent[]; onOpen: (a: Agent) => void }) {
  const { envelope } = useApp();
  const r = envelope.registry;
  return (
    <div>
      {r.business || r.governance ? (
        <div className="panel p-3 mb-3 text-[13px] grid gap-1 md:grid-cols-2">
          {r.business ? <div><span className="caption">Business: </span>{Object.entries(r.business).map(([k, v]) => `${k}=${Array.isArray(v) ? v.join("|") : String(v)}`).join(" · ")}</div> : null}
          {r.governance ? <div><span className="caption">Governance: </span>{Object.entries(r.governance).map(([k, v]) => `${k}=${typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}`).join(" · ")}</div> : null}
        </div>
      ) : null}
      <div className="panel overflow-x-auto">
        <table className="tbl">
          <thead><tr><th>Agent</th><th>Owner</th><th>Declared autonomy</th><th>Inferred</th><th>Status</th><th>Contradictions</th></tr></thead>
          <tbody>
            {agents.length === 0 ? <tr><td colSpan={6} className="caption text-center">No stoa-declared.toml entries in this scan.</td></tr> : agents.map((a) => {
              const d = a.declared!;
              const inferred = a.autonomy_level?.level ?? "indeterminate";
              const mismatch = Boolean(d.autonomy_intent && inferred !== "indeterminate" && d.autonomy_intent !== inferred);
              const n = contradictions(envelope, a).length;
              return (
                <tr key={a.id} data-clickable="true" onClick={() => onOpen(a)} tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") onOpen(a); }}>
                  <td className="font-medium">{agentLabel(a)}</td>
                  <td>{d.owner || <span className="caption">not declared</span>}</td>
                  <td>{d.autonomy_intent ?? <span className="caption">not declared</span>}</td>
                  <td className={mismatch ? "text-sev-high font-medium" : ""}>{inferred}</td>
                  <td>{d.production_status ?? <span className="caption">not declared</span>}</td>
                  <td>{n ? <Pill tone="warn">{n}</Pill> : <span className="caption">0</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
