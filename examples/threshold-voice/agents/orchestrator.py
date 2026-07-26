"""Call orchestrator — owns the live voice session. Deliberately hand-rolled:
no agent framework, just the raw model call in a turn loop that is the
framework-independent signature of an agentic system (SCORE_AGENTIC_LOOP).

Planted: AI001 — the voice transcript is untrusted input (a caller can say
anything) and flows straight into the prompt with no delimiting.
"""
import os
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

SYSTEM = "You are conducting a structured screening interview. Stay on topic."


@app.route("/webhook/transcript", methods=["POST"])
def handle_transcript():
    """Twilio-style webhook: POSTs the live transcription of what the caller
    just said. This is the call's actual untrusted-input boundary."""
    turn = request.get_json()
    transcript = turn["text"]  # caller-controlled — AI001 source

    prompt = f"{SYSTEM}\nParticipant said: {transcript}\nRespond naturally."
    reply = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],  # AI001 sink
    )
    return {"say": reply.choices[0].message.content}


def run_session(call_id: str, max_turns: int = 12):
    """The actual turn loop — repeatedly calls the model as the conversation
    continues. This is the agentic-control-flow signal: a model call inside
    a loop, no framework required."""
    history = []
    for _ in range(max_turns):
        turn = _next_turn(call_id)
        if turn is None:
            break
        history.append(turn)
        client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": turn["text"]}],
        )
    return history


def _next_turn(call_id: str):
    """Placeholder for the telephony provider's next-utterance callback."""
    return None
