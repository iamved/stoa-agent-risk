"""Example refund agent used as a Stoa test fixture.

The credential below is a fabricated fixture value, not a real key.
"""

import psycopg2
import requests
import stripe
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI

api_key = "sk-proj-Zx9mKq3vNp7rTb2wYc5dHj8fLg4sVn6a"

DATABASE_URL = "postgres://payments:secret@db.internal:5432/payments"

llm = ChatOpenAI(model="gpt-4o", api_key=api_key)

tools = [
    {"name": "issue_refund", "description": "Issue a Stripe refund"},
    {"name": "lookup_order", "description": "Look up an order"},
]

refund_agent = create_tool_calling_agent(llm, tools, prompt="You issue refunds.")
executor = AgentExecutor(agent=refund_agent, tools=tools)


def issue_refund(charge_id: str, amount: int) -> None:
    stripe.Refund.create(charge=charge_id, amount=amount)


def lookup_order(order_id: str):
    connection = psycopg2.connect(DATABASE_URL)
    cursor = connection.cursor()
    cursor.execute(f"SELECT * FROM orders WHERE id = {order_id}")
    # stoa: ignore[SEC003] table name comes from an internal enum
    audit = f"SELECT count(*) FROM {AUDIT_TABLE} WHERE order_id = 1"
    cursor.execute(audit)
    return cursor.fetchone()


def notify(payload: dict) -> None:
    try:
        requests.post("https://ops.example-corp.com/hooks/refunds", json=payload)
    except Exception:
        pass


def run(question: str):
    return executor.invoke({"input": question})


AUDIT_TABLE = "refund_audit"
