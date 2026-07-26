"""The intake MCP server -- the actual tool surface every conversation and
escalation agent calls into. A genuine agentic surface in its own right: it
decides what actions get taken, not just what gets said.
"""
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("threshold-intake")
STORE = Path("./call_records")


@mcp.tool()
def save_response(question_id: str, answer: str) -> str:
    STORE.mkdir(exist_ok=True)
    (STORE / f"{question_id}.json").write_text(json.dumps({"answer": answer}))
    return "saved"


@mcp.tool()
def flag_for_review(call_id: str, reason: str) -> str:
    STORE.mkdir(exist_ok=True)
    (STORE / f"flag-{call_id}.json").write_text(json.dumps({"reason": reason}))
    return "flagged"


@mcp.tool()
def schedule_followup(call_id: str, when: str) -> str:
    STORE.mkdir(exist_ok=True)
    (STORE / f"followup-{call_id}.json").write_text(json.dumps({"when": when}))
    return "scheduled"


if __name__ == "__main__":
    mcp.run()
