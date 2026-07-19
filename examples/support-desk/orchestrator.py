"""Supervisor that routes customer messages to specialist agents."""

import os

from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from agents.account_agent import run_account_task
from agents.billing_agent import billing_executor
from agents.escalation_agent import escalate
from agents.research_agent import research
from agents.triage_agent import triage_agent

supervisor_llm = ChatOpenAI(model="gpt-4o", api_key=os.environ["OPENAI_API_KEY"])


def route(state: dict) -> str:
    intent = state.get("intent", "triage")
    return {
        "billing": "billing",
        "account": "account",
        "research": "research",
        "escalate": "escalate",
    }.get(intent, "triage")


def triage_node(state: dict) -> dict:
    result = triage_agent.run_sync(state["message"])
    return {**state, "intent": result.output}


def billing_node(state: dict) -> dict:
    reply = billing_executor.invoke({"input": state["message"]})
    return {**state, "reply": reply["output"]}


workflow = StateGraph(dict)
workflow.add_node("triage", triage_node)
workflow.add_node("billing", billing_node)
workflow.add_node("account", lambda s: {**s, "reply": run_account_task(s["message"])})
workflow.add_node("research", lambda s: {**s, "reply": research(s["message"])})
workflow.add_node("escalate", lambda s: {**s, "reply": escalate(s["message"])})
workflow.set_entry_point("triage")
workflow.add_conditional_edges("triage", route)
for node in ("billing", "account", "research", "escalate"):
    workflow.add_edge(node, END)

support_desk = workflow.compile()
