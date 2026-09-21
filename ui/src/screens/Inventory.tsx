import { useMemo, useState } from "react";
import { useApp } from "../app/context";
import { buildHash, navigate, useRoute } from "../app/router";
import { AgentDrawer } from "../components/AgentDrawer";
import { ExposureBadge, Pill } from "../components/Badge";
import { DataTable, sortRows, type Column, type SortState } from "../components/DataTable";
import { GraphView } from "../components/GraphView";
import { Chips } from "../components/KeyValue";
import { ExposureTip } from "../components/InfoTip";
import { autonomyOf, definedIn, exposureOf, uniqueAgentById, uniqueAgents, type UniqueAgent } from "../data/agents";
import { agentCapabilities, agentFindingCount, agentSource, categories, codeAgents, contradictions, declaredAgents, filterAgents, filterUniqueAgents, iacAgents, integrationRows, providerRows, spendingAuthority, toolRows, uniqueAgentFindingCount, worstExposure, type CategoryId, type NameRow, type ToolRow } from "../data/inventory";
import { CAPABILITY_LABEL, CAPABILITY_ORDER, autonomyLabel, type CapabilityId } from "../data/labels";
import { EXPOSURE_RANK, agentById, agentLabel } from "../data/selectors";
import type { Agent } from "../data/types";

export function Inventory() {
  const { envelope } = useApp();
  const route = useRoute();
  const view = route.query.get("view") === "graph" ? "graph" : "table";
  const category = (route.query.get("category") ?? "agents") as CategoryId;
  const cats = categories(envelope);
  const [sort, setSort] = useState<SortState | null>(null);
  // A link may name a scanned record or a unique agent; a unique agent opens on its first record (code before infrastructure).
  const selected = route.id ? agentById(envelope.registry, route.id) ?? uniqueAgentById(envelope, route.id)?.records[0] ?? null : null;
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
        <h1 className="m-0">Agent Inventory</h1>
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
          <p className="caption mt-0 mb-3">Agents, tools, providers and what they reach. Click a node or edge for its evidence.</p>
          <GraphView />
        </div>
      ) : (
        <div className="mt-4 grid gap-4 md:grid-cols-[204px_minmax(0,1fr)]">
          <nav aria-label="Categories" className="panel p-2 self-start min-w-0 max-w-full overflow-hidden">
            <ul className="m-0 p-0 list-none flex md:flex-col gap-1 overflow-x-auto">
              {cats.map((c) => (
                <li key={c.id}>
                  <button type="button" onClick={() => setQuery({ category: c.id === "agents" ? null : c.id, authority: null, capability: null, q: null })} aria-current={category === c.id ? "true" : undefined} className={`w-full flex items-center justify-between gap-2 rounded px-2.5 py-1.5 text-left text-[13px] whitespace-nowrap ${category === c.id ? "bg-gold-100 text-navy border-l-2 border-gold" : "hover:bg-paper"}`}>
                    <span>{c.label}</span>
                    <span className="caption tabular-nums">{c.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          <div className="min-w-0">
            {category === "agents" ? (
              <UniqueAgentsTable query={route.query} onQuery={setQuery} onOpen={(u) => open(u.records[0]!)} sort={sort} onSort={onSort} />
            ) : category === "agents_code" || category === "agents_iac" ? (
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
    { id: "name", header: "Record", width: "minmax(180px, 1.4fr)", cell: (a) => <span className="block min-w-0"><span className="block font-medium truncate">{agentLabel(a)}</span><span className="caption block truncate">part of {uniqueAgentById(envelope, a.id)?.name ?? agentLabel(a)}</span></span>, sortValue: (a) => agentLabel(a) },
    { id: "type", header: "Type", width: "minmax(120px, 1fr)", cell: (a) => <span className="truncate block">{agentSource(a)}</span>, sortValue: (a) => agentSource(a) },
    { id: "location", header: "Location", width: "minmax(180px, 1.5fr)", cell: (a) => <span className="mono truncate block" title={a.path}>{a.path}</span>, sortValue: (a) => a.path },
    { id: "autonomy", header: "Autonomy", width: "170px", cell: (a) => <span className="text-[12.5px]" title={a.autonomy_level?.level ?? "indeterminate"}>{autonomyLabel(a.autonomy_level?.level)}</span>, sortValue: (a) => a.autonomy_level?.level ?? "" },
    { id: "exposure", header: "Exposure", hint: <ExposureTip align="right" />, width: "130px", cell: (a) => <ExposureBadge exposure={worstExposure(a)} />, sortValue: (a) => EXPOSURE_RANK[worstExposure(a)] },
    { id: "findings", header: "Findings", width: "96px", align: "right", cell: (a) => <span className="tabular-nums">{agentFindingCount(envelope, a)}</span>, sortValue: (a) => agentFindingCount(envelope, a) },
  ], [envelope]);
  const sorted = sortRows(rows, columns, sort ?? { column: "exposure", dir: "desc" });
  return (
    <div>
      <div className="panel px-3 py-2.5 flex flex-wrap items-center gap-3 mb-3 text-[13px] no-print sticky top-2 z-20">
        <input value={query.get("q") ?? ""} onChange={(e) => onQuery({ q: e.target.value || null })} placeholder="filter by name, path, capability" className="field" aria-label="Filter records" />
        <span className="caption">{sorted.length} of {agents.length} discovered records</span>
      </div>
      <DataTable rows={sorted} columns={columns} rowKey={(a) => a.id} onRowClick={onOpen} sort={sort} onSort={onSort} ariaLabel="Discovered records" height={520} />
    </div>
  );
}

/** The default view: one row per unique agent, however many places it was found in. */
function UniqueAgentsTable({ query, onQuery, onOpen, sort, onSort }: { query: URLSearchParams; onQuery: (p: Record<string, string | null>) => void; onOpen: (a: UniqueAgent) => void; sort: SortState | null; onSort: (c: string) => void }) {
  const { envelope } = useApp();
  const all = uniqueAgents(envelope);
  const rows = filterUniqueAgents(all, query);
  const selected = new Set((query.get("capability") ?? "").split(",").filter(Boolean));
  const present = CAPABILITY_ORDER.filter((id) => all.some((a) => agentCapabilities(a).includes(id)));
  const toggle = (id: CapabilityId) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    onQuery({ capability: CAPABILITY_ORDER.filter((c) => next.has(c)).join(",") || null });
  };
  const columns = useMemo<Column<UniqueAgent>[]>(() => [
    { id: "name", header: "Agent", width: "minmax(190px, 1.6fr)", cell: (a) => (
      <span className="block min-w-0">
        <span className="block font-medium text-navy truncate">{a.name}</span>
        <span className="mono caption block truncate" title={a.records.map((r) => `${agentLabel(r)} (${r.path})`).join("\n")}>{a.records.map(agentLabel).join(" · ")}</span>
        <span className="caption block">{definedIn(a)}</span>
      </span>
    ), sortValue: (a) => a.name.toLowerCase() },
    { id: "capabilities", header: "Capabilities", width: "minmax(136px, 1.2fr)", cell: (a) => <Chips items={agentCapabilities(a).map((id) => ({ label: CAPABILITY_LABEL[id], hot: id === "payments" }))} empty="none detected" />, sortValue: (a) => agentCapabilities(a).length },
    { id: "autonomy", header: "Autonomy", width: "minmax(108px, 0.9fr)", cell: (a) => <span title={autonomyOf(a) ?? "indeterminate"}>{autonomyLabel(autonomyOf(a))}</span>, sortValue: (a) => autonomyOf(a) ?? "" },
    { id: "spending", header: "Spending authority", width: "minmax(108px, 0.9fr)", cell: (a) => spendingAuthority(a) ? <span title="From your declaration file">{spendingAuthority(a)}</span> : null, sortValue: (a) => spendingAuthority(a) },
    { id: "exposure", header: "Exposure", hint: <ExposureTip align="right" />, width: "116px", cell: (a) => <ExposureBadge exposure={exposureOf(a)} />, sortValue: (a) => EXPOSURE_RANK[exposureOf(a)] },
    { id: "findings", header: "Findings", width: "84px", align: "right", cell: (a) => <span className="tabular-nums">{uniqueAgentFindingCount(envelope, a)}</span>, sortValue: (a) => uniqueAgentFindingCount(envelope, a) },
  ], [envelope]);
  const sorted = sortRows(rows, columns, sort ?? { column: "exposure", dir: "desc" });
  return (
    <div>
      <div className="panel px-3 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-2 mb-3 text-[13px] no-print sticky top-2 z-20">
        {present.length ? (
          <div role="group" aria-label="Filter by capability" className="flex flex-wrap items-center gap-1.5">
            <span className="caption">Can do</span>
            {present.map((id) => <button key={id} type="button" aria-pressed={selected.has(id)} onClick={() => toggle(id)} className={`rounded border px-2 py-1 text-[12px] leading-none cursor-pointer ${selected.has(id) ? "border-navy bg-navy text-white" : "border-line bg-paper text-ink hover:border-line-strong"}`}>{CAPABILITY_LABEL[id]}</button>)}
          </div>
        ) : null}
        <input value={query.get("q") ?? ""} onChange={(e) => onQuery({ q: e.target.value || null })} placeholder="filter by name or location" className="field" aria-label="Filter agents" />
        <span className="caption">{sorted.length} of {all.length} agents{envelope.registry.agents.length !== all.length ? ` · ${envelope.registry.agents.length} discovered records` : ""}</span>
      </div>
      <DataTable rows={sorted} columns={columns} rowKey={(a) => a.id} onRowClick={onOpen} sort={sort} onSort={onSort} ariaLabel="Agents" height={520} emptyText="No agent matches these filters." />
    </div>
  );
}

function ToolsTable({ rows, onOpen, sort, onSort }: { rows: ToolRow[]; onOpen: (a: Agent) => void; sort: SortState | null; onSort: (c: string) => void }) {
  const columns = useMemo<Column<ToolRow>[]>(() => [
    { id: "name", header: "Tool", width: "minmax(140px, 1.2fr)", cell: (r) => <span className="mono">{r.tool.name}</span>, sortValue: (r) => r.tool.name },
    { id: "kind", header: "Kind", width: "150px", cell: (r) => <span className="caption">{r.tool.kind}</span>, sortValue: (r) => r.tool.kind },
    { id: "effects", header: "Effects", width: "minmax(160px, 1.4fr)", cell: (r) => <Chips items={[...(r.tool.money_action ? [{ label: "money action", hot: true }] : []), ...(r.tool.high_impact && !r.tool.money_action ? [{ label: "high impact", hot: true }] : []), ...r.tool.capabilities.map((c) => ({ label: c })), ...r.tool.integrations.map((i) => ({ label: i }))]} empty="none observed" />, sortValue: (r) => Number(r.tool.high_impact) },
    { id: "guardrails", header: "Guardrails", width: "minmax(120px, 1fr)", cell: (r) => <span className="caption">{r.tool.guards.length ? r.tool.guards.join(", ") : "none detected"}{r.tool.retry ? ` · ${r.tool.idempotency_key ? "idempotent retry" : "retry, no idempotency key"}` : ""}</span> },
    { id: "agents", header: "Bound to", width: "minmax(140px, 1fr)", cell: (r) => <span className="flex flex-wrap gap-1">{r.agents.map((a) => <button key={a.id} type="button" onClick={(e) => { e.stopPropagation(); onOpen(a); }} className="link text-left">{agentLabel(a)}</button>)}</span> },
    { id: "where", header: "Where", width: "minmax(160px, 1.2fr)", cell: (r) => <span className="mono caption truncate block">{r.tool.path}:{r.tool.line}</span>, sortValue: (r) => r.tool.path },
  ], [onOpen]);
  return <DataTable rows={sortRows(rows, columns, sort)} columns={columns} rowKey={(r) => r.key} sort={sort} onSort={onSort} ariaLabel="Tools" height={520} />;
}

function NameTable({ rows, label, onOpen }: { rows: NameRow[]; label: string; onOpen: (a: Agent) => void }) {
  return (
    <div className="panel overflow-x-auto" tabIndex={0}>
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

export function DeclarationsTable({ agents, onOpen }: { agents: Agent[]; onOpen: (a: Agent) => void }) {
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
      <div className="panel overflow-x-auto" tabIndex={0}>
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
