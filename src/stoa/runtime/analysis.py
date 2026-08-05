"""Runtime trace analysis (`stoa runtime analyze`) — `runtime-analysis/1.0`.

Pure aggregation over a span stream, single pass, never slurping a file
(the reader is a generator; ≥100k spans must not grow memory beyond the
per-agent accumulators). Deterministic body: identical trace input yields
byte-identical output below the header — the observation window is derived
from span timestamps (data, not the clock); the only wall-clock value is the
header's ``generated_at``, supplied by the caller, matching how
``build_assurance_packet`` treats its header block.

Correlation discipline: spans that can't be tied to a registry agent are
**never silently dropped** — they land in ``unmatched_agents`` with
suggested registry matches (the `stoa runtime map` guidance). Registry
agents with zero spans land in ``no_runtime_evidence``, explicitly.
"""

from __future__ import annotations

from .. import __version__
from ..rules import HIGH_IMPACT_CAPABILITIES
from .reader import TraceReader

ANALYSIS_SCHEMA = "runtime-analysis/1.0"


class _AgentAccumulator:
    __slots__ = (
        "span_count", "spans_by_kind", "status_counts", "capabilities",
        "integrations", "providers", "models", "capability_counts",
        "integration_counts", "high_impact_actions",
        "high_impact_approved", "approval_spans", "max_amount",
        "total_amounts", "redaction_modes", "first_ts", "last_ts",
        "delegations_to", "trace_files", "first_capability_span",
        "first_unapproved_high_impact", "max_amount_span",
    )

    def __init__(self) -> None:
        self.span_count = 0
        self.spans_by_kind: dict[str, int] = {}
        self.status_counts: dict[str, int] = {}
        self.capabilities: set[str] = set()
        self.integrations: set[str] = set()
        self.providers: set[str] = set()
        self.models: set[str] = set()
        self.capability_counts: dict[str, int] = {}
        self.integration_counts: dict[str, int] = {}
        self.high_impact_actions = 0
        self.high_impact_approved = 0
        self.approval_spans = 0
        self.max_amount: dict | None = None
        self.total_amounts: dict[str, float] = {}
        self.redaction_modes: set[str] = set()
        self.first_ts: str | None = None
        self.last_ts: str | None = None
        self.delegations_to: set[str] = set()
        self.trace_files: set[str] = set()
        # Representative trace refs, first occurrence in sorted-file order —
        # the evidence pointers RT findings cite ({file, line, span_id}).
        self.first_capability_span: dict[str, dict] = {}
        self.first_unapproved_high_impact: dict | None = None
        self.max_amount_span: dict | None = None

    @staticmethod
    def _ref(span: dict) -> dict:
        return {
            "file": span.get("_trace_file"),
            "line": span.get("_trace_line"),
            "span_id": span.get("span_id"),
        }

    def add(self, span: dict) -> None:
        self.span_count += 1
        kind = span["kind"]
        self.spans_by_kind[kind] = self.spans_by_kind.get(kind, 0) + 1
        status = span.get("status") or "ok"
        self.status_counts[status] = self.status_counts.get(status, 0) + 1
        for attr, bucket in (
            ("capability", self.capabilities),
            ("integration", self.integrations),
            ("provider", self.providers),
            ("model", self.models),
        ):
            value = span.get(attr)
            if value:
                bucket.add(value)
        if span.get("capability"):
            cap = span["capability"]
            self.capability_counts[cap] = self.capability_counts.get(cap, 0) + 1
            if cap not in self.first_capability_span:
                self.first_capability_span[cap] = self._ref(span)
        if span.get("integration"):
            integ = span["integration"]
            self.integration_counts[integ] = self.integration_counts.get(integ, 0) + 1
        if kind == "approval":
            self.approval_spans += 1
        if span.get("capability") in HIGH_IMPACT_CAPABILITIES and kind in ("action", "tool_call"):
            self.high_impact_actions += 1
            if span.get("approval_span_id"):
                self.high_impact_approved += 1
            elif self.first_unapproved_high_impact is None:
                self.first_unapproved_high_impact = self._ref(span)
        amount = span.get("amount")
        if isinstance(amount, dict) and isinstance(amount.get("amount"), (int, float)):
            currency = str(amount.get("currency") or "USD")
            value = float(amount["amount"])
            self.total_amounts[currency] = round(
                self.total_amounts.get(currency, 0.0) + value, 4
            )
            if self.max_amount is None or value > self.max_amount["amount"]:
                self.max_amount = {"amount": value, "currency": currency}
                self.max_amount_span = self._ref(span)
        mode = span.get("redaction")
        if mode:
            self.redaction_modes.add(mode)
        start, end = span.get("start_ts"), span.get("end_ts")
        if start and (self.first_ts is None or start < self.first_ts):
            self.first_ts = start
        if end and (self.last_ts is None or end > self.last_ts):
            self.last_ts = end
        if kind == "delegation" and span.get("to_agent_id"):
            self.delegations_to.add(span["to_agent_id"])
        if span.get("_trace_file"):
            self.trace_files.add(span["_trace_file"])

    def summary(self) -> dict:
        errors = self.status_counts.get("error", 0)
        quality = (
            "mixed" if len(self.redaction_modes) > 1
            else next(iter(self.redaction_modes), "redacted")
        )
        return {
            "span_count": self.span_count,
            "spans_by_kind": dict(sorted(self.spans_by_kind.items())),
            "status_counts": dict(sorted(self.status_counts.items())),
            "error_rate": round(errors / self.span_count, 4) if self.span_count else 0.0,
            "observed_capabilities": sorted(self.capabilities),
            "observed_integrations": sorted(self.integrations),
            "observed_providers": sorted(self.providers),
            "observed_models": sorted(self.models),
            "capability_counts": dict(sorted(self.capability_counts.items())),
            "integration_counts": dict(sorted(self.integration_counts.items())),
            "high_impact_actions": self.high_impact_actions,
            "high_impact_approved": self.high_impact_approved,
            "approval_rate_high_impact": (
                round(self.high_impact_approved / self.high_impact_actions, 4)
                if self.high_impact_actions else None
            ),
            "approval_spans": self.approval_spans,
            "max_observed_amount": self.max_amount,
            "window_total_amounts": dict(sorted(self.total_amounts.items())),
            "evidence_quality": quality,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "delegations_to": sorted(self.delegations_to),
            "trace_files": sorted(self.trace_files),
            "trace_refs": {
                "first_capability_span": dict(sorted(self.first_capability_span.items())),
                "first_unapproved_high_impact": self.first_unapproved_high_impact,
                "max_amount_span": self.max_amount_span,
            },
        }


def _hint_key(span: dict) -> str:
    hint = span.get("agent_hint") or {}
    module = hint.get("module") or "unknown"
    qualname = hint.get("qualname") or "unknown"
    return f"{module}:{qualname}"


def _suggest_matches(hint_key: str, registry: dict | None) -> list[dict]:
    """The `stoa runtime map` guidance: registry agents whose symbol or file
    stem appears in the span's module/qualname hint. Deterministic, sorted."""
    if not registry:
        return []
    module, _, qualname = hint_key.partition(":")
    needles = {part for part in module.split(".") if part} | {qualname.split(".")[0]}
    needles.discard("unknown")
    matches = []
    for agent in registry.get("agents") or []:
        stem = agent["path"].rsplit("/", 1)[-1].rsplit(".", 1)[0]
        if agent["symbol"] in needles or stem in needles:
            matches.append(
                {"agent_id": agent["id"], "name": agent["name"], "path": agent["path"]}
            )
    return sorted(matches, key=lambda m: (m["path"], m["agent_id"]))


def analyze_traces(
    traces_dir,
    registry: dict | None = None,
    *,
    generated_at: str | None = None,
    registry_path: str | None = None,
) -> dict:
    """Build the `runtime-analysis/1.0` document. Pure apart from reading
    trace files; ``generated_at`` is caller-supplied (header-only)."""
    reader = TraceReader(traces_dir)
    known_ids = {a["id"] for a in (registry or {}).get("agents") or []}

    matched: dict[str, _AgentAccumulator] = {}
    unmatched: dict[str, _AgentAccumulator] = {}
    unmatched_reason: dict[str, str] = {}
    window_start: str | None = None
    window_end: str | None = None
    total_spans = 0

    for span in reader.spans():
        total_spans += 1
        start, end = span.get("start_ts"), span.get("end_ts")
        if start and (window_start is None or start < window_start):
            window_start = start
        if end and (window_end is None or end > window_end):
            window_end = end

        agent_id = span.get("agent_id")
        if agent_id and (registry is None or agent_id in known_ids):
            bucket, key = matched, agent_id
        elif agent_id:  # id supplied but unknown to the registry
            bucket, key = unmatched, f"unknown-id:{agent_id}"
            unmatched_reason[key] = "agent_id not present in the registry"
        else:
            bucket, key = unmatched, _hint_key(span)
            unmatched_reason[key] = "no agent_id supplied (hint only)"
        if key not in bucket:
            bucket[key] = _AgentAccumulator()
        bucket[key].add(span)

    no_evidence = sorted(known_ids - set(matched)) if registry is not None else []

    return {
        "schema": ANALYSIS_SCHEMA,
        "header": {
            "generated_at": generated_at,
            "stoa_version": __version__,
            "registry": registry_path,
            "files_read": reader.stats.files_read,
            "files_skipped": reader.stats.files_skipped,
            "bad_lines": reader.stats.bad_lines,
            "headers_missing": reader.stats.headers_missing,
            "dropped_spans_reported": reader.stats.dropped_spans_reported,
            "warnings": list(reader.stats.warnings),
        },
        "window": {
            "start": window_start,
            "end": window_end,
            "span_count": total_spans,
        },
        "agents": {key: acc.summary() for key, acc in sorted(matched.items())},
        "unmatched_agents": [
            {
                "key": key,
                "reason": unmatched_reason[key],
                **acc.summary(),
                "suggested_matches": _suggest_matches(key, registry),
            }
            for key, acc in sorted(unmatched.items())
        ],
        "no_runtime_evidence": no_evidence,
    }
