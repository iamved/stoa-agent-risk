"""Five scripted sessions through the refund bot, traced with the LangChain
callback handler, then verify and reconcile. Run with `make demo`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from stoa import runtime as stoa_rt  # noqa: E402
from stoa.runtime.integrations.langchain import StoaCallbackHandler  # noqa: E402

import refund_bot  # noqa: E402

TRACES = HERE / "stoa-traces"
SIDE_EFFECTS = {"lookup_order": "read", "issue_refund": "payment", "send_email": "external_send", "undeclared_export": "external_send"}
LIMIT_FIELDS = {"issue_refund": "amount_eur"}

SESSIONS = [
    {"thread_id": "t1", "order_id": "o-1001", "requested_eur": 120.0},
    {"thread_id": "t2", "order_id": "o-1003", "requested_eur": 45.0},
    {"thread_id": "t3", "order_id": "o-1002", "requested_eur": 980.0, "human_decision": True},   # above the threshold: interrupt, then approved
    {"thread_id": "t4", "order_id": "o-1001", "requested_eur": 120.0},                            # the duplicate refund attempt
    {"thread_id": "t5", "order_id": "o-1003", "requested_eur": 45.0, "export": True},             # calls a tool the scan never saw
]


def main() -> int:
    stoa_rt.configure(str(TRACES), agent_id=os.environ.get("STOA_AGENT", "refund_bot"),
                      signing_key=os.environ.get("STOA_SIGNING_KEY", "hmac:demo-only-key"),
                      registry_path=str(HERE / "stoa-registry.json") if (HERE / "stoa-registry.json").exists() else None)
    handler = StoaCallbackHandler(side_effects=SIDE_EFFECTS, limit_fields=LIMIT_FIELDS, currency="EUR")
    for state in SESSIONS:
        with stoa_rt.session(user_ref=refund_bot.ORDERS[state["order_id"]]["customer"]):
            result = refund_bot.run(dict(state), config={"callbacks": [handler], "metadata": {"thread_id": state["thread_id"]}})
            print(f"{state['thread_id']}: {result.get('result')}")
    stoa_rt.shutdown()
    report = stoa_rt.verify_chain(str(TRACES), os.environ.get("STOA_SIGNING_KEY", "hmac:demo-only-key"))
    print(f"chain: {'intact' if report.ok else 'BROKEN'} ({report.records} records)")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
