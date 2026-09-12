# Marlowe Utilities — customer agents built in the Dialogflow CX console and
# deployed through one local module, called twice with different inputs.
#
# Nothing here is Python. Each module call is a separate deployed agent, and
# the contrast between the two lives entirely in the inputs: one gets
# redaction, logging, a knowledge connector and two read-only BigQuery roles;
# the other gets none of the controls, a primitive project role, and Pub/Sub.

locals {
  project  = var.project_id
  location = var.region
  common_roles = ["roles/bigquery.jobUser"]
}

module "billing_assistant" {
  source = "./modules/cx-agent"

  name          = "marlowe-billing-assistant"
  project       = local.project
  location      = local.location
  redaction     = true
  logging       = true
  knowledge     = true
  data_store    = google_discovery_engine_data_store.billing_policies.name
  webhook_roles = concat(local.common_roles, ["roles/bigquery.dataViewer"])
}

module "field_service" {
  source = "./modules/cx-agent"

  name          = "marlowe-field-service"
  project       = local.project
  location      = local.location
  redaction     = false                       # planted: no security settings
  logging       = false                       # planted: no interaction logging
  knowledge     = false
  webhook_roles = ["roles/editor", "roles/pubsub.publisher", "roles/bigquery.dataEditor"]
}

# --- a third agent built in Vertex AI Agent Builder, no Dialogflow resources --

resource "google_discovery_engine_data_store" "billing_policies" {
  location          = "global"
  data_store_id     = "billing-policies"
  display_name      = "Billing policies and tariff sheets"
  industry_vertical = "GENERIC"
  content_config    = "CONTENT_REQUIRED"
  solution_types    = ["SOLUTION_TYPE_CHAT"]
}

resource "google_discovery_engine_chat_engine" "knowledge_assistant" {
  engine_id         = "marlowe-knowledge-assistant"
  collection_id     = "default_collection"
  location          = google_discovery_engine_data_store.billing_policies.location
  display_name      = "Marlowe knowledge assistant"
  industry_vertical = "GENERIC"
  data_store_ids    = [google_discovery_engine_data_store.billing_policies.data_store_id]

  common_config {
    company_name = "Marlowe Utilities"
  }

  chat_engine_config {
    agent_creation_config {
      business              = "Marlowe Utilities"
      default_language_code = "en"
      time_zone             = "America/Chicago"
    }
  }
}
