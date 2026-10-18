"""Framework adapters for ``stoa.runtime`` (trace 1.1).

Each module imports its framework lazily and only inside the adapter it
builds, so importing this package never pulls a dependency in, and an
adapter degrades to a no-op with one warning when its framework is absent.
Every adapter records shapes only: tool names, model ids, token counts,
error types. Prompt and response content never reaches a span.

- ``langchain``: a callback handler for LangChain and LangGraph
  (``on_tool_start/end/error``, ``on_llm_start/end/error``,
  ``on_chain_error``), plus ``GraphInterrupt`` detection as an approval
  request and the resume as its grant.
- ``openai``: ``instrument(client)`` wraps ``chat.completions.create`` and
  ``responses.create``.
- ``anthropic``: ``instrument(client)`` wraps ``messages.create``.
- ``mcp_proxy``: a stdio JSON-RPC proxy in front of an MCP server that
  records ``tools/list`` and ``tools/call`` and applies the policy.
"""
