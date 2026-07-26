"""Pays each participant a completion incentive once their interview
wraps up. The amount is model-assessed from interview completeness, then
sent via Stripe. A real spend ceiling exists in code -- it was just never
formally declared as an economic_authority fact, which is the point.

Planted: the 'move_funds' permission tag (stripe.Payout.create), AI002/sql
(the payout log write), and a hardcoded cap -- landing bounded_autonomous on
the autonomy ladder (a level this fixture didn't otherwise demonstrate).
Paired with an intentionally absent stoa-declared.toml entry: DECL003
(money-moving permission, no declared economic_authority) -- the ceiling is
real, but nobody ever governed it.
"""
import psycopg2
import stripe
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o")
conn = psycopg2.connect(dsn="postgresql://localhost/threshold")

MAX_INCENTIVE_CENTS = 5000  # $50 -- a real ceiling, just never declared

tools = [{"type": "function", "function": {"name": "pay_incentive"}}]
agent = create_tool_calling_agent(llm, tools, "Assess interview completeness and pay the incentive.")
executor = AgentExecutor(agent=agent, tools=tools)


def pay_incentive(participant_id: str, transcript: str) -> str:
    assessment = llm.invoke(
        f"Rate completeness 0-100 and suggest a cents amount up to {MAX_INCENTIVE_CENTS}: {transcript}"
    ).content

    amount_cents = _parse_suggested_amount(assessment)
    if amount_cents > MAX_INCENTIVE_CENTS:
        amount_cents = MAX_INCENTIVE_CENTS

    payout = stripe.Payout.create(amount=amount_cents, currency="usd")

    cursor = conn.cursor()
    cursor.execute(
        f"INSERT INTO payouts (participant_id, payout_id, note) VALUES ('{participant_id}', '{payout.id}', '{assessment}')"
    )  # AI002/sql
    conn.commit()
    return payout.id


def _parse_suggested_amount(assessment: str) -> int:
    return 2500  # placeholder parse of the model's suggested amount
