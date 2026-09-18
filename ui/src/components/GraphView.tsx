import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core } from "cytoscape";
import { useApp } from "../app/context";
import { buildHash } from "../app/router";
import { SeverityBadge } from "./Badge";
import type { GraphEdge, GraphNode, Severity } from "../data/types";

/* The same visual grammar as the legacy report's graph (report_graph.py), on the same graph model. */
const SEVERITY_COLOR: Record<string, [string, string]> = {
  critical: ["#fde8e8", "#b42318"],
  high: ["#fdf0e0", "#b54708"],
  medium: ["#fef7dc", "#93700b"],
  low: ["#eef2f6", "#465063"],
  info: ["#e8f0fe", "#1d4ed8"],
  none: ["#f1f3f6", "#5a6272"],
};
const SEVERITY_RANK: Record<string, number> = { none: 0, info: 1, low: 2, medium: 3, high: 4, critical: 5 };
const SHAPE: Record<string, string> = { agent: "round-rectangle", mcp_server: "hexagon", tool: "round-diamond", resource: "barrel" };
const TYPES: { id: string; label: string }[] = [
  { id: "agent", label: "Agents" },
  { id: "mcp_server", label: "MCP servers" },
  { id: "tool", label: "Tools" },
  { id: "resource", label: "Resources" },
];

type Selected = { kind: "node"; node: GraphNode } | { kind: "edge"; edge: GraphEdge } | null;

export function GraphView() {
  const { envelope } = useApp();
  const graph = envelope.graph;
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const [selected, setSelected] = useState<Selected>(null);
  const [types, setTypes] = useState<Record<string, boolean>>({ agent: true, mcp_server: true, tool: true, resource: true });
  const [minSeverity, setMinSeverity] = useState("none");
  const [search, setSearch] = useState("");
  const nodesById = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph]);

  useEffect(() => {
    if (!container.current || !graph.nodes.length) return;
    const cy = cytoscape({
      container: container.current,
      elements: [
        ...graph.nodes.map((n) => ({ data: { id: n.id, label: n.label, type: n.type, severity: n.display_severity ?? "none" } })),
        ...graph.edges.map((e, i) => ({ data: { id: `e${i}`, source: e.source, target: e.target, kind: e.kind, severity: e.max_severity ?? "none", provenance: e.provenance, observed: e.observed ? 1 : 0 } })),
      ],
      style: [
        { selector: "node", style: {
          shape: (el: cytoscape.NodeSingular) => (SHAPE[el.data("type") as string] ?? "ellipse") as cytoscape.Css.NodeShape,
          "background-color": (el: cytoscape.NodeSingular) => (SEVERITY_COLOR[el.data("severity") as string] ?? SEVERITY_COLOR.none)![0],
          "border-color": (el: cytoscape.NodeSingular) => (SEVERITY_COLOR[el.data("severity") as string] ?? SEVERITY_COLOR.none)![1],
          "border-width": 2, label: "data(label)", "font-size": 10, color: "#1a1d23", "text-valign": "bottom", "text-margin-y": 4, width: 28, height: 28,
        } },
        { selector: "edge", style: {
          width: 1.5,
          "line-color": (el: cytoscape.EdgeSingular) => (SEVERITY_COLOR[el.data("severity") as string] ?? SEVERITY_COLOR.none)![1],
          "target-arrow-color": (el: cytoscape.EdgeSingular) => (SEVERITY_COLOR[el.data("severity") as string] ?? SEVERITY_COLOR.none)![1],
          "target-arrow-shape": "triangle", "curve-style": "bezier", opacity: 0.85,
        } },
        { selector: "edge[observed = 1]", style: { width: 3, opacity: 1 } },
        { selector: 'edge[provenance = "observed"]', style: { "line-style": "dashed", width: 2.5, opacity: 1 } },
        { selector: ".stoa-hidden", style: { display: "none" } },
      ],
      layout: { name: "cose", animate: false, nodeRepulsion: () => 8000, idealEdgeLength: () => 90 } as cytoscape.LayoutOptions,
    });
    cy.on("tap", "node", (evt) => {
      const node = nodesById.get(evt.target.id());
      if (node) setSelected({ kind: "node", node });
    });
    cy.on("tap", "edge", (evt) => {
      const index = Number.parseInt(String(evt.target.id()).slice(1), 10);
      const edge = graph.edges[index];
      if (edge) setSelected({ kind: "edge", edge });
    });
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [graph, nodesById]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const minRank = SEVERITY_RANK[minSeverity] ?? 0;
    const q = search.trim().toLowerCase();
    const visible: Record<string, boolean> = {};
    cy.nodes().forEach((node) => {
      const d = node.data() as { id: string; type: string; severity: string; label: string };
      const ok = types[d.type] !== false && (SEVERITY_RANK[d.severity] ?? 0) >= minRank && (!q || d.label.toLowerCase().includes(q));
      visible[d.id] = ok;
      node.toggleClass("stoa-hidden", !ok);
    });
    cy.edges().forEach((edge) => {
      const d = edge.data() as { source: string; target: string };
      edge.toggleClass("stoa-hidden", !(visible[d.source] && visible[d.target]));
    });
  }, [types, minSeverity, search]);

  if (!graph.nodes.length) return <p className="caption">No agent candidates detected, nothing to graph.</p>;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3 mb-3 text-[13px]">
        {TYPES.map((t) => (
          <label key={t.id} className="flex items-center gap-1">
            <input type="checkbox" checked={types[t.id] !== false} onChange={(e) => setTypes({ ...types, [t.id]: e.target.checked })} />
            {t.label}
          </label>
        ))}
        <label className="flex items-center gap-1">
          Min severity
          <select value={minSeverity} onChange={(e) => setMinSeverity(e.target.value)} className="rounded border border-line bg-panel px-1.5 py-0.5">
            <option value="none">All</option><option value="info">Info+</option><option value="low">Low+</option><option value="medium">Medium+</option><option value="high">High+</option><option value="critical">Critical</option>
          </select>
        </label>
        <label className="flex items-center gap-1">
          Search
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="label" className="rounded border border-line bg-panel px-1.5 py-0.5" />
        </label>
      </div>
      <div className="grid gap-3 lg:grid-cols-[1fr_320px]">
        <div ref={container} data-testid="graph-canvas" className="panel" style={{ height: 560 }} aria-label="Architecture graph" role="img" />
        <aside className="panel p-3 text-[13px] overflow-auto" style={{ maxHeight: 560 }}>
          {!selected ? <p className="caption m-0">Click a node or edge for its evidence. Every edge is declared (statically detected) unless marked observed.</p> : selected.kind === "node" ? <NodePanel node={selected.node} /> : <EdgePanel edge={selected.edge} nodesById={nodesById} />}
        </aside>
      </div>
    </div>
  );
}

function FindingList({ findings }: { findings: { rule_id: string; severity: Severity; path: string; line: number; message?: string }[] }) {
  if (!findings.length) return <p className="caption m-0">none</p>;
  return (
    <ul className="m-0 p-0 list-none flex flex-col gap-1">
      {findings.map((f, i) => (
        <li key={i} className="flex items-center gap-2" title={f.message ?? ""}>
          <SeverityBadge severity={f.severity} />
          <span className="mono">{f.rule_id}</span>
          <span className="caption mono truncate">{f.path}:{f.line}</span>
        </li>
      ))}
    </ul>
  );
}

function NodePanel({ node }: { node: GraphNode }) {
  const scores = Object.entries(node.dimension_scores);
  const agentId = node.type === "agent" ? node.id.replace(/^agent:/, "") : null;
  return (
    <div>
      <h3 className="text-[15px] m-0">{node.label}</h3>
      <p className="caption m-0 mt-1">{node.type}{node.path ? ` · ${node.path}${node.symbol ? ` :: ${node.symbol}` : ""}` : ""}</p>
      <p className="m-0 mt-2">Worst severity: {node.display_severity ? <SeverityBadge severity={node.display_severity} /> : "none observed"}</p>
      {scores.length ? (
        <div className="mt-2">
          <div className="caption">Dimension scores</div>
          <ul className="m-0 p-0 list-none">
            {scores.map(([k, v]) => <li key={k} className="flex justify-between gap-2"><span>{k}</span><span className="tabular-nums">{v}</span></li>)}
          </ul>
        </div>
      ) : null}
      <div className="mt-2">
        <div className="caption">Findings ({node.findings.length})</div>
        <FindingList findings={node.findings} />
      </div>
      {agentId ? <a href={buildHash("inventory", agentId)} className="link block mt-2">Open agent</a> : null}
    </div>
  );
}

function EdgePanel({ edge, nodesById }: { edge: GraphEdge; nodesById: Map<string, GraphNode> }) {
  return (
    <div>
      <h3 className="text-[15px] m-0">{nodesById.get(edge.source)?.label ?? edge.source}</h3>
      <p className="caption m-0">to {nodesById.get(edge.target)?.label ?? edge.target}</p>
      <p className="m-0 mt-2">kind: {edge.kind} · provenance: {edge.provenance}{edge.observed ? " (trace-corroborated)" : ""} · weight: {edge.weight}</p>
      <div className="mt-2">
        <div className="caption">Findings ({edge.findings.length})</div>
        <FindingList findings={edge.findings} />
      </div>
    </div>
  );
}
