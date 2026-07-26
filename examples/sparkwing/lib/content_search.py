"""Semantic search over project write-ups for the sector advisor's context —
intentionally NOT an agent: embeddings-only, no tool binding, no loop."""
import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])


def embed(texts):
    return client.embeddings.create(model="text-embedding-3-small", input=texts)
