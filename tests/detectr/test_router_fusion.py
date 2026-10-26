"""Routing, fusion, findings, calibration and the pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stoa.detectr.calibration import Label, LabelTable, fit
from stoa.detectr.checkers import CheckerManifest, CheckerUnavailable
from stoa.detectr.claims import extract_claims
from stoa.detectr.fusion import combine, fuse, to_findings
from stoa.detectr.layer0 import Verdict, run_layer0
from stoa.detectr.ledger import Ledger
from stoa.detectr.pipeline import check_ledger
from stoa.detectr.router import Router, RouterConfig, consequence_class, find_config, sampled

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROWS = {r["id"]: r for r in json.loads((FIXTURES / "trajectories.json").read_text(encoding="utf-8"))}


def _canonical() -> Ledger:
    return Ledger.from_dict(ROWS["refund-canonical"]["ledger"])


class FakeChecker:
    def __init__(self, name, label="unsupported", confidence=0.9, delay=0.0, sync=True, types=None, fail=False):
        self.manifest = CheckerManifest(id=name, claim_types=set(types or {"factual", "result", "commitment", "reasoning", "action"}), requires_evidence=True,
                                        requires_model_internals=False, max_context_tokens=512, est_latency_ms=1, est_cost_per_call=0.0,
                                        sync_capable=sync, license="MIT")
        self.name, self.label, self.confidence, self.delay, self.fail = name, label, confidence, delay, fail
        self.calls = []

    def check(self, claim, evidence, *, question=""):
        self.calls.append(claim.id)
        if self.fail:
            raise RuntimeError("boom")
        return Verdict(claim.id, self.label, None, "span", [e.entry_id for e in evidence], f"{self.name} says {self.label}", confidence=self.confidence, checker=self.name)


def test_config_parses_lanes_checkers_weights_and_tolerances(tmp_path):
    path = tmp_path / "stoa.detectr.toml"
    path.write_text('''
[detectr]
extractor = "rules"
latency_budget_ms = 80
threshold = 0.6
[detectr.lanes.default]
checkers = ["lettucedetect"]
sample_rate = 0.5
[detectr.lanes.payment]
checkers = ["lettucedetect", "hhem"]
sync = true
sample_rate = 1.0
[detectr.lanes.bogus]
checkers = ["x"]
[detectr.checkers.lettucedetect]
min_confidence = 0.7
[detectr.weights]
lettucedetect = 0.6
hhem = 0.4
[detectr.thresholds]
"meridian-refund" = 0.75
[detectr.tolerances]
money_abs = "0.05"
date_days = 2
''')
    config = RouterConfig.load(path)
    assert config.default.checkers == ["lettucedetect"] and config.default.sample_rate == 0.5 and config.default.latency_budget_ms == 80
    payment = config.lane("payment")
    assert payment.checkers == ["lettucedetect", "hhem"] and payment.sync is True and payment.sample_rate == 1.0 and payment.latency_budget_ms == 80
    assert config.lane("read") is config.default
    assert config.problems == ["lanes.bogus: unknown consequence class; expected one of ('payment', 'delete', 'external_send', 'write', 'read', 'unknown')"]
    assert config.checker_config == {"lettucedetect": {"min_confidence": 0.7}} and config.weights == {"lettucedetect": 0.6, "hhem": 0.4}
    assert config.threshold_for("meridian-refund") == 0.75 and config.threshold_for("other") == 0.6
    assert str(config.tolerances.money_abs) == "0.05" and config.tolerances.date_days == 2
    assert find_config(tmp_path) == path and find_config(tmp_path.parent.parent.parent.parent) in (None, find_config(tmp_path.parent.parent.parent.parent))
    broken = RouterConfig.load(tmp_path / "missing.toml")
    assert broken.problems and broken.default.checkers == []


def test_consequence_class_from_trace_or_registry():
    ledger = _canonical()
    assert consequence_class(ledger) == "unknown"
    for e in ledger.entries:
        if e.kind == "tool_call" and e.tool_name == "refund.issue":
            e.meta["side_effect"] = "payment"
        if e.kind == "tool_call" and e.tool_name == "orders.get":
            e.meta["side_effect"] = "read"
    assert consequence_class(ledger) == "payment"
    claims = extract_claims(ledger)
    lookup = next(c for c in claims if c.tool_name == "orders.get")
    assert consequence_class(ledger, lookup) == "read"
    fresh = _canonical()
    registry = {"agents": [{"id": "refund", "name": "meridian-refund", "tools": [{"name": "refund.issue", "side_effect": "payment"}]}]}
    assert consequence_class(fresh, registry=registry) == "payment"


def test_sampling_is_deterministic_and_proportional():
    assert sampled("c1", "t", 1.0) and not sampled("c1", "t", 0.0)
    hits = sum(1 for i in range(2000) if sampled(f"c{i}", "t", 0.25))
    assert 400 < hits < 600
    assert sampled("c7", "t", 0.3) == sampled("c7", "t", 0.3)


def test_router_runs_layer0_always_and_external_per_lane():
    ledger = _canonical()
    claims = extract_claims(ledger)
    fake = FakeChecker("fake", label="unsupported", confidence=0.8)
    config = RouterConfig.from_dict({"detectr": {"lanes": {"default": {"checkers": ["fake"], "sync": True}}}})
    router = Router(config, checkers={"fake": fake})
    result = router.run(ledger, claims)
    assert any(v.rule_id == "RT012" for v in result.layer0)
    # text claims with evidence only: the tool call claim is never sent to a text checker,
    # and a claim with no resolvable evidence is unverifiable without a call
    with_evidence = {cid for cid, ev in result.evidence.items() if ev}
    assert set(fake.calls) == with_evidence == {c.id for c in claims if c.source == "agent_output" and c.text.startswith("Your refund")}
    assert all(v.checker == "fake" for v in result.external) and result.consequence == "unknown"
    assert {v.label for v in result.external if v.claim_id not in with_evidence} == {"unverifiable"}
    assert "fake" in result.timings_ms and result.demoted == [] and result.warnings == []


def test_sync_budget_demotes_a_slow_checker_once():
    ledger = _canonical()
    claims = extract_claims(ledger)
    slow = FakeChecker("slow")
    ticks = iter([0.0, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0])  # first call takes 500 ms
    config = RouterConfig.from_dict({"detectr": {"latency_budget_ms": 100, "lanes": {"default": {"checkers": ["slow"], "sync": True}}}})
    router = Router(config, checkers={"slow": slow}, clock=lambda: next(ticks, 1.0))
    result = router.run(ledger, claims, deferred=False)
    assert result.demoted == ["slow"] and len([w for w in result.warnings if "demoted" in w]) == 1
    assert len(slow.calls) == 1 and len(result.deferred_plan) >= 1
    again = router.run(ledger, claims, deferred=False)
    assert again.external == [] and len(again.deferred_plan) == len([c for c in claims if c.source == "agent_output"])


def test_router_reports_unavailable_and_failing_checkers():
    ledger = _canonical()
    claims = extract_claims(ledger)

    def loader(name, **config):
        raise CheckerUnavailable(f"{name} is not installed")

    config = RouterConfig.from_dict({"detectr": {"lanes": {"default": {"checkers": ["lettucedetect", "boom"]}}}})
    router = Router(config, checkers={"boom": FakeChecker("boom", fail=True)}, loader=loader)
    result = router.run(ledger, claims)
    assert result.skipped == ["lettucedetect"] and any("not installed" in w for w in result.warnings)
    assert result.external and all(v.label == "unverifiable" for v in result.external)
    assert any(v.subcategory == "checker_error" and "boom" in v.detail for v in result.external)


def test_fusion_layer0_contradiction_wins_and_weights_combine():
    ledger = _canonical()
    claims = extract_claims(ledger)
    layer0 = run_layer0(ledger, claims)
    said = next(c for c in claims if c.text.startswith("Your refund"))
    promise = next(c for c in claims if c.type == "commitment")
    external = [Verdict(said.id, "grounded", None, None, ["e0006"], "looks fine", confidence=0.9, checker="a"),
                Verdict(promise.id, "unsupported", None, "span", ["e0001"], "2 days unsupported", confidence=0.7, checker="a"),
                Verdict(promise.id, "grounded", None, None, ["e0001"], "fine", confidence=0.6, checker="b")]
    fused = {f.claim_id: f for f in fuse(claims, layer0, external, weights={"a": 0.75, "b": 0.25})}
    assert fused[said.id].label == "contradicted" and fused[said.id].probability == 1.0 and fused[said.id].rule_id == "RT010"
    p = fused[promise.id].probability
    assert fused[promise.id].label == "unsupported" and fused[promise.id].rule_id == "RT011"
    assert round(p, 3) == round(0.5 * 0.85 + 0.5 * (0.75 * 0.7 + 0.25 * 0.4), 3)
    assert combine([], {}) is None and combine([Verdict("x", "unverifiable", None, None, [], "", checker="a")], {}) is None
    call = next(c for c in claims if c.source == "tool_call" and c.tool_name == "refund.issue")
    assert fused[call.id].label == "unsupported" and fused[call.id].rule_id == "RT012" and fused[call.id].blast_radius == 1
    assert fused[said.id].tainted and fused[said.id].tainted_by == [call.id]


def test_fusion_external_only_and_unverifiable():
    ledger = Ledger(trajectory_id="t", agent_id="a", model_id=None, built_from="sdk")
    ledger.add("retrieved_doc", payload="Our shop is open on weekdays.")
    ledger.add("agent_output", payload="The shop is open every day. Thanks for asking!")
    claims = extract_claims(ledger)
    layer0 = run_layer0(ledger, claims)
    assert all(v.label != "contradicted" for v in layer0)
    external = [Verdict(claims[0].id, "contradicted", None, "contradiction", ["e0001"], "weekdays only", confidence=0.9, checker="lettucedetect")]
    fused = fuse(claims, layer0, external, threshold=0.5)
    assert fused[0].label == "contradicted" and fused[0].rule_id == "RT010" and fused[0].probability == 0.9
    assert fused[1].label == "unverifiable" and fused[1].rule_id is None
    low = fuse(claims, layer0, [Verdict(claims[0].id, "unsupported", None, "span", ["e0001"], "meh", confidence=0.3, checker="x")])
    assert low[0].label == "grounded" and low[0].probability == 0.3


def test_findings_follow_the_rt_shape_and_redact():
    ledger = _canonical()
    for e in ledger.entries:
        if e.kind == "agent_output":
            e.raw_payload = e.raw_payload + " Use key sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890 if asked."
            e.text_view = e.raw_payload
    claims = extract_claims(ledger)
    layer0 = run_layer0(ledger, claims)
    fused = fuse(claims, layer0, [])
    findings = to_findings(fused, claims, ledger, agent={"path": "src/refund.py", "evidence": [{"line": 12}]}, severity_overrides={"RT011": "low"})
    rules = sorted(f["rule_id"] for f in findings)
    assert rules == ["RT010", "RT011", "RT012"]
    for f in findings:
        assert set(f) >= {"fingerprint", "rule_id", "title", "category", "severity", "confidence", "path", "line", "snippet", "remediation", "message", "detectr"}
        assert f["category"] == "hallucination" and f["path"] == "src/refund.py" and f["line"] == 12 and len(f["fingerprint"]) == 16
        assert "sk-live-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890" not in json.dumps(f)
        assert all(len(x["hash"]) == 64 for x in f["detectr"]["evidence"])
    fidelity = next(f for f in findings if f["rule_id"] == "RT010")
    assert sorted(i["subcategory"] for i in fidelity["detectr"]["issues"]) == ["numerical", "status"]
    assert next(f for f in findings if f["rule_id"] == "RT011")["severity"] == "low"
    assert next(f for f in findings if f["rule_id"] == "RT012")["severity"] == "critical"


def test_pipeline_report_is_serializable_and_counts_unverifiable_apart():
    report = check_ledger(_canonical())
    doc = report.to_dict()
    json.dumps(doc)
    assert doc["schema"] == "stoa-detectr-report/0.1" and doc["counts"] == {"grounded": 1, "unsupported": 2, "contradicted": 1, "unverifiable": 0}
    assert [f["rule_id"] for f in doc["findings"]] == ["RT012", "RT010", "RT011"]
    redacted = Ledger(trajectory_id="r", agent_id="a", model_id=None, built_from="sdk")
    redacted.add("agent_output", payload=None, content_captured=False, hash_override="ab" * 32)
    doc2 = check_ledger(redacted).to_dict()
    assert doc2["redacted"] is True and doc2["findings"] == [] and any("capture_content" in w for w in doc2["warnings"])


def test_label_table_and_calibration_fit(tmp_path):
    table = LabelTable(tmp_path / "labels.jsonl")
    with pytest.raises(ValueError):
        table.add(Label("c1", "t", "a", "guess", True))
    rows = []
    for i in range(24):
        real = i % 2 == 0
        probability = 0.8 + (i % 5) * 0.03 if real else 0.3 + (i % 4) * 0.04
        rows.append(Label(f"c{i}", "t", "refund", "human", real, probability=probability, checker_scores={"good": probability, "coin": 0.5 + (0.1 if i % 3 == 0 else -0.1)}))
    for row in rows:
        table.add(row)
    loaded = table.load()
    assert len(loaded) == 24 and loaded[0].ts and loaded[0].source == "human"
    result = fit(loaded)
    assert result.labels_used == 24 and result.per_agent_counts == {"refund": 24}
    assert 0.5 <= result.thresholds["refund"] <= 0.8
    assert result.weights["good"] == 1.0 and result.weights["coin"] < 0.4
    few = fit(loaded[:4])
    assert few.thresholds == {} and few.weights == {} and any("threshold stays" in n for n in few.notes)
    json.dumps(result.to_dict())
