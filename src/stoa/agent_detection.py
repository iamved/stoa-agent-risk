"""Weighted-evidence agent-candidate detection.

A file is never classified as an agent candidate on a single regex match:
each pattern contributes evidence with a weight, and the total score maps to
a confidence level. Test-like paths are downweighted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import Evidence, agent_id
from .rules import (
    AGENT_CONSTRUCTOR_ASSIGNMENT,
    AGENT_FACTORY_FUNCTION,
    AGENT_LIKE_VARIABLE,
    DIRECT_MODEL_ENDPOINTS,
    GENERIC_AGENT_NAME,
    HIGH_AGENT_PATTERNS,
    PROVIDER_PATTERNS,
    SUPPORTING_PATTERNS,
)

SCORE_FRAMEWORK_CONSTRUCTOR = 5
SCORE_EXECUTION = 3
SCORE_PROVIDER_CALL = 2
SCORE_TOOLS = 2
SCORE_PROVIDER_IMPORT = 1
SCORE_AGENT_CLASS = 1
SCORE_TESTLIKE_PENALTY = -3

HIGH_THRESHOLD = 8
MEDIUM_THRESHOLD = 5
LOW_THRESHOLD = 3

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
}


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


def detect_agents(content: str, relative_path: str, is_testlike: bool) -> list[AgentDetection]:
    """Return zero or more agent candidates for one file."""
    evidence: list[Evidence] = []
    frameworks: list[str] = []
    score = 0

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
        score += SCORE_AGENT_CLASS
        evidence.append(
            Evidence(
                rule_id="AGENT_CLASS_NAME",
                line=_line_of(content, class_match.start()),
                description=f"Class name suggests an agent: {class_match.group(1)}",
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
    confidence = _classify(score)
    if confidence is None and not has_constructor:
        return []
    if confidence is None:
        # A high-confidence framework constructor qualifies the candidate even
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
