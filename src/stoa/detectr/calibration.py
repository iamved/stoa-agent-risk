"""Calibration: a labels table and a fitter for per-agent thresholds and
per-checker weights. The adjudication UI that writes labels comes later;
the table and the fitter ship now so nothing is designed twice.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field as dc_field
from datetime import datetime, timezone
from pathlib import Path

LABEL_SCHEMA = "stoa-detectr-labels/0.1"
LABEL_SOURCES = ("human", "outcome", "redteam")
DEFAULT_PATH = Path(".stoa") / "detectr-labels.jsonl"
_CANDIDATE_THRESHOLDS = tuple(round(0.3 + 0.05 * i, 2) for i in range(13))  # 0.30 .. 0.90


@dataclass
class Label:
    claim_id: str
    trajectory_id: str
    agent_id: str | None
    source: str
    value: bool  # True: a real hallucination; False: a false positive
    probability: float | None = None
    layer0_label: str | None = None
    rule_id: str | None = None
    checker_scores: dict[str, float] = dc_field(default_factory=dict)
    ts: str = ""
    note: str = ""

    def to_dict(self) -> dict:
        row = asdict(self)
        row["schema"] = LABEL_SCHEMA
        return row


class LabelTable:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else DEFAULT_PATH

    def add(self, label: Label) -> None:
        if label.source not in LABEL_SOURCES:
            raise ValueError(f"source must be one of {LABEL_SOURCES}")
        if not label.ts:
            label.ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(label.to_dict(), sort_keys=True) + "\n")

    def load(self) -> list[Label]:
        if not self.path.is_file():
            return []
        out: list[Label] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row.pop("schema", None)
            try:
                out.append(Label(**row))
            except TypeError:
                continue
        return out


@dataclass
class Calibration:
    thresholds: dict[str, float]
    weights: dict[str, float]
    labels_used: int
    per_agent_counts: dict[str, int]
    notes: list[str]

    def to_dict(self) -> dict:
        return {"schema": "stoa-detectr-calibration/0.1", "thresholds": self.thresholds, "weights": self.weights,
                "labels_used": self.labels_used, "per_agent_counts": self.per_agent_counts, "notes": self.notes}


def _f1(pairs: list[tuple[float, bool]], threshold: float) -> float:
    tp = sum(1 for p, y in pairs if p >= threshold and y)
    fp = sum(1 for p, y in pairs if p >= threshold and not y)
    fn = sum(1 for p, y in pairs if p < threshold and y)
    if tp == 0:
        return 0.0
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    return 2 * precision * recall / (precision + recall)


def fit(labels: list[Label], *, min_labels_per_agent: int = 10, min_labels_per_checker: int = 5, default_threshold: float = 0.5) -> Calibration:
    """Thresholds: per agent, the candidate that maximizes F1 on labeled
    probabilities, once an agent has enough labels. Weights: per checker,
    how often its score sat on the right side of 0.5, rescaled so a coin
    flip weighs nearly nothing."""
    notes: list[str] = []
    by_agent: dict[str, list[tuple[float, bool]]] = {}
    for label in labels:
        if label.probability is None:
            continue
        by_agent.setdefault(label.agent_id or "", []).append((float(label.probability), bool(label.value)))
    thresholds: dict[str, float] = {}
    counts: dict[str, int] = {}
    for agent, pairs in by_agent.items():
        counts[agent] = len(pairs)
        if len(pairs) < min_labels_per_agent:
            notes.append(f"{agent or 'default'}: {len(pairs)} labels, threshold stays {default_threshold}")
            continue
        best = max(_CANDIDATE_THRESHOLDS, key=lambda t: (_f1(pairs, t), -abs(t - default_threshold)))
        thresholds[agent] = best
    scores: dict[str, list[tuple[float, bool]]] = {}
    for label in labels:
        for checker, score in (label.checker_scores or {}).items():
            scores.setdefault(checker, []).append((float(score), bool(label.value)))
    weights: dict[str, float] = {}
    for checker, pairs in scores.items():
        if len(pairs) < min_labels_per_checker:
            notes.append(f"{checker}: {len(pairs)} labels, weight stays 1.0")
            continue
        correct = sum(1 for s, y in pairs if (s >= 0.5) == y)
        accuracy = correct / len(pairs)
        weights[checker] = round(max(0.05, (accuracy - 0.5) * 2), 3)
    return Calibration(thresholds, weights, sum(1 for l in labels if l.probability is not None), counts, notes)
