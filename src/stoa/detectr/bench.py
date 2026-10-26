"""Offline benchmark: precision, recall, span F1, latency and cost per
checker on RAGTruth and HaluBench subsets the user has downloaded, and on
the agentic fixture set. Runs on demand, never in CI, and never downloads.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Callable, Iterable

from .claims import Claim, extract_claims
from .evidence import Evidence
from .layer0 import Verdict, run_layer0
from .ledger import Ledger

BENCH_SCHEMA = "stoa-detectr-bench/0.1"
DATASETS = ("agentic", "ragtruth", "halubench")


@dataclass
class BenchItem:
    """One labeled example: a claim text, its context passages, whether it
    is hallucinated, and the labeled spans (start, end) when known."""

    id: str
    answer: str
    context: list[str]
    question: str
    hallucinated: bool
    spans: list[tuple[int, int]] = dc_field(default_factory=list)
    source: str = "agentic"


def load_ragtruth(path: str | Path, *, limit: int | None = None) -> list[BenchItem]:
    """RAGTruth response-level JSONL: ``response``, ``source_info`` (with
    ``prompt`` or ``passages``), ``labels`` as a list of ``{start, end}``."""
    items: list[BenchItem] = []
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        row = json.loads(line)
        source = row.get("source_info") or {}
        passages = source.get("passages") or source.get("prompt") or row.get("context") or ""
        context = passages if isinstance(passages, list) else [str(passages)]
        labels = row.get("labels") or []
        spans = [(int(l["start"]), int(l["end"])) for l in labels if isinstance(l, dict) and "start" in l and "end" in l]
        items.append(BenchItem(str(row.get("id") or i), str(row.get("response") or row.get("answer") or ""), [str(c) for c in context],
                               str(source.get("question") or row.get("question") or ""), bool(spans) or bool(row.get("hallucination")), spans, "ragtruth"))
        if limit and len(items) >= limit:
            break
    return items


def load_halubench(path: str | Path, *, limit: int | None = None) -> list[BenchItem]:
    """HaluBench JSONL or JSON list: ``question``, ``passage``, ``answer``,
    ``label`` (PASS or FAIL)."""
    text = Path(path).read_text(encoding="utf-8")
    rows = json.loads(text) if text.lstrip().startswith("[") else [json.loads(l) for l in text.splitlines() if l.strip()]
    items: list[BenchItem] = []
    for i, row in enumerate(rows):
        label = str(row.get("label") or "").upper()
        items.append(BenchItem(str(row.get("id") or i), str(row.get("answer") or ""), [str(row.get("passage") or row.get("context") or "")],
                               str(row.get("question") or ""), label == "FAIL", [], "halubench"))
        if limit and len(items) >= limit:
            break
    return items


def agentic_items(trajectories: Iterable[dict]) -> list[tuple[Ledger, set[tuple[str, str | None]]]]:
    out = []
    for row in trajectories:
        out.append((Ledger.from_dict(row["ledger"]), {(e["rule_id"], e.get("subcategory")) for e in row["expected"]}))
    return out


def _span_f1(predicted: list[tuple[int, int]], gold: list[tuple[int, int]]) -> float | None:
    if not gold and not predicted:
        return None
    pred_chars = {i for s, e in predicted for i in range(s, e)}
    gold_chars = {i for s, e in gold for i in range(s, e)}
    if not pred_chars or not gold_chars:
        return 0.0
    tp = len(pred_chars & gold_chars)
    precision, recall = tp / len(pred_chars), tp / len(gold_chars)
    return 0.0 if tp == 0 else 2 * precision * recall / (precision + recall)


@dataclass
class CheckerScore:
    checker: str
    items: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    span_f1: list[float] = dc_field(default_factory=list)
    latency_ms: list[float] = dc_field(default_factory=list)
    cost: float = 0.0
    errors: int = 0

    def to_dict(self) -> dict:
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        return {
            "checker": self.checker, "items": self.items, "tp": self.tp, "fp": self.fp, "fn": self.fn, "tn": self.tn,
            "precision": round(precision, 4) if precision is not None else None, "recall": round(recall, 4) if recall is not None else None,
            "span_f1": round(sum(self.span_f1) / len(self.span_f1), 4) if self.span_f1 else None,
            "latency_ms_mean": round(sum(self.latency_ms) / len(self.latency_ms), 2) if self.latency_ms else None,
            "latency_ms_p95": round(sorted(self.latency_ms)[int(0.95 * (len(self.latency_ms) - 1))], 2) if self.latency_ms else None,
            "cost_total": round(self.cost, 4), "errors": self.errors,
        }


def bench_text_checkers(items: list[BenchItem], checkers: dict[str, object], *, clock: Callable[[], float] = time.perf_counter) -> dict[str, CheckerScore]:
    scores = {name: CheckerScore(name) for name in checkers}
    for item in items:
        claim = Claim(id=item.id, span_id=None, trajectory_id=item.source, type="factual", text=item.answer, entry_id="e0001", seq=1, char_span=(0, len(item.answer)))
        evidence = [Evidence(f"ctx{i}", "retrieved_doc", "document", passage, "", None, 1.0, 0) for i, passage in enumerate(item.context)]
        for name, checker in checkers.items():
            score = scores[name]
            score.items += 1
            started = clock()
            try:
                try:
                    verdict = checker.check(claim, evidence, question=item.question)  # type: ignore[attr-defined]
                except TypeError:
                    verdict = checker.check(claim, evidence)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                score.errors += 1
                continue
            score.latency_ms.append((clock() - started) * 1000.0)
            score.cost += float(getattr(getattr(checker, "manifest", None), "est_cost_per_call", 0.0) or 0.0)
            flagged = verdict.label in ("unsupported", "contradicted")
            if flagged and item.hallucinated:
                score.tp += 1
            elif flagged:
                score.fp += 1
            elif item.hallucinated:
                score.fn += 1
            else:
                score.tn += 1
            if item.spans:
                predicted = []
                if flagged and verdict.value and verdict.value in item.answer:
                    start = item.answer.find(verdict.value)
                    predicted.append((start, start + len(verdict.value)))
                f1 = _span_f1(predicted, item.spans)
                if f1 is not None:
                    score.span_f1.append(f1)
    return scores


def bench_layer0(trajectories: Iterable[dict], *, clock: Callable[[], float] = time.perf_counter) -> dict:
    injected = fired = false_positive = 0
    latencies: list[float] = []
    for ledger, expected in agentic_items(trajectories):
        started = clock()
        verdicts: list[Verdict] = run_layer0(ledger, extract_claims(ledger))
        latencies.append((clock() - started) * 1000.0)
        got = {(v.rule_id, v.subcategory) for v in verdicts if v.label in ("unsupported", "contradicted")}
        injected += len(expected)
        fired += len(got & expected)
        false_positive += len(got - expected)
    return {
        "checker": "layer0", "trajectories": len(latencies), "injected": injected, "caught": fired, "false_positives": false_positive,
        "recall": round(fired / injected, 4) if injected else None,
        "precision": round(fired / (fired + false_positive), 4) if fired + false_positive else None,
        "latency_ms_mean": round(sum(latencies) / len(latencies), 2) if latencies else None,
    }


def run_bench(*, datasets: Iterable[str], checkers: dict[str, object], agentic: list[dict] | None = None, ragtruth_path: str | None = None,
              halubench_path: str | None = None, limit: int | None = None) -> dict:
    out: dict = {"schema": BENCH_SCHEMA, "datasets": {}}
    for name in datasets:
        if name not in DATASETS:
            raise ValueError(f"unknown dataset {name!r}; expected one of {DATASETS}")
        if name == "agentic":
            rows = agentic or []
            section: dict = {"layer0": bench_layer0(rows)}
            if checkers:
                items = []
                for ledger, expected in agentic_items(rows):
                    for claim in extract_claims(ledger):
                        if claim.source != "agent_output":
                            continue
                        context = [e.text_view for e in ledger.entries if e.seq < claim.seq and e.kind in ("tool_result", "user_input", "system_prompt", "retrieved_doc") and e.content_captured]
                        items.append(BenchItem(f"{ledger.trajectory_id}:{claim.id}", claim.text, context, "", bool(expected), [], "agentic"))
                section["text_checkers"] = {k: v.to_dict() for k, v in bench_text_checkers(items, checkers).items()}
            out["datasets"]["agentic"] = section
        elif name == "ragtruth":
            if not ragtruth_path:
                out["datasets"]["ragtruth"] = {"skipped": "no --ragtruth path; download the dataset yourself and pass the JSONL file"}
                continue
            items = load_ragtruth(ragtruth_path, limit=limit)
            out["datasets"]["ragtruth"] = {"items": len(items), "text_checkers": {k: v.to_dict() for k, v in bench_text_checkers(items, checkers).items()}}
        else:
            if not halubench_path:
                out["datasets"]["halubench"] = {"skipped": "no --halubench path; download the dataset yourself and pass the file"}
                continue
            items = load_halubench(halubench_path, limit=limit)
            out["datasets"]["halubench"] = {"items": len(items), "text_checkers": {k: v.to_dict() for k, v in bench_text_checkers(items, checkers).items()}}
    return out


def suggest_weights(bench: dict) -> dict[str, float]:
    """Default fusion weights from bench precision: a checker that is right
    more often weighs more; below 0.5 precision it weighs almost nothing."""
    weights: dict[str, float] = {}
    for section in bench.get("datasets", {}).values():
        for name, score in (section.get("text_checkers") or {}).items():
            precision = score.get("precision")
            if precision is None:
                continue
            weights[name] = max(weights.get(name, 0.0), round(max(0.05, (precision - 0.5) * 2), 3))
    return weights


def render_bench(bench: dict) -> str:
    lines = ["DetectR bench"]
    for name, section in bench.get("datasets", {}).items():
        if "skipped" in section:
            lines.append(f"  {name}: skipped ({section['skipped']})")
            continue
        if "layer0" in section:
            l0 = section["layer0"]
            lines.append(f"  {name} layer0: {l0['caught']} of {l0['injected']} injected failures caught, {l0['false_positives']} false positives, "
                         f"{l0['latency_ms_mean']} ms per trajectory")
        for checker, score in (section.get("text_checkers") or {}).items():
            lines.append(f"  {name} {checker}: precision {score['precision']}, recall {score['recall']}, span F1 {score['span_f1']}, "
                         f"latency {score['latency_ms_mean']} ms mean, cost {score['cost_total']}, errors {score['errors']}")
    return "\n".join(lines) + "\n"
