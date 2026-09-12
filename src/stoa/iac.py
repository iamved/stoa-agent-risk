"""IaC collector: agents defined in infrastructure code, not application code.

Managed-platform agents (today: Databricks Model Serving endpoints) are
*configured*, not coded — the platform runs the loop. The agent is a resource
block in a Terraform file, so a code scanner walks straight past it. This
module reads Terraform (HCL) with a small zero-dependency block extractor,
recognizes agent-shaped resources, and emits agent candidates that flow
through the ordinary pipeline (registry, report, dimensions) with
``source="iac"``.

What the IaC layer states *explicitly* — and the code scanner can only infer:
  * reach:    ``databricks_grants`` privileges on exactly which tables/catalogs;
  * controls: an ``ai_gateway`` block (guardrails, rate limits, inference tables);
  * egress:   which model provider the endpoint calls out to.

Honesty rules, same as the rest of Stoa: values we cannot resolve from the
file (``var.*``, remote state) are left unresolved, never guessed; grants are
attributed to an endpoint only through its service principal's name stem and
that heuristic is recorded in the evidence, not hidden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .models import Evidence, agent_id

# --- zero-dependency HCL block extraction -----------------------------------

_RESOURCE_OPEN = re.compile(r'^[ \t]*resource\s+"([\w-]+)"\s+"([\w-]+)"\s*\{', re.MULTILINE)
_IDENT = re.compile(r"[A-Za-z_][\w-]*")


class Ref(str):
    """A bare HCL reference (``var.x``, ``aws_iam_role.r.arn``) — a value the file
    does not resolve. Kept distinct from a quoted string so callers never treat
    an unresolved reference as a literal (never guess)."""


@dataclass
class TfBlock:
    type: str
    name: str
    line: int
    attrs: dict[str, Any] = field(default_factory=dict)


def _skip(s: str, i: int) -> int:
    """Advance past whitespace and comments."""
    n = len(s)
    while i < n:
        c = s[i]
        if c in " \t\r\n":
            i += 1
        elif c == "#" or s.startswith("//", i):
            j = s.find("\n", i)
            i = n if j == -1 else j
        elif s.startswith("/*", i):
            j = s.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            break
    return i


def _string(s: str, i: int) -> tuple[str, int]:
    """Parse a double-quoted string starting at s[i]; returns (value, index after)."""
    j, out = i + 1, []
    while j < len(s):
        c = s[j]
        if c == "\\" and j + 1 < len(s):
            out.append(s[j + 1]); j += 2; continue
        if c == '"':
            return "".join(out), j + 1
        out.append(c); j += 1
    return "".join(out), j


def _close(s: str, i: int, open_ch: str, close_ch: str) -> int:
    """Index just past the bracket matching s[i], skipping strings and comments."""
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == '"':
            _, j = _string(s, j); continue
        if c == "#":
            k = s.find("\n", j); j = len(s) if k == -1 else k; continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    return len(s)


def _value(s: str, i: int) -> tuple[Any, int]:
    i = _skip(s, i)
    if i >= len(s):
        return None, i
    c = s[i]
    if c == '"':
        return _string(s, i)
    if c == "[":
        end = _close(s, i, "[", "]")
        return _list(s[i + 1:end - 1]), end
    if c == "{":
        end = _close(s, i, "{", "}")
        return _body(s[i + 1:end - 1]), end
    m = _IDENT.match(s, i)
    if m:
        k = _skip(s, m.end())
        if k < len(s) and s[k] == "(":          # function call, e.g. jsonencode({...}): keep raw
            end = _close(s, k, "(", ")")
            return s[i:end].strip(), end
    j = i
    while j < len(s) and s[j] not in " \t\n,]}":   # bare token: reference / number / bool
        j += 1
    tok = s[i:j]
    low = tok.lower()
    if low in ("true", "false"):
        return low == "true", j
    try:
        return (float(tok) if "." in tok else int(tok)), j
    except ValueError:
        return Ref(tok), j


def _list(inner: str) -> list:
    items, i, n = [], 0, len(inner)
    while True:
        i = _skip(inner, i)
        if i >= n:
            break
        v, i = _value(inner, i)
        items.append(v)
        i = _skip(inner, i)
        if i < n and inner[i] == ",":
            i += 1
    return items


def _body(body: str) -> dict[str, Any]:
    """Parse ``key = value`` pairs and nested blocks. Repeated blocks become lists."""
    out: dict[str, Any] = {}
    i, n = 0, len(body)
    while True:
        i = _skip(body, i)
        if i >= n:
            break
        m = _IDENT.match(body, i)
        if not m:                                # something we don't model: skip the line
            j = body.find("\n", i); i = n if j == -1 else j + 1; continue
        key, i = m.group(0), _skip(body, m.end())
        if i < n and body[i] == "=":
            val, i = _value(body, i + 1)
            out[key] = val
        elif i < n and body[i] == "{":
            end = _close(body, i, "{", "}")
            sub = _body(body[i + 1:end - 1]); i = end
            if key in out:
                out[key] = out[key] + [sub] if isinstance(out[key], list) else [out[key], sub]
            else:
                out[key] = sub
        elif i < n and body[i] == '"':           # labeled block (dynamic "x" {...}): skip
            while i < n and body[i] == '"':
                _, i = _string(body, i); i = _skip(body, i)
            if i < n and body[i] == "{":
                i = _close(body, i, "{", "}")
        else:
            j = body.find("\n", i); i = n if j == -1 else j + 1
    return out


def extract_tf_blocks(text: str) -> list[TfBlock]:
    """Every ``resource "TYPE" "NAME" { ... }`` block in a Terraform file."""
    blocks = []
    for m in _RESOURCE_OPEN.finditer(text):
        brace = m.end() - 1
        end = _close(text, brace, "{", "}")
        blocks.append(TfBlock(
            type=m.group(1), name=m.group(2),
            line=text.count("\n", 0, m.start()) + 1,
            attrs=_body(text[brace + 1:end - 1]),
        ))
    return blocks


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _one(v: Any) -> Optional[dict]:
    """A nested block that may have parsed as dict or [dict]."""
    v = _as_list(v)
    return v[0] if v and isinstance(v[0], dict) else None


def _lit(value: Any) -> Optional[str]:
    """A quoted string literal, or None for anything unresolved (a Ref) or non-string."""
    return value if isinstance(value, str) and not isinstance(value, Ref) else None


def _ref(value: Any) -> Optional[tuple[str, str]]:
    """``databricks_service_principal.x.application_id`` -> (type, name)."""
    if isinstance(value, Ref):
        m = re.match(r"^([a-z][\w]*)\.([\w-]+)(?:\.[\w-]+)*$", value)
        if m:
            return m.group(1), m.group(2)
    return None


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


def _stem(name: str) -> str:
    return re.split(r"[_-]", name, 1)[0].lower()


# --- Databricks recognition dictionary ---------------------------------------
# The IaC analog of HIGH_AGENT_PATTERNS: keyed on resource type, not on a
# constructor call. Extending to Bedrock/Vertex/Azure is adding rows here.

RES_SERVING = "databricks_model_serving"
RES_GRANTS = "databricks_grants"
RES_SP = "databricks_service_principal"
RES_VECTOR_INDEX = "databricks_vector_search_index"

DATABRICKS_RESOURCES = {
    RES_SERVING: "agent",           # a serving endpoint IS a deployed agent
    RES_GRANTS: "reach",            # exactly which data, which privileges
    RES_SP: "identity",
    RES_VECTOR_INDEX: "data_source",
}

_ENV_KEY_PROVIDER = {
    "OPENAI_API_KEY": "openai", "ANTHROPIC_API_KEY": "anthropic",
    "GOOGLE_API_KEY": "google", "COHERE_API_KEY": "cohere", "MISTRAL_API_KEY": "mistral",
}
_WRITE_PRIVS = {"MODIFY", "ALL_PRIVILEGES", "ALL PRIVILEGES", "WRITE_VOLUME", "WRITE_FILES", "CREATE_TABLE"}
_READ_PRIVS = {"SELECT", "READ_VOLUME", "READ_FILES", "USE_CATALOG", "USE_SCHEMA"}


@dataclass
class IacDetection:
    """An agent found in infrastructure code, ready to become an AgentCandidate."""

    id: str
    name: str
    symbol: str
    confidence: str
    detection_score: int
    evidence: list[Evidence]
    frameworks: list[str]
    providers: list[str]
    integrations: list[str]
    capabilities: list[str]
    controls: set[str]              # taxonomy control ids, injected into dimension scoring
    platform: str = "databricks"
    source: str = "iac"
    discovery_tier: str = "recognized"


def detect_iac_agents(content: str, relative_path: str) -> list[IacDetection]:
    """Agent candidates for every recognized agent resource in a Terraform file."""
    blocks = extract_tf_blocks(content)
    endpoints = [b for b in blocks if b.type == RES_SERVING]
    if not endpoints:
        return []
    grants = [b for b in blocks if b.type == RES_GRANTS]

    detections = []
    for ep in endpoints:
        a = ep.attrs
        display = _lit(a.get("name")) or ep.name          # a var.* name is unresolved: fall back
        cfg = _one(a.get("config")) or {}
        served = [s for s in _as_list(cfg.get("served_entities")) if isinstance(s, dict)]
        entity = next((_lit(s.get("entity_name")) for s in served if _lit(s.get("entity_name"))), None)

        evidence = [Evidence(
            "AGENT_IAC_SERVING_ENDPOINT", ep.line,
            f"Databricks model serving endpoint '{display}' — a deployed agent"
            + (f", serving UC model {entity}" if entity else ""),
        )]

        # egress: which model provider the endpoint calls out to
        providers: set[str] = set()
        for s in served:
            env = s.get("environment_vars")
            if isinstance(env, dict):
                for key in env:
                    if key in _ENV_KEY_PROVIDER:
                        prov = _ENV_KEY_PROVIDER[key]
                        providers.add(prov)
                        evidence.append(Evidence(
                            "IAC_MODEL_EGRESS", ep.line,
                            f"{key} configured — model calls leave to {prov}"))
            ext = _one(s.get("external_model"))
            if ext and isinstance(ext.get("provider"), str):
                providers.add(ext["provider"].lower())

        # controls: stated explicitly by the AI Gateway, credited rather than inferred
        controls: set[str] = set()
        gw = _one(a.get("ai_gateway"))
        if gw:
            if gw.get("guardrails"):
                controls.add("validation")
                evidence.append(Evidence("IAC_CONTROL_GUARDRAIL", ep.line,
                                         "AI Gateway guardrails configured (input/output filtering)"))
            if gw.get("rate_limits"):
                controls.add("rate_limit")
                evidence.append(Evidence("IAC_CONTROL_RATE_LIMIT", ep.line,
                                         "AI Gateway rate limit configured"))
            itc = _one(gw.get("inference_table_config"))
            utc = _one(gw.get("usage_tracking_config"))
            if (itc and _truthy(itc.get("enabled"))) or (utc and _truthy(utc.get("enabled"))):
                controls.add("observability")
                evidence.append(Evidence("IAC_CONTROL_OBSERVABILITY", ep.line,
                                         "AI Gateway inference tables / usage tracking enabled"))

        # reach: grants to the endpoint's service principal (matched by name stem)
        caps: set[str] = set()
        ep_stem = _stem(ep.name)
        for g in grants:
            scope = next(
                (f"{k} {_lit(g.attrs[k])}" for k in ("table", "schema", "catalog", "volume")
                 if _lit(g.attrs.get(k))), "unresolved scope")
            for gr in _as_list(g.attrs.get("grant")):
                if not isinstance(gr, dict):
                    continue
                ref = _ref(gr.get("principal"))
                if not ref or ref[0] != RES_SP or _stem(ref[1]) != ep_stem:
                    continue
                privs = {str(p).upper() for p in _as_list(gr.get("privileges"))}
                if privs & (_READ_PRIVS | _WRITE_PRIVS):
                    caps.add("database_read")
                if privs & _WRITE_PRIVS:
                    caps.add("database_write")
                wide = scope.startswith("catalog") and bool(privs & {"ALL_PRIVILEGES", "ALL PRIVILEGES"})
                evidence.append(Evidence(
                    "IAC_GRANT", g.line,
                    f"{', '.join(sorted(privs))} on {scope} (via {ref[1]})"
                    + (" — catalog-wide privileges, broad reach" if wide else ""),
                ))

        # Symbol = "<resource_type>.<name>" so two resource types sharing a name in
        # one file never collide on id; the human-facing name stays the endpoint name.
        symbol = f"{ep.type}.{ep.name}"
        detections.append(IacDetection(
            id=agent_id(relative_path, symbol),
            name=display, symbol=symbol,
            confidence="high", detection_score=8,     # a deployed endpoint is not ambiguous
            evidence=evidence, frameworks=[],          # Databricks is the platform, not an agent framework
            providers=sorted(providers), integrations=["databricks"],
            capabilities=sorted(caps), controls=controls,
        ))
    return detections
