"""The ledger: one shape from three sources, raw payloads kept, redaction
survived through hashes, values indexed, hand-offs chained."""

from __future__ import annotations

import json

import pytest

from stoa import runtime as rt
from stoa.detectr.ledger import (
    Ledger, build_ledgers, chain, detect_source, ledgers_from_langgraph, ledgers_from_otel, ledgers_from_spans,
    ledgers_from_trace_dir, parse_payload, payload_hash, render_ledger,
)
from stoa.detectr.values import Value
from stoa.runtime.reader import TraceReader
from stoa.runtime.spans import build_span

AGENT = "a09ff38687e9"
T0 = "2026-10-24T09:00:0{}.000Z"


@pytest.fixture(autouse=True)
def _clean_sdk():
    rt.shutdown()
    yield
    rt.shutdown()


def _span(i, kind, **kw):
    base = dict(trace_id="t1", span_id=f"s{i}", parent_span_id=None, kind=kind, agent_id=AGENT, session_id="sess1",
                start_ts=T0.format(i), end_ts=T0.format(i), status="ok", redaction="content")
    base.update(kw)
    return build_span(**base)


def _refund_spans(*, content=True):
    """The canonical trajectory: refund on order 8812, tool says pending 15.00,
    agent says processed $150 in 2 days."""
    def c(attrs):
        if content:
            return attrs
        return {f"{k}_sha256": payload_hash(v) for k, v in attrs.items()} | {f"{k}_chars": len(v) for k, v in attrs.items()}
    return [
        _span(1, "agent_run", attrs=c({"user_inputs": json.dumps(["Please refund my order 8812"]), "system_prompt": "You are the refund agent."})),
        _span(2, "llm_call", provider="openai", model="gpt-4o", attrs=c({"response": json.dumps({"content": "", "tool_calls": [{"name": "refund.issue"}]})})),
        _span(3, "action", tool="refund.issue", amount=150.0, currency="USD", approval_span_id="APR-4471",
              end_ts=T0.format(4), attrs={"side_effect": "payment", **c({"args": json.dumps({"order_id": 8812, "amount": 150, "approval_id": "APR-4471"}),
                                                                       "result": json.dumps({"status": "pending", "amount": 15.00})})}),
        _span(5, "llm_call", provider="openai", model="gpt-4o", attrs=c({"response": "Your refund of $150 has been processed and will arrive in 2 days."})),
    ]


def test_sdk_builder_orders_entries_and_keeps_raw_payloads():
    ledgers = ledgers_from_spans(_refund_spans())
    assert len(ledgers) == 1
    ledger = ledgers[0]
    assert ledger.trajectory_id == f"sess1:{AGENT}" and ledger.agent_id == AGENT and ledger.model_id == "gpt-4o" and ledger.built_from == "sdk"
    kinds = [e.kind for e in ledger.entries]
    # the first model turn only requested a tool, so it adds no agent_output
    assert kinds == ["system_prompt", "user_input", "tool_call", "tool_result", "agent_output"]
    call, result = ledger.by_tool("refund.issue")
    assert call.kind == "tool_call" and call.parsed == {"order_id": 8812, "amount": 150, "approval_id": "APR-4471"}
    assert call.meta["side_effect"] == "payment" and call.meta["approval_span_id"] == "APR-4471"
    assert result.kind == "tool_result" and result.parsed == {"status": "pending", "amount": 15.0} and result.meta["status"] == "ok"
    assert ledger.result_for(call) is result
    final = ledger.entries[-1]
    assert final.raw_payload.startswith("Your refund of $150") and final.hash == payload_hash(final.raw_payload)
    # the agent's paraphrase never stands in for the result
    assert all(e.kind != "tool_result" for e in ledger.entries if "processed" in (e.text_view or ""))


def test_value_index_answers_grounding_lookups():
    ledger = ledgers_from_spans(_refund_spans())[0]
    call = ledger.by_tool("refund.issue", "tool_call")[0]
    assert ledger.lookup(Value("id", "8812", "8812"), before_seq=call.seq)  # the user said 8812
    assert not ledger.lookup(Value("id", "APR-4471", "APR-4471"), before_seq=call.seq)  # nobody issued APR-4471
    assert not ledger.lookup(Value("money", "150", "$150"), before_seq=call.seq)
    assert ledger.lookup(Value("money", "15", "15.00"), before_seq=ledger.entries[-1].seq, kinds=["tool_result"])
    assert ledger.before(call.seq, "user_input")[0].text_view == "Please refund my order 8812"


def test_redacted_trace_gives_hashes_and_a_warning():
    ledger = ledgers_from_spans(_refund_spans(content=False))[0]
    assert ledger.redacted is False  # the span's amount and approval id are still known
    outputs = ledger.by_kind("agent_output")
    assert outputs and all(not e.content_captured and e.raw_payload is None and len(e.hash) == 64 for e in outputs)
    call = ledger.by_tool("refund.issue", "tool_call")[0]
    assert call.parsed == {"amount": 150.0, "currency": "USD", "approval_span_id": "APR-4471"}
    fully = ledgers_from_spans([_span(1, "llm_call", provider="openai", model="m", attrs={"response_sha256": "ab" * 32, "response_chars": 5})])[0]
    assert fully.redacted and "capture_content" in fully.warnings[0]


def test_sdk_records_content_only_when_opted_in(tmp_path):
    rt.configure(str(tmp_path), capture_content=True, redaction_hook=lambda s: s.replace("secret", "[x]"))

    @rt.guard("payment", limit_field="amount", approval_field="approval_id", name="refund.issue")
    def issue(order_id, amount, approval_id=None):
        return {"status": "pending", "amount": amount / 10}

    with rt.session("u1", agent_id=AGENT) as s:
        s.system_prompt("You are the refund agent. secret")
        s.user_input("Please refund my order 8812")
        s.retrieved([{"id": "doc1", "text": "Refund policy: 14 days"}], source="kb")
        with rt.model_call("openai", "gpt-4o") as m:
            m.record(prompt=[{"role": "user", "content": "Please refund my order 8812"}], response="Working on it", system="You are the refund agent.")
        issue(8812, 150, approval_id="APR-4471")
    rt.flush()
    ledger = ledgers_from_trace_dir(tmp_path)[0]
    kinds = [e.kind for e in ledger.entries]
    assert kinds.count("system_prompt") == 2 and "retrieved_doc" in kinds and "tool_call" in kinds and "tool_result" in kinds
    # the hook ran on the session's prompt; spans that share a millisecond keep file order
    assert {e.text_view for e in ledger.by_kind("system_prompt")} == {"You are the refund agent. [x]", "You are the refund agent."}
    assert ledger.by_kind("user_input") and len(ledger.by_kind("user_input")) == 1  # prompt echo deduplicated
    assert ledger.by_tool("refund.issue", "tool_result")[0].parsed == {"status": "pending", "amount": 15.0}
    assert ledger.by_kind("retrieved_doc")[0].parsed == {"id": "doc1", "text": "Refund policy: 14 days"}

    rt.shutdown()
    plain = tmp_path / "plain"
    rt.configure(str(plain))
    with rt.session("u1", agent_id=AGENT) as s:
        s.user_input("Please refund my order 8812")
        with rt.model_call("openai", "gpt-4o") as m:
            m.record(prompt="Please refund my order 8812", response="Working on it")
        issue(8812, 150, approval_id="APR-4471")
    rt.flush()
    text = "".join(p.read_text() for p in plain.glob("*.jsonl"))
    assert "Please refund" not in text and "Working on it" not in text and '"args"' not in text and '"result"' not in text
    assert '"args_sha256"' in text and '"response_sha256"' in text  # shapes survive, content does not
    assert all(span.get("redaction") == "redacted" for span in TraceReader(plain).spans())
    hashed = ledgers_from_trace_dir(plain)[0]
    assert hashed.by_kind("agent_output")[0].content_captured is False and len(hashed.by_kind("agent_output")[0].hash) == 64


def test_otel_builder_reads_current_and_legacy_shapes():
    current = {"resourceSpans": [{"resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "refund-agent"}}]}, "scopeSpans": [{"spans": [
        {"name": "chat gpt-4o", "spanId": "a1", "traceId": "tr1", "startTimeUnixNano": "1700000000000000000", "endTimeUnixNano": "1700000001000000000",
         "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}, {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4o"}},
                        {"key": "gen_ai.conversation.id", "value": {"stringValue": "conv1"}},
                        {"key": "gen_ai.system_instructions", "value": {"stringValue": json.dumps([{"type": "text", "content": "You are the refund agent."}])}},
                        {"key": "gen_ai.input.messages", "value": {"stringValue": json.dumps([{"role": "user", "parts": [{"type": "text", "content": "Please refund my order 8812"}]}])}},
                        {"key": "gen_ai.output.messages", "value": {"stringValue": json.dumps([{"role": "assistant", "parts": [{"type": "tool_call", "id": "c1", "name": "refund.issue", "arguments": {"order_id": 8812, "amount": 150}}]}])}}]},
        {"name": "execute_tool refund.issue", "spanId": "a2", "traceId": "tr1", "startTimeUnixNano": "1700000002000000000", "endTimeUnixNano": "1700000003000000000",
         "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}}, {"key": "gen_ai.tool.name", "value": {"stringValue": "refund.issue"}},
                        {"key": "gen_ai.tool.call.id", "value": {"stringValue": "c1"}}, {"key": "gen_ai.conversation.id", "value": {"stringValue": "conv1"}},
                        {"key": "gen_ai.tool.call.arguments", "value": {"stringValue": json.dumps({"order_id": 8812, "amount": 150})}},
                        {"key": "gen_ai.tool.call.result", "value": {"stringValue": json.dumps({"status": "pending", "amount": 15.0})}}]},
        {"name": "chat gpt-4o", "spanId": "a3", "traceId": "tr1", "startTimeUnixNano": "1700000004000000000", "endTimeUnixNano": "1700000005000000000",
         "attributes": [{"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}}, {"key": "gen_ai.conversation.id", "value": {"stringValue": "conv1"}},
                        {"key": "gen_ai.input.messages", "value": {"stringValue": json.dumps([{"role": "user", "parts": [{"type": "text", "content": "Please refund my order 8812"}]},
                                                                                              {"role": "tool", "parts": [{"type": "tool_call_response", "id": "c1", "response": {"status": "pending", "amount": 15.0}}]}])}},
                        {"key": "gen_ai.output.messages", "value": {"stringValue": json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": "Your refund of $150 has been processed."}]}])}}]},
    ]}]}]}
    ledger = ledgers_from_otel(current)[0]
    assert ledger.trajectory_id == "conv1" and ledger.agent_id == "refund-agent" and ledger.model_id == "gpt-4o" and ledger.built_from == "otel"
    kinds = [e.kind for e in ledger.entries]
    assert kinds[:3] == ["system_prompt", "user_input", "tool_call"]
    assert kinds.count("user_input") == 1 and kinds.count("tool_call") == 2 and kinds.count("tool_result") == 2
    assert ledger.entries[-1].kind == "agent_output" and "$150" in ledger.entries[-1].text_view
    assert ledger.by_tool("refund.issue", "tool_result")[0].parsed == {"status": "pending", "amount": 15.0}

    legacy = [{"name": "openai.chat", "span_id": "b1", "trace_id": "tr2", "start_time": "1", "end_time": "2",
               "attributes": {"gen_ai.request.model": "gpt-4o", "gen_ai.prompt": json.dumps([{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Cancel order 77"}])},
               "events": [{"name": "gen_ai.content.completion", "attributes": {"gen_ai.completion": "Order 77 is cancelled."}}]}]
    old = ledgers_from_otel(legacy)[0]
    assert [e.kind for e in old.entries] == ["system_prompt", "user_input", "agent_output"] and old.trajectory_id == "tr2"


def test_langgraph_builder_reads_model_dump_and_lc_forms():
    snapshot = {
        "config": {"configurable": {"thread_id": "thread-9", "checkpoint_id": "1ef"}}, "created_at": "2026-10-24T09:00:00Z",
        "values": {"messages": [
            {"type": "system", "content": "You are the refund agent."},
            {"type": "human", "content": "Please refund my order 8812", "id": "h1"},
            {"type": "ai", "content": "", "tool_calls": [{"name": "refund_issue", "args": {"order_id": 8812, "amount": 150}, "id": "call_1"}], "id": "a1",
             "response_metadata": {"model_name": "gpt-4o"}},
            {"type": "tool", "content": json.dumps({"status": "pending", "amount": 15.0}), "tool_call_id": "call_1", "name": "refund_issue", "status": "success", "id": "t1"},
            {"type": "ai", "content": [{"type": "text", "text": "Your refund of $150 has been processed."}], "id": "a2"},
        ]},
    }
    ledger = ledgers_from_langgraph(snapshot, agent_id="refund")[0]
    assert ledger.trajectory_id == "thread-9" and ledger.model_id == "gpt-4o" and ledger.built_from == "langgraph"
    assert [e.kind for e in ledger.entries] == ["system_prompt", "user_input", "tool_call", "tool_result", "agent_output"]
    call = ledger.by_tool("refund_issue", "tool_call")[0]
    assert ledger.result_for(call).parsed == {"status": "pending", "amount": 15.0} and call.meta["call_id"] == "call_1"

    lc = {"channel_values": {"messages": [
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "HumanMessage"], "kwargs": {"content": "Hi, order 1"}},
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "AIMessage"], "kwargs": {"content": "Hello", "tool_calls": []}},
        {"lc": 1, "type": "constructor", "id": ["langchain", "schema", "messages", "ToolMessage"], "kwargs": {"content": "Error: timeout", "tool_call_id": "x", "name": "lookup"}},
    ]}}
    other = ledgers_from_langgraph(lc)[0]
    assert [e.kind for e in other.entries] == ["user_input", "agent_output", "tool_result"]
    assert other.entries[-1].meta["status"] == "error"
    history = [snapshot, {"values": {"messages": snapshot["values"]["messages"][:2]}}]
    assert len(ledgers_from_langgraph(history)[0].entries) == 5


def test_handoffs_chain_parent_ledgers():
    spans = [
        _span(1, "agent_run", agent_id="A", attrs={"user_inputs": json.dumps(["Pay invoice INV-100 for 40 EUR"])}),
        _span(2, "delegation", agent_id="A", from_agent_id="A", to_agent_id="B", attrs={"message": "Pay INV-100, 40 EUR"}),
        _span(3, "action", agent_id="B", tool="pay", attrs={"args": json.dumps({"invoice": "INV-100", "amount": 40})}),
    ]
    ledgers = {l.trajectory_id: l for l in ledgers_from_spans(spans)}
    a, b = ledgers["sess1:A"], ledgers["sess1:B"]
    assert [e.kind for e in a.entries] == ["user_input", "handoff_out"] and a.entries[1].meta["to"] == "B"
    assert [e.kind for e in b.entries] == ["handoff_in", "tool_call"] and b.parent_trajectory_id == a.trajectory_id
    chained = chain(b, ledgers)
    assert [e.kind for e in chained] == ["user_input", "handoff_out", "handoff_in", "tool_call"]


def test_parse_payload_shapes_and_serialization_round_trip(tmp_path):
    assert parse_payload('{"a": 1}') == {"a": 1}
    assert parse_payload("status: pending\namount = 15") == {"status": "pending", "amount": "15"}
    assert parse_payload("| id | status |\n|---|---|\n| 1 | ok |") == [{"id": "1", "status": "ok"}]
    assert parse_payload("just words") is None and parse_payload(None) is None and parse_payload(True) is None
    ledger = ledgers_from_spans(_refund_spans())[0]
    again = Ledger.from_dict(json.loads(json.dumps(ledger.to_dict())))
    assert again.to_dict() == ledger.to_dict()
    text = render_ledger(ledger)
    assert "refund.issue" in text and "Ledger sess1" in text

    traces = tmp_path / "traces"; traces.mkdir()
    header = json.dumps({"kind": "header", "schema": "stoa-trace/1.1", "sdk_version": "0", "redaction": "content"})
    (traces / "trace-1-0000.jsonl").write_text("\n".join([header] + [json.dumps(s) for s in _refund_spans()]) + "\n")
    assert detect_source(traces) == "sdk" and len(build_ledgers(traces)[0].entries) == 5
    otel = tmp_path / "spans.json"; otel.write_text(json.dumps({"resourceSpans": []}))
    assert detect_source(otel) == "otel"
    lg = tmp_path / "ckpt.json"; lg.write_text(json.dumps({"values": {"messages": []}}))
    assert detect_source(lg) == "langgraph" and build_ledgers(lg) == []
    with pytest.raises(ValueError):
        build_ledgers(lg, source="csv")


def test_ledger_is_deterministic():
    a = ledgers_from_spans(_refund_spans())[0].to_dict()
    b = ledgers_from_spans(_refund_spans())[0].to_dict()
    assert a == b
