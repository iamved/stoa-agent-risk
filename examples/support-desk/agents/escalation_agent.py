"""Escalation agent: drafts a handoff, files a Zendesk ticket, pings Slack.

PLANTED RISK (for the Stoa demo): a swallowed exception around the Slack ping.
"""

import os

import requests
from anthropic import Anthropic

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

tools = [
    {"name": "file_ticket", "description": "Create a Zendesk ticket"},
    {"name": "notify_oncall", "description": "Ping the on-call channel"},
]


def escalate(message: str) -> str:
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1024,
        tools=tools,
        messages=[{"role": "user", "content": f"Draft an escalation summary: {message}"}],
    )
    summary = response.content[0].text
    file_ticket(summary)
    notify_oncall(summary)
    return summary


def file_ticket(summary: str) -> None:
    requests.post(
        "https://example-desk.zendesk.com/api/v2/tickets.json",
        json={"ticket": {"subject": "Escalation", "comment": {"body": summary}}},
        auth=(os.environ["ZENDESK_USER"], os.environ["ZENDESK_API_TOKEN"]),
        timeout=10,
    )


def notify_oncall(summary: str) -> None:
    try:
        requests.post(os.environ["SLACK_ESCALATIONS_WEBHOOK_URL"], json={"text": summary}, timeout=5)
    except Exception:
        pass
