"""Metrics over DetectR reports: per agent, per window, per claim type.

Rates are over verifiable claims; unverifiable claims are counted apart and
never enter the hallucination rate. Every number is derived from the
reports passed in; nothing is estimated.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from .layer0 import RULE_IDS

METRICS_SCHEMA = "stoa-detectr-metrics/0.1"
WINDOWS = ("all", "day", "week", "month")
CLAIM_TYPES = ("factual", "action", "result", "commitment", "reasoning")


def _parse_ts(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.isdigit():
        n = int(text)
        for divisor in (1_000_000_000, 1_000_000, 1_000, 1):
            if n // divisor < 100_000_000_000:
                return datetime.fromtimestamp(n / divisor, tz=timezone.utc)
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bucket(ts: datetime | None, window: str) -> str:
    if ts is None:
        return "unknown"
    if window == "all":
        return "all"
    if window == "day":
        return ts.strftime("%Y-%m-%d")
    if window == "week":
        year, week, _ = ts.isocalendar()
        return f"{year}-W{week:02d}"
    return ts.strftime("%Y-%m")


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


class _Cell:
    def __init__(self) -> None:
        self.claims = 0
        self.by_label: dict[str, int] = defaultdict(int)
        self.by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.phantom = 0
        self.action_text_claims = 0
        self.argument_failures = 0
        self.tool_call_claims = 0
        self.blast: list[int] = []
        self.detection_seconds: list[float] = []
        self.trajectories: set[str] = set()
        self.findings_by_rule: dict[str, int] = defaultdict(int)

    def to_dict(self) -> dict:
        verifiable = self.claims - self.by_label.get("unverifiable", 0)
        bad = self.by_label.get("unsupported", 0) + self.by_label.get("contradicted", 0)
        return {
            "trajectories": len(self.trajectories),
            "claims": self.claims,
            "verifiable_claims": verifiable,
            "labels": {k: self.by_label.get(k, 0) for k in ("grounded", "unsupported", "contradicted", "unverifiable")},
            "hallucination_rate": _rate(bad, verifiable),
            "contradiction_rate": _rate(self.by_label.get("contradicted", 0), verifiable),
            "phantom_action_rate": _rate(self.phantom, self.action_text_claims),
            "argument_grounding_failure_rate": _rate(self.argument_failures, self.tool_call_claims),
            "unverifiable_rate": _rate(self.by_label.get("unverifiable", 0), self.claims),
            "mean_blast_radius": round(sum(self.blast) / len(self.blast), 3) if self.blast else None,
            "mean_time_to_detection_seconds": round(sum(self.detection_seconds) / len(self.detection_seconds), 1) if self.detection_seconds else None,
            "findings_by_rule": dict(sorted(self.findings_by_rule.items())),
            "by_claim_type": {
                t: {"claims": sum(self.by_type[t].values()), **{k: self.by_type[t].get(k, 0) for k in ("grounded", "unsupported", "contradicted", "unverifiable")},
                    "hallucination_rate": _rate(self.by_type[t].get("unsupported", 0) + self.by_type[t].get("contradicted", 0),
                                                sum(self.by_type[t].values()) - self.by_type[t].get("unverifiable", 0))}
                for t in CLAIM_TYPES if t in self.by_type
            },
        }


def compute_metrics(reports: Iterable[dict], *, window: str = "all", detected_at: str | None = None) -> dict:
    """``reports`` are ``Report.to_dict()`` documents (or the objects). The
    time of detection defaults to now; with ``detected_at`` set, mean time
    to detection measures from each claim's timestamp to that instant."""
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {WINDOWS}")
    detection = _parse_ts(detected_at) or datetime.now(timezone.utc)
    cells: dict[tuple[str, str], _Cell] = defaultdict(_Cell)
    for report in reports:
        doc = report.to_dict() if hasattr(report, "to_dict") else report
        agent = str(doc.get("agent_id") or "unknown")
        claims = {c["id"]: c for c in doc.get("claims") or []}
        timestamps = doc.get("claim_timestamps") or {}
        for verdict in doc.get("verdicts") or []:
            claim = claims.get(verdict["claim_id"], {})
            ts = _parse_ts(timestamps.get(verdict["claim_id"]))
            cell = cells[(agent, _bucket(ts, window))]
            cell.trajectories.add(str(doc.get("trajectory_id")))
            cell.claims += 1
            cell.by_label[verdict["label"]] += 1
            cell.by_type[claim.get("type", "factual")][verdict["label"]] += 1
            if claim.get("source") == "tool_call":
                cell.tool_call_claims += 1
                if verdict.get("rule_id") == RULE_IDS["argument"] and verdict["label"] in ("unsupported", "contradicted"):
                    cell.argument_failures += 1
            elif claim.get("type") == "action":
                cell.action_text_claims += 1
                if verdict.get("rule_id") == RULE_IDS["phantom"] and verdict["label"] == "contradicted":
                    cell.phantom += 1
            if verdict["label"] in ("unsupported", "contradicted"):
                cell.blast.append(int(verdict.get("blast_radius") or 0))
                if ts is not None:
                    cell.detection_seconds.append(max(0.0, (detection - ts).total_seconds()))
        for finding in doc.get("findings") or []:
            claim_id = ((finding.get("detectr") or {}).get("claim") or {}).get("id")
            ts = _parse_ts(timestamps.get(claim_id))
            cells[(agent, _bucket(ts, window))].findings_by_rule[finding["rule_id"]] += 1
    out: dict = {"schema": METRICS_SCHEMA, "window": window, "detected_at": detection.strftime("%Y-%m-%dT%H:%M:%SZ"), "agents": {}}
    for (agent, bucket), cell in sorted(cells.items()):
        out["agents"].setdefault(agent, {})[bucket] = cell.to_dict()
    total = _Cell()
    for cell in cells.values():
        total.claims += cell.claims
        for k, v in cell.by_label.items():
            total.by_label[k] += v
        for t, labels in cell.by_type.items():
            for k, v in labels.items():
                total.by_type[t][k] += v
        total.phantom += cell.phantom
        total.action_text_claims += cell.action_text_claims
        total.argument_failures += cell.argument_failures
        total.tool_call_claims += cell.tool_call_claims
        total.blast += cell.blast
        total.detection_seconds += cell.detection_seconds
        total.trajectories |= cell.trajectories
        for k, v in cell.findings_by_rule.items():
            total.findings_by_rule[k] += v
    out["total"] = total.to_dict()
    return out


def render_metrics(metrics: dict) -> str:
    total = metrics["total"]
    lines = [f"DetectR metrics ({metrics['window']} window, {total['trajectories']} trajectories, {total['claims']} claims)"]
    labels = total["labels"]
    lines.append(f"  grounded {labels['grounded']}, unsupported {labels['unsupported']}, contradicted {labels['contradicted']}, unverifiable {labels['unverifiable']} (counted apart)")

    def pct(value):
        return "n/a" if value is None else f"{value * 100:.1f}%"

    lines.append(f"  hallucination rate {pct(total['hallucination_rate'])}, contradiction rate {pct(total['contradiction_rate'])}, "
                 f"phantom actions {pct(total['phantom_action_rate'])}, ungrounded arguments {pct(total['argument_grounding_failure_rate'])}")
    if total["mean_blast_radius"] is not None:
        lines.append(f"  mean blast radius {total['mean_blast_radius']}")
    if total["findings_by_rule"]:
        lines.append("  findings: " + ", ".join(f"{k} {v}" for k, v in total["findings_by_rule"].items()))
    for agent, buckets in metrics["agents"].items():
        for bucket, cell in buckets.items():
            lines.append(f"  {agent} [{bucket}]: {cell['claims']} claims, hallucination rate {pct(cell['hallucination_rate'])}, "
                         f"unverifiable {cell['labels']['unverifiable']}")
    return "\n".join(lines) + "\n"
