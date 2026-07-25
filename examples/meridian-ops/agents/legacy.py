# stoa: ignore-file[REL001]
"""Legacy agent — errors are swallowed on purpose here (fire-and-forget);
file-wide suppression documents that decision."""
from openai import OpenAI
client = OpenAI()
tools = [{"type": "function", "function": {"name": "lookup"}}]

def handle(msg):
    try:
        return client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": msg}], tools=tools)
    except Exception:
        pass  # REL001 (file-wide suppressed above)
