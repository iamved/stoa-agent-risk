# Tidewater — Databricks deployment layer for two agents.
#
# Two serving endpoints, planted for contrast. support_agent is the
# well-controlled baseline: an AI Gateway with guardrails, rate limits, and
# inference tables, plus a single narrow SELECT grant. refund_agent has none of
# that — no gateway, a catalog-wide ALL_PRIVILEGES grant, and MODIFY on the
# refunds table. Nothing in this file is Python: without an IaC collector, a
# code scanner cannot see that either endpoint exists.

terraform {
  required_providers {
    databricks = { source = "databricks/databricks" }
  }
}

# ── identities ───────────────────────────────────────────────────────────────

resource "databricks_service_principal" "support_sp" {
  display_name = "tidewater-support-agent"
}

resource "databricks_service_principal" "refund_sp" {
  display_name = "tidewater-refund-agent"
}

# ── support_agent: the well-controlled baseline ─────────────────────────────

resource "databricks_model_serving" "support_agent" {
  name = "tidewater-support-agent"

  config {
    served_entities {
      name                  = "support-agent"
      entity_name           = "prod.agents.support_agent"   # the UC-registered agent
      entity_version        = "3"
      workload_size         = "Small"
      scale_to_zero_enabled = true
    }
  }

  # Explicit controls — the scanner can credit these rather than infer them.
  ai_gateway {
    guardrails {
      input {
        pii { behavior = "BLOCK" }
      }
      output {
        safety = true
      }
    }
    inference_table_config {
      enabled           = true
      catalog_name      = "prod"
      schema_name       = "monitoring"
      table_name_prefix = "support_agent"
    }
    rate_limits {
      calls          = 100
      renewal_period = "minute"
      key            = "endpoint"
    }
    usage_tracking_config {
      enabled = true
    }
  }
}

# Narrow, read-only data reach: one table, SELECT only.
resource "databricks_grants" "support_transactions" {
  table = "prod.customers.transactions"
  grant {
    principal  = databricks_service_principal.support_sp.application_id
    privileges = ["SELECT"]
  }
}

# RAG source: the policy knowledge base the support agent retrieves from.
resource "databricks_vector_search_index" "policies" {
  name          = "prod.knowledge.policies_index"
  endpoint_name = "tidewater-vs"
  primary_key   = "doc_id"
  index_type    = "DELTA_SYNC"
  delta_sync_index_spec {
    source_table  = "prod.knowledge.policies"
    pipeline_type = "TRIGGERED"
  }
}

# ── refund_agent: the poorly-controlled case ────────────────────────────────

resource "databricks_model_serving" "refund_agent" {
  name = "tidewater-refund-agent"

  config {
    served_entities {
      name           = "refund-agent"
      entity_name    = "prod.agents.refund_agent"
      entity_version = "1"
      workload_size  = "Small"
      environment_vars = {
        OPENAI_API_KEY = "{{secrets/agents/openai_key}}"   # third-party model egress
      }
    }
  }
  # No ai_gateway block: no guardrails, no rate limits, no inference tables.
}

# Catalog-wide privileges for an agent that only needs one table: overreach.
resource "databricks_grants" "refund_catalog" {
  catalog = "prod"
  grant {
    principal  = databricks_service_principal.refund_sp.application_id
    privileges = ["ALL_PRIVILEGES"]
  }
}

# Write reach onto money-moving data, with no gate in front of it.
resource "databricks_grants" "refund_writes" {
  table = "prod.payments.refunds"
  grant {
    principal  = databricks_service_principal.refund_sp.application_id
    privileges = ["SELECT", "MODIFY"]
  }
}
