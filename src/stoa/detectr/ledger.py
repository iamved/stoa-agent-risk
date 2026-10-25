"""The ledger: everything an agent could have known in one trajectory, in
order, unmodified.

One trajectory is one agent's run inside one session. Three builders feed
the same shape: Stoa SDK traces (``stoa-trace/1.1``), OpenTelemetry GenAI
spans, and LangGraph checkpoints. Entries keep the raw payload exactly as
recorded; the agent's own words about a tool result are a separate
``agent_output`` entry and never stand in for the result. Every entry is
hashed so evidence survives redaction, and a value index makes the Layer 0
checks a dictionary lookup per claim.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any, Iterable

from .values import Value, values_from_payload

LEDGER_SCHEMA = "stoa-detectr-ledger/0.1"

KINDS = (
    "user_input", "system_prompt", "retrieved_doc", "tool_call", "tool_result",
    "approval", "agent_output", "handoff_in", "handoff_out",
)
SOURCES = ("sdk", "otel", "langgraph")

# Kinds whose content an agent sees before acting. Agent output is what it
# said, not what it saw, so it never grounds a later claim.
GROUNDING_KINDS = ("user_input", "system_prompt", "retrieved_doc", "tool_result", "approval", "handoff_in")


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def payload_hash(payload: Any) -> str:
    if payload is None:
        return ""
    text = payload if isinstance(payload, str) else _canonical_json(payload)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_payload(payload: Any) -> dict | list | None:
    """Best-effort structure: JSON objects and lists as they are, JSON
    strings decoded, ``key=value`` or ``key: value`` lines, pipe tables.
    ``None`` when nothing structured is there."""
    if payload is None or isinstance(payload, bool):
        return None
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, (int, float)):
        return None
    text = str(payload).strip()
    if not text:
        return None
    if text[0] in "{[":
        try:
            decoded = json.loads(text)
            if isinstance(decoded, (dict, list)):
                return decoded
        except json.JSONDecodeError:
            pass
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 2 and all("|" in ln for ln in lines):
        rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in lines]
        rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "-") for c in r)]
        if len(rows) >= 2:
            header = rows[0]
            return [dict(zip(header, r)) for r in rows[1:] if len(r) == len(header)]
    pairs: dict[str, Any] = {}
    if len(lines) < 2:
        return None
    for ln in lines:
        m = re.match(r"^\s*([A-Za-z_][\w .-]{0,40}?)\s*[:=]\s*(.+?)\s*$", ln)
        if not m:
            pairs = {}
            break
        pairs[m.group(1).strip()] = m.group(2)
    return pairs or None


def text_view(payload: Any) -> str:
    """Flat text for text checkers: dicts become ``key: value`` lines."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        return "\n".join(f"{k}: {text_view(v)}" for k, v in payload.items())
    if isinstance(payload, list):
        return "\n".join(text_view(v) for v in payload)
    return str(payload)


@dataclass
class LedgerEntry:
    id: str
    seq: int
    kind: str
    span_id: str | None = None
    timestamp: str | None = None
    tool_name: str | None = None
    raw_payload: Any = None
    parsed: dict | list | None = None
    text_view: str = ""
    hash: str = ""
    content_captured: bool = True
    meta: dict = dc_field(default_factory=dict)
    values: list[Value] = dc_field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "seq": self.seq, "kind": self.kind, "span_id": self.span_id,
            "timestamp": self.timestamp, "tool_name": self.tool_name, "raw_payload": self.raw_payload,
            "parsed": self.parsed, "text_view": self.text_view, "hash": self.hash,
            "content_captured": self.content_captured, "meta": self.meta,
            "values": [{"type": v.type, "canonical": v.canonical, "raw": v.raw, "field": v.field} for v in self.values],
        }


@dataclass
class Ledger:
    trajectory_id: str
    agent_id: str | None
    model_id: str | None
    built_from: str
    entries: list[LedgerEntry] = dc_field(default_factory=list)
    parent_trajectory_id: str | None = None
    warnings: list[str] = dc_field(default_factory=list)
    _by_key: dict[str, list[LedgerEntry]] = dc_field(default_factory=dict, repr=False)
    _by_tool: dict[str, list[LedgerEntry]] = dc_field(default_factory=dict, repr=False)

    # --- building ---------------------------------------------------------------

    def add(self, kind: str, *, span_id: str | None = None, timestamp: str | None = None,
            tool_name: str | None = None, payload: Any = None, content_captured: bool = True,
            hash_override: str | None = None, meta: dict | None = None) -> LedgerEntry:
        if kind not in KINDS:
            raise ValueError(f"unknown ledger kind {kind!r}")
        seq = len(self.entries) + 1
        parsed = parse_payload(payload) if content_captured else None
        entry = LedgerEntry(
            id=f"e{seq:04d}", seq=seq, kind=kind, span_id=span_id, timestamp=timestamp, tool_name=tool_name,
            raw_payload=payload if content_captured else None, parsed=parsed,
            text_view=text_view(parsed if parsed is not None else payload) if content_captured else "",
            hash=hash_override or payload_hash(payload if content_captured else None),
            content_captured=content_captured, meta=dict(meta or {}),
        )
        if content_captured:
            source = parsed if parsed is not None else payload
            entry.values = values_from_payload(source)
        self.entries.append(entry)
        for value in entry.values:
            self._by_key.setdefault(value.key(), []).append(entry)
        if tool_name:
            self._by_tool.setdefault(tool_name, []).append(entry)
        return entry

    # --- lookups ------------------------------------------------------------------

    def by_kind(self, *kinds: str) -> list[LedgerEntry]:
        return [e for e in self.entries if e.kind in kinds]

    def by_tool(self, tool_name: str, *kinds: str) -> list[LedgerEntry]:
        rows = self._by_tool.get(tool_name, [])
        return [e for e in rows if not kinds or e.kind in kinds]

    def before(self, seq: int, *kinds: str) -> list[LedgerEntry]:
        return [e for e in self.entries if e.seq < seq and (not kinds or e.kind in kinds)]

    def lookup(self, value: Value, *, before_seq: int | None = None, kinds: Iterable[str] | None = None) -> list[LedgerEntry]:
        """Entries holding a value with the same comparison key."""
        rows = self._by_key.get(value.key(), [])
        allowed = set(kinds) if kinds else None
        return [e for e in rows if (before_seq is None or e.seq < before_seq) and (allowed is None or e.kind in allowed)]

    def result_for(self, call: LedgerEntry) -> LedgerEntry | None:
        """The tool_result that answers a tool_call: the first result for the
        same tool after the call, or the one linked by call id."""
        call_id = call.meta.get("call_id")
        for e in self.entries:
            if e.seq <= call.seq or e.kind != "tool_result":
                continue
            if call_id and e.meta.get("call_id") == call_id:
                return e
            if e.tool_name == call.tool_name and (not call_id or not e.meta.get("call_id")):
                return e
        return None

    @property
    def redacted(self) -> bool:
        return bool(self.entries) and not any(e.content_captured for e in self.entries)

    # --- serialization ------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "schema": LEDGER_SCHEMA, "trajectory_id": self.trajectory_id, "agent_id": self.agent_id,
            "model_id": self.model_id, "built_from": self.built_from, "parent_trajectory_id": self.parent_trajectory_id,
            "entries": [e.to_dict() for e in self.entries], "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ledger":
        ledger = cls(trajectory_id=data["trajectory_id"], agent_id=data.get("agent_id"), model_id=data.get("model_id"),
                     built_from=data.get("built_from") or "sdk", parent_trajectory_id=data.get("parent_trajectory_id"),
                     warnings=list(data.get("warnings") or []))
        for row in data.get("entries") or []:
            ledger.add(row["kind"], span_id=row.get("span_id"), timestamp=row.get("timestamp"), tool_name=row.get("tool_name"),
                       payload=row.get("raw_payload"), content_captured=bool(row.get("content_captured", True)),
                       hash_override=row.get("hash") or None, meta=row.get("meta"))
        return ledger


def chain(ledger: Ledger, store: dict[str, Ledger]) -> list[LedgerEntry]:
    """The ledger's entries with its parents' entries in front, up to each
    hand-off, so a claim in agent B resolves against what agent A knew."""
    rows: list[LedgerEntry] = []
    seen: set[str] = set()
    current: Ledger | None = ledger
    while current is not None and current.trajectory_id not in seen:
        seen.add(current.trajectory_id)
        parent = store.get(current.parent_trajectory_id or "")
        if parent is not None:
            cutoff = next((e.seq for e in parent.entries if e.kind == "handoff_out" and e.meta.get("to") == current.agent_id), None)
            rows = [e for e in parent.entries if cutoff is None or e.seq <= cutoff] + rows
        current = parent
    return rows + ledger.entries


# --- helpers shared by builders -------------------------------------------------

def _maybe_json(text: Any) -> Any:
    if isinstance(text, str):
        stripped = text.strip()
        if stripped[:1] in "{[":
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return text
    return text


def _message_text(content: Any) -> str:
    """LangChain and GenAI message content: a string, or a list of parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
            elif isinstance(part, dict):
                if part.get("type") in (None, "text", "output_text", "input_text") and isinstance(part.get("text") or part.get("content"), str):
                    pieces.append(part.get("text") or part.get("content"))
        return "\n".join(p for p in pieces if p)
    if isinstance(content, dict):
        return _message_text(content.get("text") or content.get("content"))
    return str(content)


# --- builder 1: Stoa SDK traces ------------------------------------------------------

_HASHED = re.compile(r"^(?P<name>.+)_sha256$")


def _content_attr(attrs: dict, name: str) -> tuple[Any, bool, str | None]:
    """(payload, captured, hash) for a content attr that the SDK either
    recorded in clear (content mode) or as hash plus length (redacted)."""
    if name in attrs:
        return _maybe_json(attrs[name]), True, None
    digest = attrs.get(f"{name}_sha256")
    if digest:
        return None, False, str(digest)
    return None, False, None


def _sort_key(span: dict) -> tuple:
    return (span.get("start_ts") or "", span.get("_trace_file") or "", span.get("_trace_line") or 0)


def ledgers_from_spans(spans: Iterable[dict]) -> list[Ledger]:
    """One ledger per (session, agent) from ``stoa-trace/1.1`` span dicts
    (as ``TraceReader.spans()`` yields them)."""
    by_session: dict[str, list[dict]] = {}
    for span in spans:
        key = span.get("session_id") or span.get("trace_id") or "no-session"
        by_session.setdefault(key, []).append(span)

    ledgers: list[Ledger] = []
    for session_id, rows in by_session.items():
        rows.sort(key=_sort_key)
        agents = sorted({str(r.get("agent_id")) for r in rows if r.get("agent_id")}) or ["unknown"]
        per_agent: dict[str, Ledger] = {}
        for agent in agents:
            per_agent[agent] = Ledger(trajectory_id=f"{session_id}:{agent}", agent_id=agent, model_id=None, built_from="sdk")
        seen_hashes: dict[str, set[str]] = {a: set() for a in agents}

        def ledger_for(span: dict) -> Ledger:
            return per_agent.get(str(span.get("agent_id")) or agents[0], per_agent[agents[0]])

        def add_once(ledger: Ledger, kind: str, payload: Any, captured: bool, digest: str | None, **kw) -> None:
            h = digest or payload_hash(payload)
            marker = f"{kind}:{h}"
            if captured and h and marker in seen_hashes[ledger.agent_id or agents[0]]:
                return
            seen_hashes[ledger.agent_id or agents[0]].add(marker)
            ledger.add(kind, payload=payload, content_captured=captured, hash_override=digest, **kw)

        # Tool results close when the span ends, so a result is placed by end_ts
        # while everything else is placed by start_ts.
        events: list[tuple[str, int, dict, str]] = []
        for i, span in enumerate(rows):
            events.append((span.get("start_ts") or "", i, span, "start"))
            if span.get("kind") in ("action", "tool_call", "llm_call"):
                events.append((span.get("end_ts") or span.get("start_ts") or "", i, span, "end"))
        events.sort(key=lambda t: (t[0], t[1], 0 if t[3] == "start" else 1))

        for ts, _, span, phase in events:
            attrs = span.get("attrs") or {}
            kind = span.get("kind")
            ledger = ledger_for(span)
            if span.get("model") and not ledger.model_id:
                ledger.model_id = str(span["model"])
            ref = {"trace_file": span.get("_trace_file"), "trace_line": span.get("_trace_line")}
            if phase == "start":
                if kind == "agent_run":
                    system, cap, digest = _content_attr(attrs, "system_prompt")
                    if cap or digest:
                        add_once(ledger, "system_prompt", system, cap, digest, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                    inputs, cap, digest = _content_attr(attrs, "user_inputs")
                    if cap and isinstance(inputs, list):
                        for item in inputs:
                            add_once(ledger, "user_input", item, True, None, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                    elif cap or digest:
                        add_once(ledger, "user_input", inputs, cap, digest, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                elif kind == "llm_call":
                    system, cap, digest = _content_attr(attrs, "system")
                    if cap or digest:
                        add_once(ledger, "system_prompt", system, cap, digest, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                    prompt, cap, digest = _content_attr(attrs, "prompt")
                    if cap and isinstance(prompt, list):
                        for msg in prompt:
                            if not isinstance(msg, dict):
                                add_once(ledger, "user_input", msg, True, None, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                                continue
                            role = str(msg.get("role") or msg.get("type") or "user").lower()
                            body = msg.get("content")
                            if role in ("system", "developer"):
                                add_once(ledger, "system_prompt", _message_text(body), True, None, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                            elif role in ("user", "human"):
                                add_once(ledger, "user_input", _message_text(body), True, None, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                            elif role == "tool":
                                add_once(ledger, "tool_result", _maybe_json(body), True, None, span_id=span.get("span_id"), timestamp=ts,
                                         tool_name=msg.get("name"), meta={**ref, "call_id": msg.get("tool_call_id"), "status": "ok"})
                    elif cap or digest:
                        add_once(ledger, "user_input", prompt, cap, digest, span_id=span.get("span_id"), timestamp=ts, meta=ref)
                elif kind in ("action", "tool_call"):
                    args, cap, digest = _content_attr(attrs, "args")
                    payload: Any = args
                    if not cap:
                        partial = {}
                        amount = span.get("amount")
                        if isinstance(amount, dict) and amount.get("amount") is not None:
                            partial["amount"] = amount["amount"]
                            partial["currency"] = amount.get("currency")
                        if span.get("approval_span_id"):
                            partial["approval_span_id"] = span["approval_span_id"]
                        payload = partial or None
                    meta = {**ref, "side_effect": attrs.get("side_effect"), "enforcement": span.get("enforcement"),
                            "approval_span_id": span.get("approval_span_id"), "call_id": span.get("span_id")}
                    if isinstance(span.get("amount"), dict):
                        meta["amount"] = span["amount"]
                    ledger.add("tool_call", span_id=span.get("span_id"), timestamp=ts, tool_name=span.get("tool"),
                               payload=payload, content_captured=cap or bool(payload), hash_override=digest if not cap else None, meta=meta)
                elif kind == "approval":
                    approval = span.get("approval") or {}
                    payload = {"approval_id": span.get("span_id"), "approved_by": approval.get("approved_by"),
                               "method": approval.get("method"), "granted": attrs.get("granted", True)}
                    ledger.add("approval", span_id=span.get("span_id"), timestamp=ts, payload=payload, meta=ref)
                elif kind == "retrieval":
                    docs, cap, digest = _content_attr(attrs, "documents")
                    if cap and isinstance(docs, list):
                        for doc in docs:
                            ledger.add("retrieved_doc", span_id=span.get("span_id"), timestamp=ts, payload=doc, meta={**ref, "source": attrs.get("source")})
                    else:
                        ledger.add("retrieved_doc", span_id=span.get("span_id"), timestamp=ts, payload=docs, content_captured=cap,
                                   hash_override=digest, meta={**ref, "source": attrs.get("source")})
                elif kind == "delegation":
                    message, cap, digest = _content_attr(attrs, "message")
                    sender, receiver = span.get("from_agent_id"), span.get("to_agent_id")
                    if sender and sender in per_agent:
                        per_agent[sender].add("handoff_out", span_id=span.get("span_id"), timestamp=ts, payload=message,
                                              content_captured=cap, hash_override=digest, meta={**ref, "to": receiver})
                    if receiver and receiver in per_agent:
                        target = per_agent[receiver]
                        target.add("handoff_in", span_id=span.get("span_id"), timestamp=ts, payload=message,
                                   content_captured=cap, hash_override=digest, meta={**ref, "from": sender})
                        if sender and sender in per_agent and not target.parent_trajectory_id:
                            target.parent_trajectory_id = per_agent[sender].trajectory_id
            else:  # end of an action or llm_call span
                if kind == "llm_call":
                    response, cap, digest = _content_attr(attrs, "response")
                    if cap or digest:
                        body = response
                        if isinstance(response, dict):
                            body = response.get("content") if "content" in response else response
                        if isinstance(body, dict) or (isinstance(body, str) and body.strip()) or body is None and not cap:
                            ledger.add("agent_output", span_id=span.get("span_id"), timestamp=ts, payload=body if cap else None,
                                       content_captured=cap, hash_override=digest, meta=ref)
                        elif isinstance(body, list):
                            ledger.add("agent_output", span_id=span.get("span_id"), timestamp=ts, payload=_message_text(body), meta=ref)
                else:
                    result, cap, digest = _content_attr(attrs, "result")
                    status = "error" if span.get("status") == "error" or span.get("enforcement") == "denied" else "ok"
                    meta = {**ref, "status": status, "call_id": span.get("span_id"), "enforcement": span.get("enforcement")}
                    if cap or digest or status == "error":
                        ledger.add("tool_result", span_id=span.get("span_id"), timestamp=ts, tool_name=span.get("tool"),
                                   payload=result if cap else None, content_captured=cap, hash_override=digest, meta=meta)
        for ledger in per_agent.values():
            if ledger.entries and ledger.redacted:
                ledger.warnings.append("content not captured: configure(capture_content=True) to record prompts, responses and payloads")
            ledgers.append(ledger)
    return ledgers


def ledgers_from_trace_dir(path: str | Path) -> list[Ledger]:
    from ..runtime.reader import TraceReader

    target = Path(path)
    if target.is_file():
        reader = TraceReader(target.parent)
        spans = [s for s in reader.spans() if s.get("_trace_file") == target.name]
    else:
        reader = TraceReader(target)
        spans = list(reader.spans())
    ledgers = ledgers_from_spans(spans)
    for warning in reader.stats.warnings:
        for ledger in ledgers:
            ledger.warnings.append(warning)
    return ledgers


# --- builder 2: OpenTelemetry GenAI spans -----------------------------------------------

def _otlp_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            raw = value[key]
            return int(raw) if key == "intValue" and isinstance(raw, str) and raw.lstrip("-").isdigit() else raw
    if "arrayValue" in value:
        return [_otlp_value(v) for v in (value["arrayValue"].get("values") or [])]
    if "kvlistValue" in value:
        return {kv["key"]: _otlp_value(kv.get("value")) for kv in (value["kvlistValue"].get("values") or [])}
    return value


def _otel_attrs(raw: Any) -> dict:
    if isinstance(raw, dict):
        return {str(k): _maybe_json(v) for k, v in raw.items()}
    out: dict = {}
    for item in raw or []:
        if isinstance(item, dict) and "key" in item:
            out[str(item["key"])] = _maybe_json(_otlp_value(item.get("value")))
    return out


def _flatten_otel(document: Any) -> list[dict]:
    """Spans as flat dicts from an OTLP JSON export, a list of spans, or a
    dict with a ``spans`` list."""
    spans: list[dict] = []
    if isinstance(document, dict) and "resourceSpans" in document:
        for resource in document["resourceSpans"]:
            resource_attrs = _otel_attrs((resource.get("resource") or {}).get("attributes"))
            for scope in resource.get("scopeSpans") or resource.get("instrumentationLibrarySpans") or []:
                for span in scope.get("spans") or []:
                    row = dict(span)
                    row["_resource"] = resource_attrs
                    spans.append(row)
    elif isinstance(document, dict) and isinstance(document.get("spans"), list):
        spans = [dict(s) for s in document["spans"]]
    elif isinstance(document, list):
        spans = [dict(s) for s in document if isinstance(s, dict)]
    out = []
    for span in spans:
        attrs = _otel_attrs(span.get("attributes"))
        events = []
        for event in span.get("events") or []:
            events.append({"name": event.get("name"), "attributes": _otel_attrs(event.get("attributes"))})
        status = span.get("status")
        code = status.get("code") if isinstance(status, dict) else status
        error = code in (2, "2", "ERROR", "STATUS_CODE_ERROR", "error")
        out.append({
            "name": span.get("name"), "span_id": span.get("spanId") or span.get("span_id") or span.get("context", {}).get("span_id"),
            "trace_id": span.get("traceId") or span.get("trace_id") or span.get("context", {}).get("trace_id"),
            "parent_span_id": span.get("parentSpanId") or span.get("parent_span_id") or span.get("parent_id"),
            "start": str(span.get("startTimeUnixNano") or span.get("start_time_unix_nano") or span.get("start_time") or ""),
            "end": str(span.get("endTimeUnixNano") or span.get("end_time_unix_nano") or span.get("end_time") or ""),
            "attrs": attrs, "events": events, "error": error, "resource": span.get("_resource") or {},
        })
    return out


def _genai_messages(ledger: Ledger, messages: Any, *, span_id: str | None, ts: str, direction: str, seen: set[str]) -> None:
    messages = _maybe_json(messages)
    if isinstance(messages, dict):
        messages = [messages]
    if not isinstance(messages, list):
        if isinstance(messages, str) and messages.strip():
            kind = "agent_output" if direction == "output" else "user_input"
            ledger.add(kind, span_id=span_id, timestamp=ts, payload=messages)
        return
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or msg.get("type") or ("assistant" if direction == "output" else "user")).lower()
        parts = msg.get("parts")
        if parts is None:
            parts = [{"type": "text", "content": msg.get("content")}]
            for call in msg.get("tool_calls") or []:
                parts.append({"type": "tool_call", **call})
        for part in parts:
            if not isinstance(part, dict):
                part = {"type": "text", "content": part}
            ptype = part.get("type") or "text"
            if ptype == "tool_call":
                args = _maybe_json(part.get("arguments") if "arguments" in part else part.get("args"))
                name = part.get("name") or (part.get("function") or {}).get("name")
                ledger.add("tool_call", span_id=span_id, timestamp=ts, tool_name=name, payload=args,
                           meta={"call_id": part.get("id"), "from": "messages"})
            elif ptype == "tool_call_response":
                body = _maybe_json(part.get("response") if "response" in part else part.get("result", part.get("content")))
                ledger.add("tool_result", span_id=span_id, timestamp=ts, tool_name=part.get("name"), payload=body,
                           meta={"call_id": part.get("id"), "status": "ok", "from": "messages"})
            else:
                text = _message_text(part.get("content") if "content" in part else part.get("text"))
                if not text:
                    continue
                digest = payload_hash(text)
                if role in ("system", "developer"):
                    kind = "system_prompt"
                elif role in ("user", "human"):
                    kind = "user_input"
                elif role == "tool":
                    kind = "tool_result"
                else:
                    kind = "agent_output"
                marker = f"{kind}:{digest}"
                if kind != "agent_output" and marker in seen:
                    continue
                if kind == "agent_output" and direction == "input":
                    continue  # the agent's earlier words, already recorded when produced
                seen.add(marker)
                ledger.add(kind, span_id=span_id, timestamp=ts, payload=text,
                           meta={"call_id": msg.get("tool_call_id")} if kind == "tool_result" else {})


def ledgers_from_otel(document: Any) -> list[Ledger]:
    """Ledgers from OpenTelemetry GenAI spans (OTLP JSON or a span list).
    Reads the current conventions (``gen_ai.input.messages``,
    ``gen_ai.output.messages``, ``gen_ai.tool.call.arguments`` and
    ``.result``) and the older event and attribute forms
    (``gen_ai.prompt`` and ``gen_ai.completion``)."""
    spans = _flatten_otel(document)
    by_trace: dict[str, list[dict]] = {}
    for span in spans:
        a = span["attrs"]
        key = str(a.get("gen_ai.conversation.id") or a.get("session.id") or span.get("trace_id") or "no-trace")
        by_trace.setdefault(key, []).append(span)
    ledgers: list[Ledger] = []
    for trajectory_id, rows in by_trace.items():
        rows.sort(key=lambda s: (len(s["start"]), s["start"]))
        agent = next((str(s["attrs"].get(k)) for s in rows for k in ("gen_ai.agent.id", "gen_ai.agent.name") if s["attrs"].get(k)), None)
        if not agent:
            agent = next((str(s["resource"].get("service.name")) for s in rows if s["resource"].get("service.name")), None)
        model = next((str(s["attrs"]["gen_ai.request.model"]) for s in rows if s["attrs"].get("gen_ai.request.model")), None)
        ledger = Ledger(trajectory_id=trajectory_id, agent_id=agent, model_id=model, built_from="otel")
        seen: set[str] = set()
        for span in rows:
            a = span["attrs"]
            op = str(a.get("gen_ai.operation.name") or "")
            name = str(span.get("name") or "")
            ts = span["start"]
            if a.get("gen_ai.system_instructions") is not None:
                for item in (_maybe_json(a["gen_ai.system_instructions"]) if not isinstance(a["gen_ai.system_instructions"], list) else a["gen_ai.system_instructions"]) or []:
                    text = _message_text(item.get("content") if isinstance(item, dict) else item)
                    marker = f"system_prompt:{payload_hash(text)}"
                    if text and marker not in seen:
                        seen.add(marker)
                        ledger.add("system_prompt", span_id=span["span_id"], timestamp=ts, payload=text)
            if op == "execute_tool" or name.startswith("execute_tool") or a.get("gen_ai.tool.name"):
                tool = a.get("gen_ai.tool.name") or name.replace("execute_tool", "").strip() or None
                call_id = a.get("gen_ai.tool.call.id")
                ledger.add("tool_call", span_id=span["span_id"], timestamp=ts, tool_name=tool,
                           payload=_maybe_json(a.get("gen_ai.tool.call.arguments")), meta={"call_id": call_id})
                status = "error" if span["error"] else "ok"
                result = _maybe_json(a.get("gen_ai.tool.call.result"))
                if result is not None or status == "error":
                    ledger.add("tool_result", span_id=span["span_id"], timestamp=span["end"] or ts, tool_name=tool, payload=result,
                               meta={"call_id": call_id, "status": status})
                continue
            if a.get("gen_ai.input.messages") is not None:
                _genai_messages(ledger, a["gen_ai.input.messages"], span_id=span["span_id"], ts=ts, direction="input", seen=seen)
            elif a.get("gen_ai.prompt") is not None:
                _genai_messages(ledger, a["gen_ai.prompt"], span_id=span["span_id"], ts=ts, direction="input", seen=seen)
            for event in span["events"]:
                ea = event["attributes"]
                if event["name"] == "gen_ai.content.prompt" or "gen_ai.prompt" in ea:
                    _genai_messages(ledger, ea.get("gen_ai.prompt"), span_id=span["span_id"], ts=ts, direction="input", seen=seen)
                if event["name"] in ("gen_ai.user.message", "gen_ai.system.message"):
                    text = _message_text(ea.get("content"))
                    kind = "system_prompt" if event["name"].startswith("gen_ai.system") else "user_input"
                    marker = f"{kind}:{payload_hash(text)}"
                    if text and marker not in seen:
                        seen.add(marker)
                        ledger.add(kind, span_id=span["span_id"], timestamp=ts, payload=text)
                if event["name"] == "gen_ai.tool.message":
                    ledger.add("tool_result", span_id=span["span_id"], timestamp=ts, payload=_maybe_json(ea.get("content")),
                               meta={"call_id": ea.get("id"), "status": "ok"})
            end_ts = span["end"] or ts
            if a.get("gen_ai.output.messages") is not None:
                _genai_messages(ledger, a["gen_ai.output.messages"], span_id=span["span_id"], ts=end_ts, direction="output", seen=seen)
            elif a.get("gen_ai.completion") is not None:
                _genai_messages(ledger, a["gen_ai.completion"], span_id=span["span_id"], ts=end_ts, direction="output", seen=seen)
            for event in span["events"]:
                ea = event["attributes"]
                if event["name"] == "gen_ai.content.completion" or "gen_ai.completion" in ea:
                    _genai_messages(ledger, ea.get("gen_ai.completion"), span_id=span["span_id"], ts=end_ts, direction="output", seen=seen)
                if event["name"] in ("gen_ai.choice", "gen_ai.assistant.message"):
                    message = ea.get("message") if isinstance(ea.get("message"), dict) else ea
                    _genai_messages(ledger, [{"role": "assistant", "content": message.get("content"), "tool_calls": message.get("tool_calls")}],
                                    span_id=span["span_id"], ts=end_ts, direction="output", seen=seen)
        if ledger.entries:
            ledgers.append(ledger)
    return ledgers


# --- builder 3: LangGraph checkpoints -------------------------------------------------

def _lc_message(msg: Any) -> dict | None:
    """A LangChain message as a plain dict: ``type``, ``content``,
    ``tool_calls``, ``tool_call_id``, ``name``, ``status``. Accepts the
    ``model_dump`` form, the ``lc`` constructor form, and role dicts."""
    if not isinstance(msg, dict):
        return None
    if msg.get("lc") == 1 and msg.get("type") == "constructor":
        ident = msg.get("id") or []
        cls = str(ident[-1]) if ident else ""
        kwargs = dict(msg.get("kwargs") or {})
        kind = {"HumanMessage": "human", "AIMessage": "ai", "ToolMessage": "tool", "SystemMessage": "system",
                "AIMessageChunk": "ai", "FunctionMessage": "tool"}.get(cls, kwargs.get("type", "human"))
        kwargs["type"] = kind
        return kwargs
    if "type" in msg or "role" in msg:
        row = dict(msg)
        role = str(row.get("type") or row.get("role")).lower()
        row["type"] = {"user": "human", "assistant": "ai", "function": "tool"}.get(role, role)
        return row
    return None


def _checkpoint_messages(document: Any) -> tuple[list[dict], dict]:
    """(messages, info) from a StateSnapshot dict, a raw checkpoint, a
    ``{"messages": [...]}`` dict, or a list of snapshots (the richest wins)."""
    if isinstance(document, list):
        best: tuple[list[dict], dict] = ([], {})
        for item in document:
            msgs, info = _checkpoint_messages(item)
            if len(msgs) >= len(best[0]):
                best = (msgs, info)
        return best
    if not isinstance(document, dict):
        return [], {}
    info: dict = {}
    config = document.get("config") or {}
    configurable = config.get("configurable") if isinstance(config, dict) else {}
    if isinstance(configurable, dict):
        info["thread_id"] = configurable.get("thread_id")
        info["checkpoint_id"] = configurable.get("checkpoint_id")
    metadata = document.get("metadata") or {}
    if isinstance(metadata, dict):
        info["parents"] = metadata.get("parents")
    for key in ("ts", "created_at"):
        if document.get(key):
            info["ts"] = document[key]
    if document.get("id") and "checkpoint_id" not in info:
        info["checkpoint_id"] = document["id"]
    for holder in (document.get("values"), document.get("channel_values"), (document.get("checkpoint") or {}).get("channel_values") if isinstance(document.get("checkpoint"), dict) else None, document):
        if isinstance(holder, dict) and isinstance(holder.get("messages"), list):
            info.setdefault("thread_id", None)
            return [m for m in (_lc_message(x) for x in holder["messages"]) if m], info
    return [], info


def ledgers_from_langgraph(document: Any, *, agent_id: str | None = None) -> list[Ledger]:
    """One ledger from a LangGraph checkpoint or StateSnapshot (or a list
    of them). Messages give the order: human and system messages are what
    the agent saw, AI tool calls are actions, tool messages are results,
    and AI text is agent output."""
    messages, info = _checkpoint_messages(document)
    trajectory_id = str(info.get("thread_id") or info.get("checkpoint_id") or "langgraph")
    ledger = Ledger(trajectory_id=trajectory_id, agent_id=agent_id, model_id=None, built_from="langgraph")
    ts = str(info.get("ts") or "")
    pending_calls: dict[str, str] = {}
    for i, msg in enumerate(messages):
        kind = msg.get("type")
        ident = msg.get("id") if isinstance(msg.get("id"), str) else f"m{i + 1}"
        content = msg.get("content")
        if kind == "system":
            ledger.add("system_prompt", span_id=ident, timestamp=ts, payload=_message_text(content))
        elif kind == "human":
            ledger.add("user_input", span_id=ident, timestamp=ts, payload=_message_text(content))
        elif kind == "ai":
            meta = msg.get("response_metadata") or {}
            if isinstance(meta, dict) and meta.get("model_name") and not ledger.model_id:
                ledger.model_id = str(meta["model_name"])
            for call in msg.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                name = call.get("name")
                call_id = call.get("id")
                if call_id:
                    pending_calls[str(call_id)] = str(name)
                ledger.add("tool_call", span_id=ident, timestamp=ts, tool_name=name, payload=_maybe_json(call.get("args")),
                           meta={"call_id": call_id})
            text = _message_text(content)
            if text.strip():
                ledger.add("agent_output", span_id=ident, timestamp=ts, payload=text)
        elif kind == "tool":
            call_id = msg.get("tool_call_id")
            name = msg.get("name") or pending_calls.get(str(call_id))
            status = str(msg.get("status") or "success").lower()
            body = _maybe_json(content) if not isinstance(content, list) else _message_text(content)
            error = status in ("error", "failed") or (isinstance(body, str) and body.lower().startswith("error"))
            ledger.add("tool_result", span_id=ident, timestamp=ts, tool_name=name, payload=body,
                       meta={"call_id": call_id, "status": "error" if error else "ok"})
    return [ledger] if ledger.entries else []


# --- entry point ---------------------------------------------------------------------

def detect_source(path: str | Path) -> str:
    target = Path(path)
    if target.is_dir():
        return "sdk"
    if target.suffix == ".jsonl":
        return "sdk"
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "sdk"
    if isinstance(document, dict) and ("resourceSpans" in document or "spans" in document):
        return "otel"
    if isinstance(document, list) and document and isinstance(document[0], dict) and ("attributes" in document[0] or "spanId" in document[0]):
        return "otel"
    return "langgraph"


def build_ledgers(path: str | Path, *, source: str = "auto", agent_id: str | None = None) -> list[Ledger]:
    kind = detect_source(path) if source == "auto" else source
    if kind not in SOURCES:
        raise ValueError(f"unknown ledger source {kind!r}; expected one of {SOURCES}")
    if kind == "sdk":
        return ledgers_from_trace_dir(path)
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if kind == "otel":
        return ledgers_from_otel(document)
    return ledgers_from_langgraph(document, agent_id=agent_id)


def render_ledger(ledger: Ledger) -> str:
    lines = [f"Ledger {ledger.trajectory_id} (agent {ledger.agent_id or 'unknown'}, model {ledger.model_id or 'unknown'}, from {ledger.built_from})"]
    for entry in ledger.entries:
        head = f"{entry.id} {entry.kind:<13}"
        if entry.tool_name:
            head += f" {entry.tool_name}"
        body = entry.text_view.replace("\n", " | ") if entry.content_captured else f"[not captured, sha256 {entry.hash[:12] or 'none'}]"
        if len(body) > 160:
            body = body[:157] + "..."
        lines.append(f"  {head}  {body}")
    for warning in ledger.warnings:
        lines.append(f"  warning: {warning}")
    return "\n".join(lines) + "\n"
