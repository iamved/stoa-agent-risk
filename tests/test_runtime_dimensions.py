"""Runtime overlay Phase 6: the `runtime` assessability tier.

Property contract, both directions:

- the existing proxy cap is untouched — every entry still labeled ``proxy``
  is capped at moderate (the scan-time test keeps asserting that; here we
  re-assert it over merged documents too);
- the new tier's own invariant — every entry labeled ``runtime`` carries a
  non-empty evidence window — plus: no runtime evidence ⇒ dimension blocks
  byte-identical to the plain scan.
"""

from __future__ import annotations

import copy
import json

from stoa.config import StoaConfig
from stoa.runtime.analysis import analyze_traces
from stoa.runtime.merge import merge_runtime_into_registry
from stoa.runtime.spans import build_span

AGENT = "aaaaaaaaaaaa"
OTHER = "bbbbbbbbbbbb"


def _dimension_entry(dim_id, assessability="proxy", exposure="moderate", score=40):
    return {
        "id": dim_id, "group": "D", "assessability": assessability,
        "exposure": exposure, "score": score,
        "contributing_findings": [], "contributing_capabilities": [],
        "controls_observed": [], "statement": "Proxy signals only",
    }


def _registry(declared=None) -> dict:
    def agent(aid):
        record = {
            "id": aid, "name": f"a_{aid[:4]}", "symbol": f"a_{aid[:4]}",
            "path": f"agents/{aid[:4]}.py", "language": "python",
            "capabilities": ["payment_access"], "integrations": [],
            "evidence": [{"rule_id": "AGENT_LANGCHAIN", "line": 2, "description": "x"}],
            "findings": [],
            "dimension_assessment": {
                "taxonomy": {"id": "stoa-aiuc-8", "version": "2.0"},
                "dimensions": [
                    _dimension_entry("conduct-variability"),
                    _dimension_entry("dependency-drift"),
                    _dimension_entry("boundary-leakage", assessability="strong",
                                     exposure="low", score=10),
                ],
            },
        }
        if declared and aid == AGENT:
            record["declared"] = declared
        return record

    return {
        "schema_version": "1.4", "tool": {"name": "stoa", "version": "0"},
        "repository": {"name": "fixture"}, "summary": {},
        "agents": [agent(AGENT), agent(OTHER)],
        "repository_findings": [],
        "dimension_summary": {
            "taxonomy": {"id": "stoa-aiuc-8", "version": "2.0"},
            "dimensions": [
                {"id": "conduct-variability", "name": "Conduct variability",
                 "group": "D", "assessability": "proxy",
                 "max_exposure": "moderate", "agents_elevated": 0,
                 "agents_moderate": 2},
                {"id": "dependency-drift", "name": "Dependency drift",
                 "group": "D", "assessability": "proxy",
                 "max_exposure": "moderate", "agents_elevated": 0,
                 "agents_moderate": 2},
            ],
        },
    }


def _traces(tmp_path, spans):
    traces = tmp_path / "traces"
    traces.mkdir(exist_ok=True)
    lines = [json.dumps({"kind": "header", "schema": "stoa-trace/1.0"})]
    for i, kw in enumerate(spans):
        base = dict(trace_id="t", span_id=f"s{i}", parent_span_id=None,
                    kind="llm_call", start_ts=f"2026-08-0{1 + i % 5}T00:00:00Z",
                    end_ts=f"2026-08-0{1 + i % 5}T00:00:01Z", status="ok",
                    redaction="redacted", agent_id=AGENT)
        base.update(kw)
        lines.append(json.dumps(build_span(**base)))
    (traces / "t.jsonl").write_text("\n".join(lines) + "\n")
    return traces


def _merged(tmp_path, spans, registry=None, config=None):
    registry = registry or _registry()
    analysis = analyze_traces(_traces(tmp_path, spans), registry)
    return merge_runtime_into_registry(registry, analysis, config)


def _entry(document, agent_id, dim_id):
    agent = next(a for a in document["agents"] if a["id"] == agent_id)
    return next(d for d in agent["dimension_assessment"]["dimensions"]
                if d["id"] == dim_id)


# --- tier upgrades ---------------------------------------------------------------


def test_stable_pinned_model_scores_low_dependency_drift(tmp_path):
    merged = _merged(tmp_path, [
        {"provider": "openai", "model": "gpt-4o-2024-08-06"}] * 3)
    entry = _entry(merged, AGENT, "dependency-drift")
    assert entry["assessability"] == "runtime"
    assert entry["exposure"] == "low"  # the proxy tier could never say this
    assert entry["evidence_window"]["span_count"] == 3
    assert entry["runtime_basis"]["distinct_models_observed"] == 1
    assert "Assessed from traces" in entry["statement"]
    assert "not a claim about future behavior" in entry["statement"]


def test_model_change_mid_window_elevates_dependency_drift(tmp_path):
    """The cap lifts in BOTH directions: real observation can also exceed
    moderate — the whole point of the runtime tier."""
    merged = _merged(tmp_path, [
        {"provider": "openai", "model": "gpt-4o"},
        {"provider": "openai", "model": "gpt-4o-mini"},
    ])
    entry = _entry(merged, AGENT, "dependency-drift")
    assert entry["assessability"] == "runtime"
    assert entry["exposure"] == "elevated"
    assert entry["runtime_basis"]["distinct_models_observed"] == 2


def test_error_rate_thresholds_bucket_conduct_variability(tmp_path):
    clean = _merged(tmp_path, [{"model": "gpt-4o"}] * 10)
    assert _entry(clean, AGENT, "conduct-variability")["exposure"] == "low"

    flaky = _merged(tmp_path, [{"model": "gpt-4o"}] * 9 + [{"status": "error"}])
    entry = _entry(flaky, AGENT, "conduct-variability")
    assert entry["exposure"] == "elevated"  # 10% error rate at default threshold
    assert entry["runtime_basis"]["error_rate"] == 0.1


def test_conduct_thresholds_configurable(tmp_path):
    config = StoaConfig(runtime_error_rate_elevated=0.5,
                        runtime_error_rate_moderate=0.05)
    merged = _merged(tmp_path, [{}] * 9 + [{"status": "error"}], config=config)
    assert _entry(merged, AGENT, "conduct-variability")["exposure"] == "moderate"


def test_contradicted_declared_gate_elevates_conduct(tmp_path):
    registry = _registry(declared={"autonomy_intent": "human_approved"})
    merged = _merged(tmp_path, [
        {"kind": "action", "capability": "payment_access"}], registry=registry)
    entry = _entry(merged, AGENT, "conduct-variability")
    assert entry["exposure"] == "elevated"
    assert entry["runtime_basis"]["declared_gate_contradicted"] is True


# --- property tests ------------------------------------------------------------------


def test_property_proxy_entries_still_capped_after_merge(tmp_path):
    """The original invariant, re-asserted over merged documents: any entry
    still labeled proxy (here: the un-traced agent's) is capped."""
    merged = _merged(tmp_path, [{"model": "gpt-4o"}] * 3)
    for agent in merged["agents"]:
        for entry in agent["dimension_assessment"]["dimensions"]:
            if entry["assessability"] == "proxy":
                assert entry["exposure"] != "elevated", entry


def test_property_runtime_entries_always_carry_evidence_window(tmp_path):
    merged = _merged(tmp_path, [
        {"provider": "openai", "model": "gpt-4o"},
        {"provider": "openai", "model": "gpt-4o-mini"},
        {"status": "error"},
    ])
    runtime_entries = [
        entry
        for agent in merged["agents"]
        for entry in agent["dimension_assessment"]["dimensions"]
        if entry["assessability"] == "runtime"
    ]
    assert runtime_entries, "expected at least one runtime-tier entry"
    for entry in runtime_entries:
        window = entry["evidence_window"]
        assert window["start"] and window["end"] and window["span_count"] > 0
        assert "runtime_basis" in entry


def test_untraced_agent_dimensions_byte_identical(tmp_path):
    registry = _registry()
    before = copy.deepcopy(
        next(a for a in registry["agents"] if a["id"] == OTHER)["dimension_assessment"]
    )
    merged = _merged(tmp_path, [{"model": "gpt-4o"}] * 2, registry=registry)
    after = next(a for a in merged["agents"] if a["id"] == OTHER)["dimension_assessment"]
    assert after == before


def test_non_proxy_and_custom_tier_entries_never_touched(tmp_path):
    registry = _registry()
    # a custom taxonomy might tier dependency-drift as "partial" — respect it
    for entry in registry["agents"][0]["dimension_assessment"]["dimensions"]:
        if entry["id"] == "dependency-drift":
            entry["assessability"] = "partial"
    merged = _merged(tmp_path, [{"model": "gpt-4o"}] * 2, registry=registry)
    assert _entry(merged, AGENT, "dependency-drift")["assessability"] == "partial"
    assert _entry(merged, AGENT, "boundary-leakage")["assessability"] == "strong"


def test_summary_rollup_follows_upgraded_entries(tmp_path):
    merged = _merged(tmp_path, [
        {"provider": "openai", "model": "gpt-4o"},
        {"provider": "openai", "model": "gpt-4o-mini"},
    ])
    row = next(r for r in merged["dimension_summary"]["dimensions"]
               if r["id"] == "dependency-drift")
    # one agent elevated (runtime-assessed), the untraced one still moderate
    assert row["max_exposure"] == "elevated"
    assert row["agents_elevated"] == 1 and row["agents_moderate"] == 1
    # the row is relabeled runtime, so no proxy-labeled row ever shows elevated
    assert row["assessability"] == "runtime"
    conduct = next(r for r in merged["dimension_summary"]["dimensions"]
                   if r["id"] == "conduct-variability")
    if conduct["assessability"] == "proxy":
        assert conduct["max_exposure"] != "elevated"
