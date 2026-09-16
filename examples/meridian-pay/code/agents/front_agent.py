"""Front agent: conversation, intent, KBA, routing."""
import logging
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from tools.account_tools import verify_identity
from agents.account_actions_agent import account_actions
from agents.knowledge_agent import knowledge
from agents.escalation_agent import escalate

logger = logging.getLogger("meridian.front")   # ships to Splunk via the container log driver
model = ChatOpenAI(model="gpt-4o", temperature=0.3).bind_tools([verify_identity])

SYSTEM = "You are Meridian Bank's virtual assistant. Verify identity before any account action. Route account changes to the account-actions agent."

def route(state: MessagesState) -> str:
    last = state["messages"][-1].content.lower()
    if any(w in last for w in ("refund", "fee", "address", "card", "travel")):
        return "account_actions"
    if "agent" in last or "human" in last:
        return "escalate"
    return "knowledge"

graph = StateGraph(MessagesState)
graph.add_node("front", lambda s: {"messages": [model.invoke([("system", SYSTEM)] + s["messages"])]})
graph.add_node("kba", ToolNode([verify_identity]))
graph.add_node("account_actions", account_actions)
graph.add_node("knowledge", knowledge)
graph.add_node("escalate", escalate)
graph.set_entry_point("front")
graph.add_conditional_edges("front", route)
front_agent = graph.compile()
