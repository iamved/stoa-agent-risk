"""Tool executor for the claims assistant: one read-only lookup.

This is *not* an agent. There is no model call here — Bedrock runs the loop
and invokes this function with the parameters the model chose. The code
scanner correctly finds nothing agent-shaped in this file; the agent that
drives it lives in ../infra/agents.tf.
"""

import os

import boto3

_table = boto3.resource("dynamodb").Table(os.environ["CLAIMS_TABLE"])


def handler(event, _context):
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}
    item = _table.get_item(Key={"claim_id": params["claim_id"]}).get("Item")
    if item is None:
        body = {"status": "not_found"}
    else:
        body = {
            "status": item["status"],
            "adjuster": item.get("adjuster", "unassigned"),
            "next_step": item.get("next_step", "Awaiting carrier inspection report"),
        }
    return _respond(event, body)


def _respond(event, body):
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event["actionGroup"],
            "function": event["function"],
            "functionResponse": {"responseBody": {"TEXT": {"body": str(body)}}},
        },
    }
