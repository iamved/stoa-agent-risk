"""Turns a finished conversation into a structured record. Deliberately
hand-rolled batch job — no framework, processes a backlog of completed calls.

Planted: AI002/sql (model summary interpolated straight into an INSERT,
superseding the plain-SQL SEC003 signal) and CTRL005 (the batch loop touches
a high-impact capability — database_write — with nothing pacing it).
"""
import psycopg2
from openai import OpenAI

client = OpenAI()
conn = psycopg2.connect(dsn="postgresql://localhost/threshold")


def process_backlog(pending_call_ids: list[str]):
    """Runs over every completed-but-unprocessed call, unpaced -- on a large
    backlog this hammers both the model API and the database with nothing
    slowing it down. The model call and the write both live directly in the
    loop body (CTRL005's proximity signal is scoped to the loop's own text,
    not the whole file)."""
    for call_id in pending_call_ids:
        transcript = _load_transcript(call_id)
        summary = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": f"Summarize this interview as one line: {transcript}"}],
        ).choices[0].message.content

        cursor = conn.cursor()
        cursor.execute(f"INSERT INTO responses (summary) VALUES ('{summary}')")  # AI002/sql
        conn.commit()


def _load_transcript(call_id: str) -> str:
    cursor = conn.cursor()
    cursor.execute("SELECT transcript FROM calls WHERE id = %s", (call_id,))
    return cursor.fetchone()[0]
