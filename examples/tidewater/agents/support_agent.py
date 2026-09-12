"""Tidewater support agent — answers customer questions over the policy
knowledge base and a read-only view of their transactions.

Recommend-only: it explains and drafts, it never changes anything. The
Databricks deployment layer (infra/main.tf) fronts it with an AI Gateway —
PII guardrail, safety filter, rate limit, inference tables — and grants its
service principal SELECT on exactly one table. This is the well-controlled
baseline the refund agent is contrasted against.
"""

import mlflow
from databricks.vector_search.client import VectorSearchClient
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool

UC_MODEL = "prod.agents.support_agent"   # the entity_name the serving endpoint points at

vs = VectorSearchClient()
policies = vs.get_index(endpoint_name="tidewater-vs", index_name="prod.knowledge.policies_index")


@tool
def lookup_policy(question: str) -> str:
    """Retrieve the relevant policy passages for a customer question."""
    hits = policies.similarity_search(query_text=question, columns=["text"], num_results=3)
    return "\n".join(row[0] for row in hits["result"]["data_array"])


@tool
def recent_transactions(customer_id: str) -> str:
    """Read-only: the customer's last five transactions."""
    rows = spark.sql(
        "SELECT ts, amount, merchant FROM prod.customers.transactions "
        "WHERE customer_id = ? ORDER BY ts DESC LIMIT 5",
        args=[customer_id],
    ).collect()
    return "\n".join(f"{r.ts} {r.amount} {r.merchant}" for r in rows)


llm = ChatAnthropic(model="claude-3-5-sonnet-20241022")
tools = [lookup_policy, recent_transactions]
executor = AgentExecutor(agent=create_tool_calling_agent(llm, tools, prompt=None), tools=tools)


def answer(customer_id: str, question: str) -> str:
    result = executor.invoke({"input": question, "customer_id": customer_id})
    return result["output"]


def register() -> None:
    """Log and register the agent as the UC model the serving endpoint deploys."""
    with mlflow.start_run():
        info = mlflow.langchain.log_model(executor, artifact_path="agent")
        mlflow.register_model(info.model_uri, UC_MODEL)
