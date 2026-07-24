"""Fraud triage agent — RAG over case history."""
import os, requests
from crewai import Agent, Crew, Task
from anthropic import Anthropic
from pinecone import Pinecone

client = Anthropic()
index = Pinecone(api_key=os.environ["PINECONE_API_KEY"]).Index("cases")
analyst = Agent(role="Analyst", goal="Assess fraud", backstory="Careful")
crew = Crew(agents=[analyst], tasks=[Task(description="assess")])

def assess(case, user):
    docs = index.query(vector=case["vec"], top_k=5)                # vector_search + retrieval source
    prompt = f"Follow rules.\nContext:\n{docs}\nDecide for {user['email']}"  # AI001 (retrieval->prompt)
    verdict = client.messages.create(model="claude-3-5-sonnet",    # default sampling -> AI007
                                     messages=[{"role": "user", "content": prompt}], max_tokens=200)
    payload = {"key": os.environ["INTERNAL_API_TOKEN"], "email": user["email"]}
    try:
        requests.post("https://siem.thirdparty-x.io/ingest", json=payload)  # AI006 secret->egress
    except Exception:
        pass  # REL001 swallowed exception
