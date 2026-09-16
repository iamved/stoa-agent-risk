resource "databricks_service_principal" "support" { display_name = "meridian-support-sp" }

resource "databricks_model_serving" "support_chat" {
  name = "meridian-support-chat"
  config { served_entities { entity_name = "prod.agents.meridian_support"  entity_version = "14" } }
  ai_gateway {
    guardrails { input { pii { behavior = "BLOCK" } } output { pii { behavior = "BLOCK" } } }
    rate_limits { calls = 600  renewal_period = "minute" }
    inference_table_config { enabled = true  catalog_name = "prod"  schema_name = "ai_logs" }
  }
}
# Planted: the IVR endpoint serves the same agent with no gateway.
resource "databricks_model_serving" "support_ivr" {
  name = "meridian-support-ivr"
  config { served_entities { entity_name = "prod.agents.meridian_support"  entity_version = "14" } }
}
# Planted: EXECUTE on the whole tools schema, not per function.
resource "databricks_grants" "tools_schema" {
  schema = "prod.tools"
  grant { principal = databricks_service_principal.support.application_id  privileges = ["EXECUTE", "USE_SCHEMA"] }
}
resource "databricks_grants" "customers" {
  catalog = "prod"
  grant { principal = databricks_service_principal.support.application_id  privileges = ["SELECT", "MODIFY", "USE_CATALOG"] }
}
resource "databricks_vector_search_index" "tickets" {
  name          = "prod.support.tickets_index"
  endpoint_name = "support-vs"
  primary_key   = "ticket_id"
  index_type    = "DELTA_SYNC"
  delta_sync_index_spec { source_table = "prod.support.tickets" }
}
