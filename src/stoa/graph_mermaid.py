"""Render an architecture Graph as Mermaid flowchart source.

Output is deterministic (nodes/edges are already sorted by build_graph) so
renders are diffable in PRs and golden-testable.
"""

from __future__ import annotations

import sys

from .graph_model import Graph, node_severities

MAX_NODES_BEFORE_WARNING = 50

# Severity -> the exact hex values used in report_html.py's _CSS, so the
# Mermaid render and the HTML report always agree on what a color means.
_SEVERITY_COLOR = {
    "critical": ("#fde8e8", "#b42318"),
    "high": ("#fdf0e0", "#b54708"),
    "medium": ("#fef7dc", "#93700b"),
    "low": ("#eef2f6", "#465063"),
    "info": ("#e8f0fe", "#1d4ed8"),
    None: ("#f1f3f6", "#5a6272"),  # no findings observed
}

_SHAPE = {
    "agent": ("[", "]"),
    "mcp_server": ("{{", "}}"),
    "tool": ("(", ")"),
    "resource": ("[(", ")]"),
}


def _mermaid_id(raw_id: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in raw_id)
    if not safe or safe[0].isdigit():
        safe = f"n_{safe}"
    return safe


def _mermaid_label(label: str) -> str:
    escaped = label.replace('"', "&quot;").replace("{", "(").replace("}", ")")
    escaped = escaped.replace("[", "(").replace("]", ")")
    return f'"{escaped}"'


def _class_name(severity: str | None) -> str:
    return f"sev_{severity or 'none'}"


def _subgraph_node_ids(graph: Graph, focus: str) -> set[str]:
    ids = {focus}
    for edge in graph.edges:
        if edge.source == focus:
            ids.add(edge.target)
        elif edge.target == focus:
            ids.add(edge.source)
    return ids


def render_mermaid(graph: Graph, focus: str | None = None) -> str:
    """Render ``graph`` as ``graph LR`` Mermaid source.

    ``focus``, if given, limits the render to that node id plus its direct
    (1-hop) neighbors. Unknown focus ids render an empty-but-valid diagram
    with a comment noting the id wasn't found, rather than raising.
    """
    if graph.is_empty:
        return "graph LR\n%% no agents detected in this scan\n"

    nodes = graph.nodes
    edges = graph.edges
    if focus is not None:
        wanted = _subgraph_node_ids(graph, focus)
        if focus not in {n.id for n in nodes}:
            return f"graph LR\n%% focus id not found: {focus}\n"
        nodes = tuple(n for n in nodes if n.id in wanted)
        edges = tuple(e for e in edges if e.source in wanted and e.target in wanted)
    elif len(nodes) > MAX_NODES_BEFORE_WARNING:
        print(
            f"stoa: graph has {len(nodes)} nodes; consider --focus AGENT_ID "
            "for a readable diagram",
            file=sys.stderr,
        )

    severities = node_severities(Graph(nodes=nodes, edges=edges))

    lines = ["graph LR"]
    for node in nodes:
        open_ch, close_ch = _SHAPE[node.type]
        mid = _mermaid_id(node.id)
        lines.append(
            f"  {mid}{open_ch}{_mermaid_label(node.label)}{close_ch}:::{_class_name(severities.get(node.id))}"
        )

    for edge in edges:
        src = _mermaid_id(edge.source)
        dst = _mermaid_id(edge.target)
        if edge.findings:
            rule_ids = sorted({f.rule_id for f in edge.findings})
            label = f"{edge.kind}: {rule_ids[0]}"
            if len(rule_ids) > 1:
                label += f" +{len(rule_ids) - 1}"
        else:
            label = edge.kind
        if edge.observed:
            label += " (observed)"
        # Runtime-only edges (provenance "observed": delegates, runtime-
        # discovered reach) render dotted; statically-declared edges keep
        # today's solid arrow, so graphs without runtime data are unchanged.
        arrow = "-.->" if edge.provenance == "observed" else "-->"
        lines.append(f"  {src} {arrow}|{_mermaid_label(label)}| {dst}")

    for severity, (bg, fg) in _SEVERITY_COLOR.items():
        lines.append(
            f"  classDef {_class_name(severity)} fill:{bg},stroke:{fg},color:{fg};"
        )

    return "\n".join(lines) + "\n"
