resource "aws_iam_role" "front" { name = "meridian-front" }
resource "aws_iam_role" "actions" { name = "meridian-actions" }
resource "aws_iam_role" "knowledge" { name = "meridian-knowledge" }
resource "aws_iam_role" "escalation" { name = "meridian-escalation" }
resource "aws_iam_role" "kb" { name = "meridian-kb" }
resource "aws_iam_role" "sfn" { name = "meridian-sfn" }
resource "aws_iam_role" "account_tools_lambda" { name = "meridian-account-tools" }

resource "aws_lambda_function" "account_tools" {
  function_name = "meridian-account-tools"
  role          = aws_iam_role.account_tools_lambda.arn
  handler       = "handler.main"
  runtime       = "python3.12"
}

# Planted: the refund Lambda's role can read and write all of DynamoDB and send email.
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
