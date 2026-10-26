"""The envelope's runtime slot (stoa-dashboard/1.1): built from traces,
absent without them, and reachable from `stoa dashboard --runtime`."""

from __future__ import annotations

import json
from pathlib import Path

from stoa.cli import main
from stoa.dashboard import build_envelope, build_runtime_slot
from stoa.runtime.analysis import analyze_traces
from stoa.runtime.drift import build_baseline

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "ui" / "fixtures"


def _registry() -> dict:
    return json.loads((FIXTURES / "meridian-pay.baseline.json").read_text())


def test_envelope_without_traces_has_a_null_runtime_slot():
    envelope = build_envelope(_registry())
    assert envelope["schema"] == "stoa-dashboard/1.1" and envelope["runtime"] is None
    assert "runtime_evidence" not in envelope["registry"]["agents"][0]


def test_slot_carries_analysis_reconcile_chain_and_drift():
    head = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())["registry"]
    baseline = build_baseline(analyze_traces(FIXTURES / "traces" / "meridian-pay-august", head))
    enriched, slot = build_runtime_slot(FIXTURES / "traces" / "meridian-pay", head, baseline=baseline, key="hmac:6d6572696469616e2d64656d6f")
    assert slot["schema"] == "dashboard-runtime/1.0"
    assert slot["analysis"]["schema"] == "runtime-analysis/1.1" and slot["analysis"]["window"]["span_count"] > 0
    assert slot["reconcile"]["schema"] == "runtime-reconcile/1.0" and slot["reconcile"]["totals"]["used_but_undeclared"] >= 1
    assert slot["chain"]["ok"] and slot["chain"]["files"][0]["key_grade"] == "hmac-sha256" and slot["chain"]["files"][0]["signed"] > 0
    assert slot["drift"]["schema"] == "runtime-drift/1.0" and any(e["kind"] == "approval_rate_drop" for e in slot["drift"]["events"])
    assert slot["baseline_present"] is True
    states = {a["id"]: a.get("liveness_state") for a in enriched["agents"]}
    assert states["bc3db1f17013"] == "active" and states["62007a57a832"] == "idle"
    rules = {f["rule_id"] for a in enriched["agents"] for f in a["findings"]}
    assert {"RT006", "RT007"} <= rules
    # the envelope keeps the slot and the enriched registry together
    envelope = build_envelope(enriched, runtime=slot)
    assert envelope["runtime"] is slot and envelope["registry"]["runtime"]["rt_findings"] == enriched["runtime"]["rt_findings"]


def test_committed_fixture_carries_the_slot_and_verifies():
    envelope = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())
    slot = envelope["runtime"]
    assert slot and slot["chain"]["ok"] and slot["traces_dir"] == "stoa-traces"
    # every runtime-tier dimension entry names its window
    for agent in envelope["registry"]["agents"]:
        for entry in (agent.get("dimension_assessment") or {}).get("dimensions") or []:
            if entry["assessability"] == "runtime":
                assert entry["evidence_window"]["span_count"] > 0 and entry["static_exposure"]
    # the demo traces pass verification with the demo key, and fail with another
    from stoa.runtime.chain import verify_dir
    assert verify_dir(FIXTURES / "traces" / "meridian-pay", "hmac:6d6572696469616e2d64656d6f").ok
    assert not verify_dir(FIXTURES / "traces" / "meridian-pay", "hmac:00").ok


def test_cli_dashboard_runtime_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    head = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())["registry"]
    (tmp_path / "stoa-registry.json").write_text(json.dumps(head))
    monkeypatch.setenv("STOA_DASHBOARD_TEMPLATE", str(tmp_path / "t.html"))
    (tmp_path / "t.html").write_text('<html><head><meta charset="utf-8" /></head><body><script id="stoa-data" type="application/json">__STOA_DASHBOARD_DATA__</script></body></html>')
    code = main(["dashboard", "stoa-registry.json", "--runtime", str(FIXTURES / "traces" / "meridian-pay"), "--json-out", "env.json", "--out", "out.html"])
    assert code == 0
    envelope = json.loads((tmp_path / "env.json").read_text())
    assert envelope["schema"] == "stoa-dashboard/1.1" and envelope["runtime"]["analysis"]["window"]["span_count"] > 0
    assert envelope["runtime"]["drift"] is None and envelope["runtime"]["baseline_present"] is False
    assert any(a.get("liveness_state") == "active" for a in envelope["registry"]["agents"])


def test_slot_carries_the_policy_document_and_outcomes():
    envelope = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())
    block = envelope["runtime"]["policies"]
    assert block["document"]["path"] == "stoa.policy.toml" and block["document"]["mode"] == "observe" and block["document"]["problems"] == []
    ids = {p["id"] for p in block["document"]["policies"]}
    assert {"POL-BASE-001", "POL-FIN-002-BC3DB1", "POL-PAY-001-B8F011"} <= ids
    cap = next(p for p in block["document"]["policies"] if p["id"] == "POL-FIN-002-BC3DB1")
    assert cap["enforced"] is True and cap["condition_text"] == "sum(amount) over 24h > 800"
    assert block["summary"]["POL-FIN-002-BC3DB1"]["blocked"] == 1 and block["summary"]["POL-FIN-001-BC3DB1"]["would_block"] == 10
    assert block["summary"]["POL-PAY-001-B8F011"]["escalated"] == 1
    assert block["killswitch_drills"][0]["seconds_to_stop"] == 1.8
    # the enforced block is one span, status error, denied by exactly that policy
    agent = next(a for a in envelope["registry"]["agents"] if a["id"] == "bc3db1f17013")
    assert envelope["registry"]["policies"]["policies"]["POL-FIN-002-BC3DB1"]["blocked"] == 1
    assert agent["runtime_evidence"]["money_actions"] >= 10


def test_committed_fixture_carries_hallucination_detectr_for_the_captured_sessions():
    """Two September sessions carry content: the clean account refund grounds
    every claim; the support refund of 240 for a 24 request fires RT012, the
    'processed' reply fires RT010 and the 2 day promise fires RT011."""
    envelope = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text(encoding="utf-8"))
    block = envelope["runtime"]["detectr"]
    assert block["schema"] == "dashboard-detectr/0.1" and block["with_content"] == 2 and block["trajectories"] > 2
    names = {a["id"]: a["name"] for a in envelope["registry"]["agents"]}
    rows = {names[k]: v for k, v in block["by_agent"].items()}
    assert rows["support_agent"]["labels"]["contradicted"] == 1 and rows["support_agent"]["findings"] == 3
    assert rows["graph"]["findings"] == 0 and rows["graph"]["labels"] == {"grounded": 4, "unsupported": 0, "contradicted": 0, "unverifiable": 0}
    assert [f["rule_id"] for f in block["findings"]] == ["RT012", "RT010", "RT011"]
    assert all(f["category"] == "hallucination" for f in block["findings"])
    # DetectR findings stay on the Runtime tab: none is merged into an agent's findings
    assert all(f["rule_id"] not in ("RT009", "RT010", "RT011", "RT012", "RT013") for a in envelope["registry"]["agents"] for f in a["findings"])
    assert block["metrics"]["schema"] == "stoa-detectr-metrics/0.1"


def test_slot_detectr_is_null_without_captured_content(tmp_path):
    from stoa import runtime as rt

    rt.shutdown()
    rt.configure(str(tmp_path / "traces"), agent_id="refund")
    with rt.session("u1"):
        with rt.model_call("openai", "gpt-4o") as m:
            m.record(response="Your refund has been processed.")
    rt.flush()
    rt.shutdown()
    registry = {"schema_version": "1.8", "tool": {"name": "stoa", "version": "0"}, "repository": {"name": "x"}, "summary": {}, "agents": []}
    _, slot = build_runtime_slot(tmp_path / "traces", registry)
    assert slot["detectr"] is None
