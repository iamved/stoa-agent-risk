"""Mermaid export: ID sanitization, label escaping, focus, large-graph warning."""

from __future__ import annotations

import sys

from stoa.graph_mermaid import MAX_NODES_BEFORE_WARNING, render_mermaid
from stoa.graph_model import build_graph


def finding(rule_id, severity="high", path="a.py", line=1):
    return {"rule_id": rule_id, "severity": severity, "path": path, "line": line}


def agent(id, name="agt", caps=None, integs=None, findings=None):
    return {
        "id": id, "name": name, "path": "a.py", "symbol": name,
        "frameworks": [], "capabilities": caps or [], "integrations": integs or [],
        "providers": [], "call_sites": {}, "findings": findings or [],
        "highest_severity": None,
    }


def registry(agents):
    return {"agents": agents}


def test_empty_graph_renders_valid_comment_only_diagram():
    g = build_graph(registry([]))
    out = render_mermaid(g)
    assert out.startswith("graph LR")
    assert "%%" in out


def test_basic_render_contains_graph_lr_and_classdefs():
    g = build_graph(registry([agent("1abc", integs=["stripe"])]))
    out = render_mermaid(g)
    assert out.startswith("graph LR\n")
    assert "classDef sev_critical" in out
    assert "classDef sev_none" in out


def test_numeric_leading_id_gets_prefixed():
    g = build_graph(registry([agent("1abc")]))
    out = render_mermaid(g)
    assert "n_1abc[" in out
    assert "\n1abc[" not in out  # never emitted unprefixed


def test_label_with_special_chars_is_escaped():
    g = build_graph(registry([agent("a1", name='we"ird [name] {x}')]))
    out = render_mermaid(g)
    # quotes escaped, mermaid-breaking brackets/braces normalized to parens
    assert "&quot;" in out
    assert "[name]" not in out
    assert "{x}" not in out


def test_focus_includes_only_direct_neighbors():
    a1 = agent("a1", integs=["stripe"])
    a2 = agent("a2", integs=["slack"])
    g = build_graph(registry([a1, a2]))
    out = render_mermaid(g, focus="a1")
    assert "stripe" in out
    assert "slack" not in out
    assert "a2" not in out


def test_unknown_focus_id_renders_safe_empty_comment():
    g = build_graph(registry([agent("a1")]))
    out = render_mermaid(g, focus="does-not-exist")
    assert out.startswith("graph LR")
    assert "not found" in out


def test_edge_label_shows_kind_and_first_rule_with_overflow_count():
    findings = [finding("SEC001"), finding("SEC002")]
    g = build_graph(registry([agent("a1", integs=["stripe"], findings=findings)]))
    out = render_mermaid(g)
    assert "tool_call: SEC001 +1" in out


def test_edge_label_shows_kind_only_when_no_findings():
    g = build_graph(registry([agent("a1", caps=["filesystem_read"])]))
    out = render_mermaid(g)
    assert "|\"reads\"|" in out


def test_large_graph_warns_on_stderr_but_still_renders(capsys):
    agents = [agent(f"a{i}", integs=[f"tool{i}"]) for i in range(MAX_NODES_BEFORE_WARNING)]
    g = build_graph(registry(agents))
    assert len(g.nodes) > MAX_NODES_BEFORE_WARNING
    out = render_mermaid(g)
    err = capsys.readouterr().err
    assert "--focus" in err
    assert out.startswith("graph LR")
    assert "graph LR\n  n_" in out or "graph LR\n  a" in out


def test_small_graph_does_not_warn(capsys):
    g = build_graph(registry([agent("a1", integs=["stripe"])]))
    render_mermaid(g)
    assert capsys.readouterr().err == ""
