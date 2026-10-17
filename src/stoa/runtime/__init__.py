"""``stoa.runtime`` — the instrumentation SDK for the runtime trace overlay.

Shadow mode, v1: this SDK **observes** agent behavior and writes local JSONL
trace files (``stoa-trace/1.1``). It never blocks, alters, or gates anything
the instrumented code does, and it never makes a network call — traces stay
on the customer's own filesystem, full stop.

1.1 adds, on top of ``configure`` / ``stoa_trace`` / ``stoa_span`` (unchanged):

- ``@guard`` and ``session()``: thin aliases over ``stoa_span`` for tools
  and agent runs, carrying ``side_effect``, ``limit_field`` and a session id;
- ``model_call()``: an ``llm_call`` span with token and cost bookkeeping;
- per-span risk flags in ``attrs.flags`` (flags.py), computed against the
  last scan's ``stoa-registry.json`` when one is found (registry.py);
- a hash chain and signature on every record (chain.py, keys.py), verified
  with ``verify_chain()`` or ``stoa runtime verify``.

Privacy default: **redact-by-default.** Prompt/response bodies and tool
payloads are never recorded unless the caller opts in (``capture_content``),
and even then a ``redaction_hook`` can scrub them first. By default the SDK
records shapes only: SHA-256 hashes and character counts, never content.

Usage::

    from stoa import runtime as stoa_rt

    stoa_rt.configure(trace_dir="stoa-traces", agent_id="a09ff38687e9")

    @stoa_rt.stoa_trace(kind="agent_run")
    def handle(ticket): ...

    with stoa_rt.stoa_span(kind="action", capability="payment_access",
                           integration="stripe", amount=120.0, currency="USD"):
        stripe.Refund.create(...)

Unconfigured (no ``configure()`` call, no ``STOA_TRACE_DIR`` env var), every
decorator and context manager is a zero-cost pass-through. If the trace
directory ever becomes unwritable the exporter warns once and the SDK
becomes a no-op — instrumentation must never crash the customer's agent.

``stoa scan`` and the rest of the static toolchain never import this
package; the CLI loads it lazily inside the ``stoa runtime`` subcommand.
"""

from __future__ import annotations

import asyncio
import atexit
import functools
import hashlib
import hmac as _hmac
import inspect
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from .. import __version__
from .chain import ChainReport, verify_dir
from .exporter import DEFAULT_MAX_FILE_BYTES, JSONLExporter
from .flags import FlagEngine
from .keys import Signer, load_signer
from .registry import RegistryFacts, load_registry_facts
from .spans import SIDE_EFFECTS, build_span, redact_attrs, sha256_text, utc_now_iso

__all__ = [
    "configure", "stoa_trace", "stoa_span", "guard", "session", "model_call",
    "verify_chain", "flush", "shutdown",
]

_ctx_trace_id: ContextVar[str | None] = ContextVar("stoa_trace_id", default=None)
_ctx_span_id: ContextVar[str | None] = ContextVar("stoa_span_id", default=None)
_ctx_session_id: ContextVar[str | None] = ContextVar("stoa_session_id", default=None)


class _State:
    exporter: JSONLExporter | None = None
    agent_id: str | None = None
    capture_content: bool = False
    redaction_hook = None
    signer: Signer = Signer()
    registry: RegistryFacts = RegistryFacts()
    flags: FlagEngine | None = None


_state = _State()


def configure(
    trace_dir: str | None = None,
    *,
    agent_id: str | None = None,
    capture_content: bool = False,
    redaction_hook=None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    signing_key: str | None = None,
    registry_path: str | None = None,
    burst_threshold: int = 20,
) -> None:
    """Enable tracing. ``trace_dir`` falls back to ``$STOA_TRACE_DIR``;
    with neither, the SDK stays dormant. Safe to call more than once
    (reconfigures; the previous exporter is flushed and closed).

    ``signing_key`` (or ``$STOA_SIGNING_KEY``) selects the chain's key grade
    (keys.py); ``registry_path`` points at the last scan's
    ``stoa-registry.json`` (found by searching upward when not given) so
    flags can be computed against declared tools and limits. ``agent_id``
    may be the registry id or the agent's declared name.
    """
    try:
        directory = trace_dir or os.environ.get("STOA_TRACE_DIR")
        shutdown()
        if not directory:
            return
        _state.registry = load_registry_facts(registry_path)
        if agent_id and agent_id not in _state.registry.agents:
            agent_id = _state.registry.by_name.get(agent_id, agent_id)
        _state.agent_id = agent_id
        _state.capture_content = bool(capture_content)
        _state.redaction_hook = redaction_hook
        _state.signer = load_signer(signing_key)
        _state.flags = FlagEngine(_state.registry, burst_threshold=burst_threshold)
        _state.exporter = JSONLExporter(
            directory,
            sdk_version=__version__,
            redaction="content" if capture_content else "redacted",
            max_file_bytes=max_file_bytes,
            signer=_state.signer,
        )
        atexit.register(shutdown)
    except Exception:  # noqa: BLE001 - never raise into customer code
        _state.exporter = None


def flush(timeout: float = 5.0) -> None:
    """Best-effort drain of buffered spans to disk (useful in tests/exit hooks)."""
    try:
        if _state.exporter is not None:
            _state.exporter.flush(timeout)
    except Exception:  # noqa: BLE001
        pass


def shutdown() -> None:
    """Flush and stop tracing. Idempotent."""
    try:
        exporter, _state.exporter = _state.exporter, None
        if exporter is not None:
            exporter.close()
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def stoa_span(
    kind: str = "action",
    *,
    agent_id: str | None = None,
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
    capture_content: bool | None = None,
    cost: float | None = None,
    cost_currency: str | None = None,
    enforcement: str | None = None,
    _agent_hint: dict | None = None,
    _late: dict | None = None,
    _counterparty: str | None = None,
):
    """Record one span around the enclosed block.

    Exceptions raised by the block always propagate (the span is recorded
    with ``status: "error"``); exceptions raised by the SDK itself never do.
    ``_late`` is a dict the caller may fill while the block runs (amount,
    cost, extra attrs); it is read when the span is built, so ``guard`` and
    ``model_call`` can record what they learn after the call returns.
    """
    if _state.exporter is None or _state.exporter.failed:
        yield None
        return

    try:
        trace_id = _ctx_trace_id.get() or uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        parent_span_id = _ctx_span_id.get()
        trace_token = _ctx_trace_id.set(trace_id)
        span_token = _ctx_span_id.set(span_id)
        start_ts = utc_now_iso()
    except Exception:  # noqa: BLE001
        yield None
        return

    status = "ok"
    try:
        yield span_id
    except BaseException:
        status = "error"
        raise
    finally:
        try:
            _ctx_span_id.reset(span_token)
            _ctx_trace_id.reset(trace_token)
            capture = (
                _state.capture_content if capture_content is None else bool(capture_content)
            )
            late = _late or {}
            span = build_span(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                kind=kind,
                start_ts=start_ts,
                end_ts=utc_now_iso(),
                status=status,
                redaction="content" if capture else "redacted",
                agent_id=agent_id or _state.agent_id,
                agent_hint=_agent_hint,
                capability=capability,
                integration=integration,
                provider=provider,
                model=model,
                tool=tool,
                amount=late.get("amount", amount),
                currency=late.get("currency", currency),
                approved_by=approved_by,
                approval_method=approval_method,
                approval_span_id=approval_span_id,
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id,
                # User attrs go through redaction; the SDK's own bookkeeping
                # (side_effect, token counts, schema hashes) is never content.
                attrs={**redact_attrs(attrs, capture, _state.redaction_hook), **(late.get("attrs") or {})},
                session_id=_ctx_session_id.get(),
                cost=late.get("cost", cost),
                cost_currency=late.get("cost_currency", cost_currency),
                enforcement=late.get("enforcement", enforcement),
            )
            # Flags are computed on the record about to be written, from the
            # agent's recent window and the registry facts, and travel in attrs.
            flags = _state.flags.compute(span, counterparty=_counterparty) if _state.flags else []
            manual = list(late.get("flags") or [])
            if flags or manual:
                span.setdefault("attrs", {})["flags"] = sorted(set(flags) | set(manual))
            _state.exporter.emit(span)
        except Exception:  # noqa: BLE001 - never raise into customer code
            pass


def stoa_trace(
    agent_id: str | None = None,
    *,
    kind: str = "agent_run",
    capability: str | None = None,
    integration: str | None = None,
    provider: str | None = None,
    model: str | None = None,
):
    """Decorator form of :func:`stoa_span` for whole functions.

    When no ``agent_id`` is given (here or in :func:`configure`), the span
    carries an ``agent_hint`` (module + qualname) so ``stoa runtime analyze``
    can suggest a registry match instead of dropping the span.
    """

    def decorate(func):
        try:
            hint = {"module": func.__module__, "qualname": func.__qualname__}
        except Exception:  # noqa: BLE001
            hint = None

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with stoa_span(
                kind,
                agent_id=agent_id,
                capability=capability,
                integration=integration,
                provider=provider,
                model=model,
                _agent_hint=None if (agent_id or _state.agent_id) else hint,
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorate


# --- 1.1: guard, session, model_call, verify_chain ------------------------------


class _Late(dict):
    """The mutable slot a span handle writes into while its block runs."""


class _Session:
    """Handle yielded by :func:`session`: record approvals and flags."""

    def __init__(self, session_id: str, late: _Late) -> None:
        self.id = session_id
        self._late = late

    def approval(self, actor: str, channel: str, granted: bool = True, latency_ms: int | None = None) -> str | None:
        """Record a human (or system) decision as an ``approval`` span and
        return its span id, so the next guarded call can cite it. The actor
        is never stored in clear: it is keyed under the signing key when
        there is one, hashed otherwise."""
        try:
            attrs = {"granted": bool(granted), "actor_type": "human"}
            if latency_ms is not None:
                attrs["latency_ms"] = int(latency_ms)
            with stoa_span(
                "approval", approved_by=_actor_ref(actor), approval_method=channel, attrs=attrs,
            ) as span_id:
                return span_id
        except Exception:  # noqa: BLE001
            return None

    def flag(self, name: str, detail: dict | None = None) -> None:
        """Attach a caller-chosen flag to the session's own span."""
        try:
            self._late.setdefault("flags", []).append(str(name))
            if detail:
                self._late.setdefault("attrs", {})[f"flag_{name}_sha256"] = sha256_text(repr(detail))
        except Exception:  # noqa: BLE001
            pass


def _actor_ref(actor: str) -> str:
    try:
        signer = _state.signer
        if signer.grade == "hmac-sha256":
            return _hmac.new(signer._secret, actor.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    except Exception:  # noqa: BLE001
        pass
    return sha256_text(actor)[:32]


@contextmanager
def session(user_ref: str | None = None, metadata: dict | None = None, *, agent_id: str | None = None):
    """One agent run. Spans inside share its ``session_id``; the session's
    own ``agent_run`` span closes with the block."""
    if _state.exporter is None or _state.exporter.failed:
        yield _Session("", _Late())
        return
    session_id = uuid.uuid4().hex[:16]
    token = _ctx_session_id.set(session_id)
    late = _Late()
    if user_ref:
        late["attrs"] = {"user_ref": _actor_ref(user_ref)}
    metadata_attrs = {f"meta_{key}": value for key, value in (metadata or {}).items()}
    try:
        with stoa_span("agent_run", agent_id=agent_id, attrs=metadata_attrs, _late=late):
            yield _Session(session_id, late)
    finally:
        _ctx_session_id.reset(token)


def guard(
    side_effect: str = "write",
    limit_field: str | None = None,
    name: str | None = None,
    *,
    capability: str | None = None,
    integration: str | None = None,
    currency: str = "USD",
    counterparty_field: str | None = None,
    approval_field: str | None = None,
):
    """Decorate a tool. Records an ``action`` span named after the function
    (or ``name``), with ``side_effect`` in attrs, the numeric argument named
    by ``limit_field`` as the span's ``amount``, and the argument named by
    ``approval_field`` (a span id from ``session.approval``) as its
    ``approval_span_id``. Works on sync and async functions; the function's
    signature and docstring are preserved; the SDK never raises into it."""
    if side_effect not in SIDE_EFFECTS:
        side_effect = "write"

    def decorate(func):
        tool_name = name or getattr(func, "__name__", "tool")
        try:
            signature = inspect.signature(func)
        except (TypeError, ValueError):
            signature = None

        def bound(args, kwargs) -> dict:
            try:
                if signature is None:
                    return dict(kwargs)
                ba = signature.bind_partial(*args, **kwargs)
                return dict(ba.arguments)
            except Exception:  # noqa: BLE001
                return dict(kwargs)

        def prepare(args, kwargs):
            values = bound(args, kwargs)
            late = _Late()
            amount = values.get(limit_field) if limit_field else None
            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                amount = None
            counterparty = values.get(counterparty_field) if counterparty_field else None
            approval_id = values.get(approval_field) if approval_field else None
            late["attrs"] = {"side_effect": side_effect, "args_schema_hash": _schema_hash(values)}
            if limit_field:
                late["attrs"]["limit_field"] = limit_field
            return late, amount, counterparty, approval_id, None

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                late, amount, counterparty, approval_id, attrs = prepare(args, kwargs)
                with stoa_span(
                    "action", tool=tool_name, capability=capability, integration=integration,
                    amount=amount, currency=currency, approval_span_id=approval_id if isinstance(approval_id, str) else None,
                    attrs=attrs, _late=late,
                    _counterparty=sha256_text(str(counterparty))[:16] if counterparty is not None else None,
                ):
                    return await func(*args, **kwargs)
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            late, amount, counterparty, approval_id, attrs = prepare(args, kwargs)
            with stoa_span(
                "action", tool=tool_name, capability=capability, integration=integration,
                amount=amount, currency=currency, approval_span_id=approval_id if isinstance(approval_id, str) else None,
                attrs=attrs, _late=late,
                _counterparty=sha256_text(str(counterparty))[:16] if counterparty is not None else None,
            ):
                return func(*args, **kwargs)
        return wrapper

    return decorate


def _schema_hash(values: dict) -> str:
    """Hash of the argument names and types, never the values."""
    try:
        shape = ",".join(f"{k}:{type(v).__name__}" for k, v in sorted(values.items()))
        return sha256_text(shape)[:16]
    except Exception:  # noqa: BLE001
        return ""


class _ModelCall:
    def __init__(self, late: _Late) -> None:
        self._late = late

    def record(self, *, tokens_in: int | None = None, tokens_out: int | None = None,
               cost_usd: float | None = None, tool_calls_requested=None) -> None:
        try:
            attrs = self._late.setdefault("attrs", {})
            if tokens_in is not None:
                attrs["gen_ai.usage.input_tokens"] = int(tokens_in)
            if tokens_out is not None:
                attrs["gen_ai.usage.output_tokens"] = int(tokens_out)
            if tool_calls_requested:
                attrs["tool_calls_requested"] = ",".join(str(t) for t in tool_calls_requested)
            if cost_usd is not None:
                self._late["cost"] = float(cost_usd)
                self._late["cost_currency"] = "USD"
        except Exception:  # noqa: BLE001
            pass


@contextmanager
def model_call(provider: str, model: str, *, agent_id: str | None = None):
    """An ``llm_call`` span. Call ``record(...)`` on the handle with what the
    provider returned; prompt and response content are never stored."""
    late = _Late()
    with stoa_span("llm_call", agent_id=agent_id, provider=provider, model=model, _late=late):
        yield _ModelCall(late)


def verify_chain(traces_dir: str, key: str | None = None) -> ChainReport:
    """Walk every trace file's hash chain and signatures (chain.py)."""
    flush()
    return verify_dir(traces_dir, key)
