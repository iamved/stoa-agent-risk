"""The project-sector chat — framework-free, talks to a student directly
through the session widget and decides which of the 25 frontier sectors to
recommend next.

Planted: AI001 (the student's own chat message is untrusted input and flows
straight into the prompt with no delimiting), AI005 floating-alias (unpinned
model string), and AI007 (no sampling bound anywhere near a model call that
sits next to a database write, this file's high-impact capability).
"""
import psycopg2
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)
client = OpenAI()
conn = psycopg2.connect(dsn="postgresql://localhost/sparkwing")

SYSTEM = "You are a friendly project advisor for a K-12 learner. Stay encouraging."


@app.route("/widget/message", methods=["POST"])
def handle_message():
    """The chat widget POSTs each message the student types."""
    turn = request.get_json()
    student_said = turn["text"]  # student-controlled — AI001 source

    prompt = f"{SYSTEM}\nStudent said: {student_said}\nRespond with one suggestion."
    reply = client.chat.completions.create(
        model="gpt-4o",  # AI005 floating-alias — resolves differently over time
        messages=[{"role": "user", "content": prompt}],  # AI001 sink
    )
    return {"say": reply.choices[0].message.content}


def record_chosen_sector(student_id: str, sector: str) -> None:
    """Persists the sector the student settled on, once staff confirm it."""
    cursor = conn.cursor()
    cursor.execute("UPDATE students SET current_sector = %s WHERE id = %s", (sector, student_id))
    conn.commit()


def run_session(student_id: str, max_turns: int = 8):
    """The actual turn loop for a live advising session — repeatedly calls
    the model as the conversation continues. No framework required."""
    history = []
    for _ in range(max_turns):
        turn = _next_turn(student_id)
        if turn is None:
            break
        history.append(turn)
        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": turn["text"]}],
        )
    return history


def _next_turn(student_id: str):
    """Placeholder for the widget's next-message callback."""
    return None
