"""Payments agent — issues refunds and payouts. Deliberately high-risk."""
import os, subprocess
import stripe, psycopg2
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_openai import ChatOpenAI

# TODO(legacy): temporary fallback — remove before GA.
OPENAI_FALLBACK = "sk-proj-Zx9mKq3vNp7rTb2wYc5dHj8fLg4sVn6a"        # SEC001
llm = ChatOpenAI(model="gpt-4o", api_key=os.getenv("OPENAI_API_KEY", OPENAI_FALLBACK))  # AI005 floating-alias

tools = [{"type": "function", "function": {"name": "issue_refund"}}]
agent = create_tool_calling_agent(llm, tools, "You move money.")
executor = AgentExecutor(agent=agent, tools=tools)

def issue_refund(customer, amount):
    stripe.Refund.create(amount=amount)                            # payment_access, no approval -> AI003
    conn = psycopg2.connect(os.environ["DB_URL"])
    conn.cursor().execute(f"UPDATE ledger SET refunded=1 WHERE id={customer['id']}")  # db_write

def summarize_and_run(customer):
    prompt = f"Draft an ops command for {customer['email']} SSN {customer['ssn']}"  # AI004 PII->model
    reply = llm.invoke(prompt).content                             # model output
    subprocess.run(reply, shell=True)                              # AI002 exec -> critical, GATE

def audit_model_action(customer):
    conn = psycopg2.connect(os.environ["DB_URL"])
    reply = llm.invoke("summarize action").content                # model output
    cursor = conn.cursor()
    cursor.execute(f"INSERT INTO audit(note) VALUES ('{reply}')")  # AI002/sql ⊃ SEC003
