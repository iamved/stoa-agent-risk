"""Drafts a parent's weekly progress update and sends it, and syncs session
metrics to a growth-marketing vendor so the team can track engagement.

Planted: AI006 -- the marketing sync includes the student's email address,
sent to a third-party host that isn't the recognized notification provider,
isn't localhost, and isn't in [rules.AI006].allowed_hosts. Also REL001 -- the
parent-notify path swallows any send failure, so a missed update is silent.
"""
import requests
import sendgrid
from sendgrid.helpers.mail import Mail
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI

sg = sendgrid.SendGridAPIClient()

llm = ChatOpenAI(model="gpt-4o")
tools = [{"type": "function", "function": {"name": "notify_parent"}}]
agent = create_tool_calling_agent(llm, tools, "Draft a warm weekly update for a parent.")
executor = AgentExecutor(agent=agent, tools=tools)


def notify_parent(guardian, project_notes: str) -> None:
    draft = llm.invoke(f"Write a two-sentence parent update from these notes: {project_notes}")
    message = Mail(
        from_email="progress@sparkwing.example",
        to_emails=guardian.email,
        subject="This week's project update",
        html_content=draft.content,
    )
    try:
        sg.send(message)
    except Exception:
        pass


def sync_to_growth_vendor(student, outcome: str) -> None:
    """Fire-and-forget usage sync to a third-party growth-marketing vendor."""
    student_email = student.email
    requests.post(
        "https://events.thirdparty-growth.example/track",
        json={"email": student_email, "outcome": outcome},  # AI006
    )
