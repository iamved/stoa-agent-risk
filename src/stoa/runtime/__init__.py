"""``stoa.runtime`` — the instrumentation SDK for the runtime trace overlay.

Shadow mode, v1: this SDK **observes** agent behavior and writes local JSONL
trace files (``stoa-trace/1.0``). It never blocks, alters, or gates anything
the instrumented code does, and it never makes a network call — traces stay
on the customer's own filesystem, full stop.

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

import atexit
import functools
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from .. import __version__
from .exporter import DEFAULT_MAX_FILE_BYTES, JSONLExporter
from .spans import build_span, redact_attrs, utc_now_iso

__all__ = ["configure", "stoa_trace", "stoa_span", "flush", "shutdown"]

_ctx_trace_id: ContextVar[str | None] = ContextVar("stoa_trace_id", default=None)
_ctx_span_id: ContextVar[str | None] = ContextVar("stoa_span_id", default=None)


class _State:
    exporter: JSONLExporter | None = None
    agent_id: str | None = None
    capture_content: bool = False
    redaction_hook = None


_state = _State()


def configure(
    trace_dir: str | None = None,
    *,
    agent_id: str | None = None,
    capture_content: bool = False,
    redaction_hook=None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> None:
    """Enable tracing. ``trace_dir`` falls back to ``$STOA_TRACE_DIR``;
    with neither, the SDK stays dormant. Safe to call more than once
    (reconfigures; the previous exporter is flushed and closed)."""
    try:
        directory = trace_dir or os.environ.get("STOA_TRACE_DIR")
        shutdown()
        if not directory:
            return
        _state.agent_id = agent_id
        _state.capture_content = bool(capture_content)
        _state.redaction_hook = redaction_hook
        _state.exporter = JSONLExporter(
            directory,
            sdk_version=__version__,
            redaction="content" if capture_content else "redacted",
            max_file_bytes=max_file_bytes,
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
    _agent_hint: dict | None = None,
):
    """Record one span around the enclosed block.

    Exceptions raised by the block always propagate (the span is recorded
    with ``status: "error"``); exceptions raised by the SDK itself never do.
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
                amount=amount,
                currency=currency,
                approved_by=approved_by,
                approval_method=approval_method,
                approval_span_id=approval_span_id,
                from_agent_id=from_agent_id,
                to_agent_id=to_agent_id,
                attrs=redact_attrs(attrs, capture, _state.redaction_hook),
            )
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
