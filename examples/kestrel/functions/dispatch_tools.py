"""Tool executor for the dispatch agent: re-route, email, alert.

Not an agent either — but note what it does with whatever the model hands it:
an unconditional UPDATE to the shipments table, an email to any address, and
an SNS publish. None of that is visible to a code scanner as *agent* risk,
because the model call is on the other side of the Bedrock boundary. The
reach is visible in ../infra/iam.tf, which is what Stoa reads.
"""

import os

import boto3

_ddb = boto3.resource("dynamodb")
_ses = boto3.client("ses")
_sns = boto3.client("sns")


def handler(event, _context):
    params = {p["name"]: p["value"] for p in event.get("parameters", [])}
    fn = event["function"]
    if fn == "reroute_shipment":
        body = reroute_shipment(params["shipment_id"], params["new_route"], params["delivery_window"])
    elif fn == "notify_customer":
        body = notify_customer(params["email"], params["message"])
    elif fn == "notify_driver":
        body = notify_driver(params["driver_id"], params["message"])
    else:
        body = {"error": f"unknown function {fn}"}
    return _respond(event, body)


def reroute_shipment(shipment_id, new_route, delivery_window):
    _ddb.Table(os.environ["SHIPMENTS_TABLE"]).update_item(
        Key={"shipment_id": shipment_id},
        UpdateExpression="SET route = :r, delivery_window = :w, rerouted_by = :who",
        ExpressionAttributeValues={":r": new_route, ":w": delivery_window, ":who": "dispatch-agent"},
    )
    return {"ok": True, "shipment_id": shipment_id}


def notify_customer(email, message):
    _ses.send_email(
        Source=os.environ["FROM_ADDRESS"],
        Destination={"ToAddresses": [email]},
        Message={"Subject": {"Data": "Update on your Kestrel shipment"}, "Body": {"Text": {"Data": message}}},
    )
    return {"ok": True}


def notify_driver(driver_id, message):
    _sns.publish(TopicArn=os.environ["DRIVER_TOPIC"], Message=message, MessageAttributes={
        "driver_id": {"DataType": "String", "StringValue": driver_id},
    })
    return {"ok": True}


def _respond(event, body):
    return {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": event["actionGroup"],
            "function": event["function"],
            "functionResponse": {"responseBody": {"TEXT": {"body": str(body)}}},
        },
    }
