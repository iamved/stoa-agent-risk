# The knowledge agent runs on Amazon Bedrock. The front agent in
# code/agents/front_agent.py calls it for policy and ticket questions.
resource "aws_bedrockagent_agent" "knowledge" {
  agent_name              = "meridian-knowledge"
  agent_resource_role_arn = aws_iam_role.knowledge.arn
  foundation_model        = "anthropic.claude-3-5-sonnet-20241022-v2:0"
  instruction             = "Answer from the knowledge base."
}
resource "aws_bedrockagent_agent_knowledge_base_association" "kb" {
  agent_id          = aws_bedrockagent_agent.knowledge.agent_id
  knowledge_base_id = aws_bedrockagent_knowledge_base.tickets.id
  knowledge_base_state = "ENABLED"
}
# Planted: one knowledge base holds every customer's tickets, with no tenant filter.
resource "aws_bedrockagent_knowledge_base" "tickets" {
  name     = "meridian-tickets-and-policies"
  role_arn = aws_iam_role.kb.arn
}
