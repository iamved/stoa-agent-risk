"""Checker interface and adapters, with fake models. No weights are
downloaded in tests; the real libraries are optional extras."""

from __future__ import annotations

import sys
import types

import pytest

from stoa.detectr.checkers import CheckerUnavailable, available_checkers, load_checker
from stoa.detectr.checkers.deepeval import DeepEvalJudge, SameFamilyRefusal, model_family
from stoa.detectr.checkers.hhem import HHEMChecker
from stoa.detectr.checkers.lettucedetect import LettuceDetectChecker
from stoa.detectr.checkers.selfcheck import SelfCheckStub
from stoa.detectr.claims import extract_claims
from stoa.detectr.evidence import resolve_evidence
from stoa.detectr.ledger import Ledger


def _claim_and_evidence():
    ledger = Ledger(trajectory_id="t", agent_id="a", model_id="gpt-4o", built_from="sdk")
    ledger.add("user_input", payload="Please refund my order 8812")
    ledger.add("tool_call", tool_name="refund.issue", payload={"order_id": 8812, "amount": 150}, meta={"call_id": "c1"})
    ledger.add("tool_result", tool_name="refund.issue", payload={"status": "pending", "amount": 15.0}, meta={"call_id": "c1", "status": "ok"})
    ledger.add("agent_output", payload="Your refund of $150 has been processed.")
    claims = extract_claims(ledger)
    said = claims[-1]
    return said, resolve_evidence(said, ledger)


def test_registry_lists_builtins_with_manifests():
    specs = available_checkers()
    assert set(specs) >= {"lettucedetect", "hhem", "deepeval", "selfcheck"}
    assert specs["lettucedetect"].manifest.sync_capable is True and specs["lettucedetect"].manifest.license == "MIT"
    assert specs["deepeval"].manifest.sync_capable is False and specs["hhem"].manifest.sync_capable is False
    assert specs["selfcheck"].manifest.implemented is False
    assert all(spec.error is None for spec in specs.values())
    with pytest.raises(KeyError):
        load_checker("nope")
    row = specs["lettucedetect"].manifest.to_dict()
    assert row["id"] == "lettucedetect" and "result" in row["claim_types"]


def test_lettucedetect_adapter_maps_spans_to_verdicts():
    claim, evidence = _claim_and_evidence()

    class FakeDetector:
        def __init__(self):
            self.calls = []

        def predict(self, *, context, question, answer, output_format):
            self.calls.append((context, question, answer, output_format))
            if "$150" in answer:
                return [{"start": 15, "end": 19, "text": "$150", "confidence": 0.93, "category": "contradiction", "subcategory": "numerical"},
                        {"start": 0, "end": 4, "text": "Your", "confidence": 0.2}]
            return []

    fake = FakeDetector()
    checker = LettuceDetectChecker(detector=fake, min_confidence=0.5)
    verdict = checker.check(claim, evidence, question="Please refund my order 8812")
    assert verdict.label == "contradicted" and verdict.subcategory == "numerical" and verdict.confidence == 0.93 and verdict.checker == "lettucedetect"
    assert verdict.value == "$150" and verdict.evidence == [e.entry_id for e in evidence]
    context, question, answer, fmt = fake.calls[0]
    assert fmt == "spans" and answer == claim.text and question == "Please refund my order 8812"
    assert any("pending" in c for c in context) and all(len(c) < 400 for c in context)  # the result, not the whole trace
    assert checker.check(claim, [], question="").label == "unverifiable"
    claim.text = "Thanks for waiting."
    assert checker.check(claim, evidence).label == "grounded"


def test_lettucedetect_refuses_eurobert_and_reports_missing_library(monkeypatch):
    with pytest.raises(CheckerUnavailable):
        LettuceDetectChecker(model_path="KRLabsOrg/lettucedect-210m-eurobert-de-v1")
    monkeypatch.setitem(sys.modules, "lettucedetect", None)
    monkeypatch.setitem(sys.modules, "lettucedetect.models", None)
    monkeypatch.setitem(sys.modules, "lettucedetect.models.inference", None)
    claim, evidence = _claim_and_evidence()
    with pytest.raises(CheckerUnavailable, match="hallucination"):
        LettuceDetectChecker().check(claim, evidence)


def test_lettucedetect_constructs_the_real_detector_with_pinned_models(monkeypatch):
    seen = {}

    class HallucinationDetector:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def predict(self, **kwargs):
            return []

    module = types.ModuleType("lettucedetect.models.inference")
    module.HallucinationDetector = HallucinationDetector
    monkeypatch.setitem(sys.modules, "lettucedetect", types.ModuleType("lettucedetect"))
    monkeypatch.setitem(sys.modules, "lettucedetect.models", types.ModuleType("lettucedetect.models"))
    monkeypatch.setitem(sys.modules, "lettucedetect.models.inference", module)
    claim, evidence = _claim_and_evidence()
    LettuceDetectChecker().check(claim, evidence)
    assert seen == {"method": "transformer", "model_path": "KRLabsOrg/lettucedect-v2-mmbert-base", "taxonomy_head": "KRLabsOrg/lettucedect-v2-taxonomy-head"}


def test_hhem_adapter_scores_consistency():
    claim, evidence = _claim_and_evidence()

    class FakeModel:
        def predict(self, pairs):
            premise, hypothesis = pairs[0]
            assert "pending" in premise and hypothesis == claim.text
            return [0.12]

    verdict = HHEMChecker(model=FakeModel()).check(claim, evidence)
    assert verdict.label == "unsupported" and verdict.subcategory == "inconsistent" and round(verdict.confidence, 2) == 0.88 and verdict.checker == "hhem"

    class Consistent:
        def predict(self, pairs):
            return [0.97]

    assert HHEMChecker(model=Consistent()).check(claim, evidence).label == "grounded"
    assert HHEMChecker(model=Consistent()).check(claim, []).label == "unverifiable"
    HHEMChecker.record_license("Apache-2.0 (model card)")
    assert HHEMChecker.MANIFEST.license.startswith("Apache")


def test_deepeval_judge_refuses_same_family_and_grades_otherwise():
    assert model_family("gpt-4o") == "gpt" and model_family("claude-sonnet-4") == "claude" and model_family("meta-llama/Llama-3-70b") == "llama"
    with pytest.raises(SameFamilyRefusal):
        DeepEvalJudge(judge_model="gpt-4.1", agent_model="gpt-4o")
    claim, evidence = _claim_and_evidence()

    class FakeMetric:
        score = 0.3
        reason = "The refund amount does not match the retrieval context."

        def measure(self, case):
            self.case = case

    judge = DeepEvalJudge(judge_model="claude-sonnet-4", agent_model="gpt-4o", metric=FakeMetric())
    verdict = judge.check(claim, evidence, question="refund")
    assert verdict.label == "unsupported" and verdict.subcategory == "judged" and verdict.detail.startswith("The refund amount") and verdict.checker == "deepeval"
    assert DeepEvalJudge.MANIFEST.sync_capable is False


def test_selfcheck_is_a_registered_stub():
    claim, evidence = _claim_and_evidence()
    with pytest.raises(NotImplementedError):
        SelfCheckStub().check(claim, evidence)
