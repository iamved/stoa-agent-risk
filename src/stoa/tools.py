"""Tool inventory: tools as first-class objects, attributed to the agents that bind them.

An agent's reach is mostly in its tools, and its tools mostly live in another
file. Until 0.7.4 the scanner read the agent's own file and stopped, so a
LangGraph agent that binds ``issue_refund`` from ``tools/account_tools.py``
showed ``tool_calling`` and nothing else. This module runs two passes:

* **definition pass** — every file: ``@tool`` / ``@function_tool`` /
  ``@mcp.tool`` decorated functions, ``StructuredTool.from_function``,
  raw JSON function schemas, TS ``tool({...})`` / ``server.tool("name", …)``,
  ``UCFunctionToolkit(function_names=[…])``. Each tool records its
  parameters, what its body reaches (the existing capability / integration
  patterns), numeric guards on its parameters, retry wrapping, and whether an
  idempotency key is visible.
* **binding pass** — per agent file: names passed to ``bind_tools``,
  ``ToolNode``, ``tools=``, ``create_react_agent``, TS ``tools: {…}``, resolved
  through the one-hop import graph to their definitions.

The agent's capabilities become the union of its own and its tools'. That is
what lets autonomy, the declaration contradiction, and ``stoa diff`` see the
write tools an agent actually holds.

AI008 lives here too: a money action reached through a retry with no
idempotency key posts twice on a timeout, and each attempt stays under the
per-call limit — the duplicate-refund near miss.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .config import StoaConfig
from .integration_detection import detect_capabilities, detect_integrations
from .models import Finding
from .rules import HIGH_IMPACT_CAPABILITIES

# --- vocabulary ----------------------------------------------------------------

# (?<![a-z]) rather than \b: `issue_refund` and `change_payout_account` have no
# word boundary before the money verb, only an underscore.
MONEY_VERB = re.compile(
    r"(?i)(?<![a-z])(?:refund|payout|pay_?out|transfer|disburse|charge|payment|reissue|wire|settle|"
    r"chargeback|credit_?note|invoice|withdraw|remit|waive|disbursement)"
)
RETRY_SIGNAL = re.compile(
    r"@retry\b|@\w+\.retry\b|\bbackoff\.on_(?:exception|predicate)\b|\bstop_after_attempt\b|"
    r"\b(?:Async)?Retrying\s*\(|\bmax_retries\s*=\s*[1-9]|\bretries\s*=\s*[1-9]|\bRetryPolicy\s*\(|"
    r"\bretry\s*=\s*(?:RetryPolicy|\{|True)|\bmaxRetries\s*:\s*[1-9]|\bretries\s*:\s*[1-9]|"
    r"\bp-?retry\b|\bretry\s*\(\s*(?:async\s*)?\(|\bwith_retry\b|\bRetry\s*\(\s*total\s*=\s*[1-9]"
)
IDEMPOTENCY_SIGNAL = re.compile(
    r"(?i)idempoten|request[_-]?id|dedup|already[_-]?(?:processed|refunded|sent|posted)|"
    r"seen[_-]?ids|processed[_-]?keys|\bnonce\b|transaction[_-]?ref|client[_-]?reference"
)
_OUTBOUND = re.compile(
    r"\b(?:requests|httpx|aiohttp|session|client|conn|http|urllib3|fetch|axios)\b[\w.]*\.(?:post|put|patch|delete|request)\s*\(|"
    r"\b(?:fetch|urlopen)\s*\(|\bstripe\.\w+|\b_call\s*\(|\bapi\w*\.\w+\s*\(|\bclient\.\w+\s*\("
)
_TOOL_DECORATOR = re.compile(r"^\s*@(?:[\w.]*\.)?(?:tool|function_tool|register_tool)\b")
_FROM_FUNCTION = re.compile(
    r"\b(?:StructuredTool|Tool)(?:\.from_function)?\s*\(\s*(?:func\s*=\s*)?(\w+)|"
    r"\bFunctionTool\.from_defaults\s*\(\s*(?:fn\s*=\s*)?(\w+)"
)
_PY_DEF = re.compile(r"^([ \t]*)(?:async\s+)?def\s+(\w+)\s*\(((?:[^()]|\([^()]*\))*)\)", re.MULTILINE)
_JSON_FUNCTION = re.compile(r"[\"']?type[\"']?\s*[:=]\s*[\"']function[\"']")
_JSON_NAME = re.compile(r"[\"']name[\"']\s*:\s*[\"'](\w+)[\"']")
_JSON_PROPS = re.compile(r"[\"']properties[\"']\s*:\s*\{")
_TS_TOOL = re.compile(r"(?:const|let|var)\s+(\w+)(?:\s*:\s*[\w<>\[\]]+)?\s*=\s*tool\s*\(\s*\{")
_TS_SERVER_TOOL = re.compile(r"\b(?:server|mcp)\.(?:tool|registerTool)\s*\(\s*[\"'](\w[\w-]*)[\"']")
_TS_DYNAMIC = re.compile(r"new\s+Dynamic(?:Structured)?Tool\s*\(\s*\{")
_UC_TOOLKIT = re.compile(r"UCFunctionToolkit\s*\(\s*function_names\s*=\s*\[([^\]]*)\]")
_ZOD_KEYS = re.compile(r"(?<![\w.])(?!(?:parameters|inputSchema|schema|args)\b)(\w+)\s*:\s*z\.")
_IDENT = re.compile(r"[A-Za-z_]\w*")


@dataclass
class ToolDef:
    """One tool: where it is defined, what it takes, what it reaches."""

    name: str
    path: str
    line: int
    symbol: str
    kind: str                                  # langchain_tool | openai_function_tool | mcp_tool | json_schema | ts_tool | uc_function | bedrock_action_group
    params: list[dict] = field(default_factory=list)      # [{"name": "amount", "type": "float"}]
    capabilities: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    guards: list[str] = field(default_factory=list)       # "amount > 500"
    retry: Optional[str] = None                           # what wraps it in a retry, if anything
    idempotency_key: bool = False
    money_action: bool = False
    resolved: bool = True                                 # False: schema or name only, no body seen
    calls: list[str] = field(default_factory=list)        # helper identifiers the body invokes

    def to_dict(self) -> dict:
        d = {
            "name": self.name, "path": self.path, "line": self.line, "kind": self.kind,
            "params": self.params, "capabilities": self.capabilities, "integrations": self.integrations,
            "high_impact": bool(HIGH_IMPACT_CAPABILITIES.intersection(self.capabilities)),
            "money_action": self.money_action, "guards": self.guards,
            "retry": self.retry, "idempotency_key": self.idempotency_key, "resolved": self.resolved,
        }
        return d


# --- definition pass -------------------------------------------------------------


def _line_of(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _params(sig: str) -> list[dict]:
    out, depth, cur = [], 0, []
    for ch in sig:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append("".join(cur)); cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    params = []
    for raw in out:
        raw = raw.strip().lstrip("*")
        if not raw or raw in ("self", "cls") or raw.startswith("/"):
            continue
        name, _, rest = raw.partition(":")
        name = name.split("=", 1)[0].strip()
        typ = rest.split("=", 1)[0].strip() if rest else ""
        if _IDENT.fullmatch(name):
            params.append({"name": name, "type": typ} if typ else {"name": name})
    return params


def _py_body(content: str, def_end: int, indent: str) -> str:
    """Lines after the def until the first non-blank line at the same or lesser indent."""
    lines = content[def_end:].split("\n")
    body = [lines[0]]                        # remainder of the def line (": ...")
    for ln in lines[1:]:
        if ln.strip() and (len(ln) - len(ln.lstrip())) <= len(indent):
            break
        body.append(ln)
    return "\n".join(body)


def _decorators_above(lines: list[str], def_line_idx: int) -> list[str]:
    decs = []
    i = def_line_idx - 1
    while i >= 0 and lines[i].strip().startswith("@"):
        decs.insert(0, lines[i]); i -= 1
    return decs


def _classify(body: str, name: str, extra: str = "") -> tuple[list[str], list[str], bool]:
    """Capabilities, integrations, and whether this is a money action."""
    text = body + "\n" + extra                      # the tool body plus same-file helpers it calls
    caps = set(detect_capabilities(text))
    integrations, _ = detect_integrations(text)
    outbound = bool(_OUTBOUND.search(text))
    money = bool(MONEY_VERB.search(name)) or bool(MONEY_VERB.search(body) and outbound)
    if money and outbound:
        caps.add("payment_access")
    return sorted(caps), integrations, money


def _guards(body: str, params: list[dict]) -> list[str]:
    guards = []
    for p in params:
        n = re.escape(p["name"])
        for m in re.finditer(rf"\b{n}\b\s*(?:>=|<=|==|!=|>|<)\s*[\w.]+|[\w.]+\s*(?:>=|<=|>|<)\s*\b{n}\b|"
                             rf"\b{n}\b\s*(?:not\s+)?in\s+[\w\[\(]|\bassert\s+[^\n]*\b{n}\b|"
                             rf"\b{n}\s*:\s*\w+\s*=\s*Field\([^)]*\b(?:le|lt|ge|gt|max_length|regex|pattern)\s*=", body):
            guards.append(re.sub(r"\s+", " ", m.group(0).strip())[:60])
    return sorted(set(guards))


def _py_functions(content: str) -> list[tuple[str, int, str, list[str], str, str]]:
    """(name, line, params_sig, decorators, body, indent) for every def."""
    lines = content.split("\n")
    out = []
    for m in _PY_DEF.finditer(content):
        indent, name, sig = m.group(1), m.group(2), m.group(3)
        line = _line_of(content, m.start())
        decs = _decorators_above(lines, line - 1)
        body = _py_body(content, m.end(), indent)
        out.append((name, line, sig, decs, body, indent))
    return out


def _collect_python(content: str, path: str) -> list[ToolDef]:
    funcs = _py_functions(content)
    by_name = {f[0]: f for f in funcs}
    from_function = {m.group(1) or m.group(2) for m in _FROM_FUNCTION.finditer(content)}
    tools: list[ToolDef] = []

    def _retry_of(body: str, decs: list[str], depth: int = 0) -> Optional[str]:
        dec_text = "\n".join(decs)
        m = RETRY_SIGNAL.search(dec_text) or RETRY_SIGNAL.search(body)
        if m:
            return m.group(0).strip("@ (=")
        if depth >= 1:
            return None
        for ident in set(_IDENT.findall(body)):        # one hop into a same-file helper
            if ident in by_name and ident not in ("self",):
                h = by_name[ident]
                r = _retry_of(h[4], h[3], depth + 1)
                if r:
                    return f"{r} (via {ident})"
        return None

    def _helper_text(body: str) -> str:
        parts = []
        for ident in set(_IDENT.findall(body)):
            if ident in by_name:
                parts.append(by_name[ident][4])
        return "\n".join(parts)

    for name, line, sig, decs, body, _indent in funcs:
        is_tool = any(_TOOL_DECORATOR.match(d) for d in decs) or name in from_function
        if not is_tool:
            continue
        kind = "langchain_tool"
        dtext = "\n".join(decs)
        if re.search(r"@(?:mcp|server|app)\.tool", dtext):
            kind = "mcp_tool"
        elif "function_tool" in dtext:
            kind = "openai_function_tool"
        params = _params(sig)
        helper = _helper_text(body)
        caps, integrations, money = _classify(body, name, helper)
        tools.append(ToolDef(
            name=name, path=path, line=line, symbol=name, kind=kind, params=params,
            capabilities=caps, integrations=integrations, guards=_guards(body, params),
            retry=_retry_of(body, decs), idempotency_key=bool(IDEMPOTENCY_SIGNAL.search(body + helper)),
            money_action=money, calls=sorted({i for i in set(_IDENT.findall(body)) if i in by_name}),
        ))

    # raw JSON function schemas: {"type": "function", "function": {"name": ...}}
    for m in _JSON_FUNCTION.finditer(content):
        window = content[m.start(): m.start() + 600]
        nm = _JSON_NAME.search(window)
        if not nm:
            continue
        tname = nm.group(1)
        if any(t.name == tname for t in tools):
            continue
        params = []
        pm = _JSON_PROPS.search(window)
        if pm:
            depth, i, start = 0, pm.end() - 1, pm.end()
            while i < len(window):
                if window[i] == "{": depth += 1
                elif window[i] == "}":
                    depth -= 1
                    if depth == 0: break
                i += 1
            params = [{"name": k} for k in re.findall(r"[\"'](\w+)[\"']\s*:\s*\{", window[start:i])]
        # a dispatcher branch `if name == "render": ...` is the implementation: the
        # helper it calls when there is one, otherwise the branch body itself
        impl = re.search(rf"==\s*[\"']{re.escape(tname)}[\"'][^\n]*\n", content)
        body = ""
        if impl:
            branch = re.split(r"\n[ \t]*(?:elif|else|if|case|default)\b", content[impl.end(): impl.end() + 800], 1)[0]
            helper = next((by_name[i][4] for i in _IDENT.findall(branch) if i in by_name), None)
            body = (helper or "") + "\n" + branch
        caps, integrations, money = _classify(body, tname)
        tools.append(ToolDef(
            name=tname, path=path, line=_line_of(content, m.start()), symbol=tname, kind="json_schema",
            params=params, capabilities=caps, integrations=integrations, guards=_guards(body, params) if body else [],
            retry=(RETRY_SIGNAL.search(body).group(0) if body and RETRY_SIGNAL.search(body) else None),
            idempotency_key=bool(body and IDEMPOTENCY_SIGNAL.search(body)), money_action=money, resolved=bool(body),
        ))

    # Unity Catalog functions: names only, the body is SQL governed elsewhere
    for m in _UC_TOOLKIT.finditer(content):
        for fq in re.findall(r"[\"']([\w.]+)[\"']", m.group(1)):
            short = fq.rsplit(".", 1)[-1]
            money = bool(MONEY_VERB.search(short))
            tools.append(ToolDef(
                name=short, path=path, line=_line_of(content, m.start()), symbol=fq, kind="uc_function",
                capabilities=["payment_access"] if money else [], money_action=money, resolved=False,
            ))
    return tools


def _brace_block(text: str, open_idx: int) -> str:
    depth = 0
    for i in range(open_idx, len(text)):
        c = text[i]
        if c == "{": depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[open_idx:i + 1]
    return text[open_idx:]


def _collect_js(content: str, path: str) -> list[ToolDef]:
    tools: list[ToolDef] = []
    for m in _TS_TOOL.finditer(content):
        body = _brace_block(content, m.end() - 1)
        params = [{"name": k} for k in _ZOD_KEYS.findall(body)]
        nm = _JSON_NAME.search(body)
        name = nm.group(1) if nm else m.group(1)
        caps, integrations, money = _classify(body, name)
        tools.append(ToolDef(name=name, path=path, line=_line_of(content, m.start()), symbol=m.group(1),
                             kind="ts_tool", params=params, capabilities=caps, integrations=integrations,
                             guards=_guards(body, params),
                             retry=(RETRY_SIGNAL.search(body).group(0) if RETRY_SIGNAL.search(body) else None),
                             idempotency_key=bool(IDEMPOTENCY_SIGNAL.search(body)), money_action=money))
    for m in _TS_SERVER_TOOL.finditer(content):
        # body: up to the matching close paren of the call
        depth, i = 0, m.start()
        while i < len(content):
            if content[i] == "(": depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0: break
            i += 1
        body = content[m.start():i + 1]
        params = [{"name": k} for k in _ZOD_KEYS.findall(body)]
        caps, integrations, money = _classify(body, m.group(1))
        tools.append(ToolDef(name=m.group(1), path=path, line=_line_of(content, m.start()), symbol=m.group(1),
                             kind="mcp_tool", params=params, capabilities=caps, integrations=integrations,
                             guards=_guards(body, params),
                             retry=(RETRY_SIGNAL.search(body).group(0) if RETRY_SIGNAL.search(body) else None),
                             idempotency_key=bool(IDEMPOTENCY_SIGNAL.search(body)), money_action=money))
    for m in _TS_DYNAMIC.finditer(content):
        body = _brace_block(content, m.end() - 1)
        nm = _JSON_NAME.search(body)
        if not nm:
            continue
        caps, integrations, money = _classify(body, nm.group(1))
        tools.append(ToolDef(name=nm.group(1), path=path, line=_line_of(content, m.start()), symbol=nm.group(1),
                             kind="langchain_tool", capabilities=caps, integrations=integrations, money_action=money,
                             retry=(RETRY_SIGNAL.search(body).group(0) if RETRY_SIGNAL.search(body) else None),
                             idempotency_key=bool(IDEMPOTENCY_SIGNAL.search(body))))
    for m in _JSON_FUNCTION.finditer(content):
        window = content[m.start(): m.start() + 600]
        nm = _JSON_NAME.search(window)
        if nm and not any(t.name == nm.group(1) for t in tools):
            tools.append(ToolDef(name=nm.group(1), path=path, line=_line_of(content, m.start()), symbol=nm.group(1),
                                 kind="json_schema", resolved=False,
                                 money_action=bool(MONEY_VERB.search(nm.group(1)))))
    return tools


def collect_tools(file_contents: dict[str, str]) -> dict[str, list[ToolDef]]:
    """path -> tools defined in that file, for every scanned file."""
    index: dict[str, list[ToolDef]] = {}
    for path, content in file_contents.items():
        if path.endswith(".py"):
            tools = _collect_python(content, path)
        elif path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
            tools = _collect_js(content, path)
        else:
            continue
        if tools:
            index[path] = tools
    return index


# --- binding pass ----------------------------------------------------------------

_BIND_SITES = re.compile(
    r"\bbind_tools\s*\(([^)]*)\)|\bToolNode\s*\(([^)]*)\)|\btools\s*[:=]\s*(\[[^\]]*\]|\{[^}]*\}|[A-Za-z_]\w*)|"
    r"\bcreate_react_agent\s*\([^,]+,\s*([^,)]+)|\btools\.(?:append|extend)\s*\(([^)]*)\)|"
    r"\bwith_tools\s*\(([^)]*)\)|\btoolkit\s*=\s*([A-Za-z_]\w*)"
)
_LIST_ASSIGN = re.compile(r"^\s*(?:const\s+|let\s+|var\s+)?(\w+)(?:\s*:\s*[^=\n]+)?\s*=\s*(\[[^\]]*\]|\{[^}]*\})", re.MULTILINE | re.DOTALL)


def _identifiers(expr: str) -> list[str]:
    expr = re.sub(r"[\"'][^\"']*[\"']", " ", expr)             # drop string literals
    return [i for i in _IDENT.findall(expr) if i not in ("list", "dict", "tools", "self", "None", "true", "false", "z", "as", "const")]


def bind_agent_tools(
    content: str, path: str, index: dict[str, list[ToolDef]], import_graph: dict[str, set[str]],
) -> list[ToolDef]:
    """Tools bound by the agent in ``content``: same-file tools by kind, plus names
    passed at binding sites resolved to definitions in this file or one import away."""
    own = index.get(path, [])
    bound: dict[tuple[str, str], ToolDef] = {}
    # MCP servers, JSON-schema lists, TS tool objects, UC toolkits in the agent file bind everything they define
    for t in own:
        if t.kind in ("mcp_tool", "json_schema", "uc_function", "ts_tool"):
            bound[(t.path, t.name)] = t

    lists = {m.group(1): m.group(2) for m in _LIST_ASSIGN.finditer(content)}
    idents: list[str] = []
    for m in _BIND_SITES.finditer(content):
        expr = next(g for g in m.groups() if g is not None)
        for ident in _identifiers(expr):
            if ident in lists and ident not in idents:
                idents.extend(_identifiers(lists[ident]))
            idents.append(ident)
    if not idents:
        return list(bound.values())

    candidates = list(own)
    for other in import_graph.get(path, ()):
        candidates.extend(index.get(other, []))
    by_symbol: dict[str, list[ToolDef]] = {}
    for t in candidates:
        by_symbol.setdefault(t.symbol, []).append(t)
        by_symbol.setdefault(t.name, []).append(t)
    for ident in idents:
        for t in by_symbol.get(ident, []):
            bound.setdefault((t.path, t.name), t)
    return sorted(bound.values(), key=lambda t: (t.path, t.line, t.name))


# --- AI008: non-idempotent money action under retry -----------------------------------

_AGENT_RETRY = re.compile(r"\bRetryPolicy\s*\(|\bretry\s*=\s*RetryPolicy|\bmax_retries\s*=\s*[1-9]|\bmaxRetries\s*:\s*[1-9]|\bmaxSteps\b.*\bretry")


def detect_ai008(agent_tools: list[ToolDef], agent_content: str, config: StoaConfig) -> list[Finding]:
    """A money or write tool reached through a retry, with no idempotency key."""
    if not config.rule_enabled("AI008"):
        return []
    from .ai_rules import _finding

    agent_retry = _AGENT_RETRY.search(agent_content)
    findings = []
    for t in agent_tools:
        side_effect = t.money_action or bool({"payment_access", "database_write"} & set(t.capabilities))
        if not side_effect:
            continue
        retry = t.retry or (f"agent-level retry policy ({agent_retry.group(0).strip()})" if agent_retry else None)
        if not retry or t.idempotency_key:
            continue
        what = "posts a money action" if t.money_action else "performs a write"
        findings.append(_finding(
            config, "AI008", t.path, t.line, f"def {t.name}(...)", "medium" if t.resolved else "low",
            context_key=f"{t.name}:retry",
            message=(
                f"`{t.name}` {what} and is retried on failure ({retry}); no idempotency key or "
                f"dedupe check was observed. A timeout after the upstream commits will post it again, "
                f"and each attempt is checked against the per-call limit on its own."
            ),
            tags=["retry", "money_action" if t.money_action else "write"],
        ))
    return findings
