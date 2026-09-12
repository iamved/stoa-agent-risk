# Data the agents reach: the claims and shipments tables, and the RAG
# knowledge base over the policy handbook.

resource "aws_dynamodb_table" "claims" {
  name         = "kestrel-claims"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "claim_id"
  attribute {
    name = "claim_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "shipments" {
  name         = "kestrel-shipments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "shipment_id"
  attribute {
    name = "shipment_id"
    type = "S"
  }
}

resource "aws_bedrockagent_knowledge_base" "policy_docs" {
  name     = "kestrel-policy-docs"
  role_arn = aws_iam_role.kb.arn
  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    }
  }
  storage_configuration {
    type = "OPENSEARCH_SERVERLESS"
    opensearch_serverless_configuration {
      collection_arn    = aws_opensearchserverless_collection.policy_docs.arn
      vector_index_name = "policy-docs"
      field_mapping {
        vector_field   = "embedding"
        text_field     = "text"
        metadata_field = "metadata"
      }
    }
  }
}

resource "aws_bedrockagent_data_source" "policy_handbook" {
  knowledge_base_id = aws_bedrockagent_knowledge_base.policy_docs.id
  name              = "policy-handbook"
  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn = aws_s3_bucket.policy_docs.arn
    }
  }
}

resource "aws_s3_bucket" "policy_docs" {
  bucket = "kestrel-policy-docs"
}

resource "aws_opensearchserverless_collection" "policy_docs" {
  name = "kestrel-policy-docs"
  type = "VECTORSEARCH"
}

resource "aws_iam_role" "kb" {
  name               = "kestrel-knowledge-base"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json
}
