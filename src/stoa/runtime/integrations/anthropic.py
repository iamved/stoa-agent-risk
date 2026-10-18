"""Anthropic client adapter: ``instrument(client)``.

Wraps ``client.messages.create`` (sync and async clients) so each call is
an ``llm_call`` span with the model id, token usage and the names of the
``tool_use`` blocks the model returned. Content is never recorded.
"""

from __future__ import annotations

import asyncio
import functools

from .. import _Late, stoa_span


def _record(late: _Late, model: str | None, response) -> None:
    try:
        attrs = late.setdefault("attrs", {})
        usage = getattr(response, "usage", None)
        if usage is not None:
            if getattr(usage, "input_tokens", None) is not None:
                attrs["gen_ai.usage.input_tokens"] = int(usage.input_tokens)
            if getattr(usage, "output_tokens", None) is not None:
                attrs["gen_ai.usage.output_tokens"] = int(usage.output_tokens)
        names = [str(block.name) for block in getattr(response, "content", None) or [] if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None)]
        if names:
            attrs["tool_calls_requested"] = ",".join(names)
        stop = getattr(response, "stop_reason", None)
        if stop:
            attrs["gen_ai.response.finish_reason"] = str(stop)
        served = getattr(response, "model", None)
        if served and served != model:
            attrs["gen_ai.response.model"] = str(served)
    except Exception:  # noqa: BLE001
        pass


def _wrap(create, *, agent_id: str | None):
    if getattr(create, "_stoa_wrapped", False):
        return create

    if asyncio.iscoroutinefunction(create):
        @functools.wraps(create)
        async def async_wrapper(*args, **kwargs):
            late = _Late()
            with stoa_span("llm_call", agent_id=agent_id, provider="anthropic", model=str(kwargs.get("model") or "unknown"), _late=late):
                response = await create(*args, **kwargs)
                _record(late, kwargs.get("model"), response)
                return response
        async_wrapper._stoa_wrapped = True  # type: ignore[attr-defined]
        return async_wrapper

    @functools.wraps(create)
    def wrapper(*args, **kwargs):
        late = _Late()
        with stoa_span("llm_call", agent_id=agent_id, provider="anthropic", model=str(kwargs.get("model") or "unknown"), _late=late):
            response = create(*args, **kwargs)
            _record(late, kwargs.get("model"), response)
            return response
    wrapper._stoa_wrapped = True  # type: ignore[attr-defined]
    return wrapper


def instrument(client, *, agent_id: str | None = None):
    """Wrap ``client.messages.create`` in place and return the client."""
    try:
        messages = getattr(client, "messages", None)
        if messages is not None and hasattr(messages, "create"):
            messages.create = _wrap(messages.create, agent_id=agent_id)
    except Exception:  # noqa: BLE001
        pass
    return client
