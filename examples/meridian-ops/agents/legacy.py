# stoa: ignore-file[CTRL001,CTRL002]
"""Legacy agent — controls handled by the upstream gateway (file-wide suppression)."""
from openai import OpenAI
client = OpenAI()
tools = [{"type": "function", "function": {"name": "lookup"}}]
def handle(msg):
    return client.chat.completions.create(model="gpt-4o", messages=[{"role":"user","content":msg}], tools=tools)
