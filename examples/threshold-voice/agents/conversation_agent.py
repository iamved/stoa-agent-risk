"""The adaptive interview brain — framework-based (LangGraph), decides what
to ask next based on the participant's prior answers, and calls out to the
intake MCP server's tools mid-conversation.

Planted: AI005 floating-alias (unpinned model string) — the exact question
logic this agent runs can silently change behavior on a provider-side model
update, with no dated snapshot to pin against.
"""
from langgraph.graph import StateGraph
from openai import OpenAI
from mcp import ClientSession

client = OpenAI()

TOOLS = [
    {"type": "function", "function": {"name": "save_response"}},
    {"type": "function", "function": {"name": "flag_for_review"}},
]


def build_graph():
    graph = StateGraph(dict)
    graph.add_node("ask_next", ask_next_question)
    return graph


def ask_next_question(state: dict) -> dict:
    prior_answers = state.get("answers", [])
    reply = client.chat.completions.create(
        model="gpt-4o",  # AI005 floating-alias — resolves differently over time
        messages=[
            {"role": "system", "content": "Ask one adaptive follow-up question."},
            {"role": "user", "content": str(prior_answers)},
        ],
        tools=TOOLS,
    )
    return {"next_question": reply.choices[0].message.content}


async def record_answer(session: ClientSession, question_id: str, answer: str):
    """Persists a single answer through the intake MCP server's tool."""
    await session.call_tool("save_response", {"question_id": question_id, "answer": answer})
