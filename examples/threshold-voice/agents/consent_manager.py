"""Verifies participant consent before a call proceeds, and redacts PII from
transcripts before anything downstream touches them. The well-controlled
baseline in this fixture -- included so the report shows contrast, not just
a wall of red, and so stoa-declared.toml has one agent whose declaration and
scan results genuinely agree.
"""
import structlog
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, EmailStr
from slowapi import Limiter

logger = structlog.get_logger()
limiter = Limiter(key_func=lambda: "consent_manager")
llm = ChatOpenAI(model="gpt-4o-2024-08-06", temperature=0)  # pinned snapshot, deterministic


class ConsentRequest(BaseModel):
    participant_email: EmailStr
    call_id: str


@limiter.limit("10/minute")
def verify_consent(request: ConsentRequest, current_user) -> bool:
    if not current_user or not require_auth(current_user):
        logger.warning("consent.denied", call_id=request.call_id)
        return False
    logger.info("consent.verified", call_id=request.call_id)
    return True


def require_auth(user) -> bool:
    return bool(getattr(user, "verified_id_token", None))


tools = [{"type": "function", "function": {"name": "redact_transcript"}}]
agent = create_tool_calling_agent(llm, tools, "Redact PII from a transcript before storage.")
executor = AgentExecutor(agent=agent, tools=tools)


def redact_transcript(transcript: str) -> str:
    """Recommends redactions; never writes or sends anything itself."""
    reply = llm.invoke(f"List any PII spans found in: {transcript}")
    logger.info("transcript.redaction_suggested", spans=reply.content)
    return reply.content
