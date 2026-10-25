"""Evidence resolution: the right entries, ranked, within budget."""

from __future__ import annotations

from stoa.detectr.claims import extract_claims
from stoa.detectr.evidence import estimate_tokens, evidence_context, resolve_evidence
from stoa.detectr.ledger import Ledger


def _ledger():
    ledger = Ledger(trajectory_id="t", agent_id="refund", model_id="m", built_from="sdk")
    ledger.add("system_prompt", payload="You are the refund agent for Meridian Pay. Refunds return to the original card within 5 to 7 business days. Be concise. Never share internal ids. " * 3)
    ledger.add("user_input", payload="Please refund my order 8812, the headphones arrived broken.")
    ledger.add("retrieved_doc", payload={"title": "Returns policy", "text": "Broken items qualify for a full refund. Refunds take 5 to 7 business days. Gift cards are final sale."})
    ledger.add("tool_call", tool_name="orders.get", payload={"order_id": 8812}, meta={"call_id": "c0"})
    ledger.add("tool_result", tool_name="orders.get", payload={"order_id": 8812, "total": 150.0, "status": "delivered"}, meta={"call_id": "c0", "status": "ok"})
    ledger.add("approval", payload={"approval_id": "APR-2201", "approved_by": "lead", "method": "slack", "granted": True})
    ledger.add("tool_call", tool_name="refund.issue", payload={"order_id": 8812, "amount": 150, "approval_id": "APR-2201"}, meta={"call_id": "c1"})
    ledger.add("tool_result", tool_name="refund.issue", payload={"refund_id": "RF-7731", "status": "pending", "amount": 150.0}, meta={"call_id": "c1", "status": "ok"})
    ledger.add("agent_output", payload="Your refund of $150 has been processed and will arrive in 2 days.")
    return ledger


def test_matched_result_ranks_first_and_budget_is_respected():
    ledger = _ledger()
    claims = extract_claims(ledger)
    said = next(c for c in claims if c.text.startswith("Your refund"))
    evidence = resolve_evidence(said, ledger, token_budget=120)
    assert evidence[0].relation == "matched_result" and evidence[0].tool_name == "refund.issue" and "pending" in evidence[0].excerpt
    assert sum(e.tokens for e in evidence) <= 120
    assert all(len(e.hash) == 64 for e in evidence)
    kinds = [e.relation for e in evidence]
    assert "matched_call" in kinds or "value_overlap" in kinds
    context = evidence_context(evidence)
    assert context and context[0].startswith("[tool_result refund.issue]")


def test_instruction_and_document_excerpts_keep_only_relevant_sentences():
    ledger = _ledger()
    claims = extract_claims(ledger)
    promise = next(c for c in claims if c.type == "commitment")
    evidence = resolve_evidence(promise, ledger, token_budget=400)
    instruction = next(e for e in evidence if e.relation == "instruction")
    assert "5 to 7 business days" in instruction.excerpt and "Be concise" not in instruction.excerpt
    document = next(e for e in evidence if e.relation == "document")
    assert "Refunds take 5 to 7 business days" in document.excerpt and "Gift cards" not in document.excerpt


def test_tool_call_claims_see_grounding_not_their_own_call():
    ledger = _ledger()
    claims = extract_claims(ledger)
    call = next(c for c in claims if c.source == "tool_call" and c.tool_name == "refund.issue")
    evidence = resolve_evidence(call, ledger)
    assert all(e.kind != "tool_call" for e in evidence)
    relations = {e.relation for e in evidence}
    assert "matched_result" in relations  # the order lookup carries 8812 and 150
    assert any(e.kind == "approval" and e.relation == "value_overlap" for e in evidence)  # the approval shares APR-2201 with the call
    assert any(e.entry_id == "e0002" for e in evidence)  # the user asked for 8812


def test_token_estimate_and_empty_cases():
    assert estimate_tokens("") == 0 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2
    ledger = Ledger(trajectory_id="t", agent_id="a", model_id=None, built_from="sdk")
    ledger.add("agent_output", payload="Hello there.")
    claims = extract_claims(ledger)
    assert resolve_evidence(claims[0], ledger) == []
