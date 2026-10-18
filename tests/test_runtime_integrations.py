"""Framework adapters, exercised with stand-in objects so no framework is
needed: the LangChain callback handler, the OpenAI and Anthropic client
wrappers, and the MCP stdio proxy."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from stoa import runtime as rt
from stoa.runtime.integrations import anthropic as anthropic_adapter
from stoa.runtime.integrations import openai as openai_adapter
from stoa.runtime.integrations.langchain import StoaCallbackHandler
from stoa.runtime.integrations.mcp_proxy import McpProxy
from stoa.runtime.reader import TraceReader

AGENT = "b8f0111742fc"


@pytest.fixture(autouse=True)
def _clean_sdk():
    rt.shutdown()
    yield
    rt.shutdown()


def _spans(tmp_path):
    rt.flush()
    return list(TraceReader(tmp_path / "traces").spans())


def _registry(tmp_path):
    path = tmp_path / "stoa-registry.json"
    path.write_text(json.dumps({"schema_version": "1.8", "agents": [{"id": AGENT, "name": "graph", "symbol": "graph", "path": "a.py",
        "declared": {"name": "refund_bot", "economic_authority": {"max_per_action": {"amount": 500, "currency": "EUR"}}},
        "tools": [{"name": "issue_refund", "money_action": True}, {"name": "lookup_order", "money_action": False}]}]}))
    return path


class _Interrupt(Exception):
    pass


_Interrupt.__name__ = "GraphInterrupt"


def test_langchain_handler_records_tools_models_and_interrupts(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id="refund_bot", registry_path=str(_registry(tmp_path)))
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # langchain_core absent here: the handler warns once per process
        handler = StoaCallbackHandler(side_effects={"issue_refund": "payment"}, limit_fields={"issue_refund": "amount_eur"}, currency="EUR")
    meta = {"metadata": {"thread_id": "t3"}}
    # a model call with usage and a tool call request
    run = uuid.uuid4()
    handler.on_chat_model_start({"id": ["langchain", "chat_models", "openai", "ChatOpenAI"]}, [], run_id=run, invocation_params={"model": "gpt-4o"})
    message = SimpleNamespace(usage_metadata={"input_tokens": 50, "output_tokens": 9}, tool_calls=[{"name": "issue_refund"}])
    handler.on_llm_end(SimpleNamespace(llm_output={}, generations=[[SimpleNamespace(message=message)]]), run_id=run)
    # the interrupt before a big refund, then the resume, then the refund citing it
    handler.on_chain_error(_Interrupt(), run_id=uuid.uuid4(), **meta)
    handler.on_chain_start({}, {}, run_id=uuid.uuid4(), **meta)
    run = uuid.uuid4()
    handler.on_tool_start({"name": "issue_refund"}, "", run_id=run, inputs={"order_id": "o-1002", "amount_eur": 980.0}, **meta)
    handler.on_tool_end("refund-1", run_id=run)
    # a failing tool
    run = uuid.uuid4()
    handler.on_tool_start({"name": "send_email"}, "", run_id=run, inputs={"to": "x"})
    handler.on_tool_error(RuntimeError("smtp"), run_id=run)

    spans = _spans(tmp_path)
    kinds = [s["kind"] for s in spans]
    assert kinds == ["llm_call", "approval", "approval", "action", "action"]
    llm = spans[0]
    assert llm["provider"] == "openai" and llm["model"] == "gpt-4o"
    assert llm["attrs"]["gen_ai.usage.input_tokens"] == 50 and llm["attrs"]["tool_calls_requested"] == "issue_refund"
    pending, resumed = spans[1], spans[2]
    assert pending["attrs"]["granted"] is False and pending["attrs"]["pending"] is True
    assert resumed["attrs"]["granted"] is True and resumed["attrs"]["resumed"] is True
    refund = spans[3]
    assert refund["tool"] == "issue_refund" and refund["amount"] == {"amount": 980.0, "currency": "EUR"}
    assert refund["approval_span_id"] == resumed["span_id"] and refund["attrs"]["side_effect"] == "payment"
    assert "over_declared_limit" in refund["attrs"]["flags"] and "approval_bypassed" not in refund["attrs"]["flags"]
    assert "o-1002" not in json.dumps(spans)  # inputs never recorded
    email = spans[4]
    assert email["status"] == "error" and email["tool"] == "send_email" and "undeclared_tool" in email["attrs"]["flags"]


def test_langchain_handler_never_raises_into_the_framework(tmp_path):
    import warnings
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the absent-framework warning is emitted once per process
        handler = StoaCallbackHandler()
    handler.on_tool_end("x", run_id="never-started")
    handler.on_llm_error(RuntimeError("x"), run_id="never-started")
    handler.on_tool_start(None, "", run_id=uuid.uuid4(), inputs="not a dict")
    assert _spans(tmp_path) == []


class _FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            model="gpt-4o-2024-08-06",
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[SimpleNamespace(function=SimpleNamespace(name="issue_refund"))]))],
        )


def test_openai_instrument_wraps_create_and_records_usage(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)
    completions = _FakeCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions), responses=None)
    assert openai_adapter.instrument(client) is client
    openai_adapter.instrument(client)  # idempotent
    response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "secret prompt"}])
    assert response.usage.prompt_tokens == 11 and len(completions.calls) == 1
    span = _spans(tmp_path)[0]
    assert span["kind"] == "llm_call" and span["provider"] == "openai" and span["model"] == "gpt-4o"
    assert span["attrs"]["gen_ai.usage.input_tokens"] == 11 and span["attrs"]["tool_calls_requested"] == "issue_refund"
    assert span["attrs"]["gen_ai.response.model"] == "gpt-4o-2024-08-06"
    assert "secret prompt" not in json.dumps(span)


def test_anthropic_instrument_wraps_messages_create(tmp_path):
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)

    async def create(**kwargs):
        return SimpleNamespace(model=kwargs["model"], usage=SimpleNamespace(input_tokens=5, output_tokens=3), stop_reason="tool_use",
                               content=[SimpleNamespace(type="text"), SimpleNamespace(type="tool_use", name="lookup_order")])

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    anthropic_adapter.instrument(client)
    import asyncio
    asyncio.run(client.messages.create(model="claude-sonnet-5", messages=[]))
    span = _spans(tmp_path)[0]
    assert span["provider"] == "anthropic" and span["model"] == "claude-sonnet-5"
    assert span["attrs"]["tool_calls_requested"] == "lookup_order" and span["attrs"]["gen_ai.response.finish_reason"] == "tool_use"


def test_mcp_proxy_records_calls_and_denies_under_policy(tmp_path, monkeypatch):
    (tmp_path / "stoa.policy.toml").write_text('[[rules]]\nid = "no-refunds-over-100"\nwhen = \'tool == "issue_refund"\'\nexpr = "amount <= 100"\non_fail = "deny"\nenforce = true\n')
    monkeypatch.chdir(tmp_path)
    rt.configure(str(tmp_path / "traces"), agent_id="refund_bot", registry_path=str(_registry(tmp_path)))
    proxy = McpProxy("unused", side_effects={"issue_refund": "payment"}, limit_fields={"issue_refund": "amount_eur"}, currency="EUR")
    # tools/list from the server: advertised tools recorded, one undeclared
    proxy.on_response({"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "issue_refund"}, {"name": "lookup_order"}, {"name": "export_ledger"}]}})
    assert proxy.tools_advertised == ["issue_refund", "lookup_order", "export_ledger"]
    # a small refund is forwarded and closed by the server's response
    assert proxy.on_request({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "issue_refund", "arguments": {"order_id": "o", "amount_eur": 40}}}) is None
    proxy.on_response({"jsonrpc": "2.0", "id": 2, "result": {"content": []}})
    # a big one is denied before it reaches the server
    reply = proxy.on_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "issue_refund", "arguments": {"order_id": "o", "amount_eur": 400}}})
    assert reply["error"]["data"]["rule_id"] == "no-refunds-over-100" and reply["id"] == 3
    # an undeclared tool call is forwarded, flagged, and its server error closes the span as an error
    assert proxy.on_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "export_ledger", "arguments": {}}}) is None
    proxy.on_response({"jsonrpc": "2.0", "id": 4, "error": {"code": -1, "message": "boom"}})
    spans = _spans(tmp_path)
    advertised = next(s for s in spans if s["kind"] == "agent_run")
    assert advertised["attrs"]["tools_undeclared"] == "export_ledger"
    actions = [s for s in spans if s["kind"] == "action"]
    assert [a["tool"] for a in actions] == ["issue_refund", "issue_refund", "export_ledger"]
    assert actions[0]["enforcement"] == "allowed" and actions[0]["status"] == "ok"
    assert actions[1]["enforcement"] == "denied" and actions[1]["status"] == "error"
    assert actions[2]["status"] == "error" and "undeclared_tool" in actions[2]["attrs"]["flags"]


def test_mcp_proxy_relays_stdio_end_to_end(tmp_path):
    """A real subprocess as the upstream: an echo server that answers tools/list and tools/call."""
    server = tmp_path / "server.py"
    server.write_text(
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    m = json.loads(line)\n"
        "    if m.get('method') == 'tools/list': r = {'tools': [{'name': 'ping'}]}\n"
        "    else: r = {'content': [{'type': 'text', 'text': 'pong'}]}\n"
        "    sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': m.get('id'), 'result': r}) + '\\n'); sys.stdout.flush()\n"
    )
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)
    import io
    import sys
    stdin = io.BytesIO((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "ping", "arguments": {}}}) + "\n").encode())
    stdout = io.BytesIO()
    proxy = McpProxy([sys.executable, str(server)])
    assert proxy.run(stdin=stdin, stdout=stdout) == 0
    replies = [json.loads(line) for line in stdout.getvalue().decode().splitlines()]
    assert [r["id"] for r in replies] == [1, 2] and replies[1]["result"]["content"][0]["text"] == "pong"
    spans = _spans(tmp_path)
    assert [s["kind"] for s in spans] == ["agent_run", "action"] and spans[1]["tool"] == "ping" and spans[1]["status"] == "ok"


def test_cli_tail_prints_recent_spans(tmp_path, capsys):
    rt.configure(str(tmp_path / "traces"), agent_id=AGENT)

    @rt.guard(side_effect="payment", limit_field="amount")
    def pay(amount):
        return 1

    pay(12.5)
    rt.shutdown()
    from stoa.cli import main
    assert main(["runtime", "tail", str(tmp_path / "traces"), "-n", "5"]) == 0
    out = capsys.readouterr().out
    assert "action" in out and "pay" in out and "12.5 USD" in out and "flags=" in out
