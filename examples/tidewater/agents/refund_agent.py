"""Tidewater refund agent — decides and issues refunds.

Planted risks, on purpose:
  * the model's tool-call arguments are decoded and driven straight into a
    Stripe refund and an UPDATE — model output reaching money-moving sinks
    with no approval step observed (AI002, unreviewed high-impact action);
  * it is declared `human_approved` in stoa-declared.toml, which the code
    contradicts (DECL001);
  * in infra/main.tf its endpoint has no AI Gateway (no guardrails, rate
    limits, or inference tables) and its principal holds ALL_PRIVILEGES on the
    whole `prod` catalog plus MODIFY on refunds — overreach and a control gap
    that only the IaC layer can show.
"""

import json

import mlflow
import stripe
from openai import OpenAI

UC_MODEL = "prod.agents.refund_agent"
client = OpenAI()

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "issue_refund",
            "description": "Refund a charge for a given amount.",
            "parameters": {
                "type": "object",
                "properties": {
                    "charge_id": {"type": "string"},
                    "amount_cents": {"type": "integer"},
                    "reason": {"type": "string"},
                },
            },
        },
    }
]


def decide_and_refund(ticket: dict) -> str:
    messages = [
        {"role": "system", "content": "You resolve refund requests. Decide, then act."},
        {"role": "user", "content": json.dumps(ticket)},
    ]
    while True:
        r = client.chat.completions.create(model="gpt-4o", messages=messages, tools=TOOLS)
        msg = r.choices[0].message
        if not msg.tool_calls:
            return msg.content
        call = msg.tool_calls[0]
        args = json.loads(call.function.arguments)
        # Model-chosen amount, straight to the payment processor — no approval.
        stripe.Refund.create(charge=args["charge_id"], amount=args["amount_cents"])
        # Model-chosen reason, interpolated straight into the write.
        spark.sql(
            f"UPDATE prod.payments.refunds SET status = 'approved', "
            f"reason = '{args['reason']}' WHERE charge_id = '{args['charge_id']}'"
        )
        messages.append({"role": "tool", "tool_call_id": call.id, "content": "refunded"})


def register() -> None:
    with mlflow.start_run():
        info = mlflow.pyfunc.log_model(artifact_path="agent", python_model=None)
        mlflow.register_model(info.model_uri, UC_MODEL)
