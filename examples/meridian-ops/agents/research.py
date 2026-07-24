"""Research agent — web + local models."""
import os, requests
from agents import Agent, Runner
from transformers import AutoModel, pipeline
from tavily import TavilyClient

reranker = AutoModel.from_pretrained("someorg/reranker", trust_remote_code=True)  # AI005 trust-remote-code
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
embedder = AutoModel.from_pretrained("sentence-transformers/all-MiniLM")           # AI005 unpinned-artifact
tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])                        # web_search

research_agent = Agent(name="Researcher", instructions="Answer questions")

def research(q):
    result = Runner.run_sync(research_agent, q)
    return result.final_output
