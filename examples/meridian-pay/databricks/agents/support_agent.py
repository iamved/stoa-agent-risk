"""Mosaic AI Agent Framework agent: tools are Unity Catalog functions."""
import mlflow
from databricks.sdk import WorkspaceClient
from databricks_langchain import ChatDatabricks, UCFunctionToolkit, VectorSearchRetrieverTool
from langgraph.prebuilt import create_react_agent

llm = ChatDatabricks(endpoint="databricks-claude-3-7-sonnet")
tools = UCFunctionToolkit(function_names=["prod.tools.issue_refund", "prod.tools.waive_fee", "prod.tools.update_contact_info", "prod.tools.reissue_card", "prod.tools.place_travel_notice", "prod.tools.change_payout_account"]).tools
tools.append(VectorSearchRetrieverTool(index_name="prod.support.tickets_index"))
SYSTEM = "Refunds up to $500. Waivers up to $150. Verify identity before account changes."
agent = create_react_agent(llm, tools, prompt=SYSTEM)
mlflow.langchain.autolog()
mlflow.models.set_model(agent)
