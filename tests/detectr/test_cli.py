"""stoa detectr check / ledger / metrics / bench."""

from __future__ import annotations

import json

import pytest

from stoa import runtime as rt
from stoa.cli import main


@pytest.fixture(autouse=True)
def _clean_sdk():
    rt.shutdown()
    yield
    rt.shutdown()


def _checkpoint(tmp_path):
    snapshot = {"config": {"configurable": {"thread_id": "thread-9"}}, "created_at": "2026-10-24T09:00:00Z", "values": {"messages": [
        {"type": "system", "content": "You are the refund agent for Meridian Pay."},
        {"type": "human", "content": "Please refund my order 8812"},
        {"type": "ai", "content": "", "tool_calls": [{"name": "orders.get", "args": {"order_id": 8812}, "id": "c0"}]},
        {"type": "tool", "content": json.dumps({"order_id": 8812, "total": 150.0, "status": "delivered"}), "tool_call_id": "c0", "name": "orders.get"},
        {"type": "ai", "content": "", "tool_calls": [{"name": "refund.issue", "args": {"order_id": 8812, "amount": 150, "approval_id": "APR-4471"}, "id": "c1"}],
         "response_metadata": {"model_name": "gpt-4o"}},
        {"type": "tool", "content": json.dumps({"status": "pending", "amount": 15.0}), "tool_call_id": "c1", "name": "refund.issue"},
        {"type": "ai", "content": "Your refund of $150 has been processed and will arrive in 2 days."},
    ]}}
    path = tmp_path / "checkpoint.json"
    path.write_text(json.dumps(snapshot))
    return path


def test_check_and_ledger_on_a_langgraph_checkpoint(tmp_path, capsys):
    path = _checkpoint(tmp_path)
    assert main(["detectr", "ledger", str(path), "--agent-id", "refund"]) == 0
    out = capsys.readouterr().out
    assert "Ledger thread-9" in out and "e0007 agent_output" in out
    assert main(["detectr", "check", str(path), "--agent-id", "refund", "--out", str(tmp_path / "reports" / "r1.json")]) == 0
    out = capsys.readouterr().out
    assert "RT012 critical unsupported/ungrounded" in out and "[APR-4471]" in out
    assert "RT010 high contradicted/numerical" in out and "$[150]" in out and "RT011 medium" in out
    assert "counted apart" in out
    report = json.loads((tmp_path / "reports" / "r1.json").read_text())
    assert report["schema"] == "stoa-detectr-report/0.1" and [f["rule_id"] for f in report["findings"]] == ["RT012", "RT010", "RT011"]
    assert main(["detectr", "check", str(path), "--agent-id", "refund", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["contradicted"] == 1


def test_check_reads_sdk_traces_and_a_config(tmp_path, capsys):
    rt.configure(str(tmp_path / "traces"), capture_content=True, agent_id="refund")

    @rt.guard("payment", limit_field="amount", approval_field="approval_id", name="refund.issue")
    def issue(order_id, amount, approval_id=None):
        return {"status": "pending", "amount": 15.0}

    with rt.session("u1") as s:
        s.user_input("Please refund my order 8812")
        with rt.model_call("openai", "gpt-4o") as m:
            m.record(response="Your refund of $150 has been processed and will arrive in 2 days.")
        issue(8812, 150, approval_id="APR-4471")
    rt.flush()
    rt.shutdown()
    (tmp_path / "stoa.detectr.toml").write_text('[detectr]\nthreshold = 0.6\n[detectr.lanes.payment]\ncheckers = ["selfcheck"]\n')
    code = main(["detectr", "check", str(tmp_path / "traces"), "--config", str(tmp_path / "stoa.detectr.toml"), "--json"])
    assert code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["consequence"] == "payment" and report["built_from"] == "sdk"
    rules = {f["rule_id"] for f in report["findings"]}
    assert "RT011" in rules and "RT012" in rules  # approval id and the 2 day promise
    assert any("not implemented" in w for w in report["warnings"])
    assert report["findings"][0]["trace_ref"]["span_id"]


def test_check_handles_bad_input_and_redacted_traces(tmp_path, capsys):
    assert main(["detectr", "check", str(tmp_path / "missing.json")]) == 3
    (tmp_path / "empty.json").write_text(json.dumps({"values": {"messages": []}}))
    assert main(["detectr", "check", str(tmp_path / "empty.json")]) == 3
    rt.configure(str(tmp_path / "traces"), agent_id="refund")
    with rt.session("u1"):
        with rt.model_call("openai", "gpt-4o") as m:
            m.record(response="Your refund of $150 has been processed.")
    rt.flush()
    rt.shutdown()
    assert main(["detectr", "check", str(tmp_path / "traces")]) == 0
    out = capsys.readouterr().out
    assert "capture_content" in out and "RT0" not in out


def test_metrics_and_bench_commands(tmp_path, capsys):
    path = _checkpoint(tmp_path)
    reports = tmp_path / "reports"
    assert main(["detectr", "check", str(path), "--agent-id", "refund", "--out", str(reports / "a.json")]) == 0
    assert main(["detectr", "check", str(path), "--agent-id", "other", "--out", str(reports / "b.json")]) == 0
    capsys.readouterr()
    assert main(["detectr", "metrics", str(reports), "--json"]) == 0
    metrics = json.loads(capsys.readouterr().out)
    assert metrics["total"]["trajectories"] == 1 and set(metrics["agents"]) == {"refund", "other"}
    assert main(["detectr", "metrics", str(reports / "a.json"), "--agent", "refund", "--window", "month"]) == 0
    out = capsys.readouterr().out
    assert "hallucination rate 75.0%" in out and "[2026-10]" in out
    assert main(["detectr", "bench", "--datasets", "agentic", "--out", str(tmp_path / "bench.json")]) == 0
    out = capsys.readouterr().out
    assert "layer0:" in out and "0 false positives" in out
    bench = json.loads((tmp_path / "bench.json").read_text())
    assert bench["datasets"]["agentic"]["layer0"]["recall"] == 1.0
    assert main(["detectr", "bench", "--datasets", "nope"]) == 3
    assert main(["detectr", "bench", "--checkers", "unknown-checker"]) == 3
