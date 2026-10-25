"""Claim extraction: typed clauses with negation, hedges and conditionals,
on a labeled sentence set of at least fifty sentences per type."""

from __future__ import annotations

import json

import pytest

from stoa.detectr.claims import LLMClaimExtractor, RuleClaimExtractor, classify_clause, extract_claims, split_clauses, split_sentences
from stoa.detectr.ledger import Ledger

# --- labeled sentences -------------------------------------------------------------------

_OBJECTS = ("the refund", "your order", "the payment", "the ticket", "your account")
ACTION = [f"{lead} {obj}." for lead in (
    "I've issued", "I have processed", "I cancelled", "I've updated", "I just escalated", "I went ahead and refunded",
    "I have now closed", "I've successfully submitted", "We have approved", "I've flagged", "I already transferred", "I reset",
) for obj in _OBJECTS] + [
    "Your refund has been processed.", "The order was cancelled.", "Your address has been updated.", "The payment is now confirmed.",
    "Your card has been charged.", "The ticket has been closed.", "The transfer was completed.", "Your subscription has been renewed.",
    "The hold was released.", "Your password has been reset.", "Done, the refund is issued.", "Consider it cancelled.",
    "The system has logged your request.", "Our team has escalated this.", "We've credited your account.", "I've sent the confirmation email.",
    "I booked the appointment.", "I've marked the case as resolved.", "I have deleted the duplicate record.", "I've waived the fee.",
    "The invoice INV-20931 is paid.", "The order was placed on 10/02/2026.",
]
RESULT = [
    "Your balance is $1,250.50.", "Order 8812 is pending.", "The refund amount is 15.00 USD.", "The status is approved.",
    "Your ticket number is TCK-99812.", "The transaction posted on 2026-10-24.", "The fee came to 3.50 EUR.", "Your limit is 5,000 USD.",
    "The payment shows as declined.", "The order total was $42.", "Your account number ends in 4471.", "The invoice INV-20931 shows as paid.",
    "The current balance stands at 980 USD.", "The case status reads closed.", "The shipment status is in transit.", "Your plan costs $29 a month.",
    "The charge was 19.99 USD.", "The order date is 10/02/2026.", "The refund reference is RF-2211.", "The approval id is APR-4471.",
    "The lookup returned 3 matching orders.", "Your remaining credit is 120 EUR.", "The last payment was 250 USD on 2026-09-30.",
    "The dispute status is open.", "Your verification status is verified.", "The quote is 310 USD.", "The delivery date was 2026-10-20.",
    "The account state is suspended.", "The claim id is CLM-55120.", "The amount due is $77.10.", "The exchange rate was 1.08.",
    "The order count is 2.", "The reservation code is RSV-7781.", "The outstanding amount is 0 USD.", "The deposit was 500 EUR.",
    "The payout is 1,000 USD.", "The order status came back cancelled.", "The record shows status failed.", "Your card ending 1234 is active.",
    "The total refunded so far is $65.", "The chargeback amount is 88 USD.", "The merchant reference is MRC-1002.", "The loan balance is 12,400 USD.",
    "The current status is processing.", "The withdrawal was 200 USD.", "The late fee is $15.", "The ticket TCK-4410 is open.",
    "The policy number is POL-88001.", "The premium is 48 EUR.", "The date on file is 2026-01-15.", "Your tier is now 2.",
]
COMMITMENT = [
    "It will arrive in 2 days.", "You'll receive the refund within 3 to 5 business days.", "The funds will be back on your card by Friday.",
    "You will get a confirmation email shortly.", "Your order will ship tomorrow.", "The replacement is covered at no extra cost.",
    "We'll waive the fee on your next bill.", "You are eligible for a full refund.", "The card will be unlocked within 24 hours.",
    "You'll see the credit in 48 hours.", "The transfer will complete by end of day.", "Your request will be reviewed within 2 business days.",
    "We guarantee delivery by Monday.", "Your refund is guaranteed.", "The agent will call you back within the hour.", "It should arrive by Friday.",
    "The money will be returned in 5 to 7 days.", "You'll be able to log in within 10 minutes.", "Your new card is on its way.",
    "The fee will be refunded automatically.", "This change will take effect next month.", "You will not be charged again.",
    "We will notify you once the review is complete.", "The limit increase will apply within 2 days.", "Your account will be reactivated tonight.",
    "The dispute will be resolved within 30 days.", "You'll get the invoice by email.", "The order will be delivered on 2026-10-30.",
    "You won't pay anything for shipping.", "The rate is locked for the next 12 months.", "I'll have this fixed by tomorrow.",
    "We're going to credit you 20 USD.", "The upgrade is free of charge.", "You qualify for the promotional rate.", "Your points will post in 3 days.",
    "The claim will be paid within 10 business days.", "We'll send a replacement at no cost.", "The refund will show up by Wednesday.",
    "You will hear from us within 24 hours.", "The payout will land in your account tomorrow.", "Your subscription won't renew.",
    "The documents will be ready in one week.", "Your appointment is confirmed for next Tuesday.", "The hold will drop off in 2 days.",
    "We ensure a response within 4 hours.", "You'll be reimbursed in full.", "The engineer will arrive between 9 and 11.",
    "Your package arrives in 3 business days.", "The refund will be processed by the end of the week.", "No later than Friday, you'll have it.",
    "The adjustment will be visible within 2 hours.",
]
REASONING = [
    "Because the card was declined, the payment failed.", "The refund is pending since the merchant has not confirmed.",
    "Therefore the order cannot ship yet.", "The fee applies because the payment was late.", "Since your plan is basic, the limit is lower.",
    "As a result, the transfer was held.", "That's why the charge appears twice.", "This means the refund goes to the original card.",
    "The hold exists due to a mismatch in the address.", "Given that the order is unshipped, cancellation is possible.",
    "Hence the balance shows 0.", "Consequently the account was flagged.", "The delay happened because the bank rejected it.",
    "The reason is a pending verification.", "Your limit dropped since a payment was missed.", "The price changed because the promotion ended.",
    "So that the refund can clear, the card must be active.", "Because it is a weekend, settlement is slower.",
    "The order was split because one item was out of stock.", "Therefore no further action is needed.", "The alert fired since the amount exceeded the cap.",
    "Due to high volume, responses are slower.", "The card was blocked because of suspicious activity.", "Since the invoice is paid, no balance remains.",
    "That's why I escalated to the fraud team.", "The fee was charged because the balance went negative.", "The refund takes longer since it crosses banks.",
    "Thus the duplicate was removed.", "The payment bounced because the account was closed.", "Given that the policy lapsed, coverage ended.",
    "The quote is higher because the risk changed.", "Because of the dispute, the funds are frozen.", "The reason for the decline is insufficient funds.",
    "Since the address differs, the system asked for verification.", "This means the second charge is a pre-authorization.",
    "Consequently the shipment was returned.", "Therefore the order shows as cancelled.", "The rate changed because the term ended.",
    "The limit applies since the account is new.", "Hence the approval was required.", "Because the ticket was merged, the number changed.",
    "Due to the holiday, the transfer posts Monday.", "The payout is lower because fees were deducted.", "Since the item shipped, a return is needed.",
    "As a result, the subscription paused.", "That's why the email went to the old address.", "The system blocked it because the amount was unusual.",
    "The order failed since the card expired.", "This means the balance will update overnight.", "Given that it is a refund, no fee applies.",
    "Because the approval was missing, the transfer was held.",
]
FACTUAL = [
    "Thanks for your patience!", "I understand how frustrating that is.", "You can reach us any time.", "Our support hours are listed on the website.",
    "Refunds go back to the original payment method.", "Let me know if there is anything else.", "I'm sorry for the inconvenience.",
    "The policy allows returns on unused items.", "Your feedback matters to us.", "Happy to help with that.", "The app is available on both platforms.",
    "A confirmation page appears after checkout.", "Standard shipping is the default option.", "Our office is closed on public holidays.",
    "That option is in the settings menu.", "The form asks for your billing address.", "Interest accrues daily.", "Premium plans include priority support.",
    "You can change the language in your profile.", "This is a secure channel.", "The warranty covers manufacturing defects.",
    "International cards are accepted.", "Statements are available in the app.", "We never ask for your password.", "The receipt is attached.",
    "The team is reviewing similar cases.", "The store sells refurbished devices too.", "Chat is the fastest way to reach us.",
    "The link opens the help center.", "Your privacy is important to us.", "Delivery times vary by region.", "The feature is in beta.",
    "A manager can override this.", "The portal supports two-factor authentication.", "That's a great question.", "I see what you mean.",
    "The old card is no longer valid.", "Exchanges are handled by the store.", "Taxes depend on your location.", "The terms are on the website.",
    "Gift cards do not expire.", "The agent name is Meridian Support.", "You are talking to an automated assistant.", "Is there anything else I can help with?",
    "Please keep this reference for your records.", "The password must contain a symbol.", "Returns need the original packaging.",
    "The merchant handles shipping.", "Have a nice day.", "That plan is popular with small teams.", "I can also help with billing questions.",
]

ADVERSARIAL = [
    # text, type, negated, hedged, conditional
    ("I was not able to process the refund.", "action", True, False, False),
    ("I have not processed the refund yet.", "action", True, False, False),
    ("I couldn't locate the order.", "action", True, False, False),
    ("We never charged your card.", "action", True, False, False),
    ("The refund was not issued.", "action", True, False, False),
    ("It should arrive in 2 days.", "commitment", False, True, False),
    ("It will probably arrive by Friday.", "commitment", False, True, False),
    ("The balance is approximately 1,200 USD.", "result", False, True, False),
    ("If the merchant approves, the refund will post in 2 days.", "commitment", False, False, True),
    ("Once verified, your limit will increase.", "commitment", False, False, True),
    ("Unless the bank objects, the transfer completes tomorrow.", "commitment", False, False, True),
    ("You won't be charged again.", "commitment", True, False, False),
    ("I have scheduled the callback and it will happen tomorrow.", None, False, False, False),
]


def _type(text):
    return classify_clause(text)[0]


@pytest.mark.parametrize("text", ACTION)
def test_action_sentences(text):
    assert len(ACTION) >= 50 and _type(text) == "action", text


@pytest.mark.parametrize("text", RESULT)
def test_result_sentences(text):
    assert len(RESULT) >= 50 and _type(text) == "result", text


@pytest.mark.parametrize("text", COMMITMENT)
def test_commitment_sentences(text):
    assert len(COMMITMENT) >= 50 and _type(text) == "commitment", text


@pytest.mark.parametrize("text", REASONING)
def test_reasoning_sentences(text):
    assert len(REASONING) >= 50 and _type(text) == "reasoning", text


@pytest.mark.parametrize("text", FACTUAL)
def test_factual_sentences(text):
    assert len(FACTUAL) >= 50 and _type(text) == "factual", text


@pytest.mark.parametrize("text,kind,negated,hedged,conditional", ADVERSARIAL)
def test_adversarial_flags(text, kind, negated, hedged, conditional):
    got, detail = classify_clause(text)
    if kind is not None:
        assert got == kind, text
        assert (detail["negated"], detail["hedged"], detail["conditional"]) == (negated, hedged, conditional), text


def test_compound_sentence_splits_into_action_and_commitment():
    text = "I have scheduled the callback and it will happen tomorrow. Your refund of $150 has been processed and will arrive in 2 days; the order is now closed."
    sentences = split_sentences(text)
    assert len(sentences) == 2
    clauses = [text[a:b] for s in sentences for a, b in split_clauses(text, *s)]
    assert clauses == ["I have scheduled the callback", "and it will happen tomorrow.", "Your refund of $150 has been processed",
                       "and will arrive in 2 days", "the order is now closed."]
    assert [_type(c) for c in clauses] == ["action", "commitment", "action", "commitment", "action"]


def test_sentence_splitter_keeps_abbreviations_and_handles_newlines():
    text = "Use e.g. the app. Then pay.\nDone."
    assert [text[a:b] for a, b in split_sentences(text)] == ["Use e.g. the app.", "Then pay.", "Done."]
    assert split_sentences("") == []


def _ledger():
    ledger = Ledger(trajectory_id="t:agent", agent_id="agent", model_id="m", built_from="sdk")
    ledger.add("user_input", payload="Please refund my order 8812", span_id="s1")
    ledger.add("tool_call", tool_name="refund.issue", payload={"order_id": 8812, "amount": 150, "approval_id": "APR-4471"}, span_id="s2", meta={"call_id": "s2"})
    ledger.add("tool_result", tool_name="refund.issue", payload={"status": "pending", "amount": 15.0}, span_id="s2", meta={"call_id": "s2", "status": "ok"})
    ledger.add("agent_output", payload="Your refund of $150 has been processed and will arrive in 2 days. Order 8812 is all set.", span_id="s3")
    return ledger


def test_rule_extractor_builds_claims_and_links_them():
    claims = extract_claims(_ledger())
    assert [c.type for c in claims] == ["action", "action", "commitment", "result"]
    call = claims[0]
    assert call.source == "tool_call" and call.tool_name == "refund.issue" and call.text.startswith("refund.issue(")
    assert {(v.type, v.canonical, v.field) for v in call.structured_values} >= {("id", "8812", "order_id"), ("money", "150", "amount"), ("id", "APR-4471", "approval_id")}
    said = claims[1]
    assert said.text == "Your refund of $150 has been processed" and said.char_span == (0, 38) and said.tool_name == "processed"
    assert {v.canonical for v in said.structured_values} == {"150", "completed"}
    assert said.depends_on == [call.id] and call.consumed_by == [said.id, claims[3].id]
    assert claims[2].type == "commitment" and claims[2].structured_values[0].canonical == "P2D"
    assert claims[3].depends_on == [call.id]
    for claim in claims:
        row = claim.to_dict()
        assert row["id"] == claim.id and row["trajectory_id"] == "t:agent"
    assert extract_claims(_ledger()) == claims  # deterministic


def test_redacted_outputs_yield_no_text_claims():
    ledger = Ledger(trajectory_id="t", agent_id="a", model_id=None, built_from="sdk")
    ledger.add("agent_output", payload=None, content_captured=False, hash_override="ab" * 32)
    ledger.add("tool_call", tool_name="pay", payload=None, content_captured=False)
    claims = extract_claims(ledger)
    assert [c.type for c in claims] == ["action"] and claims[0].structured_values == []


def test_llm_extractor_caches_by_message_hash_and_falls_back(tmp_path):
    calls = []

    def complete(prompt):
        calls.append(prompt)
        return json.dumps([{"text": "Your refund of $150 has been processed", "type": "action"},
                           {"text": "will arrive in 2 days", "type": "commitment", "hedged": False}])

    extractor = LLMClaimExtractor(complete, cache_path=tmp_path / "cache.json")
    assert extractor.sync_capable is False
    first = extractor.extract(_ledger())
    second = LLMClaimExtractor(complete, cache_path=tmp_path / "cache.json").extract(_ledger())
    assert len(calls) == 1 and [c.to_dict() for c in first] == [c.to_dict() for c in second]
    assert [c.type for c in first] == ["action", "action", "commitment"] and first[1].extractor == "llm" and first[1].char_span == (0, 38)
    assert first[1].depends_on == [first[0].id]
    broken = LLMClaimExtractor(lambda p: "not json", cache_path=None).extract(_ledger())
    assert [c.type for c in broken] == ["action"]  # the tool call still becomes a claim
    assert RuleClaimExtractor().sync_capable is True
