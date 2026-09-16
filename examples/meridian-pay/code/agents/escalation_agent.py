"""Escalation agent: drafts case notes and pushes to the human queue."""
import requests
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState

model = ChatOpenAI(model="gpt-4o-mini")

def escalate(state: MessagesState):
    notes = model.invoke([("system", "Summarize this conversation as a case note for a human agent."), *state["messages"]])
    requests.post("https://queue.meridian.internal/cases", json={"note": notes.content}, timeout=5)
    return {"messages": [notes]}

graph = StateGraph(MessagesState)
graph.add_node("escalate", escalate)
graph.set_entry_point("escalate")
escalation = graph.compile()
