# Not part of the Meridian Pay example. The fixture builder and the tests add
# this file to a copy of the example to get an agent defined twice: the
# account-actions agent in code, and the same agent as a Bedrock agent with
# the same tools. That is the shape identity resolution and drift are tested
# on (ui/fixtures/two-stacks.envelope.json).
resource "aws_bedrockagent_agent" "account_actions" {
  agent_name              = "meridian-account-actions"
  agent_resource_role_arn = aws_iam_role.actions.arn
  foundation_model        = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  instruction             = "Refunds up to $500, waivers up to $150. Escalate above."
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
resource "aws_iam_role" "actions" { name = "meridian-actions" }
resource "aws_iam_role" "account_tools_lambda" { name = "meridian-account-tools" }
resource "aws_lambda_function" "account_tools" {
  function_name = "meridian-account-tools"
  role          = aws_iam_role.account_tools_lambda.arn
  handler       = "handler.main"
  runtime       = "python3.12"
}
data "aws_iam_policy_document" "account_tools" {
  statement {
    actions   = ["dynamodb:*"]
    resources = ["*"]
  }
  statement {
    actions   = ["ses:SendEmail", "secretsmanager:GetSecretValue"]
    resources = ["*"]
  }
}
resource "aws_iam_role_policy" "account_tools" {
  role   = aws_iam_role.account_tools_lambda.id
  policy = data.aws_iam_policy_document.account_tools.json
}
resource "aws_iam_role_policy" "actions" {
  role   = aws_iam_role.actions.id
  policy = jsonencode({ Statement = [{ Effect = "Allow", Action = ["bedrock:InvokeModel", "lambda:InvokeFunction"], Resource = "*" }] })
}
