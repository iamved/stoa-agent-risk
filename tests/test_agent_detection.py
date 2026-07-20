"""Agent-candidate detection: weighted evidence, names, false positives."""

from __future__ import annotations

from stoa.agent_detection import detect_agents

LANGCHAIN_AGENT = """
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o")
tools = [my_tool]
refund_agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=refund_agent, tools=tools)
result = executor.invoke({"input": "refund order 123"})
"""

LANGGRAPH_AGENT = """
from langgraph.prebuilt import create_react_agent
from langchain_anthropic import ChatAnthropic

graph_agent = create_react_agent(ChatAnthropic(model="claude-sonnet-4-5"), tools=[search])
graph_agent.invoke({"messages": [("user", "hi")]})
"""

CREWAI_AGENT = """
from crewai import Agent, Crew, Task

researcher = Agent(role="Researcher", goal="Find facts", backstory="Curious")
crew = Crew(agents=[researcher], tasks=[Task(description="research")])
crew.kickoff()
"""

AUTOGEN_AGENT = """
from autogen_agentchat.agents import AssistantAgent

assistant = AssistantAgent(name="helper", model_client=client)
tools = [get_weather]
"""

OPENAI_SDK_AGENT = """
from agents import Agent, Runner

triage_agent = Agent(name="Triage", instructions="Route requests")
result = Runner.run_sync(triage_agent, "Hello")
"""

PYDANTIC_AI_AGENT = """
from pydantic_ai import Agent

support_agent = Agent("openai:gpt-4o", system_prompt="Help users")
result = support_agent.run_sync("What is my balance?")
"""

LITELLM_WITH_TOOLS = """
import litellm

tools = [{"type": "function", "function": {"name": "lookup"}}]
response = litellm.completion(model="anthropic/claude-sonnet-4-5", tools=tools)
"""

RAW_REST_CALL = """
import requests

tools = [{"type": "function", "function": {"name": "search"}}]
response = requests.post(
    "https://api.openai.com/v1/chat/completions",
    headers=headers,
    json={"model": "gpt-4o", "tools": tools},
    timeout=30,
)
"""

TYPESCRIPT_ALIAS = """
import { OpenAI as LlmClient } from "openai";

const client = new LlmClient();
const tools = [{ type: "function", function: { name: "createTicket" } }];
const reply = await client.chat.completions.create({ model: "gpt-4o", tools });
"""

EMBEDDINGS_ONLY = """
from openai import OpenAI

client = OpenAI()
response = client.embeddings.create(model="text-embedding-3-small", input=["hello"])
"""

MODERATION_ONLY = """
from openai import OpenAI

client = OpenAI()
result = client.moderations.create(input="some text")
"""

USER_AGENT_PARSER = """
class UserAgentParser:
    def parse(self, user_agent: str) -> dict:
        return {"raw": user_agent}
"""

SHARED_WRAPPER = """
from openai import OpenAI

client = OpenAI()

def complete(prompt: str) -> str:
    response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}])
    return response.choices[0].message.content
"""


def _single(content: str, path: str = "src/app.py", testlike: bool = False):
    detections = detect_agents(content, path, testlike)
    assert detections, "expected at least one agent candidate"
    return detections[0]


def test_langchain_agent_detected_high_confidence():
    detections = detect_agents(LANGCHAIN_AGENT, "src/refund.py", False)
    assert detections
    assert all(d.confidence == "high" for d in detections)
    assert "langchain" in detections[0].frameworks
    assert any(e.rule_id == "AGENT_LANGCHAIN" for e in detections[0].evidence)


def test_langchain_multiple_constructors_yield_multiple_candidates():
    symbols = {d.symbol for d in detect_agents(LANGCHAIN_AGENT, "src/refund.py", False)}
    assert "refund_agent" in symbols
    assert "executor" in symbols


def test_langgraph_agent_detected():
    detection = _single(LANGGRAPH_AGENT)
    assert "langgraph" in detection.frameworks
    assert detection.symbol == "graph_agent"


def test_crewai_agent_detected():
    detection = _single(CREWAI_AGENT)
    assert "crewai" in detection.frameworks
    assert detection.confidence in ("medium", "high")


def test_autogen_agent_detected():
    detection = _single(AUTOGEN_AGENT)
    assert "autogen" in detection.frameworks
    assert detection.symbol == "assistant"


def test_openai_agents_sdk_detected():
    detection = _single(OPENAI_SDK_AGENT)
    assert "openai_agents_sdk" in detection.frameworks
    assert detection.confidence == "high"


def test_pydantic_ai_agent_detected():
    detection = _single(PYDANTIC_AI_AGENT)
    assert "pydantic_ai" in detection.frameworks
    assert detection.symbol == "support_agent"


def test_litellm_with_tools_is_candidate_not_high():
    detection = _single(LITELLM_WITH_TOOLS)
    assert detection.confidence in ("low", "medium")


def test_raw_rest_call_with_tools_is_candidate():
    detection = _single(RAW_REST_CALL, "src/bot.py")
    assert detection.confidence in ("low", "medium")


def test_typescript_import_alias_detected():
    detection = _single(TYPESCRIPT_ALIAS, "src/support.ts")
    assert detection.confidence in ("low", "medium")


def test_embeddings_only_not_an_agent():
    assert detect_agents(EMBEDDINGS_ONLY, "src/embed.py", False) == []


def test_moderation_only_not_an_agent():
    assert detect_agents(MODERATION_ONLY, "src/moderate.py", False) == []


def test_user_agent_parser_not_an_agent():
    assert detect_agents(USER_AGENT_PARSER, "src/ua.py", False) == []


def test_shared_wrapper_not_high_confidence():
    detections = detect_agents(SHARED_WRAPPER, "src/llm.py", False)
    assert all(d.confidence in ("low", "medium") for d in detections)


def test_test_fixture_downweighted():
    normal = detect_agents(LANGCHAIN_AGENT, "src/refund.py", False)[0]
    fixture = detect_agents(LANGCHAIN_AGENT, "tests/fixtures/refund.py", True)[0]
    assert fixture.detection_score == normal.detection_score - 3
    assert any(e.rule_id == "AGENT_TESTLIKE_PATH" for e in fixture.evidence)


def test_class_name_extraction():
    content = """
from openai import OpenAI

class RefundAgent:
    def run(self):
        tools = [x]
        return OpenAI().chat.completions.create(model="gpt-4o", tools=tools)
"""
    detection = _single(content)
    assert detection.symbol == "RefundAgent"


def test_factory_function_extraction():
    content = """
from openai import OpenAI

def build_refund_agent():
    tools = [x]
    return OpenAI().chat.completions.create(model="gpt-4o", tools=tools)
"""
    detection = _single(content)
    assert detection.symbol == "build_refund_agent"


def test_stable_agent_ids():
    first = detect_agents(LANGCHAIN_AGENT, "src/refund.py", False)
    second = detect_agents(LANGCHAIN_AGENT, "src/refund.py", False)
    assert [d.id for d in first] == [d.id for d in second]


# --- Vercel AI SDK and modern frameworks (stress-test regressions) ---------

AISDK_SINGLE_SHOT = """
import { generateText } from 'ai';
import { createGroq } from '@ai-sdk/groq';
const groq = createGroq({ apiKey: process.env.GROQ_API_KEY });
export async function plan(prompt: string) {
  const result = await generateText({ model: groq('llama-3.3-70b'), prompt });
  return result.text;
}
"""

AISDK_AGENTIC = """
import { streamText, tool } from 'ai';
import { anthropic } from '@ai-sdk/anthropic';
export const agent = streamText({
  model: anthropic('claude-sonnet-4-5'),
  maxSteps: 10,
  tools: { lookup: tool({ description: 'x' }) },
});
"""

MASTRA_AGENT = """
import { Agent } from '@mastra/core/agent';
import { openai } from '@ai-sdk/openai';
export const weather = new Agent({ name: 'weather', model: openai('gpt-4o'), tools: {} });
"""

SMOLAGENTS = """
from smolagents import CodeAgent, HfApiModel
agent = CodeAgent(tools=[], model=HfApiModel())
agent.run("do it")
"""

DSPY_AGENT = """
import dspy
lm = dspy.LM("openai/gpt-4o")
react = dspy.ReAct("q -> a", tools=[search])
"""

AGNO_AGENT = """
from agno.agent import Agent
from agno.models.openai import OpenAIChat
support = Agent(model=OpenAIChat(id="gpt-4o"), tools=[])
"""

ADK_AGENT = """
from google.adk.agents import Agent
root_agent = Agent(name="assistant", model="gemini-2.0-flash", tools=[search])
"""

STRANDS_AGENT = """
from strands import Agent
from strands_tools import calculator
agent = Agent(tools=[calculator])
"""

LANGCHAIN_JS = """
import { ChatOpenAI } from '@langchain/openai';
import { createReactAgent } from '@langchain/langgraph/prebuilt';
const model = new ChatOpenAI({ model: 'gpt-4o' });
export const agent = createReactAgent({ llm: model, tools: [] });
"""


def test_aisdk_single_shot_is_low_candidate_with_provider():
    detections = detect_agents(AISDK_SINGLE_SHOT, "app/api/plan/route.ts", False)
    assert detections, "single-shot generateText should still surface as a candidate"
    assert detections[0].confidence == "low"


def test_aisdk_agentic_is_high_confidence():
    detection = _single(AISDK_AGENTIC, "src/agent.ts")
    assert detection.confidence == "high"
    assert "vercel_ai_sdk" in detection.frameworks


def test_mastra_agent_high():
    detection = _single(MASTRA_AGENT, "src/weather.ts")
    assert "mastra" in detection.frameworks
    assert detection.confidence == "high"


def test_smolagents_high():
    detection = _single(SMOLAGENTS, "src/agent.py")
    assert "smolagents" in detection.frameworks
    assert detection.confidence == "high"


def test_dspy_agent_detected():
    detection = _single(DSPY_AGENT, "src/agent.py")
    assert "dspy" in detection.frameworks


def test_agno_agent_high():
    detection = _single(AGNO_AGENT, "src/support.py")
    assert "agno" in detection.frameworks
    assert detection.confidence == "high"


def test_google_adk_agent_high():
    detection = _single(ADK_AGENT, "src/agent.py")
    assert "google_adk" in detection.frameworks


def test_strands_agent_detected():
    detection = _single(STRANDS_AGENT, "src/agent.py")
    assert "strands" in detection.frameworks


def test_langchain_js_react_agent_high():
    detection = _single(LANGCHAIN_JS, "src/agent.ts")
    assert "langgraph" in detection.frameworks
    assert detection.confidence == "high"
