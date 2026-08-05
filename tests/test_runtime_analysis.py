"""Runtime overlay Phase 2: `stoa runtime analyze` + registry merge.

Covers: analysis determinism (identical traces → identical body), agent
correlation (matched / unmatched / no-runtime-evidence, never a silent
drop), the observed-behavior aggregates, merge additivity (a registry that
never passes through merge is untouched; one that does gains only the
documented optional fields), and the CLI exit codes.
"""

from __future__ import annotations

import copy
import json

import pytest

from stoa.cli import main
from stoa.runtime.analysis import analyze_traces
from stoa.runtime.merge import merge_runtime_into_registry
from stoa.runtime.spans import build_span


def _span(**overrides) -> dict:
    base = dict(
        trace_id="t1", span_id="s1", parent_span_id=None, kind="action",
        start_ts="2026-08-01T10:00:00.000Z", end_ts="2026-08-01T10:00:01.000Z",
        status="ok", redaction="redacted",
    )
    base.update(overrides)
    return build_span(**base)


def _write_traces(tmp_path, spans, name="trace-1-0000.jsonl"):
    lines = [json.dumps({"kind": "header", "schema": "stoa-trace/1.0",
                         "sdk_version": "0.0", "redaction": "redacted"})]
    lines += [json.dumps(s) for s in spans]
    traces = tmp_path / "traces"
    traces.mkdir(exist_ok=True)
    (traces / name).write_text("\n".join(lines) + "\n")
    return traces


def _registry(agent_ids=("aaaaaaaaaaaa",)) -> dict:
    return {
        "schema_version": "1.4",
        "tool": {"name": "stoa", "version": "0.0"},
        "repository": {"name": "fixture"},
        "summary": {},
        "agents": [
            {
                "id": aid, "name": f"agent_{aid[:4]}", "symbol": f"agent_{aid[:4]}",
                "path": f"agents/{aid[:4]}.py", "language": "python",
                "capabilities": ["payment_access"], "integrations": ["stripe"],
                "findings": [], "evidence": [{"rule_id": "AGENT_LANGCHAIN",
                                              "line": 3, "description": "x"}],
            }
            for aid in agent_ids
        ],
        "repository_findings": [],
    }


# --- aggregation ----------------------------------------------------------------


def test_analyze_aggregates_observed_behavior(tmp_path):
    spans = [
        _span(span_id="s1", agent_id="aaaaaaaaaaaa", kind="action",
              capability="payment_access", integration="stripe",
              amount=120.0, currency="USD", approval_span_id="ap1"),
        _span(span_id="s2", agent_id="aaaaaaaaaaaa", kind="action",
              capability="payment_access", amount=300.0, currency="USD"),
        _span(span_id="s3", agent_id="aaaaaaaaaaaa", kind="llm_call",
              provider="openai", model="gpt-4o", status="error"),
        _span(span_id="s4", agent_id="aaaaaaaaaaaa", kind="approval",
              approved_by="ops@x", approval_method="slack"),
    ]
    traces = _write_traces(tmp_path, spans)
    analysis = analyze_traces(traces, _registry())

    agent = analysis["agents"]["aaaaaaaaaaaa"]
    assert agent["span_count"] == 4
    assert agent["spans_by_kind"] == {"action": 2, "approval": 1, "llm_call": 1}
    assert agent["observed_capabilities"] == ["payment_access"]
    assert agent["observed_integrations"] == ["stripe"]
    assert agent["observed_models"] == ["gpt-4o"]
    assert agent["high_impact_actions"] == 2
    assert agent["high_impact_approved"] == 1
    assert agent["approval_rate_high_impact"] == 0.5
    assert agent["max_observed_amount"] == {"amount": 300.0, "currency": "USD"}
    assert agent["window_total_amounts"] == {"USD": 420.0}
    assert agent["error_rate"] == 0.25
    assert analysis["window"]["span_count"] == 4
    assert analysis["no_runtime_evidence"] == []


def test_analyze_delegations_collected(tmp_path):
    spans = [_span(kind="delegation", agent_id="aaaaaaaaaaaa",
                   from_agent_id="aaaaaaaaaaaa", to_agent_id="bbbbbbbbbbbb")]
    traces = _write_traces(tmp_path, spans)
    analysis = analyze_traces(traces, _registry(("aaaaaaaaaaaa", "bbbbbbbbbbbb")))
    assert analysis["agents"]["aaaaaaaaaaaa"]["delegations_to"] == ["bbbbbbbbbbbb"]


# --- correlation: nothing dropped silently -----------------------------------------


def test_unknown_agent_id_lands_in_unmatched_not_dropped(tmp_path):
    traces = _write_traces(tmp_path, [_span(agent_id="ffffffffffff")])
    analysis = analyze_traces(traces, _registry())
    assert analysis["agents"] == {}
    (entry,) = analysis["unmatched_agents"]
    assert entry["key"] == "unknown-id:ffffffffffff"
    assert entry["span_count"] == 1
    assert "not present in the registry" in entry["reason"]


def test_hint_only_span_gets_suggested_matches(tmp_path):
    span = _span(agent_id=None)
    span["agent_hint"] = {"module": "agents.agent_aaaa", "qualname": "agent_aaaa.run"}
    traces = _write_traces(tmp_path, [span])
    analysis = analyze_traces(traces, _registry())
    (entry,) = analysis["unmatched_agents"]
    assert entry["suggested_matches"] == [
        {"agent_id": "aaaaaaaaaaaa", "name": "agent_aaaa", "path": "agents/aaaa.py"}
    ]


def test_registry_agent_with_zero_spans_is_explicit(tmp_path):
    traces = _write_traces(tmp_path, [_span(agent_id="aaaaaaaaaaaa")])
    analysis = analyze_traces(traces, _registry(("aaaaaaaaaaaa", "bbbbbbbbbbbb")))
    assert analysis["no_runtime_evidence"] == ["bbbbbbbbbbbb"]


def test_analyze_without_registry_never_claims_no_evidence(tmp_path):
    traces = _write_traces(tmp_path, [_span(agent_id="aaaaaaaaaaaa")])
    analysis = analyze_traces(traces, None)
    assert analysis["no_runtime_evidence"] == []
    assert "aaaaaaaaaaaa" in analysis["agents"]


# --- determinism ---------------------------------------------------------------------


def test_analyze_body_deterministic_given_identical_traces(tmp_path):
    spans = [
        _span(span_id=f"s{i}", agent_id="aaaaaaaaaaaa",
              capability="payment_access", amount=float(i))
        for i in range(20)
    ]
    traces = _write_traces(tmp_path, spans)
    one = analyze_traces(traces, _registry(), generated_at="T1")
    two = analyze_traces(traces, _registry(), generated_at="T2")
    one.pop("header"), two.pop("header")
    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)


def test_window_derives_from_span_timestamps_not_clock(tmp_path):
    spans = [
        _span(span_id="s1", start_ts="2026-07-01T00:00:00.000Z",
              end_ts="2026-07-01T00:00:01.000Z"),
        _span(span_id="s2", start_ts="2026-07-14T00:00:00.000Z",
              end_ts="2026-07-14T00:00:05.000Z"),
    ]
    traces = _write_traces(tmp_path, spans)
    window = analyze_traces(traces, None)["window"]
    assert window == {"start": "2026-07-01T00:00:00.000Z",
                      "end": "2026-07-14T00:00:05.000Z", "span_count": 2}


# --- merge additivity ------------------------------------------------------------------


def test_merge_adds_only_documented_fields_and_never_mutates_input(tmp_path):
    traces = _write_traces(tmp_path, [
        _span(agent_id="aaaaaaaaaaaa", capability="payment_access",
              amount=50.0, approval_span_id="ap"),
    ])
    registry = _registry(("aaaaaaaaaaaa", "bbbbbbbbbbbb"))
    registry_before = copy.deepcopy(registry)
    analysis = analyze_traces(traces, registry)
    enriched = merge_runtime_into_registry(registry, analysis)

    assert registry == registry_before  # input untouched

    active = next(a for a in enriched["agents"] if a["id"] == "aaaaaaaaaaaa")
    idle = next(a for a in enriched["agents"] if a["id"] == "bbbbbbbbbbbb")
    assert active["liveness_state"] == "active"
    assert idle["liveness_state"] == "idle"
    assert "runtime_evidence" in active and "runtime_evidence" not in idle
    evidence = active["runtime_evidence"]
    assert evidence["observed_capabilities"] == ["payment_access"]
    assert evidence["approval_rate_high_impact"] == 1.0
    assert evidence["evidence_quality"] == "redacted"
    assert evidence["window"]["start"] and evidence["window"]["end"]
    assert enriched["runtime"]["agents_covered"] == 1
    assert enriched["runtime"]["agents_total"] == 2

    # additivity: removing the new keys restores the original document
    for agent in enriched["agents"]:
        agent.pop("runtime_evidence", None)
        agent.pop("liveness_state", None)
    enriched.pop("runtime")
    assert enriched == registry_before


# --- CLI --------------------------------------------------------------------------------


def test_cli_analyze_writes_output_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    traces = _write_traces(tmp_path, [_span(agent_id="aaaaaaaaaaaa")])
    (tmp_path / "reg.json").write_text(json.dumps(_registry()))
    code = main(["runtime", "analyze", str(traces), "--registry", "reg.json",
                 "--out", "runtime.json"])
    assert code == 0
    document = json.loads((tmp_path / "runtime.json").read_text())
    assert document["schema"] == "runtime-analysis/1.0"
    assert document["header"]["generated_at"]  # wall-clock lives in the header
    assert "1 matched agent(s)" in capsys.readouterr().out


def test_cli_analyze_empty_dir_fail_open_exit_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "empty").mkdir()
    code = main(["runtime", "analyze", "empty", "--out", "runtime.json"])
    assert code == 0
    assert "no trace files" in capsys.readouterr().err


def test_cli_missing_registry_is_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "empty").mkdir()
    code = main(["runtime", "analyze", "empty", "--registry", "nope.json"])
    assert code == 2
    assert "registry not found" in capsys.readouterr().err


def test_cli_runtime_without_subcommand_is_usage_error(capsys):
    assert main(["runtime"]) == 2


def test_cli_merge_writes_enriched_copy_not_in_place(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    traces = _write_traces(tmp_path, [_span(agent_id="aaaaaaaaaaaa")])
    original_text = json.dumps(_registry(), indent=2)
    (tmp_path / "reg.json").write_text(original_text)
    code = main(["runtime", "merge", str(traces), "--registry", "reg.json",
                 "--out", "enriched.json"])
    assert code == 0
    assert (tmp_path / "reg.json").read_text() == original_text  # untouched
    enriched = json.loads((tmp_path / "enriched.json").read_text())
    assert enriched["agents"][0]["liveness_state"] == "active"


def test_cli_map_prints_suggestions(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    span = _span(agent_id=None)
    span["agent_hint"] = {"module": "agents.agent_aaaa", "qualname": "agent_aaaa.run"}
    traces = _write_traces(tmp_path, [span])
    (tmp_path / "reg.json").write_text(json.dumps(_registry()))
    code = main(["runtime", "map", str(traces), "--registry", "reg.json"])
    assert code == 0
    out = capsys.readouterr().out
    assert "suggest agent_id=aaaaaaaaaaaa" in out


# --- diff must ignore runtime fields (documented exclusion) ------------------------------


def test_diff_ignores_runtime_evidence_blocks(tmp_path):
    """An enriched registry diffed against its own un-enriched twin must
    report zero drift: runtime data varies run to run and must not create
    phantom drift in code diffs."""
    from stoa.registry_diff import diff_registries

    traces = _write_traces(tmp_path, [
        _span(agent_id="aaaaaaaaaaaa", capability="shell_execution"),
    ])
    registry = _registry()
    enriched = merge_runtime_into_registry(registry, analyze_traces(traces, registry))
    diff = diff_registries(registry, enriched)
    assert diff["summary"]["agents_changed"] == 0
    assert diff["summary"]["agents_added"] == 0
    assert diff["summary"]["max_drift_severity"] == "info"


# --- stoa init runtime ---------------------------------------------------------


def test_init_runtime_scaffolds_config_and_example(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "runtime"]) == 0
    out = capsys.readouterr().out
    assert "created:     stoa.toml" in out
    assert "shadow mode" in out.lower()
    toml_text = (tmp_path / "stoa.toml").read_text()
    assert "[runtime]" in toml_text and "[runtime.drift]" in toml_text
    example = (tmp_path / "stoa_runtime_example.py").read_text()
    assert "stoa_rt.configure" in example and "capture_content" in example
    # the scaffolded config parses cleanly through the real loader
    from stoa.config import load_config

    config = load_config(tmp_path)
    assert config.runtime_trace_dir == "stoa-traces"
    assert config.runtime_drift_ratio_threshold == 3.0


def test_init_runtime_appends_to_existing_toml_and_is_idempotent(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "stoa.toml").write_text('fail_on = "critical"\n')
    assert main(["init", "runtime"]) == 0
    text = (tmp_path / "stoa.toml").read_text()
    assert text.startswith('fail_on = "critical"')  # existing config preserved
    assert "[runtime]" in text
    capsys.readouterr()
    assert main(["init", "runtime"]) == 0  # second run: skip, don't duplicate
    assert "skipped:" in capsys.readouterr().out
    assert (tmp_path / "stoa.toml").read_text().count("[runtime]") == 1
