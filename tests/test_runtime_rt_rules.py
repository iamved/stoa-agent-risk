"""Runtime overlay Phase 4: the RT contradiction rules (RT001–RT005).

Positive + negative fixture per rule, both-sides evidence (trace_ref +
declared_ref), config-based suppression for trace-anchored findings,
severity overrides, and the diff exclusion exercised with real RT findings.
"""

from __future__ import annotations

import json

from stoa.config import StoaConfig, load_config
from stoa.registry_diff import diff_registries
from stoa.runtime.merge import merge_runtime_into_registry
from stoa.runtime.rt_rules import detect_runtime_contradictions

AGENT = "aaaaaaaaaaaa"


def _registry(declared=None, capabilities=("payment_access",), autonomy=None,
              evidence=None) -> dict:
    agent = {
        "id": AGENT, "name": "payments", "symbol": "payments",
        "path": "agents/payments.py", "language": "python",
        "capabilities": sorted(capabilities),
        "integrations": ["stripe"],
        "evidence": [{"rule_id": "AGENT_LANGCHAIN", "line": 7, "description": "x"}],
        "findings": [],
    }
    if declared is not None:
        agent["declared"] = declared
    if autonomy is not None:
        agent["autonomy_level"] = {"level": autonomy, "signals": [], "reason": None}
    registry = {
        "schema_version": "1.4", "tool": {"name": "stoa", "version": "0"},
        "repository": {"name": "fixture"}, "summary": {},
        "agents": [agent], "repository_findings": [],
    }
    if evidence is not None:
        registry["evidence"] = evidence
    return registry


def _analysis(summary=None, no_evidence=(), window_spans=10) -> dict:
    agents = {AGENT: summary} if summary is not None else {}
    return {
        "schema": "runtime-analysis/1.0",
        "header": {},
        "window": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-02T00:00:00Z",
                   "span_count": window_spans},
        "agents": agents,
        "unmatched_agents": [],
        "no_runtime_evidence": sorted(no_evidence),
    }


def _summary(**overrides) -> dict:
    base = {
        "span_count": 10,
        "spans_by_kind": {"action": 10},
        "error_rate": 0.0,
        "observed_capabilities": ["payment_access"],
        "observed_integrations": ["stripe"],
        "observed_providers": [], "observed_models": [],
        "capability_counts": {"payment_access": 10},
        "integration_counts": {"stripe": 10},
        "high_impact_actions": 10,
        "high_impact_approved": 10,
        "approval_rate_high_impact": 1.0,
        "approval_spans": 10,
        "max_observed_amount": None,
        "window_total_amounts": {},
        "evidence_quality": "redacted",
        "first_ts": "2026-08-01T00:00:00Z", "last_ts": "2026-08-02T00:00:00Z",
        "delegations_to": [], "trace_files": ["t.jsonl"],
        "trace_refs": {
            "first_capability_span": {"payment_access": {"file": "t.jsonl", "line": 2, "span_id": "s1"}},
            "first_unapproved_high_impact": None,
            "max_amount_span": None,
        },
    }
    base.update(overrides)
    return base


def _rules_fired(registry, analysis, config=None):
    found = detect_runtime_contradictions(registry, analysis, config)
    return [f["rule_id"] for f in found.get(AGENT, [])]


# --- RT001 -------------------------------------------------------------------


def test_rt001_fires_on_declared_oversight_with_unapproved_actions():
    registry = _registry(declared={"autonomy_intent": "human_approved"})
    summary = _summary(
        high_impact_approved=7,
        trace_refs={
            "first_capability_span": {},
            "first_unapproved_high_impact": {"file": "t.jsonl", "line": 9, "span_id": "s9"},
            "max_amount_span": None,
        },
    )
    found = detect_runtime_contradictions(registry, _analysis(summary))
    (finding,) = [f for f in found[AGENT] if f["rule_id"] == "RT001"]
    assert finding["severity"] == "critical"
    assert finding["trace_ref"] == {"file": "t.jsonl", "line": 9, "span_id": "s9"}
    assert finding["declared_ref"]["key"] == f'agents."{AGENT}".autonomy_intent'
    assert finding["path"] == "agents/payments.py" and finding["line"] == 7
    assert "3 of 10" in finding["message"]


def test_rt001_quiet_when_every_action_approved_or_no_declaration():
    approved = _summary()  # 10/10 approved
    registry = _registry(declared={"autonomy_intent": "human_approved"})
    assert "RT001" not in _rules_fired(registry, _analysis(approved))
    # unapproved actions but agent declared autonomous: intent is honest
    unapproved = _summary(high_impact_approved=0)
    autonomous = _registry(declared={"autonomy_intent": "bounded_autonomous"})
    assert "RT001" not in _rules_fired(autonomous, _analysis(unapproved))


# --- RT002 -------------------------------------------------------------------


def test_rt002_fires_on_amount_over_declared_max_per_action():
    registry = _registry(declared={"economic_authority": {
        "max_per_action": {"amount": 2000, "currency": "USD"},
    }})
    summary = _summary(
        max_observed_amount={"amount": 5000.0, "currency": "USD"},
        trace_refs={"first_capability_span": {}, "first_unapproved_high_impact": None,
                    "max_amount_span": {"file": "t.jsonl", "line": 4, "span_id": "s4"}},
    )
    found = detect_runtime_contradictions(registry, _analysis(summary))
    (finding,) = [f for f in found[AGENT] if f["rule_id"] == "RT002"]
    assert finding["trace_ref"]["span_id"] == "s4"
    assert "max_per_action" in finding["declared_ref"]["key"]


def test_rt002_fires_on_window_total_over_daily_aggregate():
    registry = _registry(declared={"economic_authority": {
        "daily_aggregate": {"amount": 20000, "currency": "USD"},
    }})
    summary = _summary(window_total_amounts={"USD": 30000.0})
    found = detect_runtime_contradictions(registry, _analysis(summary))
    (finding,) = [f for f in found[AGENT] if f["rule_id"] == "RT002"]
    assert "daily_aggregate" in finding["declared_ref"]["key"]
    assert "overstates" in finding["message"]  # honest about window vs day


def test_rt002_quiet_within_limits_or_currency_mismatch():
    registry = _registry(declared={"economic_authority": {
        "max_per_action": {"amount": 2000, "currency": "USD"},
    }})
    within = _summary(max_observed_amount={"amount": 1500.0, "currency": "USD"})
    assert "RT002" not in _rules_fired(registry, _analysis(within))
    other_currency = _summary(max_observed_amount={"amount": 5000.0, "currency": "EUR"})
    assert "RT002" not in _rules_fired(registry, _analysis(other_currency))


# --- RT003 -------------------------------------------------------------------


def test_rt003_fires_on_observed_capability_beyond_static_reach():
    registry = _registry(capabilities=("payment_access",))
    summary = _summary(
        observed_capabilities=["payment_access", "shell_execution"],
        trace_refs={
            "first_capability_span": {
                "shell_execution": {"file": "t.jsonl", "line": 6, "span_id": "s6"}},
            "first_unapproved_high_impact": None, "max_amount_span": None,
        },
    )
    found = detect_runtime_contradictions(registry, _analysis(summary))
    (finding,) = [f for f in found[AGENT] if f["rule_id"] == "RT003"]
    assert finding["confidence"] == "medium"  # static absence could be a blind spot
    assert finding["trace_ref"]["span_id"] == "s6"


def test_rt003_quiet_for_known_capabilities_and_custom_vocabulary():
    registry = _registry(capabilities=("payment_access",))
    known = _summary(observed_capabilities=["payment_access"])
    assert "RT003" not in _rules_fired(registry, _analysis(known))
    custom = _summary(observed_capabilities=["payment_access", "my_custom_tool"])
    assert "RT003" not in _rules_fired(registry, _analysis(custom))


# --- RT004 -------------------------------------------------------------------


def test_rt004_fires_when_monitoring_claimed_but_no_traces():
    registry = _registry(
        declared={"production_status": "production"},
        evidence={"monitoring": [{"kind": "dashboard", "ref": "https://grafana"}]},
    )
    found = detect_runtime_contradictions(registry, _analysis(None, no_evidence=[AGENT]))
    (finding,) = found[AGENT]
    assert finding["rule_id"] == "RT004"
    assert finding["declared_ref"]["key"] == f'agents."{AGENT}".production_status'
    assert "claimed but not evidenced" in finding["message"]


def test_rt004_quiet_without_monitoring_claim_or_with_traces():
    no_monitoring = _registry(declared={"production_status": "production"})
    assert _rules_fired(no_monitoring, _analysis(None, no_evidence=[AGENT])) == []
    with_traces = _registry(
        declared={"production_status": "production"},
        evidence={"monitoring": [{"kind": "dashboard", "ref": "x"}]},
    )
    assert "RT004" not in _rules_fired(with_traces, _analysis(_summary()))


# --- RT005 -------------------------------------------------------------------


def test_rt005_reports_observed_good_news():
    registry = _registry(autonomy="human_approved")
    found = detect_runtime_contradictions(registry, _analysis(_summary()))
    (finding,) = [f for f in found[AGENT] if f["rule_id"] == "RT005"]
    assert finding["severity"] == "info"
    assert "100%" in finding["message"]
    assert "observed" in finding["message"]
    assert "proof" in finding["message"]  # never claims future behavior


def test_rt005_quiet_below_100_percent_or_no_high_impact():
    registry = _registry(autonomy="human_approved")
    partial = _summary(high_impact_approved=9, approval_rate_high_impact=0.9)
    assert "RT005" not in _rules_fired(registry, _analysis(partial))
    idle = _summary(high_impact_actions=0, high_impact_approved=0,
                    approval_rate_high_impact=None)
    assert "RT005" not in _rules_fired(registry, _analysis(idle))


# --- suppression, severity, config -----------------------------------------------


def test_config_suppression_marks_but_never_drops():
    registry = _registry(declared={"autonomy_intent": "recommend_only"})
    summary = _summary(high_impact_approved=0)
    config = StoaConfig(runtime_suppress=[f"RT001:{AGENT}"])
    found = detect_runtime_contradictions(registry, _analysis(summary), config)
    (finding,) = [f for f in found[AGENT] if f["rule_id"] == "RT001"]
    assert finding["suppressed"] is True
    assert "stoa.toml" in finding["suppression_reason"]


def test_wildcard_suppression_and_severity_override():
    registry = _registry(declared={"autonomy_intent": "recommend_only"})
    summary = _summary(high_impact_approved=0)
    config = StoaConfig(runtime_suppress=["RT001:*"],
                        severity_overrides={"RT001": "medium"})
    found = detect_runtime_contradictions(registry, _analysis(summary), config)
    (finding,) = [f for f in found[AGENT] if f["rule_id"] == "RT001"]
    assert finding["suppressed"] is True and finding["severity"] == "medium"


def test_rt_rule_ids_valid_in_stoa_toml(tmp_path):
    """RT ids pass the same config validation as every other rule."""
    (tmp_path / "stoa.toml").write_text(
        "[severity]\nRT003 = \"medium\"\n[rules]\nRT005 = false\n"
    )
    config = load_config(tmp_path)
    assert config.severity_overrides["RT003"] == "medium"
    assert config.rule_enabled("RT005") is False
    registry = _registry(autonomy="human_approved")
    assert "RT005" not in _rules_fired(registry, _analysis(_summary()), config)


# --- merge + diff integration --------------------------------------------------------


def test_merge_attaches_rt_findings_sorted_and_counts_them():
    registry = _registry(declared={"autonomy_intent": "human_approved"})
    registry["agents"][0]["findings"] = [{
        "fingerprint": "zzz", "rule_id": "SEC001", "severity": "critical",
        "confidence": "high", "path": "agents/payments.py", "line": 3,
        "title": "x", "category": "secret", "column": 1, "snippet": "x",
        "remediation": "x", "suppressed": False, "suppression_reason": None,
        "is_new": False,
    }]
    summary = _summary(high_impact_approved=0)
    enriched = merge_runtime_into_registry(registry, _analysis(summary))
    findings = enriched["agents"][0]["findings"]
    assert [f["rule_id"] for f in findings] == ["SEC001", "RT001"]  # line order
    assert enriched["runtime"]["rt_findings"] == 1
    # scan summary untouched: RT findings never rewrite static counts
    assert enriched["summary"] == registry["summary"]


def test_diff_ignores_rt_findings_between_plain_and_enriched():
    registry = _registry(declared={"autonomy_intent": "human_approved"})
    # Give the agent real proxy dimension entries so the runtime-tier
    # upgrade is exercised too — the leak the Meridian e2e caught: a
    # runtime-assessed exposure change must not surface as dimension_delta.
    registry["agents"][0]["dimension_assessment"] = {
        "taxonomy": {"id": "stoa-aiuc-8", "version": "2.0"},
        "dimensions": [
            {"id": "conduct-variability", "group": "D", "assessability": "proxy",
             "exposure": "low", "score": 5, "contributing_findings": [],
             "contributing_capabilities": [], "controls_observed": [],
             "statement": "x"},
        ],
    }
    summary = _summary(high_impact_approved=0)
    enriched = merge_runtime_into_registry(registry, _analysis(summary))
    assert any(f["rule_id"] == "RT001" for f in enriched["agents"][0]["findings"])
    upgraded = enriched["agents"][0]["dimension_assessment"]["dimensions"][0]
    assert upgraded["assessability"] == "runtime"  # the upgrade really happened
    diff = diff_registries(registry, enriched)
    assert diff["summary"]["agents_changed"] == 0
    assert diff["summary"]["findings_delta"] == {
        "new_critical": 0, "new_high": 0, "resolved": 0}


def test_scan_never_emits_rt_findings(tmp_path):
    """RT rules are merge-only: a plain scan of agentic code with every RT
    precondition available must not produce any RT finding."""
    (tmp_path / "agent.py").write_text(
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def refund(x):\n"
        "    stripe.Refund.create(amount=x)\n"
    )
    from stoa.config import StoaConfig as Config
    from stoa.scanner import ScanOptions, run_scan

    result = run_scan(ScanOptions(root=tmp_path, no_git=True), Config())
    all_rules = {f.rule_id for a in result.agents for f in a.findings}
    assert not any(r.startswith("RT") for r in all_rules)


def test_cli_merge_reports_rt_findings(tmp_path, monkeypatch, capsys):
    from stoa.cli import main
    from stoa.runtime.spans import build_span

    monkeypatch.chdir(tmp_path)
    traces = tmp_path / "traces"
    traces.mkdir()
    span = build_span(
        trace_id="t", span_id="s1", parent_span_id=None, kind="action",
        start_ts="2026-08-01T00:00:00Z", end_ts="2026-08-01T00:00:01Z",
        status="ok", redaction="redacted", agent_id=AGENT,
        capability="payment_access",
    )
    (traces / "t.jsonl").write_text(
        json.dumps({"kind": "header", "schema": "stoa-trace/1.0"}) + "\n"
        + json.dumps(span) + "\n"
    )
    (tmp_path / "reg.json").write_text(json.dumps(
        _registry(declared={"autonomy_intent": "human_approved"})
    ))
    code = main(["runtime", "merge", str(traces), "--registry", "reg.json",
                 "--out", "enriched.json"])
    assert code == 0
    assert "1 RT finding(s)" in capsys.readouterr().out
    enriched = json.loads((tmp_path / "enriched.json").read_text())
    rt = [f for f in enriched["agents"][0]["findings"] if f["rule_id"] == "RT001"]
    assert rt and rt[0]["trace_ref"]["file"] == "t.jsonl"
