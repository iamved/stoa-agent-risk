"""Layer 0 on the agentic fixture set: every injected failure is caught and
no clean control fires. Plus the canonical fixture, rule by rule."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from stoa.detectr.claims import extract_claims
from stoa.detectr.layer0 import RULE_IDS, Tolerances, Verdict, check_argument_grounding, run_layer0
from stoa.detectr.ledger import Ledger, chain, ledgers_from_spans
from stoa.rules import RULES

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROWS = json.loads((FIXTURES / "trajectories.json").read_text(encoding="utf-8"))


def _fired(verdicts: list[Verdict]) -> set[tuple[str, str | None]]:
    return {(v.rule_id, v.subcategory) for v in verdicts if v.label in ("unsupported", "contradicted")}


def test_fixture_set_is_large_enough_and_current():
    assert len(ROWS) >= 40
    assert {row["scenario"] for row in ROWS} == {"refund", "kyc", "support"}
    module = runpy.run_path(str(FIXTURES / "build.py"))
    fresh = json.dumps(module["build"](), indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    assert fresh == (FIXTURES / "trajectories.json").read_text(encoding="utf-8"), "run python tests/detectr/fixtures/build.py"


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_layer0_matches_expected_rules_exactly(row):
    ledger = Ledger.from_dict(row["ledger"])
    verdicts = run_layer0(ledger, extract_claims(ledger))
    expected = {(e["rule_id"], e.get("subcategory")) for e in row["expected"]}
    assert _fired(verdicts) == expected, row["note"]
    for verdict in verdicts:
        assert verdict.label in ("grounded", "unsupported", "contradicted", "unverifiable")
        if verdict.label in ("grounded", "contradicted"):
            assert verdict.evidence or verdict.subcategory in ("phantom",), verdict
        for entry_id in verdict.evidence:
            assert any(e.id == entry_id for e in ledger.entries)


def test_recall_and_false_positive_rate_on_the_set():
    injected = fired = false_positive = 0
    for row in ROWS:
        ledger = Ledger.from_dict(row["ledger"])
        got = _fired(run_layer0(ledger, extract_claims(ledger)))
        expected = {(e["rule_id"], e.get("subcategory")) for e in row["expected"]}
        injected += len(expected)
        fired += len(got & expected)
        false_positive += len(got - expected)
    assert injected >= 30
    assert fired == injected, "recall below 100%"
    assert false_positive == 0


def test_canonical_fixture_rule_by_rule():
    row = next(r for r in ROWS if r["id"] == "refund-canonical")
    ledger = Ledger.from_dict(row["ledger"])
    verdicts = run_layer0(ledger, extract_claims(ledger))
    by_rule = {}
    for v in verdicts:
        if v.rule_id:
            by_rule.setdefault(v.rule_id, []).append(v)
    assert "RT009" not in by_rule, "refund.issue was called, so the action is not phantom"
    fidelity = sorted((v.subcategory, v.value, v.expected) for v in by_rule["RT010"])
    assert fidelity == [("numerical", "150", "15"), ("status", "completed", "pending")]
    promise = by_rule["RT011"][0]
    assert promise.label == "unsupported" and promise.value == "P2D"
    argument = by_rule["RT012"]
    assert [(v.label, v.field, v.value) for v in argument] == [("unsupported", "approval_id", "APR-4471")]
    grounded = [v for v in verdicts if v.label == "grounded"]
    assert any(v.field == "amount" and v.value == "150" for v in grounded), "amount 150 traces to the order lookup"
    result = next(e for e in ledger.entries if e.kind == "tool_result" and e.tool_name == "refund.issue")
    assert all(result.id in v.evidence for v in by_rule["RT010"])


def test_rules_are_registered_with_the_scanner():
    for rule_id in RULE_IDS.values():
        assert rule_id in RULES and RULES[rule_id].category == "hallucination" and RULES[rule_id].gateable is False


def test_schema_enforcement_and_tolerances():
    ledger = Ledger(trajectory_id="t", agent_id="a", model_id=None, built_from="sdk")
    ledger.add("user_input", payload="Refund order 8812 for 150.004 USD on 2026-10-24")
    ledger.add("tool_call", tool_name="refund.issue", payload={"order_id": 8812, "amount": "150", "when": "2026-10-25"}, meta={"call_id": "c1"})
    claims = extract_claims(ledger)
    schema = {"refund.issue": {"required": ["order_id", "approval_id"], "fields": {"amount": "number"}}}
    verdicts = check_argument_grounding(claims[0], ledger, None, Tolerances(), schema)
    schema_hits = sorted(v.field for v in verdicts if v.subcategory == "schema")
    assert schema_hits == ["amount", "approval_id"]
    grounded = {v.field: v.label for v in verdicts if v.subcategory != "schema"}
    assert grounded == {"order_id": "grounded", "amount": "grounded", "when": "grounded"}  # 150 within a cent, a day of timezone drift
    strict = check_argument_grounding(claims[0], ledger, None, Tolerances(date_days=0))
    # Without the day of tolerance the date traces to nothing; the user's text names no field, so it is unsupported rather than contradicted.
    assert any(v.field == "when" and v.label == "unsupported" for v in strict)


def test_chained_ledger_grounds_handoff_values():
    spans = []
    from stoa.runtime.spans import build_span

    def span(i, kind, agent, **kw):
        base = dict(trace_id="t", span_id=f"s{i}", parent_span_id=None, kind=kind, agent_id=agent, session_id="s", start_ts=f"2026-10-24T09:00:0{i}.000Z",
                    end_ts=f"2026-10-24T09:00:0{i}.000Z", status="ok", redaction="content")
        base.update(kw)
        return build_span(**base)

    spans.append(span(1, "agent_run", "A", attrs={"user_inputs": json.dumps(["Pay invoice INV-100 for 40 EUR"])}))
    spans.append(span(2, "delegation", "A", from_agent_id="A", to_agent_id="B", attrs={"message": "Please pay INV-100"}))
    spans.append(span(3, "action", "B", tool="pay", attrs={"args": json.dumps({"invoice": "INV-100", "amount": 40})}))
    store = {l.trajectory_id: l for l in ledgers_from_spans(spans)}
    b = store["s:B"]
    alone = run_layer0(b, extract_claims(b))
    assert {(v.rule_id, v.field) for v in alone if v.label == "unsupported"} == {("RT012", "amount")}
    chained = run_layer0(b, extract_claims(b), entries=chain(b, store))
    assert all(v.label == "grounded" for v in chained)
