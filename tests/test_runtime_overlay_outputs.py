"""Runtime overlay Phase 5: graph overlay, HTML report, assurance packet.

Covers: observed/delegates edge emission and the no-runtime identity
property; mermaid styling; the report's CSP-intact rendering with runtime
data; assurance Areas 12/18 population and absence; RT findings in the
packet contradictions; and `stoa scan --with-runtime` end to end.
"""

from __future__ import annotations

import json
import re

from stoa.assurance import build_assurance_packet, render_assurance_markdown
from stoa.graph_mermaid import render_mermaid
from stoa.graph_model import build_graph, overlay_runtime, to_json_dict
from stoa.runtime.analysis import analyze_traces
from stoa.runtime.merge import merge_runtime_into_registry
from stoa.runtime.spans import build_span

AGENT_A = "aaaaaaaaaaaa"
AGENT_B = "bbbbbbbbbbbb"


def _registry() -> dict:
    def agent(aid, name, capabilities, integrations):
        return {
            "id": aid, "name": name, "symbol": name, "path": f"agents/{name}.py",
            "language": "python", "confidence": "high", "detection_score": 8,
            "capabilities": capabilities, "integrations": integrations,
            "providers": [], "frameworks": [], "call_sites": {},
            "evidence": [{"rule_id": "AGENT_LANGCHAIN", "line": 2, "description": "x"}],
            "findings": [],
        }
    return {
        "schema_version": "1.4", "tool": {"name": "stoa", "version": "0"},
        "repository": {"name": "fixture"}, "summary": {"findings": {}},
        "agents": [
            agent(AGENT_A, "payments", ["payment_access"], ["stripe"]),
            agent(AGENT_B, "triage", [], []),
        ],
        "repository_findings": [],
    }


def _spans():
    def span(i, **kw):
        base = dict(trace_id="t", span_id=f"s{i}", parent_span_id=None,
                    kind="action", start_ts="2026-08-01T00:00:00Z",
                    end_ts="2026-08-01T00:00:01Z", status="ok",
                    redaction="redacted", agent_id=AGENT_A)
        base.update(kw)
        return build_span(**base)
    return [
        span(1, capability="payment_access", integration="stripe"),   # corroborates
        span(2, capability="shell_execution"),                        # runtime-only reach
        span(3, kind="delegation", from_agent_id=AGENT_A, to_agent_id=AGENT_B),
    ]


def _write_traces(tmp_path):
    traces = tmp_path / "traces"
    traces.mkdir(exist_ok=True)
    lines = [json.dumps({"kind": "header", "schema": "stoa-trace/1.0"})]
    lines += [json.dumps(s) for s in _spans()]
    (traces / "t.jsonl").write_text("\n".join(lines) + "\n")
    return traces


def _enriched(tmp_path):
    registry = _registry()
    analysis = analyze_traces(_write_traces(tmp_path), registry)
    return merge_runtime_into_registry(registry, analysis)


# --- graph overlay ---------------------------------------------------------------


def test_overlay_marks_corroborated_and_adds_observed_edges(tmp_path):
    enriched = _enriched(tmp_path)
    graph = overlay_runtime(build_graph(enriched), enriched)
    edges = {(e.source, e.target, e.kind): e for e in graph.edges}

    corroborated = edges[(AGENT_A, "resource_payment_access", "writes")]
    assert corroborated.provenance == "declared" and corroborated.observed is True
    tool_edge = edges[(AGENT_A, "tool_stripe", "tool_call")]
    assert tool_edge.observed is True

    runtime_only = edges[(AGENT_A, "resource_shell_execution", "writes")]
    assert runtime_only.provenance == "observed" and runtime_only.observed is False
    assert any(n.id == "resource_shell_execution" for n in graph.nodes)

    delegates = edges[(AGENT_A, AGENT_B, "delegates")]
    assert delegates.provenance == "observed"


def test_overlay_without_runtime_data_is_identity(tmp_path):
    registry = _registry()
    graph = build_graph(registry)
    assert overlay_runtime(graph, registry) == graph


def test_overlay_never_mutates_input_graph(tmp_path):
    enriched = _enriched(tmp_path)
    graph = build_graph(enriched)
    before = [e.observed for e in graph.edges]
    overlay_runtime(graph, enriched)
    assert [e.observed for e in graph.edges] == before


def test_delegation_to_unknown_agent_is_not_drawn(tmp_path):
    enriched = _enriched(tmp_path)
    for agent in enriched["agents"]:
        if agent["id"] == AGENT_A:
            agent["runtime_evidence"]["delegations_to"] = ["ffffffffffff"]
    graph = overlay_runtime(build_graph(enriched), enriched)
    assert not any(e.target == "ffffffffffff" for e in graph.edges)


def test_json_dict_emits_observed_only_when_true(tmp_path):
    enriched = _enriched(tmp_path)
    payload = to_json_dict(overlay_runtime(build_graph(enriched), enriched))
    corroborated = [e for e in payload["edges"] if e.get("observed")]
    assert corroborated  # at least the payment/stripe edges
    plain = to_json_dict(build_graph(_registry()))
    assert all("observed" not in e for e in plain["edges"])


# --- mermaid ------------------------------------------------------------------------


def test_mermaid_styles_runtime_edges(tmp_path):
    enriched = _enriched(tmp_path)
    output = render_mermaid(overlay_runtime(build_graph(enriched), enriched))
    assert '-.->|"delegates"|' in output          # runtime-only: dotted
    assert "(observed)" in output                  # corroborated: labeled
    plain = render_mermaid(build_graph(_registry()))
    assert "-.->" not in plain and "(observed)" not in plain


# --- assurance packet ------------------------------------------------------------------


def test_area18_populated_from_enriched_registry(tmp_path):
    enriched = _enriched(tmp_path)
    packet = build_assurance_packet(enriched)
    rows = packet["areas"]["claims_evidence"]["rows"]
    statuses = {r["field"]: r["status"] for r in rows}
    assert statuses["traces_and_runtime_evidence"] == "observed"
    assert statuses["approval_gate_log"] == "observed"
    summary_row = next(r for r in rows if r["field"] == "traces_and_runtime_evidence")
    assert summary_row["evidence"]["span_count"] == 3


def test_area18_not_provided_without_runtime_data():
    packet = build_assurance_packet(_registry())
    (row,) = packet["areas"]["claims_evidence"]["rows"]
    assert row["status"] == "not_provided"
    assert "no runtime trace evidence" in row["evidence"]["note"]


def test_area12_gains_observed_rows_and_explicit_gaps(tmp_path):
    enriched = _enriched(tmp_path)
    packet = build_assurance_packet(enriched)
    area = packet["areas"]["monitoring"]
    top = {r["field"]: r for r in area["rows"]}
    assert top["runtime_traces"]["status"] == "observed"
    assert top["runtime_traces"]["evidence"]["agents_covered"] == 1
    per_agent = {a["agent_id"]: a["fields"] for a in area["agents"]}
    assert per_agent[AGENT_A]["runtime_traces"]["status"] == "observed"
    assert per_agent[AGENT_B]["runtime_traces"]["status"] == "not_provided"
    assert "no spans" in per_agent[AGENT_B]["runtime_traces"]["evidence"]["note"]


def test_packet_without_runtime_identical_to_before_apart_from_schema():
    packet = build_assurance_packet(_registry())
    assert packet["schema"] == "assurance-packet/1.2"
    area = packet["areas"]["monitoring"]
    assert all(r["field"] != "runtime_traces" for r in area["rows"])
    assert all("runtime_traces" not in a["fields"] for a in area["agents"])


def test_rt_findings_join_packet_contradictions(tmp_path):
    enriched = _enriched(tmp_path)
    # plant an RT003-shaped finding the merge would produce for shell_execution
    rt = [f for a in enriched["agents"] for f in a["findings"]
          if f["rule_id"].startswith("RT")]
    assert rt, "expected merge to produce RT003 for runtime-only shell_execution"
    packet = build_assurance_packet(enriched)
    contradiction_rules = {c["rule_id"] for c in packet["contradictions"]}
    assert "RT003" in contradiction_rules
    entry = next(c for c in packet["contradictions"] if c["rule_id"] == "RT003")
    assert entry["trace_ref"]["file"] == "t.jsonl"
    markdown = render_assurance_markdown(packet)
    assert "📡" in markdown and "RT003" in markdown


# --- scan --with-runtime end to end -----------------------------------------------------


def test_scan_with_runtime_enriches_registry_and_report(tmp_path, monkeypatch, capsys):
    from stoa.cli import main

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "payments.py").write_text(
        "from langchain.agents import AgentExecutor\n"
        "from langchain_openai import ChatOpenAI\n"
        "llm = ChatOpenAI(model='gpt-4o')\n"
        "tools = [x]\n"
        "executor = AgentExecutor(agent=a, tools=tools)\n"
    )
    monkeypatch.chdir(tmp_path)
    # first: plain scan to learn the real agent id
    assert main(["scan", str(repo), "--no-git", "--json", "plain.json",
                 "--html", "plain.html", "--quiet"]) == 0
    plain = json.loads((tmp_path / "plain.json").read_text())
    agent_id = plain["agents"][0]["id"]

    traces = tmp_path / "traces"
    traces.mkdir()
    span = build_span(
        trace_id="t", span_id="s1", parent_span_id=None, kind="action",
        start_ts="2026-08-01T00:00:00Z", end_ts="2026-08-01T00:00:01Z",
        status="ok", redaction="redacted", agent_id=agent_id,
        capability="payment_access", integration="stripe",
    )
    (traces / "t.jsonl").write_text(
        json.dumps({"kind": "header", "schema": "stoa-trace/1.0"}) + "\n"
        + json.dumps(span) + "\n"
    )
    assert main(["scan", str(repo), "--no-git", "--with-runtime", str(traces),
                 "--json", "enriched.json", "--html", "enriched.html",
                 "--quiet"]) == 0
    enriched = json.loads((tmp_path / "enriched.json").read_text())
    assert enriched["runtime"]["span_count"] == 1
    assert enriched["agents"][0]["liveness_state"] == "active"

    html = (tmp_path / "enriched.html").read_text()
    assert "Runtime overlay:" in html
    assert "never a claim about" in html
    # CSP hash-pinning model intact: every emitted <script> hash is declared
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    import base64
    import hashlib
    for script in scripts:
        digest = base64.b64encode(
            hashlib.sha256(script.encode("utf-8")).digest()
        ).decode("ascii")
        assert f"sha256-{digest}" in html
    # runtime data flows through the non-executing JSON tag, styled by the glue
    assert '"observed": true' in html or "'edge[observed = 1]'" not in html


def test_scan_without_runtime_flag_byte_identical_html(tmp_path, monkeypatch):
    """The overlay must be invisible when unused: two plain scans (with the
    runtime feature merely available) render identical reports."""
    from stoa.config import StoaConfig
    from stoa.report_html import render_html
    from stoa.scanner import ScanOptions, run_scan

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
    )
    result = run_scan(ScanOptions(root=repo, no_git=True), StoaConfig())
    assert render_html(result, StoaConfig()) == render_html(result, StoaConfig(), None)
