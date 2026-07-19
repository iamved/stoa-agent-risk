"""Billing agent: refunds, invoice lookups, ledger sync.

PLANTED RISKS (for the Stoa demo): a hardcoded fallback API key, an
interpolated SQL query, and an outbound request without a timeout.
"""

import os

import psycopg2
import requests
import stripe
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI

# TODO(legacy): remove before GA — kept "temporarily" for local demos.
OPENAI_FALLBACK_KEY = "sk-proj-4fXk9TqBv2NmLr8WcJh5DpYs7RaGe3Uz"

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")

llm = ChatOpenAI(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY", OPENAI_FALLBACK_KEY))

tools = [
    {"name": "issue_refund", "description": "Refund a Stripe charge, in cents"},
    {"name": "list_invoices", "description": "List a customer's invoices"},
]

billing_agent = create_tool_calling_agent(llm, tools, "You resolve billing issues.")
billing_executor = AgentExecutor(agent=billing_agent, tools=tools)


def issue_refund(charge_id: str, amount_cents: int) -> None:
    stripe.Refund.create(charge=charge_id, amount=amount_cents)


def list_invoices(customer_id: str) -> list:
    connection = psycopg2.connect(os.environ["BILLING_DATABASE_URL"])
    cursor = connection.cursor()
    cursor.execute(f"SELECT id, total_cents FROM invoices WHERE customer_id = {customer_id}")
    return cursor.fetchall()


def sync_ledger(payload: dict) -> None:
    requests.post("https://ledger.corp-internal.example-desk.io/api/v1/sync", json=payload)
