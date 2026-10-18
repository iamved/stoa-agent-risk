"""OpenAI client adapter: ``instrument(client)``.

Wraps ``client.chat.completions.create`` and ``client.responses.create``
(sync and async clients) so each call becomes an ``llm_call`` span with
the model id, token usage and the names of the tools the model asked for.
Prompt and response content are never recorded. Returns the client; the
wrapped methods keep their signatures. Nothing here imports ``openai``:
the client passed in is whatever the customer built.
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
            tokens_in = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None)
            tokens_out = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
            if tokens_in is not None:
                attrs["gen_ai.usage.input_tokens"] = int(tokens_in)
            if tokens_out is not None:
                attrs["gen_ai.usage.output_tokens"] = int(tokens_out)
        names: list[str] = []
        for choice in getattr(response, "choices", None) or []:
            message = getattr(choice, "message", None)
            for call in getattr(message, "tool_calls", None) or []:
                function = getattr(call, "function", None)
                name = getattr(function, "name", None)
                if name:
                    names.append(str(name))
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) == "function_call" and getattr(item, "name", None):
                names.append(str(item.name))
        if names:
            attrs["tool_calls_requested"] = ",".join(names)
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
            with stoa_span("llm_call", agent_id=agent_id, provider="openai", model=str(kwargs.get("model") or "unknown"), _late=late):
                response = await create(*args, **kwargs)
                _record(late, kwargs.get("model"), response)
                return response
        async_wrapper._stoa_wrapped = True  # type: ignore[attr-defined]
        return async_wrapper

    @functools.wraps(create)
    def wrapper(*args, **kwargs):
        late = _Late()
        with stoa_span("llm_call", agent_id=agent_id, provider="openai", model=str(kwargs.get("model") or "unknown"), _late=late):
            response = create(*args, **kwargs)
            _record(late, kwargs.get("model"), response)
            return response
    wrapper._stoa_wrapped = True  # type: ignore[attr-defined]
    return wrapper


def instrument(client, *, agent_id: str | None = None):
    """Wrap the client's create methods in place and return it. Safe to call
    twice; a client without the expected attributes is returned untouched."""
    try:
        completions = getattr(getattr(client, "chat", None), "completions", None)
        if completions is not None and hasattr(completions, "create"):
            completions.create = _wrap(completions.create, agent_id=agent_id)
        responses = getattr(client, "responses", None)
        if responses is not None and hasattr(responses, "create"):
            responses.create = _wrap(responses.create, agent_id=agent_id)
    except Exception:  # noqa: BLE001
        pass
    return client
