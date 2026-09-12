# The webhook's executor and identity. What the agent can *reach* is whatever
# this service account is granted below — Stoa follows agent -> webhook ->
# function -> service account -> IAM role.

resource "google_service_account" "webhook" {
  account_id   = "${var.name}-webhook"
  display_name = "Webhook executor for ${var.name}"
  project      = var.project
}

resource "google_cloudfunctions2_function" "webhook" {
  name     = "${var.name}-webhook"
  location = var.location
  project  = var.project

  build_config {
    runtime     = "python312"
    entry_point = "handle"
    source {
      storage_source {
        bucket = "${var.project}-functions"
        object = "${var.name}-webhook.zip"
      }
    }
  }

  service_config {
    service_account_email = google_service_account.webhook.email
    max_instance_count    = 10
    environment_variables = {
      AGENT_NAME = var.name
    }
  }
}

resource "google_project_iam_member" "webhook" {
  for_each = toset(var.webhook_roles)

  project = var.project
  role    = each.value
  member  = "serviceAccount:${google_service_account.webhook.email}"
}
