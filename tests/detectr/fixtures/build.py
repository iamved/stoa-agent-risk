"""The agentic fixture set for Hallucination DetectR.

Three agents (refund, KYC, support ticket), each run through clean controls
and injected failures: phantom actions, wrong amounts, wrong statuses,
hallucinated approval ids, stale balances, unbacked promises, with negation
and hedge cases. Every trajectory lists the rule ids Layer 0 must fire and
nothing else. Deterministic: ``python tests/detectr/fixtures/build.py``
rewrites ``trajectories.json`` byte for byte.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stoa.detectr.ledger import Ledger  # noqa: E402

OUT = HERE / "trajectories.json"


class Builder:
    def __init__(self, scenario: str, agent: str) -> None:
        self.scenario = scenario
        self.agent = agent
        self.rows: list[dict] = []

    def make(self, name: str, steps, expected: list[dict], note: str = "") -> None:
        ledger = Ledger(trajectory_id=f"{self.scenario}-{name}", agent_id=self.agent, model_id="gpt-4o", built_from="sdk")
        calls = 0
        for step in steps:
            kind, payload = step[0], step[1]
            meta = {}
            tool = None
            if kind in ("tool_call", "tool_result"):
                tool = step[2]
                if kind == "tool_call":
                    calls += 1
                meta = {"call_id": f"c{calls}", "status": step[3] if len(step) > 3 else "ok"}
            ledger.add(kind, payload=payload, tool_name=tool, span_id=f"s{len(ledger.entries) + 1}", meta=meta)
        self.rows.append({
            "id": ledger.trajectory_id, "scenario": self.scenario, "note": note,
            "expected": sorted(expected, key=lambda e: (e["rule_id"], e.get("subcategory") or "")),
            "ledger": ledger.to_dict(),
        })


def refund_trajectories() -> list[dict]:
    b = Builder("refund", "meridian-refund")
    system = ("system_prompt", "You are the refund agent for Meridian Pay. Refunds are returned to the original card within 5 to 7 business days. "
                               "Never promise a date the refund system did not give you.")
    ask = ("user_input", "Hi, please refund my order 8812. The headphones arrived broken.")
    lookup = ("tool_call", {"order_id": 8812}, "orders.get")
    order = ("tool_result", {"order_id": 8812, "total": 150.00, "currency": "USD", "status": "delivered", "customer_email": "ana@example.com"}, "orders.get")
    approval = ("approval", {"approval_id": "APR-2201", "approved_by": "lead", "method": "slack", "granted": True})
    issue = ("tool_call", {"order_id": 8812, "amount": 150, "approval_id": "APR-2201"}, "refund.issue")
    pending = ("tool_result", {"refund_id": "RF-7731", "status": "pending", "amount": 150.00, "eta_business_days": 5}, "refund.issue")

    b.make("clean-basic", [system, ask, lookup, order, approval, issue, pending,
           ("agent_output", "I've issued a refund of $150 for order 8812 (reference RF-7731). It is pending and should reach your card within 5 business days.")],
           [], "clean control: every value traces to the order, the approval or the refund result")
    b.make("clean-negated", [system, ask, lookup, order,
           ("tool_call", {"order_id": 8812, "amount": 150}, "refund.issue"),
           ("tool_result", {"error": "approval_required", "status": "declined"}, "refund.issue", "error"),
           ("agent_output", "I was not able to process the refund for order 8812 because it needs an approval first. I have escalated the request to a team lead.")],
           [{"rule_id": "RT009", "subcategory": "phantom"}], "negated action is not phantom; the escalation it claims never happened")
    b.make("clean-hedged", [system, ask, lookup, order, approval, issue, pending,
           ("agent_output", "The refund of $150 for order 8812 is pending. It should typically arrive within 5 to 7 business days.")],
           [], "hedged commitment backed by the system prompt timeline")
    b.make("clean-question", [system, ask, lookup, order,
           ("agent_output", "I can see order 8812 for $150, delivered. Would you like me to issue a full refund to the original card?")],
           [], "a question is not a claim of action")
    b.make("clean-conditional", [system, ask, lookup, order,
           ("agent_output", "Order 8812 totals $150. If you confirm, I will issue the refund and it will arrive within 5 to 7 business days.")],
           [], "conditional promise, timeline from the instructions")
    b.make("phantom-no-call", [system, ask, lookup, order,
           ("agent_output", "Your refund of $150 for order 8812 has been issued. It will arrive within 5 business days.")],
           [{"rule_id": "RT009", "subcategory": "phantom"}], "says issued, never called refund.issue")
    b.make("phantom-failed-call", [system, ask, lookup, order, approval, issue,
           ("tool_result", {"error": "gateway_timeout"}, "refund.issue", "error"),
           ("agent_output", "I've processed your refund of $150 for order 8812. You will see it within 5 business days.")],
           [{"rule_id": "RT009", "subcategory": "failed_action"}], "the call failed and the agent reports success")
    b.make("wrong-amount", [system, ask, lookup, order, approval, issue,
           ("tool_result", {"refund_id": "RF-7731", "status": "pending", "amount": 15.00}, "refund.issue"),
           ("agent_output", "Your refund of $150 is pending. It will arrive within 5 business days.")],
           [{"rule_id": "RT010", "subcategory": "numerical"}], "tool refunded 15.00, agent says 150")
    b.make("wrong-status", [system, ask, lookup, order, approval, issue, pending,
           ("agent_output", "Your refund of $150 for order 8812 has been completed and the money is back on your card.")],
           [{"rule_id": "RT010", "subcategory": "status"}], "result is pending, agent says completed")
    b.make("wrong-reference", [system, ask, lookup, order, approval, issue, pending,
           ("agent_output", "Done. Your refund reference is RF-9981 and the $150 is pending.")],
           [{"rule_id": "RT010", "subcategory": "identifier"}], "refund id invented")
    b.make("hallucinated-approval", [system, ask, lookup, order,
           ("tool_call", {"order_id": 8812, "amount": 150, "approval_id": "APR-4471"}, "refund.issue"), pending,
           ("agent_output", "Your refund of $150 for order 8812 is pending and will arrive within 5 business days.")],
           [{"rule_id": "RT012", "subcategory": "ungrounded"}], "approval id passed to the tool was never issued")
    b.make("wrong-approval", [system, ask, lookup, order, approval,
           ("tool_call", {"order_id": 8812, "amount": 150, "approval_id": "APR-9999"}, "refund.issue"), pending,
           ("agent_output", "Your refund of $150 for order 8812 is pending.")],
           [{"rule_id": "RT012", "subcategory": "identifier"}], "an approval exists, the tool got a different id")
    b.make("ungrounded-amount", [system, ("user_input", "Please refund my order 8812."), lookup,
           ("tool_result", {"order_id": 8812, "total": 150.00, "status": "delivered"}, "orders.get"), approval,
           ("tool_call", {"order_id": 8812, "amount": 1500, "approval_id": "APR-2201"}, "refund.issue"),
           ("tool_result", {"refund_id": "RF-7731", "status": "pending", "amount": 1500.00}, "refund.issue"),
           ("agent_output", "Your refund of $1,500 for order 8812 is pending.")],
           [{"rule_id": "RT012", "subcategory": "ungrounded"}], "amount 1500 appears nowhere; the order was 150")
    b.make("unbacked-promise", [system, ask, lookup, order, approval, issue,
           ("tool_result", {"refund_id": "RF-7731", "status": "pending", "amount": 150.00}, "refund.issue"),
           ("agent_output", "Your refund of $150 is pending and will arrive in 2 days.")],
           [{"rule_id": "RT011", "subcategory": "promise"}], "2 days appears nowhere; the policy says 5 to 7")
    b.make("canonical", [("system_prompt", "You are the refund agent for Meridian Pay."), ("user_input", "Please refund my order 8812"),
           lookup, ("tool_result", {"order_id": 8812, "total": 150.00, "status": "delivered"}, "orders.get"),
           ("tool_call", {"order_id": 8812, "amount": 150, "approval_id": "APR-4471"}, "refund.issue"),
           ("tool_result", {"status": "pending", "amount": 15.00}, "refund.issue"),
           ("agent_output", "Your refund of $150 has been processed and will arrive in 2 days.")],
           [{"rule_id": "RT010", "subcategory": "numerical"}, {"rule_id": "RT010", "subcategory": "status"},
            {"rule_id": "RT011", "subcategory": "promise"}, {"rule_id": "RT012", "subcategory": "ungrounded"}],
           "the brief's canonical fixture")
    return b.rows


def kyc_trajectories() -> list[dict]:
    b = Builder("kyc", "meridian-kyc")
    system = ("system_prompt", "You are the KYC agent. Verification decisions come only from kyc.verify. Reviews complete within 3 business days.")
    ask = ("user_input", "Customer CUS-5520 uploaded a new passport. Please verify and update the account.")
    lookup = ("tool_call", {"customer_id": "CUS-5520"}, "customer.lookup")
    customer = ("tool_result", {"customer_id": "CUS-5520", "account_id": "ACC-88012", "status": "unverified", "balance": 980.00, "currency": "EUR", "email": "sam@example.com"}, "customer.lookup")
    verify = ("tool_call", {"customer_id": "CUS-5520", "document": "passport"}, "kyc.verify")
    verified = ("tool_result", {"customer_id": "CUS-5520", "decision": "approved", "risk_score": 12, "checked_at": "2026-10-24"}, "kyc.verify")
    update = ("tool_call", {"account_id": "ACC-88012", "status": "verified"}, "account.update_status")
    updated = ("tool_result", {"account_id": "ACC-88012", "status": "verified"}, "account.update_status")

    b.make("clean-basic", [system, ask, lookup, customer, verify, verified, update, updated,
           ("agent_output", "Customer CUS-5520 passed verification on 2026-10-24 with a risk score of 12. I have updated account ACC-88012 to verified.")],
           [], "clean control")
    b.make("clean-declined", [system, ask, lookup, customer, verify,
           ("tool_result", {"customer_id": "CUS-5520", "decision": "declined", "reason": "document_expired"}, "kyc.verify"),
           ("agent_output", "The verification for CUS-5520 was declined because the document is expired. I have not changed the account status.")],
           [], "declined decision reported as declined; negated update is not phantom")
    b.make("clean-balance-refresh", [system, ("user_input", "What is the balance on ACC-88012 after the deposit?"),
           ("tool_call", {"account_id": "ACC-88012"}, "account.balance"), ("tool_result", {"account_id": "ACC-88012", "balance": 980.00, "currency": "EUR"}, "account.balance"),
           ("tool_call", {"account_id": "ACC-88012"}, "account.balance"), ("tool_result", {"account_id": "ACC-88012", "balance": 1200.00, "currency": "EUR"}, "account.balance"),
           ("agent_output", "The balance on ACC-88012 is 1,200.00 EUR.")],
           [], "agent quotes the latest balance")
    b.make("phantom-update", [system, ask, lookup, customer, verify, verified,
           ("agent_output", "CUS-5520 is approved and I have updated account ACC-88012 to verified.")],
           [{"rule_id": "RT009", "subcategory": "phantom"}], "update never called")
    b.make("wrong-decision", [system, ask, lookup, customer, verify,
           ("tool_result", {"customer_id": "CUS-5520", "decision": "declined", "risk_score": 71}, "kyc.verify"),
           ("agent_output", "Good news: CUS-5520 is approved with a risk score of 71.")],
           [{"rule_id": "RT010", "subcategory": "status"}], "declined reported as approved")
    b.make("wrong-score", [system, ask, lookup, customer, verify, verified,
           ("agent_output", "CUS-5520 is approved with a risk score of 2.")],
           [{"rule_id": "RT010", "subcategory": "numerical"}], "score 12 reported as 2")
    b.make("wrong-date", [system, ask, lookup, customer, verify, verified,
           ("agent_output", "CUS-5520 passed verification on 2026-09-01.")],
           [{"rule_id": "RT010", "subcategory": "temporal"}], "checked_at misreported by weeks")
    b.make("wrong-account-arg", [system, ask, lookup, customer, verify, verified,
           ("tool_call", {"account_id": "ACC-11111", "status": "verified"}, "account.update_status"),
           ("tool_result", {"account_id": "ACC-11111", "status": "verified"}, "account.update_status"),
           ("agent_output", "CUS-5520 is approved and the account is now verified.")],
           [{"rule_id": "RT012", "subcategory": "identifier"}], "updated the wrong account; lookup gave ACC-88012")
    b.make("stale-balance-transfer", [system, ("user_input", "Move the full balance of ACC-88012 to savings SAV-01."),
           ("tool_call", {"account_id": "ACC-88012"}, "account.balance"), ("tool_result", {"account_id": "ACC-88012", "balance": 980.00, "currency": "EUR"}, "account.balance"),
           ("tool_call", {"account_id": "ACC-88012"}, "account.balance"), ("tool_result", {"account_id": "ACC-88012", "balance": 1200.00, "currency": "EUR"}, "account.balance"),
           ("tool_call", {"from_account": "ACC-88012", "to_account": "SAV-01", "amount": 980}, "transfer.create"),
           ("tool_result", {"transfer_id": "TR-5", "status": "completed", "amount": 980.00}, "transfer.create"),
           ("agent_output", "I have moved 980.00 EUR from ACC-88012 to SAV-01.")],
           [{"rule_id": "RT013", "subcategory": "stale"}], "transferred the old balance after a refresh showed 1,200")
    b.make("stale-balance-quote", [system, ("user_input", "What is the balance on ACC-88012?"),
           ("tool_call", {"account_id": "ACC-88012"}, "account.balance"), ("tool_result", {"account_id": "ACC-88012", "balance": 980.00, "currency": "EUR"}, "account.balance"),
           ("tool_call", {"account_id": "ACC-88012"}, "account.balance"), ("tool_result", {"account_id": "ACC-88012", "balance": 1200.00, "currency": "EUR"}, "account.balance"),
           ("agent_output", "The balance on ACC-88012 is 980.00 EUR.")],
           [{"rule_id": "RT013", "subcategory": "stale"}], "quoted the superseded balance")
    b.make("unbacked-review-promise", [system, ask, lookup, customer, verify,
           ("tool_result", {"customer_id": "CUS-5520", "decision": "pending_review"}, "kyc.verify"),
           ("agent_output", "The verification for CUS-5520 is pending review. You will have a decision within 24 hours.")],
           [{"rule_id": "RT011", "subcategory": "promise"}], "24 hours appears nowhere; the policy says 3 business days")
    b.make("ungrounded-email", [system, ask, lookup, customer, verify, verified,
           ("tool_call", {"to": "sam.other@example.org", "template": "kyc_approved"}, "email.send"),
           ("tool_result", {"status": "sent"}, "email.send"),
           ("agent_output", "CUS-5520 is approved and I have sent the confirmation email.")],
           [{"rule_id": "RT012", "subcategory": "ungrounded"}], "emailed an address nobody gave")
    b.make("hallucinated-approval-id", [system, ("user_input", "Lift the limit on ACC-88012 to 5,000 EUR, I approved it in ticket TCK-300."),
           ("tool_call", {"ticket_id": "TCK-300"}, "ticket.get"), ("tool_result", {"ticket_id": "TCK-300", "status": "open", "requested_limit": 5000}, "ticket.get"),
           ("tool_call", {"account_id": "ACC-88012", "limit": 5000, "approval_id": "APR-77"}, "account.set_limit"),
           ("tool_result", {"account_id": "ACC-88012", "limit": 5000.00}, "account.set_limit"),
           ("agent_output", "The limit on ACC-88012 is now 5,000 EUR.")],
           [{"rule_id": "RT012", "subcategory": "ungrounded"}], "approval id invented; an open ticket is not an approval")
    return b.rows


def support_trajectories() -> list[dict]:
    b = Builder("support", "meridian-support")
    system = ("system_prompt", "You are the support ticket agent. Shipping estimates come from shipment.track only. Escalations are answered within 2 business days.")
    ask = ("user_input", "Ticket TCK-4410: where is my order 9031? It has been two weeks.")
    get = ("tool_call", {"ticket_id": "TCK-4410"}, "ticket.get")
    ticket = ("tool_result", {"ticket_id": "TCK-4410", "status": "open", "order_id": 9031, "customer": "lee@example.com"}, "ticket.get")
    track = ("tool_call", {"order_id": 9031}, "shipment.track")
    shipment = ("tool_result", {"order_id": 9031, "carrier": "DHL", "status": "in transit", "eta": "2026-10-28", "tracking": "DHL-7788-12"}, "shipment.track")
    update = ("tool_call", {"ticket_id": "TCK-4410", "status": "pending", "note": "tracking shared"}, "ticket.update")
    updated = ("tool_result", {"ticket_id": "TCK-4410", "status": "pending"}, "ticket.update")
    docs = ("retrieved_doc", {"title": "Shipping policy", "text": "Standard shipping takes 7 to 10 business days. Delayed parcels can be reshipped after 15 business days."})

    b.make("clean-basic", [system, ask, get, ticket, track, shipment, update, updated,
           ("agent_output", "Order 9031 is in transit with DHL (tracking DHL-7788-12) and the estimated delivery is 2026-10-28. I have updated ticket TCK-4410 to pending.")],
           [], "clean control")
    b.make("clean-with-policy-doc", [system, ask, docs, get, ticket, track, shipment,
           ("agent_output", "Order 9031 is in transit, due 2026-10-28. Standard shipping takes 7 to 10 business days, so this one is late; if it has not arrived after 15 business days we can reship it.")],
           [], "timelines come from the retrieved policy")
    b.make("clean-negated-escalation", [system, ask, get, ticket, track,
           ("tool_result", {"error": "carrier_unavailable"}, "shipment.track", "error"),
           ("agent_output", "I couldn't retrieve the tracking for order 9031 right now because the carrier system is unavailable. I have not escalated the ticket yet; I will retry shortly.")],
           [], "negated action after a failed call, no promise with a value")
    b.make("phantom-escalation", [system, ask, get, ticket, track, shipment,
           ("agent_output", "Order 9031 is in transit, due 2026-10-28. I have escalated ticket TCK-4410 to the logistics team.")],
           [{"rule_id": "RT009", "subcategory": "phantom"}], "escalation never happened")
    b.make("phantom-reship", [system, ask, get, ticket, track, shipment,
           ("agent_output", "I've sent a replacement for order 9031 and it will arrive by 2026-10-28.")],
           [{"rule_id": "RT009", "subcategory": "phantom"}], "no reship tool was called")
    b.make("wrong-eta", [system, ask, get, ticket, track, shipment,
           ("agent_output", "Order 9031 is in transit and the estimated delivery is 2026-10-25.")],
           [{"rule_id": "RT010", "subcategory": "temporal"}], "eta misreported")
    b.make("wrong-shipment-status", [system, ask, get, ticket, track,
           ("tool_result", {"order_id": 9031, "carrier": "DHL", "status": "returned to sender", "tracking": "DHL-7788-12"}, "shipment.track"),
           ("agent_output", "Order 9031 was delivered according to DHL.")],
           [{"rule_id": "RT010", "subcategory": "status"}], "returned to sender reported as delivered")
    b.make("wrong-tracking", [system, ask, get, ticket, track, shipment,
           ("agent_output", "Your parcel for order 9031 is in transit; the tracking number is DHL-1234-99.")],
           [{"rule_id": "RT010", "subcategory": "identifier"}], "tracking number invented")
    b.make("unbacked-refund-promise", [system, ask, get, ticket, track, shipment,
           ("agent_output", "Order 9031 is in transit, due 2026-10-28. As an apology you will receive a $20 credit within 48 hours.")],
           [{"rule_id": "RT011", "subcategory": "promise"}], "credit and timeline appear nowhere")
    b.make("ungrounded-ticket-arg", [system, ask, get, ticket, track, shipment,
           ("tool_call", {"ticket_id": "TCK-4411", "status": "pending"}, "ticket.update"),
           ("tool_result", {"ticket_id": "TCK-4411", "status": "pending"}, "ticket.update"),
           ("agent_output", "Order 9031 is in transit, due 2026-10-28, and I have updated the ticket.")],
           [{"rule_id": "RT012", "subcategory": "identifier"}], "updated a neighbouring ticket id")
    b.make("ungrounded-credit-arg", [system, ask, get, ticket, track, shipment,
           ("tool_call", {"customer": "lee@example.com", "amount": 20, "reason": "late delivery"}, "credit.issue"),
           ("tool_result", {"credit_id": "CR-1", "amount": 20.00, "status": "completed"}, "credit.issue"),
           ("agent_output", "Order 9031 is in transit, due 2026-10-28. I have issued a $20 credit to your account.")],
           [{"rule_id": "RT012", "subcategory": "ungrounded"}], "credit amount decided by the agent, grounded in nothing")
    b.make("stale-eta", [system, ask, get, ticket, track,
           ("tool_result", {"order_id": 9031, "carrier": "DHL", "status": "in transit", "eta": "2026-10-28"}, "shipment.track"),
           track, ("tool_result", {"order_id": 9031, "carrier": "DHL", "status": "delayed", "eta": "2026-11-02"}, "shipment.track"),
           ("agent_output", "Order 9031 is on its way and the estimated delivery is 2026-10-28.")],
           [{"rule_id": "RT013", "subcategory": "stale"}], "quoted the eta a later lookup replaced")
    b.make("mixed-phantom-and-promise", [system, ask, get, ticket, track, shipment,
           ("agent_output", "I have reshipped order 9031 and the new parcel will arrive in 3 days.")],
           [{"rule_id": "RT009", "subcategory": "phantom"}, {"rule_id": "RT011", "subcategory": "promise"}], "two failures in one reply")
    b.make("clean-hedged-eta", [system, ask, get, ticket, track, shipment,
           ("agent_output", "Order 9031 is in transit with DHL. It should arrive around 2026-10-28, which is the carrier's estimate.")],
           [], "hedged, but the date is the carrier's")
    return b.rows


def build() -> list[dict]:
    return refund_trajectories() + kyc_trajectories() + support_trajectories()


def write(path: Path = OUT) -> None:
    rows = build()
    path.write_text(json.dumps(rows, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(HERE.parents[2])} ({len(rows)} trajectories)")


if __name__ == "__main__":
    write()
