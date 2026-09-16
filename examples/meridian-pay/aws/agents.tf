resource "aws_bedrockagent_agent" "front" {
  agent_name              = "meridian-front"
  agent_resource_role_arn = aws_iam_role.front.arn
  foundation_model        = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  instruction             = "Verify identity before any account action; route to specialists."
  guardrail_configuration {
    guardrail_identifier = aws_bedrock_guardrail.customer.guardrail_id
    guardrail_version    = "1"
  }
}
resource "aws_bedrockagent_agent" "account_actions" {
  agent_name              = "meridian-account-actions"
  agent_resource_role_arn = aws_iam_role.actions.arn
  foundation_model        = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  instruction             = "Refunds up to $500, waivers up to $150. Escalate above."
  # no guardrail — planted
}
resource "aws_bedrockagent_agent" "knowledge" {
  agent_name              = "meridian-knowledge"
  agent_resource_role_arn = aws_iam_role.knowledge.arn
  foundation_model        = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  instruction             = "Answer from the knowledge base."
}
resource "aws_bedrockagent_agent" "escalation" {
  agent_name              = "meridian-escalation"
  agent_resource_role_arn = aws_iam_role.escalation.arn
  foundation_model        = "anthropic.claude-3-haiku-20240307-v1:0"
  instruction             = "Draft case notes."
}
resource "aws_bedrockagent_agent_action_group" "account_tools" {
  action_group_name = "account-tools"
  agent_id          = aws_bedrockagent_agent.account_actions.agent_id
  agent_version     = "DRAFT"
  action_group_executor { lambda = aws_lambda_function.account_tools.arn }
  function_schema {
    member_functions {
      functions { name = "issue_refund" }
      functions { name = "waive_fee" }
      functions { name = "update_contact_info" }
      functions { name = "reissue_card" }
      functions { name = "place_travel_notice" }
      functions { name = "change_payout_account" }
    }
  }
}
resource "aws_bedrockagent_agent_knowledge_base_association" "kb" {
  agent_id          = aws_bedrockagent_agent.knowledge.agent_id
  knowledge_base_id = aws_bedrockagent_knowledge_base.tickets.id
  knowledge_base_state = "ENABLED"
}
resource "aws_bedrockagent_knowledge_base" "tickets" {
  name     = "meridian-tickets-and-policies"
  role_arn = aws_iam_role.kb.arn
}
resource "aws_bedrock_guardrail" "customer" {
  name = "meridian-customer"
  blocked_input_messaging = "no"
  blocked_outputs_messaging = "no"
  content_policy_config { filters_config { input_strength = "HIGH" output_strength = "HIGH" type = "PROMPT_ATTACK" } }
  sensitive_information_policy_config { pii_entities_config { action = "ANONYMIZE" type = "US_BANK_ACCOUNT_NUMBER" } }
}
resource "aws_sfn_state_machine" "reissue_approval" {
  name       = "meridian-reissue-approval"
  role_arn   = aws_iam_role.sfn.arn
  definition = jsonencode({ StartAt = "WaitForHuman", States = { WaitForHuman = { Type = "Task", Resource = "arn:aws:states:::lambda:invoke.waitForTaskToken", End = true } } })
}
