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
import json
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from .. import __version__
from .chain import ChainReport, verify_dir
from .exporter import DEFAULT_MAX_FILE_BYTES, JSONLExporter
from .flags import FlagEngine
from .keys import Signer, load_signer
from .policy import Policy, StoaDenied, decide, load_policy
from ..policy.conditions import WindowStore
from ..policy.killswitch import KillSwitch
from .registry import RegistryFacts, load_registry_facts
from .spans import SIDE_EFFECTS, build_span, redact_attrs, sha256_text, utc_now_iso

__all__ = [
    "configure", "stoa_trace", "stoa_span", "guard", "session", "model_call",
    "on_approval", "check_input", "check_output", "StoaDenied", "verify_chain", "flush", "shutdown",
]
# ``_Late`` and ``_schema_hash`` are shared with stoa.runtime.integrations only.

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
    policy: Policy = Policy()
    fail_open: bool = True
    approval_hook = None
    mirror = None
    store: WindowStore | None = None
    killswitch: KillSwitch | None = None
    trace_dir: str | None = None


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
    policy: str | None = None,
    fail_open: bool = True,
    exporter: str = "jsonl",
    otlp_endpoint: str | None = None,
) -> None:
    """Enable tracing. ``trace_dir`` falls back to ``$STOA_TRACE_DIR``;
    with neither, the SDK stays dormant. Safe to call more than once
    (reconfigures; the previous exporter is flushed and closed).

    ``signing_key`` (or ``$STOA_SIGNING_KEY``) selects the chain's key grade
    (keys.py); ``registry_path`` points at the last scan's
    ``stoa-registry.json`` (found by searching upward when not given) so
    flags can be computed against declared tools and limits. ``agent_id``
    may be the registry id or the agent's declared name. ``policy`` (or
    ``$STOA_POLICY``, or a ``stoa.policy.toml`` found by searching upward)
    is evaluated on every guarded call; with ``fail_open`` (the default)
    only rules that set ``enforce`` can deny a call. ``exporter="otlp"``
    keeps the JSONL file and mirrors each span to ``otlp_endpoint`` (or
    ``$OTEL_EXPORTER_OTLP_ENDPOINT``), needing the ``[runtime]`` extra.
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
        _state.policy = load_policy(policy or os.environ.get("STOA_POLICY"))
        _state.fail_open = bool(fail_open)
        _state.trace_dir = directory
        # Stateful conditions (window sums and counts) and the kill switch
        # read small files beside the traces; both are stat-cached, never polled.
        _state.store = WindowStore(os.path.join(directory, ".policy-window.json"))
        _state.killswitch = KillSwitch()
        _state.exporter = JSONLExporter(
            directory,
            sdk_version=__version__,
            redaction="content" if capture_content else "redacted",
            max_file_bytes=max_file_bytes,
            signer=_state.signer,
        )
        if exporter == "otlp":
            from .otel import OtlpMirror

            _state.mirror = OtlpMirror(otlp_endpoint)
            if not _state.mirror.active:
                _state.mirror = None
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
        mirror, _state.mirror = _state.mirror, None
        if mirror is not None:
            mirror.close()
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
            # A span closed on another thread (a callback handler, the MCP
            # proxy's reader) cannot reset this thread's context tokens; the
            # record is still written.
            _ctx_span_id.reset(span_token)
            _ctx_trace_id.reset(trace_token)
        except Exception:  # noqa: BLE001
            pass
        try:
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
            if _state.mirror is not None:
                _state.mirror.emit(span)
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
            late = _Late(attrs={"granted": bool(granted), "actor_type": "human"})
            if latency_ms is not None:
                late["attrs"]["latency_ms"] = int(latency_ms)
            with stoa_span(
                "approval", approved_by=_actor_ref(actor), approval_method=channel, _late=late,
            ) as span_id:
                return span_id
        except Exception:  # noqa: BLE001
            return None

    def user_input(self, text: str) -> None:
        """Record what the user asked, for Hallucination DetectR's ledger.
        Stored only under ``capture_content=True`` (through the redaction
        hook); otherwise nothing is written."""
        try:
            if not isinstance(text, str):
                return
            attrs = self._late.setdefault("attrs", {})
            if _state.capture_content:
                inputs = json.loads(attrs["user_inputs"]) if "user_inputs" in attrs else []
                inputs.append(_content(text))
                attrs["user_inputs"] = json.dumps(inputs, ensure_ascii=False)
            else:
                _put_content(attrs, "user_inputs", text)
        except Exception:  # noqa: BLE001
            pass

    def system_prompt(self, text: str) -> None:
        """Record the instructions the agent runs under; content mode only."""
        try:
            if isinstance(text, str):
                _put_content(self._late.setdefault("attrs", {}), "system_prompt", text)
        except Exception:  # noqa: BLE001
            pass

    def retrieved(self, documents, *, source: str | None = None) -> None:
        """Record retrieved documents as a ``retrieval`` span (each one a
        ledger entry). Content mode only; otherwise only the count is kept."""
        try:
            docs = list(documents) if not isinstance(documents, (str, dict)) else [documents]
            attrs: dict = {"document_count": len(docs)}
            if source:
                attrs["source"] = source
            late = _Late(attrs=attrs)
            if _state.capture_content:
                late["attrs"]["documents"] = json.dumps([_content(d) if isinstance(d, str) else d for d in docs], ensure_ascii=False, default=str)
            else:
                _put_content(late["attrs"], "documents", json.dumps(docs, ensure_ascii=False, default=str))
            with stoa_span("retrieval", _late=late):
                pass
        except Exception:  # noqa: BLE001
            pass

    def flag(self, name: str, detail: dict | None = None) -> None:
        """Attach a caller-chosen flag to the session's own span."""
        try:
            self._late.setdefault("flags", []).append(str(name))
            if detail:
                self._late.setdefault("attrs", {})[f"flag_{name}_sha256"] = sha256_text(repr(detail))
        except Exception:  # noqa: BLE001
            pass


def _content(text: str) -> str:
    """Text the customer opted to record, through their redaction hook."""
    try:
        return _state.redaction_hook(text) if _state.redaction_hook else text
    except Exception:  # noqa: BLE001
        return text


def _put_content(attrs: dict, name: str, text: str) -> None:
    """Record a content attr for Hallucination DetectR's ledger: in clear
    (through the redaction hook) under capture_content, else as a SHA-256
    plus length, so the ledger still knows the entry existed and can be
    verified against the trace without ever holding the text."""
    if _state.capture_content:
        attrs[name] = _content(text)
    else:
        attrs[f"{name}_sha256"] = sha256_text(text)
        attrs[f"{name}_chars"] = len(text)


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
            _put_content(late["attrs"], "args", json.dumps({k: v for k, v in values.items() if k != "self"}, ensure_ascii=False, default=str))
            approval_id = _apply_policy(late, tool_name, values, side_effect, amount, approval_id if isinstance(approval_id, str) else None)
            return late, amount, counterparty, approval_id, None

        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                late, amount, counterparty, approval_id, attrs = prepare(args, kwargs)
                with stoa_span(
                    "action", tool=tool_name, capability=capability, integration=integration,
                    amount=amount, currency=currency, approval_span_id=approval_id,
                    attrs=attrs, _late=late,
                    _counterparty=sha256_text(str(counterparty))[:16] if counterparty is not None else None,
                ):
                    _raise_if_denied(late)
                    result = await func(*args, **kwargs)
                    _record_result(late, result)
                    return result
            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            late, amount, counterparty, approval_id, attrs = prepare(args, kwargs)
            with stoa_span(
                "action", tool=tool_name, capability=capability, integration=integration,
                amount=amount, currency=currency, approval_span_id=approval_id,
                attrs=attrs, _late=late,
                _counterparty=sha256_text(str(counterparty))[:16] if counterparty is not None else None,
            ):
                _raise_if_denied(late)
                result = func(*args, **kwargs)
                _record_result(late, result)
                return result
        return wrapper

    return decorate


def _record_result(late: _Late, result) -> None:
    """What the tool returned, for the ledger; content mode only."""
    try:
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        _put_content(late.setdefault("attrs", {}), "result", text)
    except Exception:  # noqa: BLE001
        pass


def on_approval(hook) -> None:
    """Register the function a ``require_approval`` decision calls:
    ``hook(tool, args, rule_id) -> bool``. A true result records an approval
    span the guarded call then cites; false or an exception records a
    denial. Without a hook the decision is recorded and the call proceeds."""
    _state.approval_hook = hook


def _policy_namespace(tool_name: str, values: dict, side_effect: str, amount, approval_id: str | None) -> dict:
    facts = _state.registry.for_agent(_state.agent_id)
    redacted_args = {}
    for key, value in values.items():
        if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
            redacted_args[key] = value
        else:
            redacted_args[key] = sha256_text(str(value))[:16]
    return {
        "tool": tool_name,
        "args": redacted_args,
        "side_effect": side_effect,
        "amount": amount,
        "approval": {"granted": approval_id is not None, "span_id": approval_id},
        "agent": {
            "id": _state.agent_id, "name": facts.name if facts else None,
            "declared_tools": sorted(facts.tools) if facts else [],
            "max_per_action": facts.max_per_action if facts else None,
        },
        "session": {"id": _ctx_session_id.get()},
    }


def _apply_policy(late: _Late, tool_name: str, values: dict, side_effect: str, amount, approval_id: str | None, *, trigger: str = "tool_call", text: str | None = None) -> str | None:
    """Evaluate the policy for one guarded call and write the outcome into
    the span's attrs and ``enforcement``. Returns the approval span id the
    call should cite (the caller's, or one minted by the approval hook).
    Never raises; a denial is signalled through ``late["denied"]``."""
    try:
        if not _state.policy.rules:
            return approval_id
        namespace = _policy_namespace(tool_name, values, side_effect, amount, approval_id)
        if text is not None:
            namespace["text"] = text
        decisions = decide(_state.policy, namespace, fail_open=_state.fail_open, trigger=trigger, store=_state.store, killswitch=_state.killswitch)
        if not decisions:
            _observe_window(tool_name, values, amount, trigger)
            return approval_id
        attrs = late.setdefault("attrs", {})
        attrs["policy_rules"] = ",".join(d.rule_id for d in decisions)
        attrs["policy_decisions"] = ",".join(d.decision for d in decisions)
        attrs["policy_actions"] = ",".join(d.action or ("block" if d.decision == "deny" else "escalate" if d.decision == "require_approval" else d.decision) for d in decisions)
        masked = [d.rule_id for d in decisions if d.decision == "mask"]
        if masked:
            attrs["policy_masked"] = ",".join(masked)
        errors = [d for d in decisions if d.error]
        if errors:
            attrs["policy_errors"] = ";".join(f"{d.rule_id}: {d.error}" for d in errors)
        worst = decisions[0]
        for d in decisions:
            if d.decision == "deny" and (d.enforced or worst.decision != "deny"):
                worst = d
            elif d.decision == "require_approval" and worst.decision not in ("deny",) and (d.enforced or worst.decision != "require_approval"):
                worst = d
        if worst.decision == "require_approval" and approval_id is None and _state.approval_hook is not None:
            try:
                granted = bool(_state.approval_hook(tool_name, values, worst.rule_id))
            except Exception:  # noqa: BLE001
                granted = False
            hook_late = _Late(attrs={"granted": granted, "actor_type": "system"})
            with stoa_span("approval", approved_by="policy-hook", approval_method=f"hook:{worst.rule_id}", _late=hook_late) as span_id:
                pass
            if granted:
                approval_id = span_id
                worst = type(worst)(worst.rule_id, "allow", False, f"{worst.reason}; approved through the hook", action="allow")
            else:
                worst = type(worst)(worst.rule_id, "deny", not _state.fail_open or any(r.enforce for r in _state.policy.rules if r.id == worst.rule_id), worst.reason)
        elif worst.decision == "require_approval" and approval_id is None and worst.enforced:
            # Enforced escalation with nobody to ask: fail closed.
            worst = type(worst)(worst.rule_id, "deny", True, f"{worst.reason}; no approval hook registered")
        if worst.decision == "deny" and worst.enforced:
            late["enforcement"] = "denied"
            late["denied"] = (worst.rule_id, worst.reason)
            attrs["policy_denied_by"] = worst.rule_id
        elif worst.decision in ("deny", "require_approval", "observe", "mask") or masked:
            late["enforcement"] = "observed"
        else:
            late["enforcement"] = "allowed"
        if late.get("enforcement") != "denied":
            _observe_window(tool_name, values, amount, trigger)  # a blocked call never counts toward a window
        return approval_id
    except Exception:  # noqa: BLE001
        return approval_id


def _observe_window(tool_name: str, values: dict, amount, trigger: str) -> None:
    if _state.store is None or trigger != "tool_call":
        return
    from datetime import datetime, timezone

    observed = {k: v for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    if amount is not None:
        observed["amount"] = amount
    _state.store.observe(datetime.now(timezone.utc), _state.agent_id or "?", tool_name, observed)


def _check_text(trigger: str, text: str, *, name: str) -> str:
    """Run input or output policies over a piece of text. Records an
    ``action`` span named ``stoa.input`` / ``stoa.output`` with the decision;
    a ``mask`` decision returns the text with identifier shapes replaced;
    an enforced block raises ``StoaDenied``. Content is never recorded."""
    if _state.exporter is None or _state.exporter.failed or not _state.policy.rules:
        return text
    late = _Late(attrs={"side_effect": "read", "text_chars": len(text)})
    _apply_policy(late, name, {}, "read", None, None, trigger=trigger, text=text)
    masked = late.get("attrs", {}).get("policy_masked")
    with stoa_span("action", tool=name, _late=late):
        _raise_if_denied(late)
    if masked:
        from ..policy.conditions import _PII_PATTERNS

        for pattern in _PII_PATTERNS:
            text = pattern.sub("[masked]", text)
    return text


def check_input(text: str) -> str:
    """Evaluate ``trigger = "input"`` policies over untrusted text before the model sees it."""
    try:
        return _check_text("input", text, name="stoa.input")
    except StoaDenied:
        raise
    except Exception:  # noqa: BLE001
        return text


def check_output(text: str) -> str:
    """Evaluate ``trigger = "output"`` policies over the agent's reply; masks when a policy says so."""
    try:
        return _check_text("output", text, name="stoa.output")
    except StoaDenied:
        raise
    except Exception:  # noqa: BLE001
        return text


def _raise_if_denied(late: _Late) -> None:
    denied = late.get("denied")
    if denied:
        raise StoaDenied(denied[0], denied[1])


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
               cost_usd: float | None = None, tool_calls_requested=None,
               prompt=None, response=None, system: str | None = None) -> None:
        try:
            attrs = self._late.setdefault("attrs", {})
            # Prompt, response and system text feed Hallucination DetectR's
            # ledger: in clear under capture_content (through the redaction
            # hook), otherwise as hash and length only.
            if prompt is not None:
                _put_content(attrs, "prompt", prompt if isinstance(prompt, str) else json.dumps(prompt, ensure_ascii=False, default=str))
            if response is not None:
                _put_content(attrs, "response", response if isinstance(response, str) else json.dumps(response, ensure_ascii=False, default=str))
            if system is not None:
                _put_content(attrs, "system", str(system))
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
    provider returned. Prompt and response content are stored only when
    ``configure(capture_content=True)``; in redacted mode only a hash and a
    length are kept."""
    late = _Late()
    with stoa_span("llm_call", agent_id=agent_id, provider=provider, model=model, _late=late):
        yield _ModelCall(late)


def verify_chain(traces_dir: str, key: str | None = None) -> ChainReport:
    """Walk every trace file's hash chain and signatures (chain.py)."""
    flush()
    return verify_dir(traces_dir, key)
