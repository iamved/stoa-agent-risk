# IAM is where a Bedrock agent's *reach* is written down. Two roles per agent:
# the agent's own role (invoke the model, call its Lambdas) and each tool
# Lambda's role (what the tool may touch). The second is where the risk lives.

data "aws_iam_policy_document" "bedrock_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# --- claims_assistant ---------------------------------------------------------

resource "aws_iam_role" "claims_agent" {
  name               = "kestrel-claims-agent"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json
}

resource "aws_iam_role_policy" "claims_agent" {
  name = "claims-agent-runtime"
  role = aws_iam_role.claims_agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"
      },
      {
        Effect   = "Allow"
        Action   = ["bedrock:Retrieve"]
        Resource = aws_bedrockagent_knowledge_base.policy_docs.arn
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = aws_lambda_function.claims_lookup.arn
      },
    ]
  })
}

resource "aws_iam_role" "claims_lookup_lambda" {
  name               = "kestrel-claims-lookup"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Narrow: two read actions on one table.
resource "aws_iam_role_policy" "claims_lookup_lambda" {
  name = "claims-lookup-read"
  role = aws_iam_role.claims_lookup_lambda.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.claims.arn
    }]
  })
}

# --- dispatch_agent -----------------------------------------------------------

resource "aws_iam_role" "dispatch_agent" {
  name               = "kestrel-dispatch-agent"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json
}

resource "aws_iam_role_policy" "dispatch_agent" {
  name = "dispatch-agent-runtime"
  role = aws_iam_role.dispatch_agent.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = aws_lambda_function.dispatch_tools.arn
      },
    ]
  })
}

resource "aws_iam_role" "dispatch_tools_lambda" {
  name               = "kestrel-dispatch-tools"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# Planted: a heredoc JSON policy with dynamodb:* on every table, email send on
# any identity, and SNS publish. This is the reach the dispatch agent's tools
# actually have when the model decides to "re-route" or "notify".
resource "aws_iam_role_policy" "dispatch_tools_lambda" {
  name   = "dispatch-tools-runtime"
  role   = aws_iam_role.dispatch_tools_lambda.name
  policy = <<EOP
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["dynamodb:*"], "Resource": "*" },
    { "Effect": "Allow", "Action": ["ses:SendEmail", "ses:SendRawEmail"], "Resource": "*" },
    { "Effect": "Allow", "Action": ["sns:Publish"], "Resource": "arn:aws:sns:us-east-1:123456789012:kestrel-driver-alerts" }
  ]
}
EOP
}

# Planted: a managed full-access policy on top of the inline one.
resource "aws_iam_role_policy_attachment" "dispatch_tools_s3" {
  role       = aws_iam_role.dispatch_tools_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}
