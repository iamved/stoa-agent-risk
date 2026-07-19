"""Research agent: answers product questions from the KB and the web.

PLANTED RISK (for the Stoa demo): a plain-HTTP legacy knowledge-base URL.
"""

import os

import requests
from agents import Agent, Runner
from tavily import TavilyClient

tavily = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

research_agent = Agent(
    name="Researcher",
    instructions="Answer product questions using the knowledge base and web search.",
)


def research(question: str) -> str:
    result = Runner.run_sync(research_agent, question)
    return result.final_output


def search_web(query: str) -> list:
    return tavily.search(query=query, max_results=5)["results"]


def search_legacy_kb(query: str) -> dict:
    response = requests.get(
        "http://legacy-kb.corp-intranet-desk.com/search",
        params={"q": query},
        timeout=15,
    )
    return response.json()
