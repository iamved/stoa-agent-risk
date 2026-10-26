"""Metrics: derived from reports, unverifiable counted apart, windows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stoa.detectr.ledger import Ledger
from stoa.detectr.metrics import compute_metrics, render_metrics
from stoa.detectr.pipeline import check_ledger

FIXTURES = Path(__file__).resolve().parent / "fixtures"
ROWS = json.loads((FIXTURES / "trajectories.json").read_text(encoding="utf-8"))


def _reports(scenario=None):
    out = []
    for row in ROWS:
        if scenario and row["scenario"] != scenario:
            continue
        ledger = Ledger.from_dict(row["ledger"])
        for i, entry in enumerate(ledger.entries):
            entry.timestamp = f"2026-10-{1 + (hash(row['id']) % 20):02d}T09:00:{i:02d}Z"
        out.append(check_ledger(ledger).to_dict())
    return out


def test_rates_are_derived_and_unverifiable_is_kept_apart():
    reports = _reports("refund")
    metrics = compute_metrics(reports, detected_at="2026-10-31T00:00:00Z")
    total = metrics["total"]
    labels = total["labels"]
    assert total["claims"] == sum(labels.values()) and total["verifiable_claims"] == total["claims"] - labels["unverifiable"]
    assert total["hallucination_rate"] == round((labels["unsupported"] + labels["contradicted"]) / total["verifiable_claims"], 4)
    assert total["trajectories"] == len(reports)
    assert total["findings_by_rule"]["RT009"] >= 2 and total["findings_by_rule"]["RT012"] >= 3
    assert 0 < total["phantom_action_rate"] < 1 and 0 < total["argument_grounding_failure_rate"] < 1
    assert total["mean_time_to_detection_seconds"] > 0
    assert set(total["by_claim_type"]) <= {"factual", "action", "result", "commitment", "reasoning"}
    agent = metrics["agents"]["meridian-refund"]["all"]
    assert agent["claims"] == total["claims"]
    text = render_metrics(metrics)
    assert "hallucination rate" in text and "counted apart" in text


def test_windows_split_by_day_and_month():
    reports = _reports("kyc")
    by_day = compute_metrics(reports, window="day")
    by_month = compute_metrics(reports, window="month")
    assert len(by_day["agents"]["meridian-kyc"]) >= 2
    assert list(by_month["agents"]["meridian-kyc"]) == ["2026-10"]
    assert by_month["total"]["claims"] == by_day["total"]["claims"]
    with pytest.raises(ValueError):
        compute_metrics(reports, window="hour")


def test_metrics_accept_report_objects_and_empty_input():
    empty = compute_metrics([])
    assert empty["total"]["claims"] == 0 and empty["total"]["hallucination_rate"] is None and empty["agents"] == {}
    ledger = Ledger.from_dict(next(r for r in ROWS if r["id"] == "refund-canonical")["ledger"])
    report = check_ledger(ledger)
    metrics = compute_metrics([report])
    assert metrics["total"]["labels"] == {"grounded": 1, "unsupported": 2, "contradicted": 1, "unverifiable": 0}
    assert metrics["total"]["mean_blast_radius"] == round(1 / 3, 3)
