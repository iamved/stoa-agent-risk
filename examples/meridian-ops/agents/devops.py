"""DevOps agent — infra operations."""
import os, subprocess, boto3
from agno.agent import Agent
from agno.models.openai import OpenAIChat

DB_PASSWORD = "Sup3rS3cretPr0d!2026"                               # SEC002
agent = Agent(model=OpenAIChat(id="gpt-4o", base_url="http://mlgw.internal-x.io/v1"),  # AI005 insecure-endpoint ⊃ NET001
              tools=[], markdown=True)

def deploy(service):
    subprocess.run(["kubectl", "rollout", "restart", service])     # shell_execution
    boto3.client("ecs").update_service(service=service)            # cloud_resource_access  # HEAD-ONLY
