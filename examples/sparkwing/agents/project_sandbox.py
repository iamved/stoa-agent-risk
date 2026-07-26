"""Auto-grading harness for student coding projects: asks the model for a
quick shell check that validates a submission, then runs whatever it says.
Deliberately left out of stoa-declared.toml entirely -- see DECL006 in
RISK_MAP.md.

Planted: AI002/exec -- the model's suggested command reaches a shell with no
sandbox construct anywhere in this file. This is the one finding in the
fixture that is gate-eligible on its own (high-confidence exec class).
"""
import subprocess
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o")
tools = [{"type": "function", "function": {"name": "grade_submission"}}]
agent = create_tool_calling_agent(llm, tools, "Suggest and run a check for a student's submission.")
executor = AgentExecutor(agent=agent, tools=tools)


def grade_submission(submission_path: str) -> str:
    resp = llm.invoke(f"Give one shell command that sanity-checks {submission_path}")
    subprocess.run(resp.choices[0].message.content, shell=True)  # AI002 exec -> critical, gate-eligible
    return "graded"
