"""RT006 to RT008 and reconcile, over the 1.1 analysis fields."""

from __future__ import annotations

import copy
import json

from stoa.cli import main
from stoa.runtime.analysis import analyze_traces
from stoa.runtime.drift import build_baseline
from stoa.runtime.merge import merge_runtime_into_registry
from stoa.runtime.reconcile import reconcile, render_reconcile
from stoa.runtime.rt_rules import detect_runtime_contradictions
from stoa.runtime.spans import build_span

AGENT = "aaaaaaaaaaaa"


def _span(**overrides):
    base = dict(trace_id="t1", span_id="s1", parent_span_id=None, kind="action", agent_id=AGENT,
                start_ts="2026-08-01T10:00:00.000Z", end_ts="2026-08-01T10:00:01.000Z", status="ok", redaction="redacted")
    base.update(overrides)
    return build_span(**base)


def _write(tmp_path, spans):
    traces = tmp_path / "traces"
    traces.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"kind": "header", "schema": "stoa-trace/1.1", "sdk_version": "0", "redaction": "redacted"})]
    lines += [json.dumps(s) for s in spans]
    (traces / "trace-1-0000.jsonl").write_text("\n".join(lines) + "\n")
    return traces


def _registry():
    return {
        "schema_version": "1.8", "tool": {"name": "stoa", "version": "0"}, "repository": {"name": "fx"}, "summary": {},
        "agents": [{
            "id": AGENT, "name": "graph", "symbol": "graph", "path": "a.py", "language": "python",
            "capabilities": ["payment_access"], "integrations": ["stripe"], "providers": ["openai"],
            "declared": {"name": "account-actions", "autonomy_intent": "human_approved"},
            "tools": [{"name": "issue_refund", "money_action": True}, {"name": "waive_fee", "money_action": True}],
            "findings": [], "evidence": [{"rule_id": "AGENT_LANGCHAIN", "line": 3, "description": "x"}],
        }],
        "repository_findings": [],
    }


def _rules(findings):
    return sorted(f["rule_id"] for f in findings.get(AGENT, []))


def test_rt006_fires_per_tool_outside_the_scanned_inventory(tmp_path):
    traces = _write(tmp_path, [
        _span(span_id="s1", tool="issue_refund", amount=10.0, approval_span_id="ap"),
        _span(span_id="ap", kind="approval"),
        _span(span_id="s2", tool="lookup_balance"),
        _span(span_id="s3", tool="lookup_balance"),
    ])
    analysis = analyze_traces(traces, _registry())
    summary = analysis["agents"][AGENT]
    assert summary["observed_tools"] == ["issue_refund", "lookup_balance"] and summary["tool_counts"]["lookup_balance"] == 2
    findings = detect_runtime_contradictions(_registry(), analysis)
    rt006 = [f for f in findings[AGENT] if f["rule_id"] == "RT006"]
    assert len(rt006) == 1 and "lookup_balance" in rt006[0]["snippet"] and rt006[0]["trace_ref"]["span_id"] == "s2"
    assert "RT007" not in _rules(findings)


def test_rt007_fires_when_the_approval_does_not_resolve(tmp_path):
    traces = _write(tmp_path, [
        _span(span_id="s1", tool="issue_refund", amount=10.0, approval_span_id="dangling"),
        _span(span_id="s2", tool="waive_fee", attrs={"side_effect": "payment"}),
        _span(span_id="ap", kind="approval"),
        _span(span_id="s3", tool="issue_refund", amount=5.0, approval_span_id="ap"),
    ])
    analysis = analyze_traces(traces, _registry())
    summary = analysis["agents"][AGENT]
    assert summary["money_actions"] == 3 and summary["money_actions_approved"] == 1
    findings = detect_runtime_contradictions(_registry(), analysis)
    rt007 = [f for f in findings[AGENT] if f["rule_id"] == "RT007"]
    assert len(rt007) == 1 and rt007[0]["severity"] == "high" and rt007[0]["trace_ref"]["span_id"] == "s1"
    assert rt007[0]["declared_ref"]["key"].endswith("autonomy_intent")


def test_rt008_knows_scan_and_baseline(tmp_path):
    spans = [
        _span(span_id="s1", tool="issue_refund", integration="shopify", amount=1.0, approval_span_id="ap"),
        _span(span_id="ap", kind="approval"),
        _span(span_id="s2", kind="llm_call", provider="openai", model="gpt-4o"),
    ]
    traces = _write(tmp_path, spans)
    analysis = analyze_traces(traces, _registry())
    # no baseline: the unknown integration fires, models are not judged
    findings = detect_runtime_contradictions(_registry(), analysis)
    rt008 = [f for f in findings[AGENT] if f["rule_id"] == "RT008"]
    assert len(rt008) == 1 and "shopify" in rt008[0]["snippet"]
    # a baseline that knows shopify and gpt-4o silences it; a new model then fires
    baseline = build_baseline(analysis)
    assert baseline["agents"][AGENT]["observed_models"] == ["gpt-4o"]
    assert "RT008" not in _rules(detect_runtime_contradictions(_registry(), analysis, baseline=baseline))
    traces2 = _write(tmp_path / "later", spans + [_span(span_id="s9", kind="llm_call", provider="openai", model="gpt-5")])
    later = analyze_traces(traces2, _registry())
    rt008 = [f for f in detect_runtime_contradictions(_registry(), later, baseline=baseline).get(AGENT, []) if f["rule_id"] == "RT008"]
    assert len(rt008) == 1 and "gpt-5" in rt008[0]["snippet"]


def test_reconcile_three_columns_and_dormancy(tmp_path):
    traces = _write(tmp_path, [
        _span(span_id="s1", tool="issue_refund", amount=1.0, approval_span_id="ap", end_ts="2026-08-30T10:00:01.000Z"),
        _span(span_id="ap", kind="approval"),
        _span(span_id="s2", tool="lookup_balance", end_ts="2026-09-10T10:00:01.000Z"),
    ])
    analysis = analyze_traces(traces, _registry())
    doc = reconcile(_registry(), analysis, dormant_days=30)
    row = doc["agents"][0]
    assert [t["tool"] for t in row["declared_and_used"]] == ["issue_refund"]
    assert [t["tool"] for t in row["used_but_undeclared"]] == ["lookup_balance"]
    assert [t["tool"] for t in row["declared_but_dormant"]] == ["waive_fee"]
    # a tighter window makes issue_refund dormant too (last seen 11 days before the window end)
    assert [t["tool"] for t in reconcile(_registry(), analysis, dormant_days=5)["agents"][0]["declared_but_dormant"]] == ["issue_refund", "waive_fee"]
    text = render_reconcile(doc)
    assert "used but undeclared" in text and "lookup_balance" in text and "—" not in text


def test_merge_carries_11_fields_and_is_additive(tmp_path):
    traces = _write(tmp_path, [_span(span_id="s1", tool="issue_refund", amount=1.0, approval_span_id="ap"), _span(span_id="ap", kind="approval")])
    registry = _registry()
    before = copy.deepcopy(registry)
    enriched = merge_runtime_into_registry(registry, analyze_traces(traces, registry))
    assert registry == before
    evidence = enriched["agents"][0]["runtime_evidence"]
    assert evidence["observed_tools"] == ["issue_refund"] and evidence["money_actions_approved"] == 1 and evidence["flag_counts"] == {}


def test_cli_verify_and_reconcile(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    traces = _write(tmp_path, [_span(span_id="s1", tool="lookup_balance")])
    (tmp_path / "reg.json").write_text(json.dumps(_registry()))
    assert main(["runtime", "reconcile", str(traces), "--registry", "reg.json", "--out", "rec.json"]) == 0
    out = capsys.readouterr().out
    assert "lookup_balance" in out and json.loads((tmp_path / "rec.json").read_text())["schema"] == "runtime-reconcile/1.0"
    # hand-written 1.1 file without chain fields: verify reports the break, exit 1
    assert main(["runtime", "verify", str(traces)]) == 1
    assert "BROKEN" in capsys.readouterr().out


# --- dimension extension (trace 1.1) -------------------------------------------------


def _assessed_registry():
    registry = _registry()
    dims = [
        {"id": d, "group": "x", "score": 10, "exposure": "low", "assessability": tier, "controls_observed": [], "contributing_findings": [], "contributing_capabilities": [], "statement": ""}
        for d, tier in (
            ("boundary-leakage", "strong"), ("mandate-overreach", "strong"), ("injection-tamper-surface", "partial"),
            ("control-coverage-gap", "strong"), ("unreviewed-high-impact-action", "strong"), ("output-fidelity", "proxy"),
            ("conduct-variability", "proxy"), ("dependency-drift", "proxy"),
        )
    ]
    registry["agents"][0]["dimension_assessment"] = {"schema": "stoa-dimensions/1.0", "dimensions": dims}
    registry["dimension_summary"] = {"dimensions": [{"id": d["id"], "max_exposure": "low", "agents_elevated": 0, "agents_moderate": 0, "assessability": d["assessability"]} for d in dims]}
    return registry


def _entry(enriched, dim):
    return next(e for e in enriched["agents"][0]["dimension_assessment"]["dimensions"] if e["id"] == dim)


def test_runtime_tier_reaches_the_new_dimensions_only_with_evidence(tmp_path):
    registry = _assessed_registry()
    traces = _write(tmp_path, [
        _span(span_id="s1", tool="lookup_balance", attrs={"flags": ["undeclared_tool"]}),
        _span(span_id="s2", tool="issue_refund", amount=900.0, attrs={"side_effect": "payment"}),
        _span(span_id="s3", kind="llm_call", provider="openai", model="gpt-4o", status="error"),
        _span(span_id="s4", kind="llm_call", provider="openai", model="gpt-4o"),
    ])
    enriched = merge_runtime_into_registry(registry, analyze_traces(traces, registry))
    mandate = _entry(enriched, "mandate-overreach")
    assert mandate["assessability"] == "runtime" and mandate["exposure"] == "elevated" and mandate["static_exposure"] == "low"
    assert mandate["runtime_basis"]["undeclared_tool"] == 1
    unreviewed = _entry(enriched, "unreviewed-high-impact-action")
    assert unreviewed["assessability"] == "runtime" and unreviewed["exposure"] == "elevated"
    coverage = _entry(enriched, "control-coverage-gap")
    assert coverage["assessability"] == "runtime" and coverage["exposure"] == "elevated"  # declared gate, 0% approved
    fidelity = _entry(enriched, "output-fidelity")
    assert fidelity["assessability"] == "runtime" and fidelity["exposure"] == "elevated" and fidelity["runtime_basis"]["llm_error_rate"] == 0.5
    # no external_send, no integration outside the scan: boundary-leakage reads low from actions alone
    assert _entry(enriched, "boundary-leakage")["assessability"] == "runtime" and _entry(enriched, "boundary-leakage")["exposure"] == "low"
    # never upgraded: redacted traces cannot show what reached the prompt
    assert _entry(enriched, "injection-tamper-surface")["assessability"] == "partial"
    for entry in enriched["agents"][0]["dimension_assessment"]["dimensions"]:
        if entry["assessability"] == "runtime":
            assert entry["evidence_window"]["start"] and entry["evidence_window"]["end"] and entry["evidence_window"]["span_count"] > 0
    row = next(r for r in enriched["dimension_summary"]["dimensions"] if r["id"] == "mandate-overreach")
    assert row["assessability"] == "runtime" and row["max_exposure"] == "elevated"


def test_dimensions_without_evidence_in_the_window_keep_the_scan_assessment(tmp_path):
    registry = _assessed_registry()
    traces = _write(tmp_path, [_span(span_id="s1", kind="llm_call", provider="openai", model="gpt-4o")])
    enriched = merge_runtime_into_registry(registry, analyze_traces(traces, registry))
    for dim in ("mandate-overreach", "unreviewed-high-impact-action", "control-coverage-gap", "boundary-leakage"):
        entry = _entry(enriched, dim)
        assert entry["assessability"] == "strong" and "runtime_basis" not in entry
    assert _entry(enriched, "output-fidelity")["assessability"] == "runtime"
