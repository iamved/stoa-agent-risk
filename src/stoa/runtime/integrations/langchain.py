"""LangChain / LangGraph adapter: ``StoaCallbackHandler``.

Usage::

    from stoa.runtime.integrations.langchain import StoaCallbackHandler
    graph.invoke(state, config={"callbacks": [StoaCallbackHandler()]})

The handler subclasses LangChain's ``BaseCallbackHandler`` when
``langchain_core`` is importable and a plain object otherwise, so the
module always imports. It opens an ``action`` span per tool run and an
``llm_call`` span per model call, closes them on end or error, and reads
token usage from the LLM result when the provider reports it. Tool inputs
and prompts are never recorded: an action span carries the tool name, the
argument schema hash and the ``side_effect`` the caller declared for that
tool (``side_effects={"issue_refund": "payment"}``), and the numeric field
named in ``limit_fields`` becomes the span's ``amount``.

LangGraph ``interrupt()``: when a chain errors with ``GraphInterrupt`` the
handler records an ``approval`` span with ``granted = false`` and
``pending = true`` and remembers the thread; the next ``on_chain_start`` for
the same thread records the resume as a granted approval the following
tool span cites. That is the human-in-the-loop pattern LangGraph documents,
seen from the outside, with no content captured.
"""

from __future__ import annotations

import contextvars
import warnings
from contextlib import ExitStack
from typing import Any

from .. import _Late, stoa_span

try:  # optional dependency
    from langchain_core.callbacks import BaseCallbackHandler as _Base
except Exception:  # noqa: BLE001
    _Base = object  # type: ignore[assignment,misc]
    _warned = False


def _is_interrupt(error: BaseException) -> bool:
    return type(error).__name__ in ("GraphInterrupt", "NodeInterrupt") or any(
        type(e).__name__ == "GraphInterrupt" for e in getattr(error, "exceptions", []) or []
    )


class StoaCallbackHandler(_Base):  # type: ignore[misc]
    """Record LangChain tool and model activity as stoa spans."""

    raise_error = False
    run_inline = True

    def __init__(
        self,
        *,
        agent_id: str | None = None,
        side_effects: dict[str, str] | None = None,
        limit_fields: dict[str, str] | None = None,
        capabilities: dict[str, str] | None = None,
        integrations: dict[str, str] | None = None,
        currency: str = "USD",
    ) -> None:
        if _Base is object and not globals().get("_warned"):
            globals()["_warned"] = True
            warnings.warn(
                "stoa.runtime: langchain_core is not installed; StoaCallbackHandler records nothing.",
                RuntimeWarning, stacklevel=2,
            )
        self.agent_id = agent_id
        self.side_effects = side_effects or {}
        self.limit_fields = limit_fields or {}
        self.capabilities = capabilities or {}
        self.integrations = integrations or {}
        self.currency = currency
        self._open: dict[Any, tuple[ExitStack, _Late, contextvars.Context]] = {}
        self._pending_approval: dict[Any, str | None] = {}
        self._last_approval: dict[Any, str] = {}

    # --- helpers ----------------------------------------------------------------

    def _start(self, run_id, kind: str, **kwargs) -> None:
        # Frameworks may call start and end on different threads; each span
        # lives in its own copied context so neither thread's context changes.
        try:
            stack = ExitStack()
            late = _Late()
            ctx = contextvars.copy_context()
            span_id = ctx.run(stack.enter_context, stoa_span(kind, agent_id=self.agent_id, _late=late, **kwargs))
            late["span_id"] = span_id
            self._open[run_id] = (stack, late, ctx)
        except Exception:  # noqa: BLE001
            pass

    def _end(self, run_id, error: BaseException | None = None) -> None:
        entry = self._open.pop(run_id, None)
        if entry is None:
            return
        stack, _, ctx = entry
        try:
            if error is None:
                ctx.run(stack.close)
            else:
                ctx.run(stack.__exit__, type(error), error, error.__traceback__)
        except BaseException:  # noqa: BLE001 - the span is closed; never re-raise into the framework
            pass

    @staticmethod
    def _thread(kwargs) -> Any:
        metadata = kwargs.get("metadata") or {}
        return metadata.get("thread_id") or (kwargs.get("tags") or [None])[0]

    # --- tools --------------------------------------------------------------------

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs) -> None:
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        values = inputs if isinstance(inputs, dict) else {}
        amount = None
        limit_field = self.limit_fields.get(name)
        if limit_field and isinstance(values.get(limit_field), (int, float)) and not isinstance(values.get(limit_field), bool):
            amount = float(values[limit_field])
        from .. import _schema_hash

        late_attrs = {"side_effect": self.side_effects.get(name, "write"), "args_schema_hash": _schema_hash(values), "framework": "langchain"}
        if limit_field:
            late_attrs["limit_field"] = limit_field
        thread = self._thread(kwargs)
        approval = self._last_approval.pop(thread, None) if thread is not None else None
        self._start(
            run_id, "action", tool=name, capability=self.capabilities.get(name), integration=self.integrations.get(name),
            amount=amount, currency=self.currency, approval_span_id=approval,
        )
        entry = self._open.get(run_id)
        if entry:
            entry[1]["attrs"] = late_attrs

    def on_tool_end(self, output, *, run_id, **kwargs) -> None:
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs) -> None:
        self._end(run_id, error)

    # --- models -------------------------------------------------------------------

    def _model_start(self, serialized, *, run_id, **kwargs) -> None:
        serialized = serialized or {}
        ids = serialized.get("id") or []
        provider = (ids[-2] if len(ids) >= 2 else "unknown").lower().replace("langchain_", "").replace("chat_models", "").strip(".") or "unknown"
        params = kwargs.get("invocation_params") or serialized.get("kwargs") or {}
        model = params.get("model") or params.get("model_name") or serialized.get("name") or "unknown"
        self._start(run_id, "llm_call", provider=provider, model=str(model))
        entry = self._open.get(run_id)
        if entry:
            entry[1]["attrs"] = {"framework": "langchain"}

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs) -> None:
        self._model_start(serialized, run_id=run_id, **kwargs)

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs) -> None:
        self._model_start(serialized, run_id=run_id, **kwargs)

    def on_llm_end(self, response, *, run_id, **kwargs) -> None:
        entry = self._open.get(run_id)
        if entry:
            try:
                usage = _usage_from(response)
                attrs = entry[1].setdefault("attrs", {})
                if usage.get("input") is not None:
                    attrs["gen_ai.usage.input_tokens"] = int(usage["input"])
                if usage.get("output") is not None:
                    attrs["gen_ai.usage.output_tokens"] = int(usage["output"])
                tools = _tool_calls_from(response)
                if tools:
                    attrs["tool_calls_requested"] = ",".join(tools)
            except Exception:  # noqa: BLE001
                pass
        self._end(run_id)

    def on_llm_error(self, error, *, run_id, **kwargs) -> None:
        self._end(run_id, error)

    # --- chains and interrupts ------------------------------------------------

    def on_chain_start(self, serialized, inputs, *, run_id, **kwargs) -> None:
        thread = self._thread(kwargs)
        if thread is not None and thread in self._pending_approval:
            self._pending_approval.pop(thread, None)
            try:
                late = _Late(attrs={"granted": True, "actor_type": "human", "resumed": True})
                with stoa_span("approval", agent_id=self.agent_id, approved_by="langgraph-resume", approval_method="langgraph_interrupt", _late=late) as span_id:
                    self._last_approval[thread] = span_id
            except Exception:  # noqa: BLE001
                pass

    def on_chain_error(self, error, *, run_id, **kwargs) -> None:
        if _is_interrupt(error):
            thread = self._thread(kwargs)
            try:
                late = _Late(attrs={"granted": False, "pending": True, "actor_type": "human"})
                with stoa_span("approval", agent_id=self.agent_id, approved_by="langgraph-interrupt", approval_method="langgraph_interrupt", _late=late):
                    pass
            except Exception:  # noqa: BLE001
                pass
            if thread is not None:
                self._pending_approval[thread] = None
        self._end(run_id, error if not _is_interrupt(error) else None)


def _usage_from(response) -> dict:
    """Token usage from an LLMResult, whichever of the shapes providers use."""
    out: dict = {}
    llm_output = getattr(response, "llm_output", None) or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    out["input"] = usage.get("prompt_tokens", usage.get("input_tokens"))
    out["output"] = usage.get("completion_tokens", usage.get("output_tokens"))
    if out["input"] is None:
        for generation in (getattr(response, "generations", None) or [[]])[0] or []:
            message = getattr(generation, "message", None)
            meta = getattr(message, "usage_metadata", None) or {}
            if meta:
                out["input"], out["output"] = meta.get("input_tokens"), meta.get("output_tokens")
                break
    return out


def _tool_calls_from(response) -> list[str]:
    names: list[str] = []
    for generation in (getattr(response, "generations", None) or [[]])[0] or []:
        message = getattr(generation, "message", None)
        for call in getattr(message, "tool_calls", None) or []:
            name = call.get("name") if isinstance(call, dict) else getattr(call, "name", None)
            if name:
                names.append(str(name))
    return names
