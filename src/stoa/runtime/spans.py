"""Span records and constants for the ``stoa-trace/1.0`` schema.

One JSONL record per span. The first line of every trace file is a header
record (``kind: "header"``); readers tolerate a missing header (warn, assume
the current version — fail-open, matching how ``stoa diff`` treats
unresolvable refs).

Vocabulary discipline: ``capability`` / ``integration`` / ``provider`` reuse
the scanner's existing ids (``rules.CAPABILITY_PATTERNS`` etc.) verbatim —
never a parallel taxonomy. A value outside the scanner's vocabulary is still
recorded (the customer may have custom tools) but flagged
``"vocabulary": "custom"`` so analysis can report it without pretending it
maps to a scanned capability.

Reserved span fields (documented, never emitted in 1.0, consumers must
ignore unknown fields): ``enforcement``, ``session_id``, ``cost``.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from functools import lru_cache

TRACE_SCHEMA = "stoa-trace/1.0"

SPAN_KINDS = (
    "agent_run",
    "llm_call",
    "tool_call",
    "action",
    "approval",
    "retrieval",
    "delegation",
)

STATUSES = ("ok", "error")
REDACTION_MODES = ("redacted", "content")


@lru_cache(maxsize=1)
def scanner_vocabulary() -> dict[str, frozenset[str]]:
    """The scanner's own capability/integration/provider id sets.

    Imported lazily so a customer process using only the SDK pays the
    rules-module import cost once, on first span build — and so this module
    stays importable even if the vocabulary tables move.
    """
    from ..rules import CAPABILITY_PATTERNS, INTEGRATION_PATTERNS, PROVIDER_PATTERNS

    return {
        "capability": frozenset(CAPABILITY_PATTERNS),
        "integration": frozenset(INTEGRATION_PATTERNS),
        "provider": frozenset(PROVIDER_PATTERNS),
    }


def utc_now_iso() -> str:
    """ISO-8601 UTC with millisecond precision, e.g. 2026-08-01T12:00:00.123Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def header_record(sdk_version: str, redaction: str, dropped_spans: int = 0) -> dict:
    return {
        "kind": "header",
        "schema": TRACE_SCHEMA,
        "sdk_version": sdk_version,
        "redaction": redaction,
        "dropped_spans": dropped_spans,
    }


def redact_attrs(attrs: dict | None, capture_content: bool, redaction_hook) -> dict:
    """Apply the redact-by-default contract to user-supplied attrs.

    - int/float/bool values pass through verbatim (never sensitive shapes).
    - str values are NEVER recorded verbatim unless content capture is on:
      redacted mode records ``<key>_sha256`` + ``<key>_chars`` instead.
    - Any other type is treated like a string of its ``repr``.
    - With content capture on, strings pass through ``redaction_hook`` first
      when one is configured.
    """
    if not attrs:
        return {}
    out: dict = {}
    for key, value in attrs.items():
        if isinstance(value, bool) or isinstance(value, (int, float)):
            out[str(key)] = value
            continue
        text = value if isinstance(value, str) else repr(value)
        if capture_content:
            out[str(key)] = redaction_hook(text) if redaction_hook else text
        else:
            out[f"{key}_sha256"] = sha256_text(text)
            out[f"{key}_chars"] = len(text)
    return out


def build_span(
    *,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    kind: str,
    start_ts: str,
    end_ts: str,
    status: str,
    redaction: str,
    agent_id: str | None = None,
    agent_hint: dict | None = None,
    capability: str | None = None,
    integration: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    tool: str | None = None,
    amount: float | None = None,
    currency: str | None = None,
    approved_by: str | None = None,
    approval_method: str | None = None,
    approval_span_id: str | None = None,
    from_agent_id: str | None = None,
    to_agent_id: str | None = None,
    attrs: dict | None = None,
) -> dict:
    """Build one validated ``stoa-trace/1.0`` span record (a plain dict).

    Raises ``ValueError`` only for structurally invalid kinds/statuses — the
    SDK wraps all calls so instrumentation never raises into customer code;
    the reader is fail-open on anything malformed.
    """
    if kind not in SPAN_KINDS:
        raise ValueError(f"unknown span kind {kind!r}; expected one of {SPAN_KINDS}")
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")

    span: dict = {
        "kind": kind,
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "agent_id": agent_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "status": status,
        "redaction": redaction,
    }
    if agent_hint:
        span["agent_hint"] = agent_hint

    vocab = scanner_vocabulary()
    custom_vocab = False
    for field_name, value in (
        ("capability", capability),
        ("integration", integration),
        ("provider", provider),
    ):
        if value is None:
            continue
        span[field_name] = value
        if value not in vocab[field_name]:
            custom_vocab = True
    if custom_vocab:
        span["vocabulary"] = "custom"

    if model is not None:
        span["model"] = model
    if tool is not None:
        span["tool"] = tool
    if amount is not None:
        span["amount"] = {"amount": amount, "currency": currency or "USD"}
    if approved_by is not None or approval_method is not None:
        span["approval"] = {"approved_by": approved_by, "method": approval_method}
    if approval_span_id is not None:
        span["approval_span_id"] = approval_span_id
    if kind == "delegation":
        span["from_agent_id"] = from_agent_id
        span["to_agent_id"] = to_agent_id
    if attrs:
        span["attrs"] = attrs
    return span
