"""Compliance agent — well-controlled by design (the contrast case)."""
import os
import structlog
from pydantic import BaseModel
from langgraph.prebuilt import create_react_agent
from langgraph.types import interrupt
from langchain_anthropic import ChatAnthropic

logger = structlog.get_logger()                                   # observability control
llm = ChatAnthropic(model="claude-3-5-sonnet-20241022", temperature=0)  # dated snapshot + deterministic sampling

class Filing(BaseModel):                                          # input validation control
    entity_id: str
    amount: float

compliance_agent = create_react_agent(llm, tools=[file_report])

def file_report(filing: Filing, user):
    if not authenticate(user):                                    # authentication control
        raise PermissionError("unauthorized")
    decision = interrupt({"action": "file", "entity": filing.entity_id})  # approval control
    if not decision.get("approved"):
        return "declined"
    logger.info("compliance.file", entity=filing.entity_id, amount=filing.amount)
    return "filed"
