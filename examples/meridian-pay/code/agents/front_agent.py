"""Front agent: conversation, intent, KBA, routing.

Runs in code. Two of the specialists it routes to run elsewhere: the
knowledge agent is an Amazon Bedrock agent (aws/agents.tf) and the escalation
agent is a Databricks model serving endpoint (databricks/infra/main.tf).
"""
import logging
import os
import boto3
import requests
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from tools.account_tools import verify_identity
from agents.account_actions_agent import account_actions

logger = logging.getLogger("meridian.front")   # ships to Splunk via the container log driver
model = ChatOpenAI(model="gpt-4o", temperature=0.3).bind_tools([verify_identity])
bedrock = boto3.client("bedrock-agent-runtime", region_name="us-east-1")
ESCALATION_ENDPOINT = "https://meridian.cloud.databricks.com/serving-endpoints/meridian-escalation/invocations"

SYSTEM = "You are Meridian Bank's virtual assistant. Verify identity before any account action. Route account changes to the account-actions agent."

def route(state: MessagesState) -> str:
    last = state["messages"][-1].content.lower()
    if any(w in last for w in ("refund", "fee", "address", "card", "travel")):
        return "account_actions"
    if "agent" in last or "human" in last:
        return "escalate"
    return "knowledge"

def knowledge(state: MessagesState):
    """The Bedrock knowledge agent answers from the ticket and policy knowledge base."""
    response = bedrock.invoke_agent(agentId=os.environ["KNOWLEDGE_AGENT_ID"], agentAliasId="TSTALIASID", sessionId="front", inputText=state["messages"][-1].content)
    return {"messages": [("assistant", "".join(chunk["chunk"]["bytes"].decode() for chunk in response["completion"]))]}

def escalate(state: MessagesState):
    """The Databricks escalation endpoint drafts the case note and queues it for a person."""
    response = requests.post(ESCALATION_ENDPOINT, json={"messages": [m.content for m in state["messages"]]}, headers={"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}"}, timeout=10)
    return {"messages": [("assistant", response.json()["note"])]}

graph = StateGraph(MessagesState)
graph.add_node("front", lambda s: {"messages": [model.invoke([("system", SYSTEM)] + s["messages"])]})
graph.add_node("kba", ToolNode([verify_identity]))
graph.add_node("account_actions", account_actions)
graph.add_node("knowledge", knowledge)
graph.add_node("escalate", escalate)
graph.set_entry_point("front")
graph.add_conditional_edges("front", route)
front_agent = graph.compile()
