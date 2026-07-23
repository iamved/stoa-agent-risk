"""Taint-based AI rules (Part II §AI001/AI002/AI004, Part IV §B.1 AI006).

These consume the intra-file taint engine (`stoa.flow`) over a tree-sitter
parse. Each rule supplies node-matching source/sink predicates and turns the
resulting flows into findings with a redacted `flow` array. Confidence is the
flow's tier (high = unbroken same-function chain, medium = crosses a same-file
function). AI002 exec-class at high confidence is the only gate-eligible AI
finding, and only when the precision bar is met.
"""

from __future__ import annotations

import re

from .ai_rules import _finding
from .ast_layer import ParsedFile
from .config import StoaConfig
from .flow import Flow, find_flows
from .models import Finding, FlowRecord

_CONF_ORDER = ["low", "medium", "high"]

INTRA_FILE_FOOTER = " Analysis is intra-file; flows through other files are not visible."


def _text(node) -> str:
    return node.text.decode("utf-8", "replace")


# --- source / sink node predicates -----------------------------------------

_MODEL_OUTPUT = re.compile(
    r"\.choices\[\d+\]\.(?:message|delta)\.content\b|\.output_text\b|"
    r"\.content\[\d+\]\.text\b|\bmessage\.content\b|\.completion\b|"
    r"\b(?:llm|chain|agent)\.(?:invoke|ainvoke|run|call)\s*\(|"
    r"\b(?:generateText|streamText)\s*\("
)
_MODEL_CALL = re.compile(
    r"\.(?:chat\.completions|responses|messages)\.create\s*\(|"
    r"\.(?:generate_content|generateContent)\s*\(|"
    r"\b(?:llm|chain|agent|model)\.(?:invoke|ainvoke|stream|run)\s*\(|"
    r"\b(?:generateText|streamText|generateObject|streamObject)\s*\("
)
_REQUEST_SOURCE = re.compile(
    r"\brequest\.(?:args|form|get_json|json|data|values|files)\b|"
    r"\breq\.(?:body|query|params)\b|\bformData\.get\s*\(|"
    r"\binput\s*\(\s*\)|\bsys\.stdin\b|\.read\s*\(\s*\)|"
    r"\b(?:retriever\.invoke|get_relevant_documents|index\.query)\s*\(|"
    r"\.(?:similarity_search|similaritySearch)\s*\("
)
_SECRET_SOURCE = re.compile(
    r"os\.environ\[['\"][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|DSN)['\"]\]|"
    r"os\.getenv\(\s*['\"][A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|DSN)|"
    r"process\.env\.[A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|DSN)|"
    r"\.(?:api_key|secret|token|password|private_key)\b"
)
_DEFAULT_PII = (
    "email", "phone", "ssn", "social_security", "dob", "date_of_birth",
    "address", "salary", "diagnosis", "patient", "passport", "iban",
    "card_number", "national_id",
)
_EGRESS = re.compile(
    r"\brequests\.(?:post|put|patch)\s*\(|\bhttpx\.(?:post|put|patch)\b|"
    r"\burllib\.request\.urlopen\s*\(|\bsmtplib\b|\.sendmail\s*\(|\.sendMail\s*\(|"
    r"\bfetch\s*\(|\baxios\.(?:post|put|patch)\s*\(|\bput_object\s*\("
)
_PROVIDER_HOST = re.compile(
    r"api\.openai\.com|api\.anthropic\.com|api\.groq\.com|openrouter\.ai|"
    r"generativelanguage\.googleapis\.com|api\.mistral\.ai|api\.cohere|"
    r"api\.together|api\.perplexity\.ai|\.openai\.azure\.com"
)
_LOCAL_HOST = re.compile(r"localhost|127\.0\.0\.1|0\.0\.0\.0|://10\.|://192\.168\.|://172\.(?:1[6-9]|2\d|3[01])\.")
_BOUNDARY = re.compile(r"(?i)sanitize|escape|redact|moderat|guard")

# AI002 sink classes.
_EXEC = re.compile(
    r"(?<![\w.])(?:eval|exec)\s*\(|\bos\.system\s*\(|"
    r"\bsubprocess\.(?:run|Popen|call|check_output|check_call)\s*\(|\bpty\.spawn\s*\(|"
    r"\bnew\s+Function\s*\(|\bchild_process\.(?:exec|execSync|spawn)\b|\bvm\.runInContext\b"
)
_SQL = re.compile(r"\bcursor\.execute\s*\(|\.raw\s*\(|\btext\s*\(|\.query\s*\(")
_DESERIALIZE = re.compile(r"\bpickle\.loads?\s*\(|\byaml\.load\s*\(|\bmarshal\.loads?\s*\(")
_MARKUP_CALL = re.compile(r"\bdocument\.write\s*\(|\bMarkup\s*\(|\bmark_safe\s*\(|\bdangerouslySetInnerHTML\b")
_REQUEST_SINK = re.compile(r"\brequests\.(?:get|post)\s*\(|\bfetch\s*\(|\bhttpx\.(?:get|post)\b")

_SINK_CLASS_SEVERITY = {
    "exec": "critical", "sql": "critical", "deserialize": "critical",
    "markup": "high", "request": "high",
}


def _escalate(conf: str) -> str:
    return _CONF_ORDER[min(_CONF_ORDER.index(conf) + 1, 2)]


def _flow_records(flow: Flow) -> list[FlowRecord]:
    return [FlowRecord(role=s.role, line=s.line, snippet=s.snippet) for s in flow.steps]


def _classify_ai002_sink(node) -> str | None:
    t = _text(node)
    # markup assignment: x.innerHTML = tainted
    if node.type in ("assignment", "assignment_expression"):
        left = node.child_by_field_name("left")
        if left is not None and _text(left).endswith(".innerHTML"):
            return "markup"
        return None
    if node.type not in ("call", "call_expression"):
        return None
    if _EXEC.search(t):
        return "exec"
    if _DESERIALIZE.search(t):
        return "deserialize"
    if _SQL.search(t):
        return "sql"
    if _MARKUP_CALL.search(t):
        return "markup"
    if _REQUEST_SINK.search(t):
        return "request"
    return None


# --- rule drivers -----------------------------------------------------------

def _detect_ai002(parsed, path, config) -> list[Finding]:
    if not config.rule_enabled("AI002"):
        return []
    findings = []
    for flow in find_flows(
        parsed,
        lambda n: "model_output" if _MODEL_OUTPUT.search(_text(n)) else None,
        _classify_ai002_sink,
    ):
        sink_class = flow.sink_tag
        severity = _SINK_CLASS_SEVERITY.get(sink_class, "high")
        gate = sink_class == "exec" and flow.confidence == "high"
        sink = flow.steps[-1]
        src = flow.steps[0]
        supersedes = ["SEC003"] if sink_class == "sql" else []
        msg = (
            f"The value from `{src.snippet}` (line {src.line}) reaches a "
            f"{sink_class}-class sink at line {sink.line} with no interposed "
            "allowlist observed on the flow. Model output is attacker-influenceable "
            "whenever any untrusted content reaches the model (OWASP LLM02)."
            + (" This finding is gate-eligible." if gate else "")
            + INTRA_FILE_FOOTER
        )
        f = _finding(
            config, "AI002", path, sink.line, sink.snippet, flow.confidence,
            message=msg, severity=severity, variant=sink_class,
            supersedes=supersedes or None,
            context_key=f"AI002:{sink_class}:{sink.snippet}",
        )
        f.flow = _flow_records(flow)
        f.gate_eligible = gate
        findings.append(f)
    return findings


def _detect_ai001(parsed, path, config) -> list[Finding]:
    if not config.rule_enabled("AI001"):
        return []
    findings = []
    for flow in find_flows(
        parsed,
        lambda n: "request" if _REQUEST_SOURCE.search(_text(n)) else None,
        lambda n: "prompt" if (n.type in ("call", "call_expression") and _MODEL_CALL.search(_text(n))) else None,
    ):
        sink = flow.steps[-1]
        src = flow.steps[0]
        conf = flow.confidence
        tags = []
        severity = "high"
        system_role = "system" in _text_window(flow)
        boundary = any(_BOUNDARY.search(s.snippet) for s in flow.steps)
        if system_role:
            conf = _escalate(conf)
            tags.append("system_role_interpolation")
        if boundary:
            severity = "info"
            tags.append("boundary_observed")
        msg = (
            f"A request-derived value (`{src.snippet}`, line {src.line}) flows into "
            f"prompt construction reaching a model call at line {sink.line}."
            + ("" if boundary else " No boundary construct was observed on this flow.")
            + " Content that reaches instruction text can override agent behavior "
            "(OWASP LLM01). Consider moving untrusted content into a delimited "
            "user-role message and keeping instruction text static." + INTRA_FILE_FOOTER
        )
        f = _finding(
            config, "AI001", path, sink.line, sink.snippet, conf,
            message=msg, severity=severity, tags=tags or None,
            context_key=f"AI001:{sink.snippet}",
        )
        f.flow = _flow_records(flow)
        findings.append(f)
    return findings


def _detect_ai004(parsed, path, config, providers) -> list[Finding]:
    if not config.rule_enabled("AI004"):
        return []
    pii = re.compile(
        r"\.(?:" + "|".join(_DEFAULT_PII + tuple(config.ai004_pii_terms)) + r")\b|"
        r"\[['\"](?:" + "|".join(_DEFAULT_PII + tuple(config.ai004_pii_terms)) + r")['\"]\]",
        re.IGNORECASE,
    )

    def is_source(n):
        t = _text(n)
        if _SECRET_SOURCE.search(t):
            return "secret"
        if pii.search(t):
            return "pii"
        return None

    local = "ollama" in providers or bool(_LOCAL_HOST.search(parsed.source.decode("utf-8", "replace")))
    findings = []
    for flow in find_flows(
        parsed, is_source,
        lambda n: "prompt" if (n.type in ("call", "call_expression") and _MODEL_CALL.search(_text(n))) else None,
    ):
        cls = flow.source_tag
        severity = "high" if cls == "secret" else "medium"
        tags = []
        if local:
            severity = _downgrade(severity)
            tags.append("local_endpoint_observed")
        src, sink = flow.steps[0], flow.steps[-1]
        kind = "a credential" if cls == "secret" else "personal data"
        msg = (
            f"An identifier suggesting {kind} (`{src.snippet}`, line {src.line}) is "
            f"interpolated into a prompt passed to a model call at line {sink.line}. "
            "Identifier names suggest — but do not prove — sensitive data (OWASP "
            "LLM06). Values are never read or transmitted by Stoa; this finding is "
            "based on identifier names and flow shape only." + INTRA_FILE_FOOTER
        )
        f = _finding(
            config, "AI004", path, sink.line, sink.snippet, flow.confidence,
            message=msg, severity=severity, variant=cls, tags=tags or None,
            context_key=f"AI004:{cls}:{sink.snippet}",
        )
        f.flow = _flow_records(flow)
        findings.append(f)
    return findings


def _detect_ai006(parsed, path, config) -> list[Finding]:
    if not config.rule_enabled("AI006"):
        return []
    pii = re.compile(
        r"\.(?:" + "|".join(_DEFAULT_PII + tuple(config.ai004_pii_terms)) + r")\b",
        re.IGNORECASE,
    )
    allowed = config.ai006_allowed_hosts

    def is_source(n):
        t = _text(n)
        if _SECRET_SOURCE.search(t):
            return "secret"
        if pii.search(t):
            return "pii"
        if _MODEL_OUTPUT.search(t):
            return "model-output"
        return None

    def is_sink(n):
        if n.type not in ("call", "call_expression"):
            return None
        t = _text(n)
        if not _EGRESS.search(t):
            return None
        if _PROVIDER_HOST.search(t):  # provider egress is AI004's jurisdiction
            return None
        if _LOCAL_HOST.search(t) or any(h in t for h in allowed):
            return None
        return "egress"

    findings = []
    for flow in find_flows(parsed, is_source, is_sink):
        cls = flow.source_tag
        severity = "high" if cls == "secret" else "medium"
        src, sink = flow.steps[0], flow.steps[-1]
        # Dynamic destination (no literal URL host in the call) is lower confidence.
        dynamic = not re.search(r"https?://", sink.snippet)
        conf = _downgrade_conf(flow.confidence) if dynamic else flow.confidence
        tags = ["dynamic_destination"] if dynamic else []
        kind = "a credential" if cls == "secret" else ("personal data" if cls == "pii" else "model output")
        msg = (
            f"A value suggesting {kind} (`{src.snippet}`, line {src.line}) flows into "
            f"a network egress sink at line {sink.line}, a destination not in the "
            "recognized-provider set or the allowed_hosts list. Identifier names and "
            "flow shape suggest — but do not prove — sensitive egress (OWASP LLM06). "
            "If org-approved, add the destination to [rules.AI006].allowed_hosts."
            + INTRA_FILE_FOOTER
        )
        f = _finding(
            config, "AI006", path, sink.line, sink.snippet, conf,
            message=msg, severity=severity, variant=cls, tags=tags or None,
            supersedes=["AI004"] if cls in ("secret", "pii") else None,
            context_key=f"AI006:{cls}:{sink.snippet}",
        )
        f.flow = _flow_records(flow)
        findings.append(f)
    return findings


def _text_window(flow: Flow) -> str:
    return " ".join(s.snippet for s in flow.steps)


def _downgrade(sev: str) -> str:
    order = ["info", "low", "medium", "high", "critical"]
    return order[max(order.index(sev) - 1, 0)]


def _downgrade_conf(conf: str) -> str:
    return _CONF_ORDER[max(_CONF_ORDER.index(conf) - 1, 0)]


def detect_ai_taint(
    parsed: ParsedFile,
    path: str,
    is_testlike: bool,
    config: StoaConfig,
    providers: list[str],
) -> list[Finding]:
    """Run all taint-based AI rules over one parsed file."""
    if not parsed.available:
        return []  # conservative: no regex-fallback taint findings (would be low-confidence guesses)
    findings: list[Finding] = []
    findings += _detect_ai002(parsed, path, config)
    findings += _detect_ai001(parsed, path, config)
    findings += _detect_ai004(parsed, path, config, providers)
    findings += _detect_ai006(parsed, path, config)
    return findings
