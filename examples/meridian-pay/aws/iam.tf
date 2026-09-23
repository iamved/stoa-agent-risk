resource "aws_iam_role" "knowledge" { name = "meridian-knowledge" }
resource "aws_iam_role" "kb" { name = "meridian-kb" }

# Planted: the knowledge base role can read every table and bucket.
data "aws_iam_policy_document" "kb" {
  statement {
    actions   = ["s3:GetObject", "s3:ListBucket", "dynamodb:Scan", "dynamodb:Query"]
    resources = ["*"]
  }
}
resource "aws_iam_role_policy" "kb" {
  role   = aws_iam_role.kb.id
  policy = data.aws_iam_policy_document.kb.json
}
resource "aws_iam_role_policy" "knowledge" {
  role   = aws_iam_role.knowledge.id
  policy = jsonencode({ Statement = [{ Effect = "Allow", Action = ["bedrock:InvokeModel", "bedrock:Retrieve"], Resource = "*" }] })
}
