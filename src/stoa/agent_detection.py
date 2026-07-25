"""Weighted-evidence agent-candidate detection.

A file is never classified as an agent candidate on a single regex match:
each pattern contributes evidence with a weight, and the total score maps to
a confidence level. Test-like paths are downweighted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from typing import Optional

from .models import Evidence, agent_id
from .rules import (
    AGENT_CONSTRUCTOR_ASSIGNMENT,
    AGENT_FACTORY_FUNCTION,
    AGENT_LIKE_VARIABLE,
    DIRECT_MODEL_ENDPOINTS,
    GENERIC_AGENT_NAME,
    HIGH_AGENT_PATTERNS,
    MODEL_CALL_FOR_FLOW,
    PROVIDER_PATTERNS,
    SUPPORTING_PATTERNS,
)

SCORE_FRAMEWORK_CONSTRUCTOR = 5
SCORE_AGENTIC_LOOP = 4        # a model call inside a loop — hand-rolled agent
SCORE_EXECUTION = 3
SCORE_MULTI_STEP = 2         # ≥2 model call sites — orchestration
SCORE_PROVIDER_CALL = 2
SCORE_TOOLS = 2
SCORE_PROVIDER_IMPORT = 1
SCORE_AGENT_CLASS = 1
SCORE_TESTLIKE_PENALTY = -3

HIGH_THRESHOLD = 8
MEDIUM_THRESHOLD = 5
LOW_THRESHOLD = 3

# Loop node types across languages (for the AST agentic-loop signal).
_LOOP_TYPES = {"for_statement", "while_statement", "for_in_statement",
               "do_statement", "comprehension"}

FRAMEWORK_LABELS = {
    "langchain": "LangChain",
    "langgraph": "LangGraph",
    "crewai": "CrewAI",
    "autogen": "AutoGen",
    "llamaindex": "LlamaIndex",
    "openai_agents_sdk": "OpenAI Agents SDK",
    "pydantic_ai": "PydanticAI",
    "bedrock_agents": "Amazon Bedrock Agents",
    "semantic_kernel": "Semantic Kernel",
    "vercel_ai_sdk": "Vercel AI SDK",
    "mastra": "Mastra",
    "smolagents": "smolagents",
    "dspy": "DSPy",
    "agno": "Agno",
    "google_adk": "Google ADK",
    "strands": "AWS Strands",
    "mcp": "MCP server",
}


def _model_call_in_loop(parsed) -> Optional[int]:
    """Line of a recognized model call whose ancestor is a loop, if any.

    A model call inside a loop is the framework-independent signature of an
    agentic system — the thing hand-rolled agents share with framework ones.
    """
    if parsed is None or not getattr(parsed, "available", False):
        return None
    call_types = {"call", "call_expression"}
    for node in parsed.walk():
        if node.type in call_types and MODEL_CALL_FOR_FLOW.search(
            node.text.decode("utf-8", "replace")
        ):
            cur = node.parent
            while cur is not None:
                if cur.type in _LOOP_TYPES:
                    return node.start_point[0] + 1
                cur = cur.parent
    return None


@dataclass
class AgentDetection:
    """Raw detection outcome for one candidate before enrichment."""

    id: str
    name: str
    symbol: str
    confidence: str
    detection_score: int
    frameworks: list[str]
    evidence: list[Evidence]


def _line_of(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _classify(score: int) -> str | None:
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    if score >= LOW_THRESHOLD:
        return "low"
    return None


def detect_agents(
    content: str, relative_path: str, is_testlike: bool, parsed=None
) -> list[AgentDetection]:
    """Return zero or more agent candidates for one file.

    A candidate needs an *agentic* signal — a framework construct, a tool
    binding, an execution/orchestration call, a model call inside a loop, or
    multiple model call sites. An LLM SDK import plus a single provider call
    (a generation/pipeline utility) is **not** an agent and is not emitted.
    """
    evidence: list[Evidence] = []
    frameworks: list[str] = []
    score = 0
    sig_execution = sig_tools = sig_agent_class = False

    constructor_lines: list[int] = []
    for framework, pattern in HIGH_AGENT_PATTERNS.items():
        match = pattern.search(content)
        if match:
            frameworks.append(framework)
            score += SCORE_FRAMEWORK_CONSTRUCTOR
            line = _line_of(content, match.start())
            constructor_lines.append(line)
            evidence.append(
                Evidence(
                    rule_id=f"AGENT_{framework.upper()}",
                    line=line,
                    description=f"{FRAMEWORK_LABELS[framework]} agent construct",
                )
            )

    match = SUPPORTING_PATTERNS["execution"].search(content)
    if match:
        sig_execution = True
        score += SCORE_EXECUTION
        evidence.append(
            Evidence(
                rule_id="AGENT_EXECUTION",
                line=_line_of(content, match.start()),
                description="Agent execution or orchestration call",
            )
        )

    provider_call = SUPPORTING_PATTERNS["provider_call"].search(content)
    litellm_call = SUPPORTING_PATTERNS["litellm"].search(content)
    direct_endpoint = DIRECT_MODEL_ENDPOINTS.search(content)
    call = provider_call or litellm_call or direct_endpoint
    if call:
        score += SCORE_PROVIDER_CALL
        evidence.append(
            Evidence(
                rule_id="AGENT_PROVIDER_CALL",
                line=_line_of(content, call.start()),
                description="LLM provider invocation",
            )
        )

    match = SUPPORTING_PATTERNS["tools"].search(content)
    if match:
        sig_tools = True
        score += SCORE_TOOLS
        evidence.append(
            Evidence(
                rule_id="AGENT_TOOLS",
                line=_line_of(content, match.start()),
                description="Tool or function schema",
            )
        )

    import_match = None
    for pattern in PROVIDER_PATTERNS.values():
        import_match = pattern.search(content)
        if import_match:
            break
    if import_match:
        score += SCORE_PROVIDER_IMPORT
        evidence.append(
            Evidence(
                rule_id="AGENT_PROVIDER_IMPORT",
                line=_line_of(content, import_match.start()),
                description="LLM provider import or reference",
            )
        )

    class_match = None
    for candidate in SUPPORTING_PATTERNS["agent_class"].finditer(content):
        if not GENERIC_AGENT_NAME.search(candidate.group(1)):
            class_match = candidate
            break
    if class_match:
        sig_agent_class = True
        score += SCORE_AGENT_CLASS
        evidence.append(
            Evidence(
                rule_id="AGENT_CLASS_NAME",
                line=_line_of(content, class_match.start()),
                description=f"Class name suggests an agent: {class_match.group(1)}",
            )
        )

    # Framework-independent agentic control flow: a model call inside a loop,
    # and/or multiple model call sites (orchestration). These catch hand-rolled
    # agents that use direct API calls with no agent framework.
    loop_line = _model_call_in_loop(parsed)
    if loop_line:
        score += SCORE_AGENTIC_LOOP
        evidence.append(
            Evidence(
                rule_id="AGENT_LOOP",
                line=loop_line,
                description="Model call inside a loop (agentic control flow)",
            )
        )
    model_call_sites = len(MODEL_CALL_FOR_FLOW.findall(content))
    sig_multi = model_call_sites >= 2
    if sig_multi:
        score += SCORE_MULTI_STEP
        evidence.append(
            Evidence(
                rule_id="AGENT_MULTI_STEP",
                line=1,
                description=f"Multiple model call sites ({model_call_sites}) — orchestration",
            )
        )

    if is_testlike:
        score += SCORE_TESTLIKE_PENALTY
        evidence.append(
            Evidence(
                rule_id="AGENT_TESTLIKE_PATH",
                line=1,
                description="Likely test, fixture, mock, or example path (downweighted)",
            )
        )

    has_constructor = bool(frameworks)
    # An agentic signal is required — provider import + a single provider call
    # (a pipeline/generation utility) is not an agent.
    has_agentic_signal = (
        has_constructor or sig_execution or sig_tools or sig_agent_class
        or bool(loop_line) or sig_multi
    )
    if not has_agentic_signal:
        return []
    confidence = _classify(score)
    if confidence is None and not has_constructor:
        return []  # an agentic hint that is too weak on its own
    if confidence is None:
        # A high-confidence framework/MCP construct qualifies the candidate even
        # when the overall score falls slightly below the low threshold.
        confidence = "low"

    frameworks.sort()
    symbols = _extract_symbols(content, class_match)
    detections: list[AgentDetection] = []
    if len(symbols) > 1:
        for symbol, _line in symbols:
            detections.append(
                AgentDetection(
                    id=agent_id(relative_path, symbol),
                    name=symbol,
                    symbol=symbol,
                    confidence=confidence,
                    detection_score=score,
                    frameworks=list(frameworks),
                    evidence=list(evidence),
                )
            )
    else:
        symbol = symbols[0][0] if symbols else _filename_symbol(relative_path)
        detections.append(
            AgentDetection(
                id=agent_id(relative_path, symbol),
                name=symbol,
                symbol=symbol,
                confidence=confidence,
                detection_score=score,
                frameworks=list(frameworks),
                evidence=list(evidence),
            )
        )
    return detections


def _extract_symbols(content: str, class_match) -> list[tuple[str, int]]:
    """Symbol extraction order: constructor variable, class, variable, factory."""
    seen: set[str] = set()
    symbols: list[tuple[str, int]] = []

    for match in AGENT_CONSTRUCTOR_ASSIGNMENT.finditer(content):
        name = match.group(1)
        if name not in seen and not GENERIC_AGENT_NAME.search(name):
            seen.add(name)
            symbols.append((name, _line_of(content, match.start())))
    if symbols:
        return symbols

    if class_match is not None:
        return [(class_match.group(1), _line_of(content, class_match.start()))]

    for match in AGENT_LIKE_VARIABLE.finditer(content):
        name = match.group(1)
        if name not in seen and not GENERIC_AGENT_NAME.search(name):
            seen.add(name)
            symbols.append((name, _line_of(content, match.start())))
    if symbols:
        return symbols

    match = AGENT_FACTORY_FUNCTION.search(content)
    if match and not GENERIC_AGENT_NAME.search(match.group(1)):
        return [(match.group(1), _line_of(content, match.start()))]

    return []


def _filename_symbol(relative_path: str) -> str:
    return PurePosixPath(relative_path).stem
