"""Intent triage: classifies each customer message and picks a specialist."""

from pydantic_ai import Agent

triage_agent = Agent(
    "openai:gpt-4o-mini",
    system_prompt=(
        "Classify the customer message into exactly one intent: "
        "billing, account, research, or escalate. Reply with the intent only."
    ),
)


@triage_agent.tool_plain
def recent_ticket_count(customer_id: str) -> int:
    """How many tickets this customer opened in the last 30 days."""
    from tools.database import count_recent_tickets

    return count_recent_tickets(customer_id)
