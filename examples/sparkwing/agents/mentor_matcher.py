"""Suggests a mentor pairing for a student, from their project sector and
availability. The well-controlled baseline in this fixture — included so the
report shows contrast, not just a wall of red, and so stoa-declared.toml has
one agent whose declaration and scan results genuinely agree. Recommend-only:
it never books or notifies anyone, a human staff member does that from its
suggestion.
"""
import structlog
from pydantic import BaseModel
from langgraph.prebuilt import create_react_agent
from langchain_anthropic import ChatAnthropic

logger = structlog.get_logger()
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)  # dated snapshot + deterministic


class MatchRequest(BaseModel):
    student_id: str
    sector: str
    grade_band: str


def suggest_mentor(request: MatchRequest, current_user) -> str:
    if not current_user:
        logger.warning("match.denied", student_id=request.student_id)
        return ""
    agent = create_react_agent(llm, tools=[])
    reply = agent.invoke({"messages": [("user", f"Suggest a mentor for sector {request.sector}")]})
    logger.info("match.suggested", student_id=request.student_id, sector=request.sector)
    return reply["messages"][-1].content
