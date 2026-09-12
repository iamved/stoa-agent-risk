variable "project_id" {
  description = "GCP project the agents run in (overridden by terraform.tfvars)"
  type        = string
  default     = "marlowe-dev"
}

variable "region" {
  type    = string
  default = "us-central1"
}
