# One Dialogflow CX agent, its webhook, and the controls — all driven by inputs.

resource "google_dialogflow_cx_agent" "this" {
  display_name          = var.name
  location              = var.location
  default_language_code = "en"
  time_zone             = "America/Chicago"
  description           = "Marlowe customer agent ${var.name}"

  enable_stackdriver_logging = var.logging
  security_settings          = var.redaction ? google_dialogflow_cx_security_settings.this[0].id : null

  advanced_settings {
    logging_settings {
      enable_stackdriver_logging  = var.logging
      enable_interaction_logging  = var.logging
    }
  }
}

resource "google_dialogflow_cx_security_settings" "this" {
  count = var.redaction ? 1 : 0

  display_name          = "${var.name}-security"
  location              = var.location
  redaction_strategy    = "REDACT_WITH_SERVICE"
  redaction_scope       = ["REDACT_DISK_STORAGE"]
  retention_window_days = 30
  purge_data_types      = ["DIALOGFLOW_HISTORY"]

  insights_export_settings {
    enable_insights_export = true
  }
}

# The tool: every fulfilment goes through this webhook to a Cloud Function.
resource "google_dialogflow_cx_webhook" "account" {
  parent       = google_dialogflow_cx_agent.this.id
  display_name = "${var.name}-account-webhook"
  timeout      = "10s"

  generic_web_service {
    uri = google_cloudfunctions2_function.webhook.service_config[0].uri
  }
}

resource "google_dialogflow_cx_flow" "knowledge" {
  count = var.knowledge ? 1 : 0

  parent       = google_dialogflow_cx_agent.this.id
  display_name = "Knowledge"

  knowledge_connector_settings {
    enabled = true
    data_store_connections {
      data_store      = var.data_store
      data_store_type = "UNSTRUCTURED"
    }
  }
}
