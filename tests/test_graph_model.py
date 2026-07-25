"""Architecture graph model: node/edge extraction, determinism, empty input."""

from __future__ import annotations

from stoa.graph_model import build_graph, node_severities, to_json_dict


def finding(rule_id, severity="high", path="a.py", line=1, message=None):
    return {"rule_id": rule_id, "severity": severity, "path": path, "line": line, "message": message}


def agent(id="a1", name="agt", path="a.py", symbol="agt", frameworks=None,
          caps=None, integs=None, providers=None, call_sites=None, findings=None,
          dims=None, highest_severity=None, autonomy_level=None):
    a = {
        "id": id, "name": name, "path": path, "symbol": symbol,
        "frameworks": frameworks or [], "capabilities": caps or [],
        "integrations": integs or [], "providers": providers or [],
        "call_sites": call_sites or {}, "findings": findings or [],
        "highest_severity": highest_severity,
    }
    if dims is not None:
        a["dimension_assessment"] = {"dimensions": dims}
    if autonomy_level is not None:
        a["autonomy_level"] = {"level": autonomy_level, "signals": [], "reason": None}
    return a


def registry(agents):
    return {"agents": agents}


# --- empty / basic shape ------------------------------------------------


def test_empty_registry_is_empty_graph():
    g = build_graph(registry([]))
    assert g.is_empty
    assert g.nodes == () and g.edges == ()


def test_missing_agents_key_is_empty_graph():
    g = build_graph({})
    assert g.is_empty


def test_agent_node_created_with_expected_fields():
    a = agent(id="a1", name="My Agent", path="p.py", symbol="run",
              highest_severity="critical", dims=[{"id": "data-exfiltration", "score": 40}])
    g = build_graph(registry([a]))
    node = next(n for n in g.nodes if n.id == "a1")
    assert node.type == "agent"
    assert node.label == "My Agent"
    assert node.worst_severity == "critical"
    assert node.path == "p.py" and node.symbol == "run"
    assert node.dimension_scores == {"data-exfiltration": 40}


def test_mcp_framework_produces_mcp_server_node_type():
    a = agent(id="m1", frameworks=["mcp"])
    g = build_graph(registry([a]))
    node = next(n for n in g.nodes if n.id == "m1")
    assert node.type == "mcp_server"


# --- tool / resource edges -----------------------------------------------


def test_integration_produces_tool_node_and_edge():
    a = agent(id="a1", integs=["stripe"], call_sites={"stripe": 3})
    g = build_graph(registry([a]))
    tool = next(n for n in g.nodes if n.type == "tool" and n.label == "stripe")
    edge = next(e for e in g.edges if e.target == tool.id)
    assert edge.source == "a1"
    assert edge.kind == "tool_call"
    assert edge.weight == 3


def test_provider_produces_tool_node_and_edge():
    a = agent(id="a1", providers=["openai"])
    g = build_graph(registry([a]))
    tool = next(n for n in g.nodes if n.type == "tool" and n.label == "openai")
    edge = next(e for e in g.edges if e.target == tool.id)
    assert edge.kind == "tool_call"


def test_capability_produces_resource_node_with_correct_kind():
    a = agent(id="a1", caps=["filesystem_read", "filesystem_write", "external_http"])
    g = build_graph(registry([a]))
    kinds = {e.target: e.kind for e in g.edges}
    assert kinds["resource_filesystem_read"] == "reads"
    assert kinds["resource_filesystem_write"] == "writes"
    assert kinds["resource_external_http"] == "network"


def test_mcp_tools_capability_has_mcp_edge_kind():
    a = agent(id="a1", caps=["mcp_tools"])
    g = build_graph(registry([a]))
    edge = next(e for e in g.edges if e.target == "resource_mcp_tools")
    assert edge.kind == "mcp"


def test_meta_capabilities_produce_no_resource_node():
    a = agent(id="a1", caps=["tool_calling", "function_calling"])
    g = build_graph(registry([a]))
    assert not any(n.type == "resource" for n in g.nodes)
    assert g.edges == ()


def test_shared_tool_node_across_agents():
    a1 = agent(id="a1", integs=["stripe"])
    a2 = agent(id="a2", integs=["stripe"])
    g = build_graph(registry([a1, a2]))
    tools = [n for n in g.nodes if n.type == "tool" and n.label == "stripe"]
    assert len(tools) == 1
    targets = [e.target for e in g.edges if e.target == tools[0].id]
    assert len(targets) == 2


# --- edge/finding correlation --------------------------------------------


def test_sec001_attaches_to_tool_edge_not_resource_edge():
    f = finding("SEC001", severity="critical")
    a = agent(id="a1", integs=["stripe"], caps=["filesystem_read"], findings=[f])
    g = build_graph(registry([a]))
    tool_edge = next(e for e in g.edges if e.kind == "tool_call")
    resource_edge = next(e for e in g.edges if e.kind == "reads")
    assert [ref.rule_id for ref in tool_edge.findings] == ["SEC001"]
    assert resource_edge.findings == ()


def test_sec003_attaches_to_database_resource_edge():
    f = finding("SEC003", severity="high", path="a.py", line=9)
    a = agent(id="a1", caps=["database_write"], findings=[f])
    g = build_graph(registry([a]))
    edge = next(e for e in g.edges if e.target == "resource_database_write")
    assert [ref.rule_id for ref in edge.findings] == ["SEC003"]
    assert edge.findings[0].line == 9
    assert edge.max_severity == "high"


def test_ai003_attaches_to_high_impact_capability_edges():
    f = finding("AI003", severity="info")
    a = agent(id="a1", caps=["payment_access"], findings=[f])
    g = build_graph(registry([a]))
    edge = next(e for e in g.edges if e.target == "resource_payment_access")
    assert "AI003" in [ref.rule_id for ref in edge.findings]


def test_ctrl_and_rel_findings_never_attach_to_any_edge():
    findings = [finding("CTRL001", severity="info"), finding("REL001", severity="low")]
    a = agent(id="a1", integs=["stripe"], caps=["shell_execution"], findings=findings)
    g = build_graph(registry([a]))
    for edge in g.edges:
        assert edge.findings == ()
    # but they DO still show up on the agent node itself
    node = next(n for n in g.nodes if n.id == "a1")
    assert {ref.rule_id for ref in node.findings} == {"CTRL001", "REL001"}


def test_unrelated_rule_does_not_attach_to_unrelated_edge():
    f = finding("SEC003", severity="high")  # SQL injection: db-only
    a = agent(id="a1", integs=["slack"], findings=[f])
    g = build_graph(registry([a]))
    edge = next(e for e in g.edges if e.kind == "tool_call")
    assert edge.findings == ()


# --- determinism + severity rollup ----------------------------------------


def test_build_graph_is_deterministic():
    a = agent(id="a1", integs=["stripe", "slack"], caps=["external_http", "database_write"])
    g1 = build_graph(registry([a]))
    g2 = build_graph(registry([a]))
    assert [n.id for n in g1.nodes] == [n.id for n in g2.nodes]
    assert [(e.source, e.target, e.kind) for e in g1.edges] == \
           [(e.source, e.target, e.kind) for e in g2.edges]


def test_node_severities_rolls_up_from_edges_for_resource_nodes():
    f = finding("NET001", severity="medium")
    a = agent(id="a1", caps=["external_http"], findings=[f])
    g = build_graph(registry([a]))
    sev = node_severities(g)
    assert sev["resource_external_http"] == "medium"


def test_to_json_dict_round_trips_through_json():
    import json

    a = agent(id="a1", name="agt", integs=["stripe"], caps=["external_http"],
              findings=[finding("NET001")], dims=[{"id": "model-drift", "score": 10}])
    g = build_graph(registry([a]))
    payload = to_json_dict(g)
    text = json.dumps(payload)  # must be plain-JSON-serializable
    reloaded = json.loads(text)
    assert len(reloaded["nodes"]) == len(g.nodes)
    assert len(reloaded["edges"]) == len(g.edges)


def test_autonomy_level_propagates_to_agent_node():
    a = agent(id="a1", autonomy_level="unrestricted_autonomous")
    g = build_graph(registry([a]))
    node = next(n for n in g.nodes if n.id == "a1")
    assert node.autonomy_level == "unrestricted_autonomous"
    payload = to_json_dict(g)
    assert payload["nodes"][0]["autonomy_level"] == "unrestricted_autonomous"


def test_autonomy_level_absent_when_not_populated():
    a = agent(id="a1")
    g = build_graph(registry([a]))
    node = next(n for n in g.nodes if n.id == "a1")
    assert node.autonomy_level is None
