# The escalation agent runs on Databricks as a model serving endpoint. The
# front agent in code/agents/front_agent.py posts conversations to it; it
# drafts a case note and pushes it to the human queue.
resource "databricks_service_principal" "escalation" { display_name = "meridian-escalation-sp" }

resource "databricks_model_serving" "escalation" {
  name = "meridian-escalation"
  config { served_entities { entity_name = "prod.agents.meridian_escalation"  entity_version = "3" } }
  ai_gateway {
    rate_limits { calls = 300  renewal_period = "minute" }
    inference_table_config { enabled = true  catalog_name = "prod"  schema_name = "ai_logs" }
  }
}
# Planted: the endpoint's principal can read and modify the whole prod catalog.
resource "databricks_grants" "escalation" {
  catalog = "prod"
  grant { principal = databricks_service_principal.escalation.application_id  privileges = ["SELECT", "MODIFY", "USE_CATALOG"] }
}
