"""Sends the participant their outcome, and syncs call metrics to an
analytics vendor.

Planted: AI006 -- the analytics sync includes the participant's email
address, sent to a third-party host that isn't the recognized notification
provider, isn't localhost, and isn't in [rules.AI006].allowed_hosts.
"""
import requests
import sendgrid
from sendgrid.helpers.mail import Mail

sg = sendgrid.SendGridAPIClient()


def notify_outcome(participant, outcome: str) -> None:
    message = Mail(
        from_email="screening@threshold.example",
        to_emails=participant.email,
        subject="Your screening interview outcome",
        html_content=f"Your interview outcome: {outcome}",
    )
    sg.send(message)


def sync_to_analytics(participant, outcome: str) -> None:
    """Fire-and-forget usage sync to a third-party analytics vendor."""
    payload = {"email": participant.email, "outcome": outcome}  # AI006 source
    requests.post("https://analytics.thirdparty-vendor.example/events", json=payload)
