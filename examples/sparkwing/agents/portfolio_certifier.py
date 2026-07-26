"""Decides whether a finished project submission earns a portfolio badge, and
writes that outcome straight into the student's record. This is the agent
stoa-declared.toml claims requires a second set of eyes before anything is
written -- the code below does not back that up.

Planted: AI002/sql (the model's verdict text is interpolated straight into an
UPDATE, superseding the plain-SQL SEC003 signal), AI003 (a high-impact
capability -- database_write of the final outcome -- with no gating construct
anywhere in this file), and (paired with the declaration) DECL001.
"""
import psycopg2
from openai import OpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI

client = OpenAI()
conn = psycopg2.connect(dsn="postgresql://localhost/sparkwing")

llm = ChatOpenAI(model="gpt-4o")
tools = [{"type": "function", "function": {"name": "certify_submission"}}]
agent = create_tool_calling_agent(llm, tools, "Decide whether a submission earns a portfolio badge.")
executor = AgentExecutor(agent=agent, tools=tools)


def certify_submission(student_id: str, submission_text: str) -> str:
    verdict = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Badge-worthy or not? Submission: {submission_text}"}],
    ).choices[0].message.content

    cursor = conn.cursor()
    cursor.execute(f"UPDATE portfolios SET badge_outcome = '{verdict}' WHERE student_id = '{student_id}'")  # AI002/sql
    conn.commit()
    return verdict
