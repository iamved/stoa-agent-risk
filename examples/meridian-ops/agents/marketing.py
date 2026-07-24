"""Marketing agent — drafts and sends campaigns. NEW in head (diff scenario)."""
import os, sendgrid
from autogen_agentchat.agents import AssistantAgent

mailer = sendgrid.SendGridAPIClient(os.environ["SENDGRID_API_KEY"])   # email_send integration
campaigner = AssistantAgent(name="campaigner", model_client=None)
def send(segment, body):
    mailer.send({"to": segment, "html": body})                       # email_send capability
