variable "name" { type = string }
variable "project" { type = string }
variable "location" {
  type    = string
  default = "us-central1"
}
variable "redaction" {
  description = "Attach security settings with PII redaction and a retention window"
  type        = bool
  default     = true
}
variable "logging" {
  type    = bool
  default = true
}
variable "knowledge" {
  type    = bool
  default = false
}
variable "data_store" {
  type    = string
  default = ""
}
variable "webhook_roles" {
  description = "IAM roles granted to the webhook's service account"
  type        = list(string)
  default     = []
}
