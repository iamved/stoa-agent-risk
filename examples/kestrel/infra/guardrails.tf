# Controls, stated explicitly. The guardrail is attached to claims_assistant
# only (agents.tf); invocation logging is account-wide and so covers both.

resource "aws_bedrock_guardrail" "customer_facing" {
  name                      = "kestrel-customer-facing"
  description               = "PII masking, harmful-content filter, and off-topic blocking for customer agents"
  blocked_input_messaging   = "Sorry, I can't help with that request."
  blocked_outputs_messaging = "Sorry, I can't share that."

  content_policy_config {
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "HATE"
    }
    filters_config {
      input_strength  = "HIGH"
      output_strength = "HIGH"
      type            = "PROMPT_ATTACK"
    }
  }

  sensitive_information_policy_config {
    pii_entities_config {
      action = "ANONYMIZE"
      type   = "EMAIL"
    }
    pii_entities_config {
      action = "ANONYMIZE"
      type   = "PHONE"
    }
    pii_entities_config {
      action = "BLOCK"
      type   = "CREDIT_DEBIT_CARD_NUMBER"
    }
  }

  topic_policy_config {
    topics_config {
      name       = "payout-commitments"
      definition = "Promising a specific claim payout amount or settlement date"
      examples   = ["You will receive $1,200 by Friday."]
      type       = "DENY"
    }
  }
}

resource "aws_bedrock_guardrail_version" "customer_facing" {
  guardrail_arn = aws_bedrock_guardrail.customer_facing.guardrail_arn
  description   = "v1"
}

resource "aws_cloudwatch_log_group" "bedrock_invocations" {
  name              = "/kestrel/bedrock/invocations"
  retention_in_days = 90
}

resource "aws_bedrock_model_invocation_logging_configuration" "account" {
  logging_config {
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    text_data_delivery_enabled      = true
    cloudwatch_config {
      log_group_name = aws_cloudwatch_log_group.bedrock_invocations.name
      role_arn       = aws_iam_role.bedrock_logging.arn
    }
  }
}

resource "aws_iam_role" "bedrock_logging" {
  name               = "kestrel-bedrock-logging"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json
}
