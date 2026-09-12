# The tool executors. Each action group in agents.tf points at one of these;
# each one runs under a role defined in iam.tf. Stoa follows that chain:
# agent -> action group -> Lambda -> role -> policy.

resource "aws_lambda_function" "claims_lookup" {
  function_name = "kestrel-claims-lookup"
  role          = aws_iam_role.claims_lookup_lambda.arn
  handler       = "claims_lookup.handler"
  runtime       = "python3.12"
  filename      = "${path.module}/../functions/claims_lookup.zip"
  environment {
    variables = {
      CLAIMS_TABLE = aws_dynamodb_table.claims.name
    }
  }
}

resource "aws_lambda_function" "dispatch_tools" {
  function_name = "kestrel-dispatch-tools"
  role          = aws_iam_role.dispatch_tools_lambda.arn
  handler       = "dispatch_tools.handler"
  runtime       = "python3.12"
  filename      = "${path.module}/../functions/dispatch_tools.zip"
  environment {
    variables = {
      SHIPMENTS_TABLE = aws_dynamodb_table.shipments.name
      DRIVER_TOPIC    = "arn:aws:sns:us-east-1:123456789012:kestrel-driver-alerts"
      FROM_ADDRESS    = "dispatch@kestrel.example"
    }
  }
}

resource "aws_lambda_permission" "claims_lookup_bedrock" {
  statement_id  = "AllowBedrockInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.claims_lookup.function_name
  principal     = "bedrock.amazonaws.com"
}

resource "aws_lambda_permission" "dispatch_tools_bedrock" {
  statement_id  = "AllowBedrockInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dispatch_tools.function_name
  principal     = "bedrock.amazonaws.com"
}
