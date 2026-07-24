"""Triage agent — routes intents. Low risk."""
from pydantic_ai import Agent

triage_agent = Agent("openai:gpt-4o-mini", system_prompt="Classify: billing|fraud|other")

def route(message: str) -> str:
    return triage_agent.run_sync(message).output
