"""Architecture graph: a derived, read-only lens over a scanned registry.

``build_graph()`` is a pure function over the JSON-serializable registry
document (the same shape written to ``stoa-registry.json`` / returned by
:func:`stoa.report_json.build_document`) — it adds no new persisted schema
fields and requires no registry-version bump.

Registry fields carry no per-instance location data for capabilities or
integrations (only a static match count via ``call_sites``), so ``resource``
and ``tool`` nodes are shared, by identity/class, across every agent that
touches them; only ``agent``/``mcp_server`` nodes carry a single source
location (their file path + symbol). Every edge's ``findings`` are populated
by a small, documented rule-id correlation table (see
``_RULE_EDGE_TARGETS``) — never a blanket attach of every finding on the
agent — so a user can trace an edge back to the specific evidence that
explains it.

Edge ``provenance`` is the edge's *origin*: ``"declared"`` (statically
detected from source — everything ``build_graph`` emits) or ``"observed"``
(discovered only from runtime traces — emitted exclusively by
:func:`overlay_runtime`, never by ``build_graph``). A statically-declared
edge that traces *corroborate* keeps ``provenance="declared"`` and gains the
additive ``observed: true`` flag instead, preserving the single-valued
origin enum while still distinguishing corroboration (see
docs/design/runtime-overlay.md §6).

Inter-agent delegation is modeled only from runtime evidence: the registry's
*static* schema has no call-graph or handoff data between agents, so
``build_graph`` emits no agent-to-agent edges; ``overlay_runtime`` emits
``"delegates"`` edges from delegation spans recorded in
``runtime_evidence.delegations_to``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

NODE_TYPES = ("agent", "mcp_server", "tool", "resource")
EDGE_KINDS = ("delegates", "tool_call", "mcp", "reads", "writes", "network")
PROVENANCES = ("declared", "observed")  # "observed": runtime-trace-sourced edges only

_ID_SAFE = re.compile(r"[^a-z0-9_]+")


def _slug(value: str) -> str:
    return _ID_SAFE.sub("_", value.lower()).strip("_") or "node"


# --- capability -> resource-node kind + human label -------------------------
# Every capability id from rules.CAPABILITY_PATTERNS except the two
# meta-capabilities ("tool_calling", "function_calling" describe how an agent
# calls tools, not an external sink) becomes a resource node. mcp_tools gets
# its own "mcp" edge kind rather than folding into reads/writes/network.
_READS = {
    "database_read", "filesystem_read", "vector_search",
    "document_processing", "pdf_processing", "cache_access", "queue_access",
}
_WRITES = {
    "database_write", "filesystem_write", "code_execution", "shell_execution",
    "cloud_resource_access", "source_control", "payment_access", "customer_support",
}
_NETWORK = {
    "web_search", "browser_automation", "external_http", "email_send", "messaging",
}

CAPABILITY_EDGE_KIND: dict[str, str] = {
    **{cap: "reads" for cap in _READS},
    **{cap: "writes" for cap in _WRITES},
    **{cap: "network" for cap in _NETWORK},
    "mcp_tools": "mcp",
}

_LABEL_OVERRIDES = {
    "mcp_tools": "MCP tools",
    "external_http": "External HTTP",
    "pdf_processing": "PDF processing",
    "cache_access": "Cache",
    "queue_access": "Message queue",
}


def _capability_label(capability: str) -> str:
    return _LABEL_OVERRIDES.get(capability, capability.replace("_", " ").capitalize())


# --- rule id -> which edge category it explains ------------------------------
# A finding is attached to an edge only when its rule_id is listed here for
# that edge's target category. CTRL001-004 (control-not-observed prompts) and
# REL001 (swallowed exception) are agent-level smells, not specific to any one
# edge, so they are deliberately never attached to an edge.
_RULE_TARGETS_PROVIDER = {"AI001", "AI004", "AI005", "AI007", "SEC001", "SEC002"}
_RULE_TARGETS_TOOL = {"SEC001", "SEC002"}
_RULE_TARGETS_NETWORK_RESOURCE = {"NET001", "NET002", "AI006"}
_RULE_TARGETS_DB_RESOURCE = {"SEC003"}
_RULE_TARGETS_EXEC_RESOURCE = {"AI002"}


def _rules_for_resource_edge(capability: str) -> set[str]:
    rules = set()
    if capability in ("database_read", "database_write"):
        rules |= _RULE_TARGETS_DB_RESOURCE
    if capability in ("code_execution", "shell_execution"):
        rules |= _RULE_TARGETS_EXEC_RESOURCE
    if capability in _NETWORK:
        rules |= _RULE_TARGETS_NETWORK_RESOURCE
    from .rules import HIGH_IMPACT_CAPABILITIES

    if capability in HIGH_IMPACT_CAPABILITIES:
        rules.add("AI003")
    return rules


@dataclass
class FindingRef:
    """A lightweight, evidence-traceable pointer to the Finding explaining a
    node or edge — never the full Finding object, just enough for a UI to
    show and link to it."""

    rule_id: str
    severity: str
    path: str
    line: int
    message: str | None = None


@dataclass
class GraphNode:
    id: str
    type: str  # one of NODE_TYPES
    label: str
    dimension_scores: dict[str, int] = field(default_factory=dict)
    worst_severity: str | None = None  # None: no findings observed on this node
    path: str | None = None  # populated for "agent"/"mcp_server" nodes only
    symbol: str | None = None
    findings: tuple[FindingRef, ...] = ()  # all findings on this agent's file
    autonomy_level: str | None = None  # agent/mcp_server nodes only


@dataclass
class GraphEdge:
    source: str
    target: str
    kind: str  # one of EDGE_KINDS
    findings: tuple[FindingRef, ...] = ()  # the specific findings explaining this edge
    max_severity: str | None = None
    provenance: str = "declared"
    weight: int = 1  # call_sites count when known, else 1
    # True when runtime traces corroborate a statically-declared edge.
    # Serialized only when true, so registries without runtime evidence
    # produce byte-identical graph JSON to previous releases.
    observed: bool = False


@dataclass
class Graph:
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.nodes


_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _max_severity(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if _SEVERITY_RANK[a] >= _SEVERITY_RANK[b] else b


def build_graph(registry: dict) -> Graph:
    """Build the architecture graph from a registry document (dict).

    Pure function, no I/O. An empty/agent-less registry yields an empty
    ``Graph`` (``graph.is_empty``), never an error.
    """
    agents = registry.get("agents") or []

    nodes: dict[str, GraphNode] = {}
    edges: dict[tuple[str, str, str], GraphEdge] = {}

    for agent in agents:
        agent_id = agent["id"]
        frameworks = agent.get("frameworks") or []
        node_type = "mcp_server" if "mcp" in frameworks else "agent"
        dim_scores = {
            d["id"]: d["score"]
            for d in (agent.get("dimension_assessment") or {}).get("dimensions", [])
        }
        findings = agent.get("findings") or []
        node_findings = tuple(_finding_ref(f) for f in findings)
        nodes[agent_id] = GraphNode(
            id=agent_id,
            type=node_type,
            label=agent.get("name", agent_id),
            dimension_scores=dim_scores,
            worst_severity=agent.get("highest_severity"),
            path=agent.get("path"),
            symbol=agent.get("symbol"),
            findings=node_findings,
            autonomy_level=(agent.get("autonomy_level") or {}).get("level"),
        )

        findings_by_rule: dict[str, list[dict]] = {}
        for f in findings:
            findings_by_rule.setdefault(f["rule_id"], []).append(f)

        call_sites = agent.get("call_sites") or {}

        # tool edges: named integrations + providers
        for integration in agent.get("integrations") or []:
            tool_id = f"tool_{_slug(integration)}"
            if tool_id not in nodes:
                nodes[tool_id] = GraphNode(id=tool_id, type="tool", label=integration)
            matched = [
                f for rid in _RULE_TARGETS_TOOL for f in findings_by_rule.get(rid, [])
            ]
            _add_edge(
                edges, agent_id, tool_id, "tool_call",
                matched, weight=call_sites.get(integration, 1),
            )

        for provider in agent.get("providers") or []:
            tool_id = f"tool_{_slug(provider)}"
            if tool_id not in nodes:
                nodes[tool_id] = GraphNode(id=tool_id, type="tool", label=provider)
            matched = [
                f for rid in _RULE_TARGETS_PROVIDER for f in findings_by_rule.get(rid, [])
            ]
            _add_edge(edges, agent_id, tool_id, "tool_call", matched)

        # resource edges: capability classes
        for capability in agent.get("capabilities") or []:
            kind = CAPABILITY_EDGE_KIND.get(capability)
            if kind is None:  # tool_calling / function_calling: no external sink
                continue
            resource_id = f"resource_{capability}"
            if resource_id not in nodes:
                nodes[resource_id] = GraphNode(
                    id=resource_id, type="resource", label=_capability_label(capability)
                )
            wanted_rules = _rules_for_resource_edge(capability)
            matched = [f for rid in wanted_rules for f in findings_by_rule.get(rid, [])]
            _add_edge(edges, agent_id, resource_id, kind, matched)

    sorted_nodes = tuple(
        sorted(nodes.values(), key=lambda n: (n.type, n.id))
    )
    sorted_edges = tuple(
        sorted(edges.values(), key=lambda e: (e.source, e.target, e.kind))
    )
    return Graph(nodes=sorted_nodes, edges=sorted_edges)


def _finding_ref_dict(ref: FindingRef) -> dict:
    d = {"rule_id": ref.rule_id, "severity": ref.severity, "path": ref.path, "line": ref.line}
    if ref.message:
        d["message"] = ref.message
    return d


def to_json_dict(graph: Graph) -> dict:
    """Serialize ``graph`` to the plain-dict shape embedded in the report's
    JSON data blob (and available for any other consumer)."""
    severities = node_severities(graph)
    return {
        "nodes": [
            {
                "id": n.id,
                "type": n.type,
                "label": n.label,
                "dimension_scores": n.dimension_scores,
                "display_severity": severities.get(n.id),
                "path": n.path,
                "symbol": n.symbol,
                "autonomy_level": n.autonomy_level,
                "findings": [_finding_ref_dict(f) for f in n.findings],
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "source": e.source,
                "target": e.target,
                "kind": e.kind,
                "provenance": e.provenance,
                "max_severity": e.max_severity,
                "weight": e.weight,
                "findings": [_finding_ref_dict(f) for f in e.findings],
                **({"observed": True} if e.observed else {}),
            }
            for e in graph.edges
        ],
    }


def node_severities(graph: Graph) -> dict[str, str | None]:
    """Display severity per node: the node's own ``worst_severity`` if it has
    one (agents), else the max severity of any edge touching it (tool/resource
    nodes carry no severity of their own — it lives on the edges instead).
    """
    severities: dict[str, str | None] = {n.id: n.worst_severity for n in graph.nodes}
    for edge in graph.edges:
        for node_id in (edge.source, edge.target):
            severities[node_id] = _max_severity(severities.get(node_id), edge.max_severity)
    return severities


def _finding_ref(finding: dict) -> FindingRef:
    return FindingRef(
        rule_id=finding["rule_id"],
        severity=finding["severity"],
        path=finding["path"],
        line=finding["line"],
        message=finding.get("message"),
    )


def _dedupe_finding_refs(refs: list[FindingRef]) -> tuple[FindingRef, ...]:
    seen: dict[tuple[str, str, int], FindingRef] = {}
    for ref in refs:
        seen[(ref.rule_id, ref.path, ref.line)] = ref
    return tuple(
        sorted(seen.values(), key=lambda r: (r.rule_id, r.path, r.line))
    )


def overlay_runtime(graph: Graph, registry: dict) -> Graph:
    """Overlay runtime evidence from an *enriched* registry onto a graph.

    Reads the per-agent ``runtime_evidence`` blocks written by
    ``stoa runtime merge`` — never trace files directly — and returns a new
    ``Graph`` (inputs are not mutated):

    - a statically-declared edge whose capability/integration was observed
      in traces gains ``observed=True`` (dual evidence, ``declared`` origin);
    - an observed capability/integration with **no** static edge becomes a
      new edge with ``provenance="observed"`` (runtime-only reach — the
      graph-level view of what RT003 reports as a finding);
    - ``delegations_to`` entries become ``"delegates"`` edges with
      ``provenance="observed"``, but only between nodes the graph already
      has — a delegation to an id the registry doesn't know is reported in
      the analysis document's ``unmatched_agents``, not drawn as an edge to
      a node that can't be labeled.

    A registry with no ``runtime_evidence`` blocks returns an identical
    graph.
    """
    nodes: dict[str, GraphNode] = {n.id: n for n in graph.nodes}
    edges: dict[tuple[str, str, str], GraphEdge] = {
        (e.source, e.target, e.kind): e for e in graph.edges
    }

    for agent in registry.get("agents") or []:
        evidence = agent.get("runtime_evidence")
        if not evidence or agent["id"] not in nodes:
            continue
        agent_id = agent["id"]

        for capability in evidence.get("observed_capabilities") or []:
            kind = CAPABILITY_EDGE_KIND.get(capability)
            if kind is None:
                continue  # meta-capabilities / custom ids: no external sink
            resource_id = f"resource_{capability}"
            key = (agent_id, resource_id, kind)
            if key in edges:
                edges[key] = replace(edges[key], observed=True)
            else:
                if resource_id not in nodes:
                    nodes[resource_id] = GraphNode(
                        id=resource_id, type="resource",
                        label=_capability_label(capability),
                    )
                edges[key] = GraphEdge(
                    source=agent_id, target=resource_id, kind=kind,
                    provenance="observed",
                )

        for integration in evidence.get("observed_integrations") or []:
            tool_id = f"tool_{_slug(integration)}"
            key = (agent_id, tool_id, "tool_call")
            if key in edges:
                edges[key] = replace(edges[key], observed=True)
            else:
                if tool_id not in nodes:
                    nodes[tool_id] = GraphNode(id=tool_id, type="tool", label=integration)
                edges[key] = GraphEdge(
                    source=agent_id, target=tool_id, kind="tool_call",
                    provenance="observed",
                )

        for target_id in evidence.get("delegations_to") or []:
            if target_id in nodes:
                key = (agent_id, target_id, "delegates")
                if key not in edges:
                    edges[key] = GraphEdge(
                        source=agent_id, target=target_id, kind="delegates",
                        provenance="observed",
                    )

    return Graph(
        nodes=tuple(sorted(nodes.values(), key=lambda n: (n.type, n.id))),
        edges=tuple(sorted(edges.values(), key=lambda e: (e.source, e.target, e.kind))),
    )


def _add_edge(
    edges: dict[tuple[str, str, str], GraphEdge],
    source: str,
    target: str,
    kind: str,
    matched_findings: list[dict],
    weight: int = 1,
) -> None:
    key = (source, target, kind)
    refs = [_finding_ref(f) for f in matched_findings]
    max_sev = None
    for ref in refs:
        max_sev = _max_severity(max_sev, ref.severity)
    existing = edges.get(key)
    if existing is None:
        edges[key] = GraphEdge(
            source=source, target=target, kind=kind,
            findings=_dedupe_finding_refs(refs), max_severity=max_sev, weight=weight,
        )
        return
    # An agent can list the same integration name twice across detections in
    # rare cases; merge defensively rather than overwrite.
    existing.findings = _dedupe_finding_refs(list(existing.findings) + refs)
    existing.max_severity = _max_severity(existing.max_severity, max_sev)
    existing.weight = max(existing.weight, weight)
