"""Runtime overlay end-to-end: the checked-in Meridian trace fixture, and the
streaming performance smoke test.

The fixture (examples/meridian-ops/traces/) is small, deterministic, and
hand-auditable — 12 spans over three agents, engineered against Meridian's
real stoa-declared.toml so a full scan → analyze → merge → packet pass
exercises RT001 (twice), RT002, RT003, a delegates edge, and corroborated
static edges, with real agent ids.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from pathlib import Path

import pytest

from stoa.config import StoaConfig, load_config
from stoa.report_json import build_document
from stoa.runtime.analysis import analyze_traces
from stoa.runtime.merge import merge_runtime_into_registry
from stoa.scanner import ScanOptions, run_scan

MERIDIAN = Path(__file__).resolve().parents[1] / "examples" / "meridian-ops"
TRACES = MERIDIAN / "traces"

PAYMENTS = "a09ff38687e9"
SUPPORT_BOT = "2e0ab9a50e4e"
TRIAGE = "b02789752d1c"


@pytest.fixture(scope="module")
def meridian_enriched():
    config = load_config(MERIDIAN)
    result = run_scan(ScanOptions(root=MERIDIAN, no_git=True), config)
    document = build_document(result, config)
    analysis = analyze_traces(TRACES, document)
    return document, analysis, merge_runtime_into_registry(document, analysis, config)


def test_fixture_correlates_all_three_agents(meridian_enriched):
    _, analysis, _ = meridian_enriched
    assert set(analysis["agents"]) == {PAYMENTS, SUPPORT_BOT, TRIAGE}
    assert analysis["unmatched_agents"] == []
    assert analysis["window"]["span_count"] == 12
    # every other Meridian agent is explicitly evidence-less, never dropped
    assert len(analysis["no_runtime_evidence"]) >= 8


def test_fixture_payments_summary_hand_checkable(meridian_enriched):
    _, analysis, _ = meridian_enriched
    payments = analysis["agents"][PAYMENTS]
    assert payments["high_impact_actions"] == 2
    assert payments["high_impact_approved"] == 1
    assert payments["approval_rate_high_impact"] == 0.5
    assert payments["max_observed_amount"] == {"amount": 2500.0, "currency": "USD"}
    assert payments["window_total_amounts"] == {"USD": 3700.0}


def test_fixture_rt_findings_against_real_declarations(meridian_enriched):
    _, _, enriched = meridian_enriched
    by_agent = {
        a["id"]: [f["rule_id"] for f in a["findings"] if f["rule_id"].startswith("RT")]
        for a in enriched["agents"]
    }
    # payments: declared human_approved, one unapproved 2500 USD action
    assert "RT001" in by_agent[PAYMENTS]
    assert "RT002" in by_agent[PAYMENTS]
    # support_bot: declared recommend_only, unapproved messaging action
    assert "RT001" in by_agent[SUPPORT_BOT]
    # triage: filesystem_write observed, absent from its static capabilities
    assert "RT003" in by_agent[TRIAGE]
    rt002 = next(f for a in enriched["agents"] for f in a["findings"]
                 if f["rule_id"] == "RT002")
    assert rt002["trace_ref"]["span_id"] == "b2"
    assert rt002["declared_ref"]["key"].endswith("economic_authority.max_per_action")


def test_fixture_graph_gains_delegates_and_corroboration(meridian_enriched):
    from stoa.graph_model import build_graph, overlay_runtime

    _, _, enriched = meridian_enriched
    graph = overlay_runtime(build_graph(enriched), enriched)
    edges = {(e.source, e.target, e.kind): e for e in graph.edges}
    delegates = edges[(SUPPORT_BOT, PAYMENTS, "delegates")]
    assert delegates.provenance == "observed"
    assert edges[(PAYMENTS, "tool_stripe", "tool_call")].observed is True
    # triage's runtime-only filesystem reach appears as an observed edge
    assert edges[(TRIAGE, "resource_filesystem_write", "writes")].provenance == "observed"


def test_fixture_packet_area18_lists_the_incident_records(meridian_enriched):
    from stoa.assurance import build_assurance_packet

    _, _, enriched = meridian_enriched
    packet = build_assurance_packet(enriched)
    fields = [r["field"] for r in packet["areas"]["claims_evidence"]["rows"]]
    assert "traces_and_runtime_evidence" in fields
    assert "RT001" in fields and "RT002" in fields and "RT003" in fields
    assert "approval_gate_log" in fields
    contradiction_rules = {c["rule_id"] for c in packet["contradictions"]}
    assert {"RT001", "RT002", "RT003"} <= contradiction_rules
    assert "DECL001" in contradiction_rules  # static contradictions still there


def test_fixture_runtime_dimension_tier_applied(meridian_enriched):
    _, _, enriched = meridian_enriched
    triage = next(a for a in enriched["agents"] if a["id"] == TRIAGE)
    conduct = next(d for d in triage["dimension_assessment"]["dimensions"]
                   if d["id"] == "conduct-variability")
    assert conduct["assessability"] == "runtime"
    assert conduct["exposure"] == "elevated"  # 1 of 2 spans errored
    assert conduct["evidence_window"]["span_count"] == 2
    assert "Assessed from traces" in conduct["statement"]


def test_fixture_determinism_two_passes_identical(meridian_enriched):
    document, _, first = meridian_enriched
    config = load_config(MERIDIAN)
    second = merge_runtime_into_registry(
        document, analyze_traces(TRACES, document), config
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- performance smoke -----------------------------------------------------------


def test_analyze_streams_100k_spans_bounded_memory(tmp_path):
    """≥100k spans must stream: peak RSS growth stays far below the ~60 MB
    the raw JSON would occupy if slurped (budget documented in
    docs/runtime.md). Also a wall-clock sanity bound so a quadratic
    regression fails loudly."""
    traces = tmp_path / "traces"
    traces.mkdir()
    header = json.dumps({"kind": "header", "schema": "stoa-trace/1.0"})
    span_count = 100_000
    with open(traces / "big.jsonl", "w") as handle:
        handle.write(header + "\n")
        for i in range(span_count):
            handle.write(json.dumps({
                "kind": "tool_call", "trace_id": f"t{i % 500}",
                "span_id": f"s{i}", "parent_span_id": None,
                "agent_id": "aaaaaaaaaaaa",
                "start_ts": f"2026-08-01T{i % 24:02d}:00:00.000Z",
                "end_ts": f"2026-08-01T{i % 24:02d}:00:01.000Z",
                "status": "ok", "redaction": "redacted",
                "capability": "database_read", "integration": "postgres",
            }) + "\n")

    rss_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    started = time.perf_counter()
    analysis = analyze_traces(traces, None)
    elapsed = time.perf_counter() - started
    rss_after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    assert analysis["window"]["span_count"] == span_count
    assert analysis["agents"]["aaaaaaaaaaaa"]["span_count"] == span_count
    assert elapsed < 30, f"analyze took {elapsed:.1f}s for 100k spans"
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes vs KiB
    growth_mb = (rss_after - rss_before) * scale / (1024 * 1024)
    assert growth_mb < 60, f"peak RSS grew {growth_mb:.0f} MB — analyze is slurping"
