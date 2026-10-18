"""stoa.policy.toml: the safe evaluator, loading, decisions, and enforcement through @guard."""

from __future__ import annotations

import json

import pytest

from stoa import runtime as rt
from stoa.runtime.policy import Policy, Rule, StoaDenied, UnknownName, decide, evaluate, load_policy
from stoa.runtime.reader import TraceReader

NS = {"tool": "issue_refund", "args": {"amount": 900, "order_id": "ab12"}, "amount": 900, "side_effect": "payment",
      "approval": {"granted": False, "span_id": None}, "agent": {"declared_tools": ["issue_refund", "waive_fee"], "max_per_action": {"amount": 500}}, "session": {"id": "s1"}}

POLICY = '''
version = 1
[defaults]
mode = "observe"

[[rules]]
id = "refund-cap"
when = 'tool == "issue_refund"'
expr = "amount <= 500"
on_fail = "require_approval"

[[rules]]
id = "payment-needs-approval"
when = 'side_effect == "payment"'
expr = "approval.granted == true"
on_fail = "deny"
enforce = true

[[rules]]
id = "allowlist"
when = "true"
expr = "tool in agent.declared_tools"
on_fail = "observe"
'''


@pytest.fixture(autouse=True)
def _clean_sdk():
    rt.shutdown()
    rt.on_approval(None)
    yield
    rt.shutdown()
    rt.on_approval(None)


def test_evaluator_covers_the_documented_grammar():
    assert evaluate("amount <= 500", NS) is False
    assert evaluate("tool in agent.declared_tools and not approval.granted", NS) is True
    assert evaluate("agent.max_per_action.amount * 2 >= amount", NS) is True
    assert evaluate("args['order_id'] == 'ab12'", NS) is True
    assert evaluate("approval.span_id == null", NS) is True
    assert evaluate("500 < amount < 1000", NS) is True
    assert evaluate("agent.nosuch.deeper == null", NS) is True  # missing attribute reads as None
    assert evaluate("agent.nosuch > 1", NS) is False  # ordering against None is false, not an error


def test_evaluator_refuses_calls_imports_and_unknown_names():
    for bad in ("__import__('os')", "open('x')", "amount.__class__", "lambda: 1", "[x for x in args]"):
        with pytest.raises(ValueError):
            evaluate(bad, NS)
    with pytest.raises(UnknownName):
        evaluate("nosuch > 1", NS)


def test_decide_reports_each_applicable_rule(tmp_path):
    path = tmp_path / "stoa.policy.toml"
    path.write_text(POLICY)
    policy = load_policy(path)
    assert policy.loaded and [r.id for r in policy.rules] == ["refund-cap", "payment-needs-approval", "allowlist"]
    decisions = {d.rule_id: d for d in decide(policy, NS)}
    assert decisions["refund-cap"].decision == "require_approval" and not decisions["refund-cap"].enforced
    assert decisions["payment-needs-approval"].decision == "deny" and decisions["payment-needs-approval"].enforced
    assert decisions["allowlist"].decision == "allow"
    # a rule whose `when` is false is left out; an unknown name is an error, never a raise
    policy.rules.append(Rule("never", 'tool == "other"', "true"))
    policy.rules.append(Rule("broken", "true", "nosuch == 1"))
    decisions = {d.rule_id: d for d in decide(policy, NS)}
    assert "never" not in decisions and decisions["broken"].error == "unknown name nosuch"


def test_loading_is_fail_open(tmp_path):
    assert load_policy(tmp_path / "missing.toml").rules == []
    bad = tmp_path / "stoa.policy.toml"
    bad.write_text("this is not toml = = =")
    with pytest.warns(RuntimeWarning):
        assert load_policy(bad).rules == []
    half = tmp_path / "half.toml"
    half.write_text('[[rules]]\nid = "ok"\nexpr = "true"\n[[rules]]\nid = "nope"\non_fail = "explode"\n[[rules]]\nid = "syntax"\nexpr = "amount <<"\n')
    with pytest.warns(RuntimeWarning):
        policy = load_policy(half)
    assert [r.id for r in policy.rules] == ["ok"] and len(policy.warnings) == 2


def _spans(traces):
    rt.flush()
    return list(TraceReader(traces).spans())


def _registry(tmp_path):
    path = tmp_path / "stoa-registry.json"
    path.write_text(json.dumps({"schema_version": "1.8", "agents": [{"id": "b8f0111742fc", "name": "graph", "symbol": "graph", "path": "a.py", "declared": {"name": "account-actions"}, "tools": [{"name": "issue_refund", "money_action": True}]}]}))
    return path


def test_enforced_deny_raises_and_is_recorded(tmp_path):
    (tmp_path / "stoa.policy.toml").write_text(POLICY)
    rt.configure(str(tmp_path / "traces"), agent_id="account-actions", registry_path=str(_registry(tmp_path)), policy=str(tmp_path / "stoa.policy.toml"))

    calls = []

    @rt.guard(side_effect="payment", limit_field="amount", approval_field="approval")
    def issue_refund(order_id, amount, approval=None):
        calls.append(order_id)
        return "ok"

    with pytest.raises(StoaDenied) as exc:
        issue_refund("o1", 100.0)
    assert exc.value.rule_id == "payment-needs-approval" and calls == []
    span = [x for x in _spans(tmp_path / "traces") if x["kind"] == "action"][0]
    assert span["enforcement"] == "denied" and span["status"] == "error"
    assert span["attrs"]["policy_rules"] == "refund-cap,payment-needs-approval,allowlist"
    assert span["attrs"]["policy_decisions"] == "allow,deny,allow"


def test_observed_rules_record_and_let_the_call_through(tmp_path, monkeypatch):
    (tmp_path / "stoa.policy.toml").write_text(POLICY.replace("enforce = true", "enforce = false"))
    monkeypatch.chdir(tmp_path)
    rt.configure(str(tmp_path / "traces"), agent_id="account-actions", registry_path=str(_registry(tmp_path)))  # found by upward search

    @rt.guard(side_effect="payment", limit_field="amount", approval_field="approval")
    def issue_refund(order_id, amount, approval=None):
        return "ok"

    assert issue_refund("o1", 900.0) == "ok"
    span = [x for x in _spans(tmp_path / "traces") if x["kind"] == "action"][0]
    assert span["enforcement"] == "observed" and span["status"] == "ok"
    assert "refund-cap" in span["attrs"]["policy_rules"] and "require_approval" in span["attrs"]["policy_decisions"]


def test_fail_closed_makes_every_deny_enforced(tmp_path, monkeypatch):
    (tmp_path / "stoa.policy.toml").write_text(POLICY.replace("enforce = true", "enforce = false"))
    monkeypatch.chdir(tmp_path)
    rt.configure(str(tmp_path / "traces"), agent_id="account-actions", registry_path=str(_registry(tmp_path)), fail_open=False)

    @rt.guard(side_effect="payment", limit_field="amount")
    def issue_refund(order_id, amount):
        return "ok"

    with pytest.raises(StoaDenied):
        issue_refund("o1", 10.0)


def test_require_approval_calls_the_hook_and_cites_its_span(tmp_path, monkeypatch):
    (tmp_path / "stoa.policy.toml").write_text(POLICY)
    monkeypatch.chdir(tmp_path)
    rt.configure(str(tmp_path / "traces"), agent_id="account-actions", registry_path=str(_registry(tmp_path)))
    asked = []
    rt.on_approval(lambda tool, args, rule: asked.append((tool, rule)) or True)

    @rt.guard(side_effect="write", limit_field="amount", name="issue_refund")
    def refund(order_id, amount):
        return "ok"

    assert refund("o1", 900.0) == "ok"
    assert asked == [("issue_refund", "refund-cap")]
    spans = _spans(tmp_path / "traces")
    approval = next(x for x in spans if x["kind"] == "approval")
    action = next(x for x in spans if x["kind"] == "action")
    assert action["approval_span_id"] == approval["span_id"] and approval["attrs"]["actor_type"] == "system"
    assert "approval_bypassed" not in action.get("attrs", {}).get("flags", [])


def test_no_policy_means_no_enforcement_fields(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id="b8f0111742fc")

    @rt.guard()
    def f(x):
        return x

    f(1)
    span = _spans(tmp_path / "traces")[0]
    assert "enforcement" not in span and "policy_rules" not in span["attrs"]
