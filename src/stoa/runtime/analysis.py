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

ANALYSIS_SCHEMA = "runtime-analysis/1.1"


class _AgentAccumulator:
    __slots__ = (
        "span_count", "spans_by_kind", "status_counts", "capabilities",
        "integrations", "providers", "models", "capability_counts",
        "integration_counts", "high_impact_actions",
        "high_impact_approved", "approval_spans", "max_amount",
        "total_amounts", "redaction_modes", "first_ts", "last_ts",
        "delegations_to", "trace_files", "first_capability_span",
        "first_unapproved_high_impact", "max_amount_span",
        "tool_counts", "tool_last_ts", "first_tool_span", "money_actions",
        "money_candidates", "flag_counts", "first_flag_span", "approval_ids",
        "llm_calls", "llm_errors", "side_effect_counts", "first_external_send",
        "flag_events",
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
        # 1.1: tools, money actions, flags, model-call errors, side effects.
        self.tool_counts: dict[str, int] = {}
        self.tool_last_ts: dict[str, str] = {}
        self.first_tool_span: dict[str, dict] = {}
        self.money_actions = 0
        # (ref, approval_span_id) for money actions; resolved after the pass.
        self.money_candidates: list[tuple[dict, str | None]] = []
        self.flag_counts: dict[str, int] = {}
        self.first_flag_span: dict[str, dict] = {}
        self.approval_ids: set[str] = set()
        self.llm_calls = 0
        self.llm_errors = 0
        self.side_effect_counts: dict[str, int] = {}
        self.first_external_send: dict | None = None
        # Up to 200 flagged spans per agent, oldest first: the timeline the dashboard draws.
        self.flag_events: list[dict] = []

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
            if span.get("span_id"):
                self.approval_ids.add(span["span_id"])
        if kind == "llm_call":
            self.llm_calls += 1
            if status == "error":
                self.llm_errors += 1
        attrs = span.get("attrs") or {}
        for flag in attrs.get("flags") or []:
            self.flag_counts[flag] = self.flag_counts.get(flag, 0) + 1
            if flag not in self.first_flag_span:
                self.first_flag_span[flag] = self._ref(span)
        if attrs.get("flags") and len(self.flag_events) < 200:
            self.flag_events.append({
                "ts": span.get("end_ts") or span.get("start_ts"),
                "flags": sorted(attrs["flags"]),
                "kind": kind,
                "tool": span.get("tool"),
                "amount": span.get("amount"),
                "trace_ref": self._ref(span),
            })
        tool = span.get("tool")
        if tool and kind in ("action", "tool_call"):
            self.tool_counts[tool] = self.tool_counts.get(tool, 0) + 1
            if span.get("end_ts") and span["end_ts"] > self.tool_last_ts.get(tool, ""):
                self.tool_last_ts[tool] = span["end_ts"]
            if tool not in self.first_tool_span:
                self.first_tool_span[tool] = self._ref(span)
        side_effect = attrs.get("side_effect")
        if side_effect and kind in ("action", "tool_call"):
            self.side_effect_counts[side_effect] = self.side_effect_counts.get(side_effect, 0) + 1
            if side_effect == "external_send" and self.first_external_send is None:
                self.first_external_send = self._ref(span)
        money = kind in ("action", "tool_call") and (
            side_effect == "payment"
            or isinstance((span.get("amount") or {}).get("amount"), (int, float))
        )
        if money:
            self.money_actions += 1
            self.money_candidates.append((self._ref(span), span.get("approval_span_id")))
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

    def resolve_money(self, approval_ids: set[str]) -> tuple[int, dict | None]:
        """Money actions whose ``approval_span_id`` resolves to an approval
        span seen anywhere in the stream; the first that does not."""
        approved = 0
        first_unapproved = None
        for ref, approval_id in self.money_candidates:
            if approval_id and approval_id in approval_ids:
                approved += 1
            elif first_unapproved is None:
                first_unapproved = ref
        return approved, first_unapproved

    def summary(self, approval_ids: set[str] | None = None) -> dict:
        errors = self.status_counts.get("error", 0)
        money_approved, first_unapproved_money = self.resolve_money(approval_ids or self.approval_ids)
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
            "observed_tools": sorted(self.tool_counts),
            "tool_counts": dict(sorted(self.tool_counts.items())),
            "tool_last_ts": dict(sorted(self.tool_last_ts.items())),
            "money_actions": self.money_actions,
            "money_actions_approved": money_approved,
            "approval_rate_money": (
                round(money_approved / self.money_actions, 4) if self.money_actions else None
            ),
            "flag_counts": dict(sorted(self.flag_counts.items())),
            "side_effect_counts": dict(sorted(self.side_effect_counts.items())),
            "llm_calls": self.llm_calls,
            "llm_error_rate": round(self.llm_errors / self.llm_calls, 4) if self.llm_calls else 0.0,
            "flag_events": list(self.flag_events),
            "trace_refs": {
                "first_capability_span": dict(sorted(self.first_capability_span.items())),
                "first_unapproved_high_impact": self.first_unapproved_high_impact,
                "max_amount_span": self.max_amount_span,
                "first_tool_span": dict(sorted(self.first_tool_span.items())),
                "first_unapproved_money": first_unapproved_money,
                "first_flag_span": dict(sorted(self.first_flag_span.items())),
                "first_external_send": self.first_external_send,
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
    # Approval spans may be recorded by one agent and cited by another's
    # action (a delegated approval), so money actions resolve against every
    # approval span in the stream.
    all_approval_ids: set[str] = set()
    for acc in (*matched.values(), *unmatched.values()):
        all_approval_ids |= acc.approval_ids

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
        "agents": {key: acc.summary(all_approval_ids) for key, acc in sorted(matched.items())},
        "unmatched_agents": [
            {
                "key": key,
                "reason": unmatched_reason[key],
                **acc.summary(all_approval_ids),
                "suggested_matches": _suggest_matches(key, registry),
            }
            for key, acc in sorted(unmatched.items())
        ],
        "no_runtime_evidence": no_evidence,
    }
