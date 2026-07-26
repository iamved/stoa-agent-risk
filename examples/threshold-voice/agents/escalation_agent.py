"""Decides the outcome of a finished screening: advance or reject. This is
the agent stoa-declared.toml claims is human-in-the-loop -- the code below
does not back that up.

Planted: AI002/sql (the model's own verdict text is interpolated straight
into the UPDATE -- the outcome write path is not just unapproved, it's also
injectable), AI003 (a high-impact capability -- database_write of the final
outcome -- with no gating construct anywhere in this file), AI007 (no
sampling bound near that call), and (paired with the declaration) DECL001:
AI002's side-effecting sink is what autonomy inference keys off of.
"""
import psycopg2
from crewai import Agent, Crew
from openai import OpenAI

client = OpenAI()
conn = psycopg2.connect(dsn="postgresql://localhost/threshold")

decision_agent = Agent(
    role="Screening Decision Maker",
    goal="Advance or reject each completed interview based on the transcript",
    backstory="An experienced screener who moves fast.",
)
crew = Crew(agents=[decision_agent])


@tool
def decide_outcome(call_id: str, transcript: str) -> str:
    verdict = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": f"Advance or reject? Transcript: {transcript}"}],
    ).choices[0].message.content

    cursor = conn.cursor()
    cursor.execute(f"UPDATE candidates SET outcome = '{verdict}' WHERE call_id = '{call_id}'")  # AI002/sql
    conn.commit()
    return verdict
