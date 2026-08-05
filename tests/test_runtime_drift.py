"""Runtime overlay Phase 3: behavioral baseline + drift detection.

Golden-fixture coverage for every drift class (high / medium / info), the
documented frequency-ratio statistic and its thresholds, declared
economic-authority checks, baseline version mismatch (exit 2), and shadow-
mode gating semantics (report-only unless --fail-on-drift).
"""

from __future__ import annotations

import json

import pytest

from stoa.cli import main
from stoa.config import ConfigError, StoaConfig, load_config
from stoa.runtime.drift import (
    BaselineVersionMismatch,
    build_baseline,
    compute_drift,
)


def _analysis(agents: dict) -> dict:
    return {
        "schema": "runtime-analysis/1.0",
        "header": {"stoa_version": "0.0"},
        "window": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-02T00:00:00Z",
                   "span_count": sum(a.get("span_count", 0) for a in agents.values())},
        "agents": agents,
        "unmatched_agents": [],
        "no_runtime_evidence": [],
    }


def _agent_summary(**overrides) -> dict:
    base = {
        "span_count": 100,
        "spans_by_kind": {"tool_call": 100},
        "capability_counts": {},
        "integration_counts": {},
        "observed_capabilities": [],
        "observed_integrations": [],
        "approval_rate_high_impact": None,
        "max_observed_amount": None,
        "window_total_amounts": {},
    }
    base.update(overrides)
    return base


AGENT = "aaaaaaaaaaaa"


def _events(drift, kind=None):
    events = drift["events"]
    return [e for e in events if kind is None or e["kind"] == kind]


# --- high ---------------------------------------------------------------------


def test_new_high_impact_capability_absent_everywhere_is_high():
    baseline = build_baseline(_analysis({AGENT: _agent_summary()}))
    now = _analysis({AGENT: _agent_summary(
        observed_capabilities=["shell_execution"],
        capability_counts={"shell_execution": 5},
    )})
    registry = {"agents": [{"id": AGENT, "capabilities": ["database_read"]}]}
    drift = compute_drift(now, baseline, registry)
    (event,) = _events(drift, "new_high_impact_capability")
    assert event["class"] == "high"
    assert event["capability"] == "shell_execution"
    assert "static registry" in event["absent_from"]
    assert drift["summary"]["max_drift_class"] == "high"


def test_high_impact_capability_known_to_static_registry_is_medium():
    """Observed for the first time at runtime, but the scanner already knew
    the code could do this — new evidence, not new reach: medium."""
    baseline = build_baseline(_analysis({AGENT: _agent_summary()}))
    now = _analysis({AGENT: _agent_summary(
        observed_capabilities=["shell_execution"],
    )})
    registry = {"agents": [{"id": AGENT, "capabilities": ["shell_execution"]}]}
    drift = compute_drift(now, baseline, registry)
    assert _events(drift, "new_high_impact_capability") == []
    (event,) = _events(drift, "new_capability")
    assert event["class"] == "medium" and event["high_impact"] is True


def test_approval_rate_drop_is_high():
    baseline = build_baseline(_analysis({AGENT: _agent_summary(
        approval_rate_high_impact=1.0,
    )}))
    now = _analysis({AGENT: _agent_summary(approval_rate_high_impact=0.85)})
    drift = compute_drift(now, baseline, None)
    (event,) = _events(drift, "approval_rate_drop")
    assert event["class"] == "high"
    assert event["rate_baseline"] == 1.0 and event["rate_now"] == 0.85


def test_approval_drop_below_threshold_is_quiet():
    baseline = build_baseline(_analysis({AGENT: _agent_summary(
        approval_rate_high_impact=1.0,
    )}))
    now = _analysis({AGENT: _agent_summary(approval_rate_high_impact=0.95)})
    drift = compute_drift(now, baseline, None)  # default approval_drop=0.10
    assert _events(drift, "approval_rate_drop") == []


def test_amount_exceeding_declared_max_per_action_is_high():
    baseline = build_baseline(_analysis({AGENT: _agent_summary()}))
    now = _analysis({AGENT: _agent_summary(
        max_observed_amount={"amount": 5000.0, "currency": "USD"},
        window_total_amounts={"USD": 5000.0},
    )})
    registry = {"agents": [{"id": AGENT, "capabilities": [], "declared": {
        "economic_authority": {
            "max_per_action": {"amount": 2000, "currency": "USD"},
            "daily_aggregate": {"amount": 20000, "currency": "USD"},
        }}}]}
    drift = compute_drift(now, baseline, registry)
    (event,) = _events(drift, "amount_exceeds_declared_max_per_action")
    assert event["class"] == "high"
    assert event["observed"]["amount"] == 5000.0
    assert event["declared"]["amount"] == 2000


def test_window_total_exceeding_daily_aggregate_notes_the_approximation():
    baseline = build_baseline(_analysis({AGENT: _agent_summary()}))
    now = _analysis({AGENT: _agent_summary(
        window_total_amounts={"USD": 30000.0},
    )})
    registry = {"agents": [{"id": AGENT, "capabilities": [], "declared": {
        "economic_authority": {"daily_aggregate": {"amount": 20000, "currency": "USD"}},
    }}]}
    drift = compute_drift(now, baseline, registry)
    (event,) = _events(drift, "window_total_exceeds_declared_daily_aggregate")
    assert event["class"] == "high"
    assert "overstates" in event["note"]  # honest about window vs day


# --- medium: frequency-ratio statistic -----------------------------------------


def test_frequency_shift_flags_ratio_above_threshold():
    baseline = build_baseline(_analysis({AGENT: _agent_summary(
        span_count=1000, spans_by_kind={"tool_call": 1000},
        capability_counts={"database_read": 10},
        observed_capabilities=["database_read"],
    )}))
    now = _analysis({AGENT: _agent_summary(
        span_count=1000, spans_by_kind={"tool_call": 1000},
        capability_counts={"database_read": 100},  # 1% → 10%: ratio 10
        observed_capabilities=["database_read"],
    )})
    drift = compute_drift(now, baseline, None)
    (event,) = _events(drift, "frequency_shift")
    assert event["class"] == "medium"
    assert event["category"] == "database_read"
    assert event["ratio"] == 10.0
    assert event["rate_now"] == 0.1 and event["rate_baseline"] == 0.01


def test_frequency_shift_respects_min_count():
    """Small samples never alarm: same 10× ratio, but only 5 observations."""
    baseline = build_baseline(_analysis({AGENT: _agent_summary(
        span_count=1000, capability_counts={"database_read": 1},
        observed_capabilities=["database_read"], spans_by_kind={},
    )}))
    now = _analysis({AGENT: _agent_summary(
        span_count=500, capability_counts={"database_read": 5},
        observed_capabilities=["database_read"], spans_by_kind={},
    )})
    drift = compute_drift(now, baseline, None)  # default min_count=20
    assert _events(drift, "frequency_shift") == []


def test_frequency_shift_thresholds_configurable():
    baseline = build_baseline(_analysis({AGENT: _agent_summary(
        span_count=100, capability_counts={"database_read": 20},
        observed_capabilities=["database_read"], spans_by_kind={},
    )}))
    now = _analysis({AGENT: _agent_summary(
        span_count=100, capability_counts={"database_read": 44},  # ratio 2.2
        observed_capabilities=["database_read"], spans_by_kind={},
    )})
    quiet = compute_drift(now, baseline, None)  # default 3.0: no event
    assert _events(quiet, "frequency_shift") == []
    loud = compute_drift(now, baseline, None, ratio_threshold=2.0, min_count=10)
    assert len(_events(loud, "frequency_shift")) == 1


# --- info -------------------------------------------------------------------------


def test_capability_no_longer_observed_is_info():
    baseline = build_baseline(_analysis({AGENT: _agent_summary(
        observed_capabilities=["email_send"],
        capability_counts={"email_send": 3},
    )}))
    now = _analysis({AGENT: _agent_summary()})
    drift = compute_drift(now, baseline, None)
    (event,) = _events(drift, "capability_no_longer_observed")
    assert event["class"] == "info" and event["capability"] == "email_send"


def test_no_drift_at_all_reports_none():
    summary = _agent_summary(observed_capabilities=["database_read"],
                             capability_counts={"database_read": 50})
    baseline = build_baseline(_analysis({AGENT: summary}))
    drift = compute_drift(_analysis({AGENT: summary}), baseline, None)
    assert drift["events"] == []
    assert drift["summary"]["max_drift_class"] == "none"


# --- versioning & config -------------------------------------------------------------


def test_unsupported_baseline_schema_raises_version_mismatch():
    with pytest.raises(BaselineVersionMismatch):
        compute_drift(_analysis({}), {"schema": "runtime-baseline/2.0"}, None)


def test_runtime_config_section_parses_and_validates(tmp_path):
    (tmp_path / "stoa.toml").write_text(
        "[runtime]\n"
        'trace_dir = "traces"\n'
        'suppress = ["RT002:aaaaaaaaaaaa"]\n'
        "[runtime.drift]\n"
        "ratio_threshold = 5.0\n"
        "min_count = 50\n"
        "approval_drop = 0.2\n"
        "[runtime.dimensions]\n"
        "error_rate_elevated = 0.5\n"
    )
    config = load_config(tmp_path)
    assert config.runtime_trace_dir == "traces"
    assert config.runtime_suppress == ["RT002:aaaaaaaaaaaa"]
    assert config.runtime_drift_ratio_threshold == 5.0
    assert config.runtime_drift_min_count == 50
    assert config.runtime_drift_approval_drop == 0.2
    assert config.runtime_error_rate_elevated == 0.5


def test_runtime_config_rejects_otlp_and_bad_values(tmp_path):
    (tmp_path / "stoa.toml").write_text('[runtime]\nexporter = "otlp"\n')
    with pytest.raises(ConfigError, match="reserved for a future release"):
        load_config(tmp_path)
    (tmp_path / "stoa.toml").write_text("[runtime.drift]\nmin_count = -1\n")
    with pytest.raises(ConfigError, match="positive number"):
        load_config(tmp_path)


def test_absent_runtime_section_leaves_defaults():
    config = StoaConfig()
    assert config.runtime_trace_dir is None
    assert config.runtime_drift_ratio_threshold == 3.0


# --- CLI ---------------------------------------------------------------------------------


def _write_trace_file(tmp_path, spans):
    from stoa.runtime.spans import build_span

    traces = tmp_path / "traces"
    traces.mkdir(exist_ok=True)
    lines = [json.dumps({"kind": "header", "schema": "stoa-trace/1.0"})]
    for i, kw in enumerate(spans):
        base = dict(trace_id="t", span_id=f"s{i}", parent_span_id=None,
                    kind="action", start_ts="2026-08-01T00:00:00Z",
                    end_ts="2026-08-01T00:00:01Z", status="ok",
                    redaction="redacted", agent_id=AGENT)
        base.update(kw)
        lines.append(json.dumps(build_span(**base)))
    (traces / "t.jsonl").write_text("\n".join(lines) + "\n")
    return traces


def test_cli_baseline_then_drift_shadow_mode_exit_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    traces = _write_trace_file(tmp_path, [{"capability": "database_read"}] * 3)
    assert main(["runtime", "baseline", str(traces), "--out", "b.json"]) == 0
    assert json.loads((tmp_path / "b.json").read_text())["schema"] == "runtime-baseline/1.0"

    shifted = _write_trace_file(tmp_path, [{"capability": "shell_execution"}] * 3)
    # shadow mode: a high-class event without --fail-on-drift still exits 0
    assert main(["runtime", "drift", str(shifted), "--baseline", "b.json"]) == 0
    assert "new_high_impact_capability" in capsys.readouterr().out


def test_cli_drift_gates_only_when_asked(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    traces = _write_trace_file(tmp_path, [{"capability": "database_read"}] * 3)
    main(["runtime", "baseline", str(traces), "--out", "b.json"])
    shifted = _write_trace_file(tmp_path, [{"capability": "shell_execution"}] * 3)
    code = main(["runtime", "drift", str(shifted), "--baseline", "b.json",
                 "--fail-on-drift", "high", "--out", "d.json"])
    assert code == 1
    assert "drift gate failed" in capsys.readouterr().err
    assert json.loads((tmp_path / "d.json").read_text())["schema"] == "runtime-drift/1.0"


def test_cli_drift_missing_baseline_is_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    traces = _write_trace_file(tmp_path, [{}])
    assert main(["runtime", "drift", str(traces), "--baseline", "nope.json"]) == 2
    assert "baseline not found" in capsys.readouterr().err


def test_cli_drift_bad_baseline_version_is_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    traces = _write_trace_file(tmp_path, [{}])
    (tmp_path / "old.json").write_text('{"schema": "runtime-baseline/9.9", "agents": {}}')
    assert main(["runtime", "drift", str(traces), "--baseline", "old.json"]) == 2
    assert "unsupported baseline schema" in capsys.readouterr().err
