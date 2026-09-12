# Kestrel Freight — two customer-facing agents on Amazon Bedrock.
#
# Nothing in this directory is Python. The agents are *configured*: Bedrock
# runs the loop, the instruction is the prompt, action groups are the tools,
# and IAM (iam.tf) says what those tools may actually touch. A code scanner
# sees none of it. Every risk here is planted on purpose, for contrast.

# --- claims_assistant: the well-controlled baseline -------------------------
# Read-only. Answers "where is my damage claim" from a knowledge base and one
# lookup tool. A guardrail sits in front of it; invocation logging is on.

resource "aws_bedrockagent_agent" "claims_assistant" {
  agent_name                  = "kestrel-claims-assistant"
  agent_resource_role_arn     = aws_iam_role.claims_agent.arn
  foundation_model            = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  idle_session_ttl_in_seconds = 600
  prepare_agent               = true
  instruction                 = <<-EOT
    You help Kestrel customers understand the status of a freight damage claim.
    Look the claim up, explain the next step in plain language, and never
    promise a payout amount or a date you cannot see in the claim record.
  EOT

  guardrail_configuration {
    guardrail_identifier = aws_bedrock_guardrail.customer_facing.guardrail_id
    guardrail_version    = aws_bedrock_guardrail_version.customer_facing.version
  }
}

resource "aws_bedrockagent_agent_action_group" "claims_lookup" {
  action_group_name          = "claims-lookup"
  agent_id                   = aws_bedrockagent_agent.claims_assistant.agent_id
  agent_version              = "DRAFT"
  skip_resource_in_use_check = true

  action_group_executor {
    lambda = aws_lambda_function.claims_lookup.arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "get_claim_status"
        description = "Return the status, adjuster, and next step for a claim id"
        parameters {
          map_block_key = "claim_id"
          type          = "string"
          required      = true
        }
      }
    }
  }
}

resource "aws_bedrockagent_agent_knowledge_base_association" "claims_policy" {
  agent_id             = aws_bedrockagent_agent.claims_assistant.agent_id
  description          = "Damage-claim policy handbook and carrier liability terms"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.policy_docs.id
  knowledge_base_state = "ENABLED"
}

# --- dispatch_agent: the poorly-controlled case -----------------------------
# Re-routes live shipments and messages customers and drivers. No guardrail.
# Its tools run in a Lambda whose role (iam.tf) has dynamodb:* on every table,
# SES send, SNS publish, and a managed S3 full-access policy on top. It also
# has the code interpreter switched on.

resource "aws_bedrockagent_agent" "dispatch_agent" {
  agent_name              = "kestrel-dispatch-agent"
  agent_resource_role_arn = aws_iam_role.dispatch_agent.arn
  foundation_model        = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  prepare_agent           = true
  instruction             = <<-EOT
    You are the Kestrel dispatch desk. When a shipment is delayed or a customer
    asks for a change, re-route it, update the delivery window, and notify the
    customer and the assigned driver of the new plan.
  EOT
  # no guardrail_configuration — planted
}

resource "aws_bedrockagent_agent_action_group" "dispatch_tools" {
  action_group_name = "dispatch-tools"
  agent_id          = aws_bedrockagent_agent.dispatch_agent.agent_id
  agent_version     = "DRAFT"

  action_group_executor {
    lambda = aws_lambda_function.dispatch_tools.arn
  }

  function_schema {
    member_functions {
      functions {
        name        = "reroute_shipment"
        description = "Change a shipment's route and delivery window"
      }
      functions {
        name        = "notify_customer"
        description = "Email the customer about a change to their shipment"
      }
      functions {
        name        = "notify_driver"
        description = "Push an SNS alert to the assigned driver"
      }
    }
  }
}

resource "aws_bedrockagent_agent_action_group" "dispatch_code" {
  action_group_name             = "dispatch-code-interpreter"
  agent_id                      = aws_bedrockagent_agent.dispatch_agent.agent_id
  agent_version                 = "DRAFT"
  parent_action_group_signature = "AMAZON.CodeInterpreter"
}
