"""guard / session / model_call aliases, registry link, and per-span flags."""

from __future__ import annotations

import asyncio
import json

import pytest

from stoa import runtime as rt
from stoa.runtime.flags import FlagEngine
from stoa.runtime.registry import load_registry_facts
from stoa.runtime.reader import TraceReader

AGENT = "b8f0111742fc"


@pytest.fixture(autouse=True)
def _clean_sdk():
    rt.shutdown()
    yield
    rt.shutdown()


def _registry(tmp_path):
    path = tmp_path / "stoa-registry.json"
    path.write_text(json.dumps({
        "schema_version": "1.8", "agents": [{
            "id": AGENT, "name": "graph", "symbol": "graph", "display_name": "account_actions_agent·graph",
            "path": "code/agents/account_actions_agent.py",
            "declared": {"name": "account-actions", "economic_authority": {"max_per_action": {"amount": 500, "currency": "USD"}}},
            "tools": [{"name": "issue_refund", "money_action": True}, {"name": "waive_fee", "money_action": True}, {"name": "update_contact_info", "money_action": False}],
        }],
    }))
    return path


def _spans(tmp_path):
    rt.flush()
    reader = TraceReader(tmp_path / "traces")
    return list(reader.spans())


def test_registry_facts_resolve_names_tools_and_limits(tmp_path):
    facts = load_registry_facts(_registry(tmp_path))
    assert facts.found and facts.registry_hash
    agent = facts.for_agent("account-actions")
    assert agent and agent.agent_id == AGENT and agent.max_per_action == {"amount": 500.0, "currency": "USD"}
    assert agent.money_tools == frozenset({"issue_refund", "waive_fee"})
    assert load_registry_facts(tmp_path / "missing.json").found is False


def test_guard_records_tool_side_effect_amount_and_approval(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id="account-actions", registry_path=str(_registry(tmp_path)))

    @rt.guard(side_effect="payment", limit_field="amount", approval_field="approval")
    def issue_refund(order_id: str, amount: float, approval: str | None = None):
        """Refund an order."""
        return "ok"

    assert issue_refund.__doc__ == "Refund an order."
    with rt.session(user_ref="cust-1") as s:
        assert issue_refund("o1", 900.0) == "ok"
        ok = s.approval("ops@meridian.example", "slack", granted=True, latency_ms=800)
        assert issue_refund("o2", 120.0, approval=ok) == "ok"
    spans = _spans(tmp_path)
    actions = [x for x in spans if x["kind"] == "action"]
    assert [a["tool"] for a in actions] == ["issue_refund", "issue_refund"]
    assert actions[0]["agent_id"] == AGENT  # the declared name resolved to the registry id
    assert actions[0]["amount"] == {"amount": 900.0, "currency": "USD"}
    assert actions[0]["attrs"]["side_effect"] == "payment" and actions[0]["attrs"]["limit_field"] == "amount"
    assert set(actions[0]["attrs"]["flags"]) == {"approval_bypassed", "over_declared_limit"}
    approval = next(x for x in spans if x["kind"] == "approval")
    assert actions[1]["approval_span_id"] == approval["span_id"]
    assert "flags" not in actions[1].get("attrs", {})
    assert "ops@meridian.example" not in json.dumps(spans)  # actor never in clear
    assert len({x["session_id"] for x in spans}) == 1
    run = next(x for x in spans if x["kind"] == "agent_run")
    assert run["attrs"]["user_ref"] != "cust-1"


def test_guard_works_on_async_functions_and_errors_propagate(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)

    @rt.guard(side_effect="external_send")
    async def send_email(to: str):
        raise RuntimeError("smtp down")

    with pytest.raises(RuntimeError):
        asyncio.run(send_email("x@y"))
    span = _spans(tmp_path)[0]
    assert span["kind"] == "action" and span["status"] == "error" and span["tool"] == "send_email"


def test_model_call_records_tokens_and_cost_never_content(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)
    with rt.model_call("openai", "gpt-4o") as m:
        m.record(tokens_in=120, tokens_out=30, cost_usd=0.0021, tool_calls_requested=["issue_refund"])
    span = _spans(tmp_path)[0]
    assert span["kind"] == "llm_call" and span["cost"] == {"amount": 0.0021, "currency": "USD"}
    assert span["attrs"]["gen_ai.usage.input_tokens"] == 120 and span["attrs"]["tool_calls_requested"] == "issue_refund"


def test_undeclared_tool_and_no_registry_flags(tmp_path, tmp_path_factory, monkeypatch):
    rt.configure(str(tmp_path / "traces"), agent_id="account-actions", registry_path=str(_registry(tmp_path)))

    @rt.guard(side_effect="read")
    def lookup_balance(account: str):
        return 1

    lookup_balance("a")
    assert _spans(tmp_path)[0]["attrs"]["flags"] == ["undeclared_tool"]
    rt.shutdown()
    elsewhere = tmp_path_factory.mktemp("elsewhere")  # no registry above here
    monkeypatch.chdir(elsewhere)
    rt.configure(str(elsewhere / "traces2"), agent_id=AGENT)
    with rt.stoa_span("action", tool="x"):
        pass
    rt.flush()
    first = list(TraceReader(elsewhere / "traces2").spans())[0]
    assert "no_registry" in first["attrs"]["flags"]


def test_session_flag_lands_on_the_session_span(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)
    with rt.session() as s:
        s.flag("manual_review", {"why": "vip"})
    run = _spans(tmp_path)[0]
    assert run["kind"] == "agent_run" and "manual_review" in run["attrs"]["flags"]
    assert "flag_manual_review_sha256" in run["attrs"] and "vip" not in json.dumps(run)


def test_unconfigured_aliases_are_passthroughs():
    @rt.guard()
    def f(x):
        return x * 2

    with rt.session() as s:
        s.approval("a", "b")
        assert f(2) == 4
    with rt.model_call("p", "m") as m:
        m.record(tokens_in=1)


def _span(**kw):
    base = {"kind": "action", "agent_id": "a", "trace_id": "t", "span_id": "s", "start_ts": "2026-08-01T10:00:00.000Z", "end_ts": "2026-08-01T10:00:01.000Z", "status": "ok", "attrs": {}}
    base.update(kw)
    return base


def test_flag_engine_burst_repeat_failure_and_changes():
    engine = FlagEngine(burst_threshold=2)
    engine.compute(_span(tool="t"))  # no_registry on the very first span
    assert engine.compute(_span(tool="t", end_ts="2026-08-01T10:00:02.000Z")) == []
    assert "burst" in engine.compute(_span(tool="t", end_ts="2026-08-01T10:00:03.000Z"))
    for i in range(2):
        assert "repeat_failure" not in engine.compute(_span(tool="f", status="error"))
    assert "repeat_failure" in engine.compute(_span(tool="f", status="error"))
    # model change across sessions, not within one
    assert engine.compute(_span(kind="llm_call", model="gpt-4o", session_id="s1")) == []
    assert engine.compute(_span(kind="llm_call", model="gpt-4o-mini", session_id="s2")) == ["model_changed"]
    assert engine.compute(_span(tool="u", integration="stripe", session_id="s2")) == []
    assert "integration_changed" in engine.compute(_span(tool="u", integration="adyen", session_id="s3"))


def test_flag_engine_new_counterparty_and_approval_in_trace():
    engine = FlagEngine()
    engine.compute(_span(kind="approval", trace_id="t1", span_id="ap"))
    paid = engine.compute(_span(tool="pay", trace_id="t1", attrs={"side_effect": "payment"}), counterparty="c1")
    assert "approval_bypassed" not in paid and "new_counterparty" not in paid
    assert "new_counterparty" in engine.compute(_span(tool="pay", trace_id="t1", attrs={"side_effect": "payment"}), counterparty="c2")
    assert "approval_bypassed" in engine.compute(_span(tool="pay", trace_id="t2", attrs={"side_effect": "payment"}))


def test_flag_engine_never_raises():
    assert FlagEngine().compute({"kind": "action", "attrs": None, "amount": "bad"}) in ([], ["no_registry"])
