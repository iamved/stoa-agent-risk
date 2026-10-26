"""The offline bench: loaders, scoring, Layer 0 summary, suggested weights.
No dataset is downloaded; small files stand in."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stoa.detectr.bench import BenchItem, bench_layer0, bench_text_checkers, load_halubench, load_ragtruth, render_bench, run_bench, suggest_weights
from stoa.detectr.checkers import CheckerManifest
from stoa.detectr.layer0 import Verdict

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROWS = json.loads((FIXTURES / "trajectories.json").read_text(encoding="utf-8"))


class KeywordChecker:
    """Flags an answer when it contains a word the context lacks."""

    manifest = CheckerManifest(id="kw", claim_types={"factual"}, requires_evidence=True, requires_model_internals=False, max_context_tokens=None,
                               est_latency_ms=1, est_cost_per_call=0.001, sync_capable=True, license="MIT")

    def check(self, claim, evidence, *, question=""):
        context = " ".join(e.excerpt for e in evidence).lower()
        for word in ("150", "processed", "2 days", "approved"):
            if word in claim.text.lower() and word not in context:
                return Verdict(claim.id, "unsupported", None, "span", [e.entry_id for e in evidence], f"{word} not in context", confidence=0.9, checker="kw", value=word)
        return Verdict(claim.id, "grounded", None, None, [e.entry_id for e in evidence], "fine", confidence=0.9, checker="kw")


def test_loaders_read_ragtruth_and_halubench_shapes(tmp_path):
    rt = tmp_path / "ragtruth.jsonl"
    rt.write_text("\n".join([
        json.dumps({"id": "a", "response": "The refund of 150 was processed.", "source_info": {"passages": ["Refund of 15 pending."], "question": "refund?"}, "labels": [{"start": 14, "end": 17}]}),
        json.dumps({"id": "b", "response": "The refund of 15 is pending.", "source_info": {"prompt": "Refund of 15 pending."}, "labels": []}),
    ]) + "\n")
    items = load_ragtruth(rt)
    assert [i.hallucinated for i in items] == [True, False] and items[0].spans == [(14, 17)] and items[1].context == ["Refund of 15 pending."]
    hb = tmp_path / "halubench.json"
    hb.write_text(json.dumps([{"id": 1, "question": "q", "passage": "The order is approved.", "answer": "The order is approved.", "label": "PASS"},
                              {"id": 2, "question": "q", "passage": "The order is pending.", "answer": "The order is approved.", "label": "FAIL"}]))
    hb_items = load_halubench(hb, limit=5)
    assert [i.hallucinated for i in hb_items] == [False, True] and hb_items[1].source == "halubench"


def test_text_checker_scoring_and_span_f1():
    items = [
        BenchItem("1", "The refund of 150 was processed.", ["Refund of 15 pending."], "", True, [(14, 17)]),
        BenchItem("2", "The refund of 15 is pending.", ["Refund of 15 pending."], "", False, []),
        BenchItem("3", "The order is approved.", ["The order is pending."], "", True, []),
    ]
    scores = bench_text_checkers(items, {"kw": KeywordChecker()})
    row = scores["kw"].to_dict()
    assert row["items"] == 3 and row["tp"] == 2 and row["fp"] == 0 and row["fn"] == 0 and row["tn"] == 1
    assert row["precision"] == 1.0 and row["recall"] == 1.0 and row["span_f1"] == 1.0
    assert row["latency_ms_mean"] is not None and row["cost_total"] == 0.003


def test_layer0_bench_on_the_fixture_set_and_suggested_weights():
    summary = bench_layer0(ROWS)
    assert summary["recall"] == 1.0 and summary["false_positives"] == 0 and summary["trajectories"] == len(ROWS)
    bench = run_bench(datasets=["agentic", "ragtruth"], checkers={"kw": KeywordChecker()}, agentic=ROWS)
    assert bench["datasets"]["agentic"]["layer0"]["caught"] == bench["datasets"]["agentic"]["layer0"]["injected"]
    assert "skipped" in bench["datasets"]["ragtruth"]
    kw = bench["datasets"]["agentic"]["text_checkers"]["kw"]
    assert kw["items"] > 40
    weights = suggest_weights(bench)
    assert "kw" in weights and 0.05 <= weights["kw"] <= 1.0
    text = render_bench(bench)
    assert "layer0" in text and "ragtruth: skipped" in text
    with pytest.raises(ValueError):
        run_bench(datasets=["nope"], checkers={}, agentic=ROWS)
