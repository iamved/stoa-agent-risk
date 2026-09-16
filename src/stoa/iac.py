"""IaC collector: agents defined in infrastructure code, not application code.

Managed-platform agents (Databricks Model Serving endpoints, Amazon Bedrock
agents) are *configured*, not coded — the platform runs the loop. The agent is
a resource block in a Terraform file, so a code scanner walks straight past
it. This module reads Terraform (HCL) with a small zero-dependency block
extractor, recognizes agent-shaped resources, and emits agent candidates that
flow through the ordinary pipeline (registry, report, dimensions) with
``source="iac"``.

Scope is the Terraform **module**: every ``.tf`` file in one directory is one
configuration, and real deployments split the agent, its IAM, and its
guardrail across files. Detection therefore runs over all blocks in the
directory, and each agent keeps the path of the file that defines it.

Values are **resolved** before detection where the module itself says what
they are: ``variable`` defaults, ``terraform.tfvars`` / ``*.auto.tfvars``,
``locals``, ``${...}`` interpolation of those, ``count`` / ``for_each``
expansion, ``cond ? a : b`` on a resolved boolean, ``data
"aws_iam_policy_document"`` statements. A local ``module "x" { source =
"./..." }`` call instantiates that directory with the call's inputs, so each
call is its own agent (``module.x.<type>.<name>``). A ``terraform show -json``
plan can be supplied instead of the files: values arrive fully resolved and
resource links come from the configuration's expression references.

What the IaC layer states *explicitly* — and the code scanner can only infer:
  * reach:    ``databricks_grants`` privileges, or IAM policy actions on the
              agent's role and its tools' Lambda roles;
  * controls: an ``ai_gateway`` block, a Bedrock guardrail, invocation logging;
  * tools:    Bedrock action groups — literal tool bindings;
  * egress:   which model provider the agent calls.

Honesty rules, same as the rest of Stoa: values we cannot resolve from the
module (``var.*``, remote state, data sources) are left unresolved, never
guessed; every attribution path (a name stem, a role, a Lambda's role) is
recorded in the evidence, not hidden.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .models import Evidence, agent_id

# --- zero-dependency HCL block extraction -----------------------------------

_RESOURCE_OPEN = re.compile(r'^[ \t]*resource\s+"([\w-]+)"\s+"([\w-]+)"\s*\{', re.MULTILINE)
_TOP_OPEN = re.compile(
    r'^[ \t]*(resource|data|variable|module|locals|output)\b((?:[ \t]+"[\w./-]+")*)[ \t]*\{', re.MULTILINE)
_LABEL = re.compile(r'"([^"]*)"')
_MANAGED_REF = re.compile(r"^(?!var\.|local\.|module\.|each\.|count\.|path\.|data\.|null$|true$|false$)([a-z][\w]*)\.([\w-]+)")
_INTERP = re.compile(r"\$\{\s*((?:var|local)\.[\w-]+|each\.(?:key|value)|count\.index)\s*\}")
_IDENT = re.compile(r"[A-Za-z_][\w-]*")
_HEREDOC_OPEN = re.compile(r"<<-?[ \t]*([A-Za-z_]\w*)[ \t]*\r?\n")


class Ref(str):
    """A bare HCL reference (``var.x``, ``aws_iam_role.r.arn``) — a value the file
    does not resolve. Kept distinct from a quoted string so callers never treat
    an unresolved reference as a literal (never guess)."""


@dataclass
class Cond:
    """``cond ? a : b`` — picked once ``cond`` resolves to a boolean, else unresolved."""

    cond: Any
    a: Any
    b: Any


@dataclass
class TfBlock:
    type: str
    name: str
    line: int
    attrs: dict[str, Any] = field(default_factory=dict)
    path: str = ""                  # file that defines the block (module scope)
    instance: str = ""              # '["key"]' / '[0]' after count/for_each expansion

    @property
    def address(self) -> str:
        return f"{self.type}.{self.name}{self.instance}"


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
        v, j = _string(s, i)
        return _maybe_ternary(s, v, j)
    if c == "[":
        end = _close(s, i, "[", "]")
        return _list(s[i + 1:end - 1]), end
    if c == "{":
        end = _close(s, i, "{", "}")
        return _body(s[i + 1:end - 1]), end
    if s.startswith("<<", i):                    # heredoc (<<EOF ... EOF): raw text
        m = _HEREDOC_OPEN.match(s, i)
        if m:
            start = m.end()
            term = re.compile(r"^[ \t]*" + re.escape(m.group(1)) + r"[ \t]*$", re.MULTILINE)
            t = term.search(s, start)
            return (s[start:t.start()] if t else s[start:]), (t.end() if t else len(s))
    m = _IDENT.match(s, i)
    if m:
        k = _skip(s, m.end())
        if k < len(s) and s[k] == "(":          # function call, e.g. jsonencode({...}): keep raw
            end = _close(s, k, "(", ")")
            return _maybe_ternary(s, s[i:end].strip(), end)
    j = i
    while j < len(s) and s[j] not in " \t\n,]}?":  # bare token: reference / number / bool
        if s[j] == "[":                              # index segment: this[0].id, each["k"]
            j = _close(s, j, "[", "]"); continue
        j += 1
    tok = s[i:j]
    low = tok.lower()
    if low in ("true", "false"):
        val: Any = low == "true"
    else:
        try:
            val = float(tok) if "." in tok else int(tok)
        except ValueError:
            val = Ref(tok)
    return _maybe_ternary(s, val, j)


def _maybe_ternary(s: str, val: Any, j: int) -> tuple[Any, int]:
    """``val ? a : b`` on the same line -> Cond."""
    k = j
    while k < len(s) and s[k] in " \t":
        k += 1
    if k < len(s) and s[k] == "?":
        a, k = _value(s, k + 1)
        k = _skip(s, k)
        if k < len(s) and s[k] == ":":
            b, k = _value(s, k + 1)
            return Cond(val, a, b), k
    return val, j


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
    """Parse ``key = value`` pairs and nested blocks. Repeated blocks become lists.

    Also accepts quoted keys with ``=`` or ``:`` (the object syntax inside
    ``jsonencode({...})`` and plain JSON), so IAM policy documents parse.
    """
    out: dict[str, Any] = {}
    i, n = 0, len(body)
    while True:
        i = _skip(body, i)
        if i >= n:
            break
        if body[i] == ",":                       # separator inside an object literal
            i += 1; continue
        m = _IDENT.match(body, i)
        if m:
            key, i = m.group(0), _skip(body, m.end())
            if i < n and body[i] in "=:":
                val, i = _value(body, i + 1)
                out[key] = val
            elif i < n and body[i] == "{":
                end = _close(body, i, "{", "}")
                sub = _body(body[i + 1:end - 1]); i = end
                if key in out:
                    out[key] = out[key] + [sub] if isinstance(out[key], list) else [out[key], sub]
                else:
                    out[key] = sub
            elif i < n and body[i] == '"':       # labeled block (dynamic "x" {...}): skip
                while i < n and body[i] == '"':
                    _, i = _string(body, i); i = _skip(body, i)
                if i < n and body[i] == "{":
                    i = _close(body, i, "{", "}")
            else:
                j = body.find("\n", i); i = n if j == -1 else j + 1
            continue
        if body[i] == '"':                       # quoted key: "Version" = ... / "Action": [...]
            key, j = _string(body, i); j = _skip(body, j)
            if j < n and body[j] in "=:":
                val, i = _value(body, j + 1)
                out[key] = val
                continue
        j = body.find("\n", i); i = n if j == -1 else j + 1   # something we don't model
    return out


@dataclass
class TfFile:
    """Top-level blocks of one Terraform file, by kind."""

    blocks: list[TfBlock] = field(default_factory=list)      # resource + data ("data.<type>")
    variables: dict[str, Any] = field(default_factory=dict)  # name -> default (None if none)
    locals: dict[str, Any] = field(default_factory=dict)
    module_calls: list[TfBlock] = field(default_factory=list)  # type "module", name = call label
    outputs: dict[str, Any] = field(default_factory=dict)


def parse_tf(text: str, path: str = "") -> TfFile:
    """Every top-level ``resource`` / ``data`` / ``variable`` / ``locals`` / ``module`` block."""
    out = TfFile()
    pos = 0
    while True:
        m = _TOP_OPEN.search(text, pos)
        if not m:
            break
        brace = m.end() - 1
        end = _close(text, brace, "{", "}")
        pos = end
        kind = m.group(1)
        labels = _LABEL.findall(m.group(2))
        line = text.count("\n", 0, m.start()) + 1
        attrs = _body(text[brace + 1:end - 1])
        if kind == "resource" and len(labels) == 2:
            out.blocks.append(TfBlock(labels[0], labels[1], line, attrs, path))
        elif kind == "data" and len(labels) == 2:
            out.blocks.append(TfBlock(f"data.{labels[0]}", labels[1], line, attrs, path))
        elif kind == "variable" and labels:
            out.variables[labels[0]] = attrs.get("default")
        elif kind == "locals":
            out.locals.update(attrs)
        elif kind == "module" and labels:
            out.module_calls.append(TfBlock("module", labels[0], line, attrs, path))
        elif kind == "output" and labels:
            out.outputs[labels[0]] = attrs.get("value")
    return out


def extract_tf_blocks(text: str, path: str = "") -> list[TfBlock]:
    """Every ``resource "TYPE" "NAME" { ... }`` block in a Terraform file."""
    return [b for b in parse_tf(text, path).blocks if not b.type.startswith("data.")]


# --- resolution: variables, locals, tfvars, interpolation, count / for_each ---


def _lookup(env: dict, ref: str) -> tuple[bool, Any]:
    """``var.x`` / ``local.y`` / ``each.value`` / ``count.index`` -> (found, value)."""
    ns, _, rest = ref.partition(".")
    if ns not in env or not rest:
        return False, None
    name = rest.split(".", 1)[0].split("[", 1)[0]
    if name not in env[ns]:
        return False, None
    val = env[ns][name]
    if rest != name:                      # deeper path (var.x.y, var.x[0]): not modeled
        return False, None
    return val is not None, val


def _resolve(value: Any, env: dict, depth: int = 0) -> Any:
    """Replace what the module itself resolves; leave everything else as-is."""
    if depth > 6:
        return value
    if isinstance(value, Cond):
        cond = _resolve(value.cond, env, depth + 1)
        if isinstance(cond, bool):
            return _resolve(value.a if cond else value.b, env, depth + 1)
        return value
    if isinstance(value, Ref):
        if value == "null":
            return None
        found, v = _lookup(env, value)
        return _resolve(v, env, depth + 1) if found else value
    if isinstance(value, str):
        stripped = value.strip()
        for fn in ("toset(", "tolist("):
            if stripped.startswith(fn) and stripped.endswith(")"):
                inner, _ = _value(stripped[len(fn):-1], 0)
                return _resolve(inner, env, depth + 1)
        if stripped.startswith("concat(") and stripped.endswith(")"):
            parts = [_resolve(v, env, depth + 1) for v in _list(stripped[len("concat("):-1])]
            if all(isinstance(pt, list) for pt in parts):
                return [x for pt in parts for x in pt]
            return value
        if "${" in value:
            whole = _INTERP.fullmatch(stripped)
            if whole:
                found, v = _lookup(env, whole.group(1))
                return _resolve(v, env, depth + 1) if found else value

            def _sub(m: re.Match) -> str:
                found, v = _lookup(env, m.group(1))
                v = _resolve(v, env, depth + 1) if found else None
                if isinstance(v, (str, int, float)) and not isinstance(v, Ref):
                    return str(v)
                raise KeyError(m.group(1))
            try:
                return _INTERP.sub(_sub, value)
            except KeyError:
                return value
        return value
    if isinstance(value, list):
        return [_resolve(v, env, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: _resolve(v, env, depth + 1) for k, v in value.items()}
    return value


def _make_env(variables: dict[str, Any], overrides: list[dict[str, Any]], locals_: dict[str, Any]) -> dict:
    """Variables (defaults, then tfvars, then module inputs) and locals resolved against them."""
    var = dict(variables)
    for o in overrides:
        for k, v in o.items():
            if k in var or not variables:      # unknown inputs still usable (undeclared vars)
                var[k] = v
            else:
                var[k] = v
    env: dict = {"var": var, "local": {}, "each": {}, "count": {}}
    loc = dict(locals_)
    for _ in range(4):                          # locals may reference vars and other locals
        loc = {k: _resolve(v, env, 0) for k, v in loc.items()}
        env["local"] = loc
    return env


def _expand(blocks: list[TfBlock], env: dict) -> list[TfBlock]:
    """Resolve every block's attributes; expand ``count`` / ``for_each`` instances."""
    out: list[TfBlock] = []
    for b in blocks:
        attrs = dict(b.attrs)
        fe = _resolve(attrs.pop("for_each", None), env)
        cnt = _resolve(attrs.pop("count", None), env)
        if isinstance(fe, (list, dict)) and not isinstance(fe, Ref):
            items = list(fe.items()) if isinstance(fe, dict) else [(v, v) for v in fe]
            for key, val in items:
                if isinstance(key, Ref) or isinstance(val, Ref):
                    out.append(TfBlock(b.type, b.name, b.line, _resolve(attrs, env), b.path)); break
                inst = dict(env); inst["each"] = {"key": key, "value": val}
                out.append(TfBlock(b.type, b.name, b.line, _resolve(attrs, inst), b.path, f'["{key}"]'))
            continue
        if isinstance(cnt, bool):
            cnt = int(cnt)
        if isinstance(cnt, (int, float)) and not isinstance(cnt, bool):
            n = int(cnt)
            for i in range(n):
                inst = dict(env); inst["count"] = {"index": i}
                out.append(TfBlock(b.type, b.name, b.line, _resolve(attrs, inst), b.path, f"[{i}]" if n > 1 else ""))
            continue
        out.append(TfBlock(b.type, b.name, b.line, _resolve(attrs, env), b.path))
    return out


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
        m = re.match(r"^([a-z][\w]*)\.([\w-]+)(?:\[[^\]]*\])?(?:\.[\w-]+(?:\[[^\]]*\])?)*$", value)
        if m:
            return m.group(1), m.group(2)
    return None


def _data_ref(value: Any) -> Optional[tuple[str, str]]:
    """``data.aws_iam_policy_document.x.json`` -> ("data.aws_iam_policy_document", "x")."""
    if isinstance(value, Ref):
        m = re.match(r"^data\.([\w-]+)\.([\w-]+)", value)
        if m:
            return f"data.{m.group(1)}", m.group(2)
    return None


def _truthy(v: Any) -> bool:
    return v is True or (isinstance(v, str) and v.lower() == "true")


def _stem(name: str) -> str:
    return re.split(r"[_-]", name, 1)[0].lower()


def _where(block: TfBlock, home: TfBlock) -> str:
    """' (in infra/iam.tf)' when evidence comes from another file of the module."""
    return f" (in {block.path})" if block.path and block.path != home.path else ""


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
    path: str = ""                  # file defining the agent resource (module scope)
    tools: list[dict] = field(default_factory=list)   # schema 1.7 tool inventory (action groups, UC functions)


# --- Databricks recognition dictionary ---------------------------------------
# The IaC analog of HIGH_AGENT_PATTERNS: keyed on resource type, not on a
# constructor call. Extending to another platform is adding rows + a detector.

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


def _detect_databricks(blocks: list[TfBlock]) -> list[IacDetection]:
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
                    f"{', '.join(sorted(privs))} on {scope} (via {ref[1]}){_where(g, ep)}"
                    + (" — catalog-wide privileges, broad reach" if wide else ""),
                ))

        # Symbol = "<resource_type>.<name>" so two resource types sharing a name in
        # one file never collide on id; the human-facing name stays the endpoint name.
        symbol = ep.address
        detections.append(IacDetection(
            id=agent_id(ep.path, symbol),
            name=display, symbol=symbol,
            confidence="high", detection_score=8,     # a deployed endpoint is not ambiguous
            evidence=evidence, frameworks=[],          # Databricks is the platform, not an agent framework
            providers=sorted(providers), integrations=["databricks"],
            capabilities=sorted(caps), controls=controls,
            platform="databricks", path=ep.path,
        ))
    return detections


# --- Amazon Bedrock recognition dictionary -----------------------------------
# Bedrock's Terraform surface is more agent-shaped than Databricks': the agent
# is a resource with an instruction, its tools are action groups pointing at
# Lambda functions, guardrails are a resource, and reach is spelled out in IAM.

RES_BR_AGENT = "aws_bedrockagent_agent"
RES_BR_ACTION_GROUP = "aws_bedrockagent_agent_action_group"
RES_BR_KB_ASSOC = "aws_bedrockagent_agent_knowledge_base_association"
RES_BR_GUARDRAIL = "aws_bedrock_guardrail"
RES_BR_LOGGING = "aws_bedrock_model_invocation_logging_configuration"
RES_IAM_ROLE = "aws_iam_role"
RES_IAM_ROLE_POLICY = "aws_iam_role_policy"
RES_IAM_POLICY = "aws_iam_policy"
RES_IAM_ATTACH = "aws_iam_role_policy_attachment"
RES_LAMBDA = "aws_lambda_function"

BEDROCK_RESOURCES = {
    RES_BR_AGENT: "agent",              # a Bedrock agent IS a deployed agent
    RES_BR_ACTION_GROUP: "tools",       # literal tool bindings (Lambda / return-control / code interpreter)
    RES_BR_KB_ASSOC: "data_source",     # RAG knowledge base attached to the agent
    RES_BR_GUARDRAIL: "control",
    RES_BR_LOGGING: "control",          # account-wide model invocation logging
    RES_IAM_ROLE_POLICY: "reach",       # exactly which actions on which resources
    RES_IAM_ATTACH: "reach",
}

# Foundation-model id prefix -> Stoa provider id (models Bedrock hosts for other vendors).
_FM_VENDOR = {"anthropic": "anthropic", "cohere": "cohere", "mistral": "mistral"}

_DB_SERVICES = {"dynamodb", "rds", "rds-data", "redshift", "redshift-data", "athena",
                "timestream", "neptune-db", "docdb", "docdb-elastic", "qldb", "keyspaces"}
_MGMT_SERVICES = {"iam", "sts", "ec2", "cloudformation", "organizations", "eks", "ecs",
                  "autoscaling", "route53", "acm", "kms"}
_SEARCH_SERVICES = {"aoss", "es", "opensearch", "kendra"}
_WRITE_VERBS = ("put", "update", "delete", "batchwrite", "execute", "modify", "create",
                "write", "transactwrite", "restore", "import")


def _caps_for_action(action: str) -> set[str]:
    """IAM action -> Stoa capability ids. Conservative: unknown services map to nothing."""
    if action in ("*", "*:*"):
        return {"cloud_resource_access"}
    svc, _, verb = action.partition(":")
    svc, verb = svc.lower(), verb.lower()
    wild = verb in ("", "*")
    if svc in _DB_SERVICES:
        return {"database_read"} | ({"database_write"} if wild or verb.startswith(_WRITE_VERBS) else set())
    if svc == "s3":
        w = wild or verb.startswith(("put", "delete", "create", "abort", "restore", "replicate"))
        return {"filesystem_read"} | ({"filesystem_write"} if w else set())
    if svc == "ses":
        return {"email_send"} if wild or verb.startswith("send") else set()
    if svc == "sns":
        return {"messaging"} if wild or verb.startswith("publish") else set()
    if svc == "sqs":
        return {"queue_access"} if wild or verb.startswith(("send", "receive", "delete")) else set()
    if svc == "lambda":
        return {"tool_calling"} if wild or verb.startswith("invoke") else set()
    if svc == "states":
        return {"tool_calling"} if wild or verb.startswith("start") else set()
    if svc == "ssm":
        return {"shell_execution"} if wild or verb.startswith(("sendcommand", "startsession")) else set()
    if svc == "codecommit":
        return {"source_control"}
    if svc in _SEARCH_SERVICES:
        return {"vector_search"}
    if svc in _MGMT_SERVICES:
        if wild or not verb.startswith(("describe", "get", "list", "decrypt", "encrypt", "generatedatakey")):
            if not (svc == "iam" and verb == "passrole"):
                return {"cloud_resource_access"}
    return set()


_MANAGED_POLICY_CAPS = {
    "AdministratorAccess": {"cloud_resource_access"},
    "PowerUserAccess": {"cloud_resource_access"},
    "AmazonDynamoDBFullAccess": {"database_read", "database_write"},
    "AmazonDynamoDBReadOnlyAccess": {"database_read"},
    "AmazonRDSFullAccess": {"database_read", "database_write"},
    "AmazonRDSDataFullAccess": {"database_read", "database_write"},
    "AmazonRDSReadOnlyAccess": {"database_read"},
    "AmazonRedshiftFullAccess": {"database_read", "database_write"},
    "AmazonS3FullAccess": {"filesystem_read", "filesystem_write"},
    "AmazonS3ReadOnlyAccess": {"filesystem_read"},
    "AmazonSESFullAccess": {"email_send"},
    "AmazonSNSFullAccess": {"messaging"},
    "AmazonSQSFullAccess": {"queue_access"},
    "AWSLambda_FullAccess": {"tool_calling"},
    "AWSLambdaRole": {"tool_calling"},
}


def _policy_from_data(block: TfBlock) -> dict:
    """``data "aws_iam_policy_document"`` statements -> the JSON policy shape."""
    statements = []
    for st in _as_list(block.attrs.get("statement")):
        if isinstance(st, dict):
            statements.append({
                "Effect": _lit(st.get("effect")) or "Allow",
                "Action": _as_list(st.get("actions")),
                "Resource": _as_list(st.get("resources")),
            })
    return {"Statement": statements}


def _policy_doc(value: Any, blocks: Optional[list[TfBlock]] = None) -> Optional[dict]:
    """An IAM policy document from ``jsonencode({...})``, a JSON string, a heredoc,
    or a ``data.aws_iam_policy_document`` defined in the module.

    Any other reference (``var.policy``, a data source from elsewhere) is
    unresolved and returns None — never guessed.
    """
    dref = _data_ref(value)
    if dref and blocks is not None and dref[0] == "data.aws_iam_policy_document":
        blk = next((b for b in blocks if (b.type, b.name) == dref), None)
        return _policy_from_data(blk) if blk else None
    text = _lit(value)
    if text is None:
        return None
    text = text.strip()
    if text.startswith("jsonencode("):
        inner = text[len("jsonencode("):-1]
        i = _skip(inner, 0)
        if i < len(inner) and inner[i] == "{":
            doc, _ = _value(inner, i)
            return doc if isinstance(doc, dict) else None
        return None
    try:
        doc = json.loads(text)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def _get(d: dict, key: str) -> Any:
    """Case-insensitive key lookup (``Statement`` / ``statement``)."""
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == key.lower():
            return v
    return None


def _label(resources: list) -> str:
    items = [str(r) for r in resources if isinstance(r, str)]
    if not items or items == ["*"]:
        return "all resources" if items else "unresolved resources"
    shown = ", ".join(items[:2]) + (f" (+{len(items) - 2} more)" if len(items) > 2 else "")
    return shown


def _doc_reach(doc: dict) -> Iterable[tuple[set[str], set[str], list, bool]]:
    """Per Allow statement: (capabilities, actions, resources, wildcard?)."""
    for st in _as_list(_get(doc, "Statement")):
        if not isinstance(st, dict):
            continue
        effect = _lit(_get(st, "Effect")) or "Allow"
        if effect.lower() != "allow":
            continue
        actions = {str(a) for a in _as_list(_get(st, "Action")) if isinstance(a, str)}
        if not actions:
            continue
        caps: set[str] = set()
        for act in actions:
            caps |= _caps_for_action(act)
        wildcard = any(a in ("*", "*:*") or a.endswith(":*") for a in actions)
        yield caps, actions, _as_list(_get(st, "Resource")), wildcard


def _role_name(value: Any) -> Optional[str]:
    """``aws_iam_role.x.arn`` / ``.id`` / ``.name`` -> ``x``; None if unresolved."""
    ref = _ref(value)
    return ref[1] if ref and ref[0] == RES_IAM_ROLE else None


def _role_reach(
    role: str, blocks: list[TfBlock], home: TfBlock, via: str,
) -> tuple[set[str], list[Evidence], set[str]]:
    """Capabilities, evidence, and IAM services granted to ``role`` in this module."""
    caps: set[str] = set()
    evidence: list[Evidence] = []
    services: set[str] = set()

    def _apply(doc: Optional[dict], block: TfBlock) -> None:
        if doc is None:
            evidence.append(Evidence(
                "IAC_IAM_POLICY", block.line,
                f"policy on role {role} is not resolvable in this module — reach unresolved"
                f" ({via}){_where(block, home)}"))
            return
        for st_caps, actions, resources, wildcard in _doc_reach(doc):
            services.update(a.partition(":")[0].lower() for a in actions)
            if not st_caps:
                continue          # bedrock:InvokeModel etc. — the agent's own plumbing
            caps.update(st_caps)
            evidence.append(Evidence(
                "IAC_IAM_POLICY", block.line,
                f"{', '.join(sorted(actions))} on {_label(resources)} ({via}){_where(block, home)}"
                + (" — wildcard actions, broad reach" if wildcard else ""),
            ))

    for p in blocks:
        if p.type == RES_IAM_ROLE_POLICY and _role_name(p.attrs.get("role")) == role:
            _apply(_policy_doc(p.attrs.get("policy"), blocks), p)
        elif p.type == RES_IAM_ATTACH and _role_name(p.attrs.get("role")) == role:
            arn = p.attrs.get("policy_arn")
            lit = _lit(arn)
            if lit and ":iam::aws:policy/" in lit:
                name = lit.rsplit("/", 1)[1]
                managed = _MANAGED_POLICY_CAPS.get(name)
                if managed:
                    caps.update(managed)
                    evidence.append(Evidence(
                        "IAC_IAM_POLICY", p.line,
                        f"AWS managed policy {name} attached ({via}){_where(p, home)}"
                        + (" — full-access policy, broad reach" if "Full" in name or "Administrator" in name else ""),
                    ))
                else:
                    evidence.append(Evidence(
                        "IAC_IAM_POLICY", p.line,
                        f"AWS managed policy {name} attached ({via}) — not in Stoa's dictionary, reach unknown"
                        f"{_where(p, home)}"))
                continue
            ref = _ref(arn)
            if ref and ref[0] == RES_IAM_POLICY:
                pol = next((b for b in blocks if b.type == RES_IAM_POLICY and b.name == ref[1]), None)
                _apply(_policy_doc(pol.attrs.get("policy"), blocks) if pol else None, pol or p)
            else:
                _apply(None, p)
    if not evidence and not caps:
        evidence.append(Evidence(
            "IAC_IAM_POLICY", home.line,
            f"no policy for role {role} is defined in this module ({via}) — reach unresolved"))
    return caps, evidence, services


def _detect_bedrock(blocks: list[TfBlock]) -> list[IacDetection]:
    agents = [b for b in blocks if b.type == RES_BR_AGENT]
    if not agents:
        return []
    by_key = {(b.type, b.name): b for b in blocks}
    logging = [b for b in blocks if b.type == RES_BR_LOGGING]

    detections = []
    for ag in agents:
        a = ag.attrs
        display = _lit(a.get("agent_name")) or ag.name
        fm = _lit(a.get("foundation_model"))
        evidence = [Evidence(
            "AGENT_IAC_BEDROCK_AGENT", ag.line,
            f"Amazon Bedrock agent '{display}' — a deployed agent"
            + (f", on foundation model {fm}" if fm else ""),
        )]
        providers = {"bedrock"}
        if fm:
            vendor = next((_FM_VENDOR[seg] for seg in fm.lower().split(".") if seg in _FM_VENDOR), None)
            if vendor:
                providers.add(vendor)
                evidence.append(Evidence("IAC_FOUNDATION_MODEL", ag.line,
                                         f"foundation model by {vendor}, served inside Bedrock"))
        caps: set[str] = set()
        controls: set[str] = set()
        integrations = {"aws"}

        # controls: a guardrail attached to the agent; account-wide invocation logging
        for gc in _as_list(a.get("guardrail_configuration")):
            if not isinstance(gc, dict) or gc.get("guardrail_identifier") is None:
                continue
            controls.add("validation")
            gid = gc.get("guardrail_identifier")
            desc = "Bedrock guardrail attached"
            ref = _ref(gid)
            gb = by_key.get((RES_BR_GUARDRAIL, ref[1])) if ref and ref[0] == RES_BR_GUARDRAIL else None
            if gb:
                policies = [k.replace("_policy_config", "").replace("_", " ")
                            for k in ("content_policy_config", "sensitive_information_policy_config",
                                      "topic_policy_config", "word_policy_config",
                                      "contextual_grounding_policy_config") if gb.attrs.get(k)]
                desc += f" ({ref[1]}: {', '.join(policies)} policies){_where(gb, ag)}" if policies else f" ({ref[1]})"
            elif _lit(gid):
                desc += f" ({gid})"
            evidence.append(Evidence("IAC_CONTROL_GUARDRAIL", ag.line, desc))
        if logging:
            controls.add("observability")
            evidence.append(Evidence(
                "IAC_CONTROL_OBSERVABILITY", logging[0].line,
                f"model invocation logging configured, account-wide{_where(logging[0], ag)}"))

        # tools: action groups bound to this agent
        lambda_roles: list[tuple[str, str]] = []
        tool_records: list[dict] = []
        for grp in blocks:
            if grp.type != RES_BR_ACTION_GROUP or _ref(grp.attrs.get("agent_id")) != (RES_BR_AGENT, ag.name):
                continue
            gname = _lit(grp.attrs.get("action_group_name")) or grp.name
            sig = _lit(grp.attrs.get("parent_action_group_signature"))
            if sig == "AMAZON.CodeInterpreter":
                caps.add("code_execution")
                evidence.append(Evidence(
                    "IAC_TOOL_BINDING", grp.line,
                    f"code interpreter enabled ('{gname}') — the agent runs generated code{_where(grp, ag)}"))
                continue
            if sig == "AMAZON.UserInput":
                evidence.append(Evidence("IAC_TOOL_BINDING", grp.line,
                                         f"'{gname}' lets the agent ask the user for missing input{_where(grp, ag)}"))
                continue
            caps.add("tool_calling")
            ex = _one(grp.attrs.get("action_group_executor")) or {}
            lam = _ref(ex.get("lambda"))
            if lam and lam[0] == RES_LAMBDA:
                desc = f"action group '{gname}' executes in Lambda {lam[1]}"
                fn = by_key.get((RES_LAMBDA, lam[1]))
                role = _role_name(fn.attrs.get("role")) if fn else None
                if role:
                    lambda_roles.append((role, lam[1]))
                elif fn is None:
                    desc += " (function not defined in this module)"
            elif _lit(ex.get("custom_control")) == "RETURN_CONTROL":
                desc = f"action group '{gname}' returns control to the caller (tools run in application code)"
            else:
                desc = f"action group '{gname}' (executor unresolved)"
            fns = [_lit(f.get("name")) for m in _as_list((_one(grp.attrs.get("function_schema")) or {}).get("member_functions"))
                   if isinstance(m, dict) for f in _as_list(m.get("functions")) if isinstance(f, dict) and _lit(f.get("name"))]
            if fns:
                desc += f": {', '.join(fns)}"
            evidence.append(Evidence("IAC_TOOL_BINDING", grp.line, desc + _where(grp, ag)))
            for fn_name in fns:
                params = [{"name": _lit(pp.get("map_block_key"))} for m in _as_list((_one(grp.attrs.get("function_schema")) or {}).get("member_functions"))
                          if isinstance(m, dict) for f in _as_list(m.get("functions"))
                          if isinstance(f, dict) and _lit(f.get("name")) == fn_name
                          for pp in _as_list(f.get("parameters")) if isinstance(pp, dict) and _lit(pp.get("map_block_key"))]
                tool_records.append({
                    "name": fn_name, "path": grp.path, "line": grp.line, "kind": "bedrock_action_group",
                    "params": params, "capabilities": [], "integrations": [], "high_impact": False,
                    "money_action": bool(re.search(r"(?i)refund|payout|transfer|charge|payment|reissue|wire|settle|waive", fn_name)),
                    "guards": [], "retry": None, "idempotency_key": False, "resolved": False,
                    "executor": (lam[1] if lam and lam[0] == RES_LAMBDA else None),
                })

        # RAG: knowledge bases associated with the agent
        for kb in blocks:
            if kb.type == RES_BR_KB_ASSOC and _ref(kb.attrs.get("agent_id")) == (RES_BR_AGENT, ag.name):
                caps.add("vector_search")
                kref = _ref(kb.attrs.get("knowledge_base_id"))
                evidence.append(Evidence(
                    "IAC_KNOWLEDGE_BASE", kb.line,
                    f"knowledge base {kref[1] if kref else _lit(kb.attrs.get('knowledge_base_id')) or 'unresolved'} attached"
                    f"{_where(kb, ag)}"))

        # reach: the agent's own role, then each tool Lambda's role (where the tools act)
        role_value = a.get("agent_resource_role_arn")
        role = _role_name(role_value)
        if role:
            c, ev, svcs = _role_reach(role, blocks, ag, via="agent role")
            caps |= c; evidence += ev
            if "ses" in svcs:
                integrations.add("ses")
        elif role_value is not None:
            evidence.append(Evidence("IAC_IAM_POLICY", ag.line,
                                     "agent role is not defined in this module — reach unresolved"))
        for role, fn in lambda_roles:
            c, ev, svcs = _role_reach(role, blocks, ag, via=f"Lambda {fn}'s role")
            caps |= c; evidence += ev
            if "ses" in svcs:
                integrations.add("ses")
            for rec in tool_records:                       # the tool reaches what its Lambda's role allows
                if rec.get("executor") == fn:
                    rec["capabilities"] = sorted(set(rec["capabilities"]) | c)
                    rec["high_impact"] = bool(set(rec["capabilities"]) & {
                        "cloud_resource_access", "code_execution", "database_write", "email_send",
                        "filesystem_write", "messaging", "payment_access", "shell_execution", "source_control"})
        for rec in tool_records:
            rec.pop("executor", None)

        symbol = ag.address
        detections.append(IacDetection(
            id=agent_id(ag.path, symbol),
            name=display, symbol=symbol,
            confidence="high", detection_score=8,
            evidence=evidence, frameworks=[],
            providers=sorted(providers), integrations=sorted(integrations),
            capabilities=sorted(caps), controls=controls,
            platform="bedrock", path=ag.path, tools=tool_records,
        ))
    return detections


# --- Google recognition dictionary (Dialogflow CX / Vertex AI Agent Builder) --
# The GUI-built agent: a Dialogflow CX agent is the agent, its webhooks are
# the tools (followed to the Cloud Function / Cloud Run service, its service
# account, and that account's IAM roles), security settings and logging are
# the controls, knowledge connectors and Discovery Engine data stores the RAG.

RES_CX_AGENT = "google_dialogflow_cx_agent"
RES_CX_WEBHOOK = "google_dialogflow_cx_webhook"
RES_CX_SECURITY = "google_dialogflow_cx_security_settings"
RES_CX_GENERATIVE = "google_dialogflow_cx_generative_settings"
RES_CX_FLOW = "google_dialogflow_cx_flow"
RES_CX_PAGE = "google_dialogflow_cx_page"
RES_CX_TOOL = "google_dialogflow_cx_tool"
RES_DE_CHAT = "google_discovery_engine_chat_engine"
RES_DE_DATASTORE = "google_discovery_engine_data_store"
RES_GCF2 = "google_cloudfunctions2_function"
RES_GCF1 = "google_cloudfunctions_function"
RES_RUN2 = "google_cloud_run_v2_service"
RES_RUN1 = "google_cloud_run_service"
RES_GSA = "google_service_account"

GOOGLE_RESOURCES = {
    RES_CX_AGENT: "agent",
    RES_CX_WEBHOOK: "tools",
    RES_CX_TOOL: "tools",
    RES_CX_SECURITY: "control",
    RES_CX_GENERATIVE: "control",
    RES_CX_FLOW: "data_source",           # knowledge connectors
    RES_DE_CHAT: "agent",                 # unless it links an existing CX agent
    RES_DE_DATASTORE: "data_source",
}

_GCP_RW = {"database_read", "database_write"}
_GCP_ROLE_CAPS: dict[str, set[str]] = {
    "roles/owner": {"cloud_resource_access"}, "roles/editor": {"cloud_resource_access"},
    "roles/resourcemanager.projectIamAdmin": {"cloud_resource_access"},
    "roles/iam.serviceAccountTokenCreator": {"cloud_resource_access"},
    "roles/iam.serviceAccountAdmin": {"cloud_resource_access"}, "roles/compute.admin": {"cloud_resource_access"},
    "roles/bigquery.dataViewer": {"database_read"}, "roles/bigquery.jobUser": {"database_read"},
    "roles/bigquery.user": {"database_read"}, "roles/bigquery.dataEditor": _GCP_RW,
    "roles/bigquery.dataOwner": _GCP_RW, "roles/bigquery.admin": _GCP_RW,
    "roles/datastore.viewer": {"database_read"}, "roles/datastore.user": _GCP_RW, "roles/datastore.owner": _GCP_RW,
    "roles/cloudsql.client": {"database_read"}, "roles/cloudsql.editor": _GCP_RW, "roles/cloudsql.admin": _GCP_RW,
    "roles/spanner.databaseReader": {"database_read"}, "roles/spanner.databaseUser": _GCP_RW, "roles/spanner.admin": _GCP_RW,
    "roles/storage.objectViewer": {"filesystem_read"}, "roles/storage.objectCreator": {"filesystem_write"},
    "roles/storage.objectUser": {"filesystem_read", "filesystem_write"},
    "roles/storage.objectAdmin": {"filesystem_read", "filesystem_write"},
    "roles/storage.admin": {"filesystem_read", "filesystem_write"},
    "roles/pubsub.publisher": {"messaging"}, "roles/pubsub.editor": {"messaging"}, "roles/pubsub.admin": {"messaging"},
    "roles/pubsub.subscriber": {"queue_access"},
    "roles/run.invoker": {"tool_calling"}, "roles/cloudfunctions.invoker": {"tool_calling"},
    "roles/workflows.invoker": {"tool_calling"},
    "roles/discoveryengine.viewer": {"vector_search"}, "roles/discoveryengine.editor": {"vector_search"},
}
_GCP_PRIMITIVE = {"roles/owner", "roles/editor", "roles/viewer"}
_GSA_REF = re.compile(r"google_service_account\.([\w-]+)\.(?:email|member|name|id)")
_EXEC_REF = re.compile(r"(google_cloudfunctions2_function|google_cloudfunctions_function|"
                       r"google_cloud_run_v2_service|google_cloud_run_service)\.([\w-]+)")
_CX_AGENT_REF = re.compile(r"google_dialogflow_cx_agent\.([\w-]+)")


def _sa_of_executor(fn: TfBlock) -> Optional[str]:
    """Service-account resource name a Cloud Function / Cloud Run service runs as."""
    a = fn.attrs
    if fn.type == RES_GCF2:
        v = (_one(a.get("service_config")) or {}).get("service_account_email")
    elif fn.type == RES_GCF1:
        v = a.get("service_account_email")
    elif fn.type == RES_RUN2:
        v = (_one(a.get("template")) or {}).get("service_account")
    else:
        v = (_one((_one(a.get("template")) or {}).get("spec")) or {}).get("service_account_name")
    m = _GSA_REF.search(str(v)) if v is not None else None
    return m.group(1) if m else None


def _sa_reach(sa: str, blocks: list[TfBlock], home: TfBlock, via: str) -> tuple[set[str], list[Evidence], set[str]]:
    """Capabilities granted to a service account by ``google_*_iam_member/binding`` blocks."""
    caps: set[str] = set()
    evidence: list[Evidence] = []
    services: set[str] = set()
    for b in blocks:
        if not (b.type.startswith("google_") and (b.type.endswith("_iam_member") or b.type.endswith("_iam_binding"))):
            continue
        members = _as_list(b.attrs.get("member")) + _as_list(b.attrs.get("members"))
        if not any(_GSA_REF.search(str(m)) and _GSA_REF.search(str(m)).group(1) == sa for m in members):
            continue
        role = _lit(b.attrs.get("role"))
        if role is None:
            evidence.append(Evidence("IAC_IAM_POLICY", b.line,
                                     f"role unresolved on {b.type} ({via}){_where(b, home)}"))
            continue
        scope_kind = b.type[len("google_"):].rsplit("_iam_", 1)[0].replace("_", " ")
        scope_name = next((_lit(b.attrs[k]) for k in ("dataset_id", "bucket", "topic", "name", "project", "instance")
                           if _lit(b.attrs.get(k))), None)
        scope = f"{scope_kind} {scope_name}" if scope_name else scope_kind
        role_caps = _GCP_ROLE_CAPS.get(role, set())
        services.add(role.split("/", 1)[-1].split(".", 1)[0])
        caps |= role_caps
        evidence.append(Evidence(
            "IAC_IAM_POLICY", b.line,
            f"{role} on {scope} ({via}){_where(b, home)}"
            + (" — primitive role, broad reach" if role in _GCP_PRIMITIVE else "")
            + ("" if role_caps or role in _GCP_PRIMITIVE else " — not in Stoa's dictionary, reach unknown"),
        ))
    if not evidence:
        evidence.append(Evidence("IAC_IAM_POLICY", home.line,
                                 f"no IAM role for service account {sa} is defined in this module ({via}) — reach unresolved"))
    return caps, evidence, services


def _store_label(value: Any, by_key: dict) -> str:
    """A data store's literal id, or the data store block it references, or the reference."""
    lit = _lit(value)
    if lit:
        return lit
    if isinstance(value, Ref):
        m = re.search(r"google_discovery_engine_data_store\.([\w-]+)", value)
        blk = by_key.get((RES_DE_DATASTORE, m.group(1))) if m else None
        if blk:
            return _lit(blk.attrs.get("data_store_id")) or _lit(blk.attrs.get("display_name")) or blk.name
        return f"{value} (reference)"
    return "unresolved data store"


def _cx_agent_of(block: TfBlock, by_key: dict, depth: int = 0) -> Optional[str]:
    """Follow ``parent`` / ``agent`` references up to the owning CX agent name."""
    if depth > 3:
        return None
    for key in ("parent", "agent"):
        v = block.attrs.get(key)
        if v is None:
            continue
        m = _CX_AGENT_REF.search(str(v))
        if m:
            return m.group(1)
        ref = _ref(v)
        if ref and ref[0] in (RES_CX_FLOW, RES_CX_PAGE) and ref in by_key:
            return _cx_agent_of(by_key[ref], by_key, depth + 1)
    return None


def _detect_google(blocks: list[TfBlock]) -> list[IacDetection]:
    cx_agents = [b for b in blocks if b.type == RES_CX_AGENT]
    chat_engines = [b for b in blocks if b.type == RES_DE_CHAT]
    if not cx_agents and not chat_engines:
        return []
    by_key = {(b.type, b.name): b for b in blocks}
    detections = []

    for ag in cx_agents:
        a = ag.attrs
        display = _lit(a.get("display_name")) or ag.name
        evidence = [Evidence("AGENT_IAC_DIALOGFLOW_AGENT", ag.line,
                             f"Dialogflow CX agent '{display}' — a deployed conversational agent"
                             + (f" in {_lit(a.get('location'))}" if _lit(a.get("location")) else ""))]
        caps: set[str] = set()
        controls: set[str] = set()
        providers = {"google"}
        integrations = {"gcp"}

        # controls: security settings (redaction / retention), logging, generative safety
        sec = a.get("security_settings")
        if sec is not None:
            ref = _ref(sec)
            sb = by_key.get((RES_CX_SECURITY, ref[1])) if ref and ref[0] == RES_CX_SECURITY else None
            if sb:
                st = sb.attrs
                parts = []
                if _lit(st.get("redaction_strategy")):
                    controls.add("validation")
                    parts.append(f"redaction {st['redaction_strategy']}"
                                 + (f" on {', '.join(str(x) for x in _as_list(st.get('redaction_scope')))}"
                                    if st.get("redaction_scope") else ""))
                if st.get("retention_window_days") is not None:
                    parts.append(f"retention {st['retention_window_days']} days")
                elif _lit(st.get("retention_strategy")):
                    parts.append(f"retention {st['retention_strategy']}")
                ins = _one(st.get("insights_export_settings"))
                if ins and _truthy(ins.get("enable_insights_export")):
                    controls.add("observability")
                    parts.append("insights export")
                evidence.append(Evidence("IAC_CONTROL_GUARDRAIL", ag.line,
                                         f"security settings {sb.name}: {', '.join(parts) or 'attached'}{_where(sb, ag)}"))
            elif _lit(sec):
                controls.add("validation")
                evidence.append(Evidence("IAC_CONTROL_GUARDRAIL", ag.line, f"security settings attached ({sec})"))
        adv = _one(a.get("advanced_settings")) or {}
        logs = _one(adv.get("logging_settings")) or {}
        if _truthy(a.get("enable_stackdriver_logging")) or _truthy(logs.get("enable_stackdriver_logging")) \
                or _truthy(logs.get("enable_interaction_logging")):
            controls.add("observability")
            evidence.append(Evidence("IAC_CONTROL_OBSERVABILITY", ag.line,
                                     "Cloud Logging / interaction logging enabled on the agent"))
        for g in blocks:
            if g.type != RES_CX_GENERATIVE or _cx_agent_of(g, by_key) != ag.name:
                continue
            safety = _one(g.attrs.get("generative_safety_settings"))
            if safety and safety.get("banned_phrases"):
                controls.add("validation")
                evidence.append(Evidence("IAC_CONTROL_GUARDRAIL", g.line,
                                         f"generative safety settings: banned phrases{_where(g, ag)}"))
            llm = _one(g.attrs.get("llm_model_settings"))
            if llm and _lit(llm.get("model")):
                evidence.append(Evidence("IAC_FOUNDATION_MODEL", g.line,
                                         f"generative model {llm['model']} (Google){_where(g, ag)}"))
        gab = _one(a.get("gen_app_builder_settings"))
        if gab and gab.get("engine") is not None:
            caps.add("vector_search")
            evidence.append(Evidence("IAC_KNOWLEDGE_BASE", ag.line,
                                     "Vertex AI Agent Builder engine linked (generative answers over a data store)"))

        # tools: webhooks -> executor -> service account -> IAM roles
        for wh in blocks:
            if wh.type != RES_CX_WEBHOOK or _cx_agent_of(wh, by_key) != ag.name:
                continue
            caps.add("tool_calling")
            wname = _lit(wh.attrs.get("display_name")) or wh.name
            gws = _one(wh.attrs.get("generic_web_service")) or {}
            uri = gws.get("uri")
            m = _EXEC_REF.search(str(uri)) if uri is not None else None
            fn = by_key.get((m.group(1), m.group(2))) if m else None
            if fn:
                sa = _sa_of_executor(fn)
                kind = "Cloud Run service" if "run" in fn.type else "Cloud Function"
                evidence.append(Evidence("IAC_TOOL_BINDING", wh.line,
                                         f"webhook '{wname}' calls {kind} {fn.name}"
                                         + (f" (service account {sa})" if sa else " (service account unresolved)")
                                         + _where(wh, ag)))
                if sa:
                    c, ev, svcs = _sa_reach(sa, blocks, ag, via=f"{kind} {fn.name}'s service account")
                    caps |= c; evidence += ev
                    if "bigquery" in svcs:
                        integrations.add("bigquery")
            elif _lit(uri):
                caps.add("external_http")
                host = re.sub(r"^https?://", "", uri).split("/", 1)[0]
                evidence.append(Evidence("IAC_TOOL_BINDING", wh.line,
                                         f"webhook '{wname}' calls external service {host}{_where(wh, ag)}"))
            else:
                caps.add("external_http")
                evidence.append(Evidence("IAC_TOOL_BINDING", wh.line,
                                         f"webhook '{wname}' (target unresolved){_where(wh, ag)}"))
        for tool in blocks:
            if tool.type != RES_CX_TOOL or _cx_agent_of(tool, by_key) != ag.name:
                continue
            tname = _lit(tool.attrs.get("display_name")) or tool.name
            if tool.attrs.get("data_store_spec") is not None:
                caps.add("vector_search")
                evidence.append(Evidence("IAC_KNOWLEDGE_BASE", tool.line, f"tool '{tname}' searches a data store{_where(tool, ag)}"))
            if tool.attrs.get("open_api_spec") is not None:
                caps |= {"tool_calling", "external_http"}
                evidence.append(Evidence("IAC_TOOL_BINDING", tool.line, f"tool '{tname}' calls an OpenAPI service{_where(tool, ag)}"))
            if tool.attrs.get("function_spec") is not None:
                caps.add("tool_calling")
                evidence.append(Evidence("IAC_TOOL_BINDING", tool.line,
                                         f"tool '{tname}' is a client-side function (runs in application code){_where(tool, ag)}"))

        # RAG: knowledge connectors on flows / pages, linked Discovery Engine chat engines
        for fl in blocks:
            if fl.type not in (RES_CX_FLOW, RES_CX_PAGE) or _cx_agent_of(fl, by_key) != ag.name:
                continue
            kc = _one(fl.attrs.get("knowledge_connector_settings"))
            if kc:
                stores = [_store_label(d.get("data_store"), by_key)
                          for d in _as_list(kc.get("data_store_connections")) if isinstance(d, dict)]
                caps.add("vector_search")
                evidence.append(Evidence("IAC_KNOWLEDGE_BASE", fl.line,
                                         f"knowledge connector on {fl.type.rsplit('_', 1)[1]} '{fl.name}'"
                                         + (f": {', '.join(stores)}" if stores else "") + _where(fl, ag)))
        for ce in chat_engines:
            cfg = _one(ce.attrs.get("chat_engine_config")) or {}
            link = cfg.get("dialogflow_agent_to_link")
            m = _CX_AGENT_REF.search(str(link)) if link is not None else None
            if m and m.group(1) == ag.name:
                caps.add("vector_search")
                stores = [_store_label(x, by_key) for x in _as_list(ce.attrs.get("data_store_ids"))]
                evidence.append(Evidence("IAC_KNOWLEDGE_BASE", ce.line,
                                         f"Discovery Engine chat engine {ce.name} linked"
                                         + (f" over {', '.join(stores)}" if stores else "") + _where(ce, ag)))

        detections.append(IacDetection(
            id=agent_id(ag.path, ag.address), name=display, symbol=ag.address,
            confidence="high", detection_score=8, evidence=evidence, frameworks=[],
            providers=sorted(providers), integrations=sorted(integrations),
            capabilities=sorted(caps), controls=controls, platform="dialogflow_cx", path=ag.path,
        ))

    # a chat engine that creates its own agent is an agent; one that links a CX agent was attributed above
    for ce in chat_engines:
        cfg = _one(ce.attrs.get("chat_engine_config")) or {}
        if cfg.get("dialogflow_agent_to_link") is not None:
            continue
        display = _lit(ce.attrs.get("display_name")) or ce.name
        stores = [_store_label(x, by_key) for x in _as_list(ce.attrs.get("data_store_ids"))]
        evidence = [Evidence("AGENT_IAC_CHAT_ENGINE", ce.line,
                             f"Vertex AI Agent Builder chat engine '{display}' — a deployed conversational agent")]
        caps = set()
        if stores:
            caps.add("vector_search")
            evidence.append(Evidence("IAC_KNOWLEDGE_BASE", ce.line, f"answers over data stores: {', '.join(stores)}"))
        detections.append(IacDetection(
            id=agent_id(ce.path, ce.address), name=display, symbol=ce.address,
            confidence="high", detection_score=8, evidence=evidence, frameworks=[],
            providers=["google"], integrations=["gcp"], capabilities=sorted(caps), controls=set(),
            platform="vertex_ai_agent_builder", path=ce.path,
        ))
    return detections


# --- module instantiation ------------------------------------------------------

_CALL_META = {"source", "version", "providers", "depends_on", "count", "for_each"}
_TFVARS_PRIORITY = ("terraform.tfvars", "terraform.tfvars.json")


@dataclass
class TfModule:
    dir: str
    files: list[TfFile] = field(default_factory=list)
    tfvars: dict[str, Any] = field(default_factory=dict)

    @property
    def blocks(self) -> list[TfBlock]:
        return [b for f in self.files for b in f.blocks]

    @property
    def variables(self) -> dict[str, Any]:
        return {k: v for f in self.files for k, v in f.variables.items()}

    @property
    def locals(self) -> dict[str, Any]:
        return {k: v for f in self.files for k, v in f.locals.items()}

    @property
    def module_calls(self) -> list[TfBlock]:
        return [c for f in self.files for c in f.module_calls]


def _parse_module(dir_: str, files: Iterable[tuple[str, str]]) -> TfModule:
    mod = TfModule(dir_)
    tfvars_files = []
    for path, content in sorted(files):
        base = path.rsplit("/", 1)[-1]
        if base.endswith(".tfvars"):
            if base in _TFVARS_PRIORITY or base.endswith(".auto.tfvars"):
                tfvars_files.append((base, content))
        else:
            mod.files.append(parse_tf(content, path))
    for base, content in sorted(tfvars_files, key=lambda t: (t[0] not in _TFVARS_PRIORITY, t[0])):
        mod.tfvars.update(_body(content))
    return mod


def _norm(dir_: str, source: str) -> str:
    parts = [p for p in (dir_.split("/") if dir_ else [])]
    for seg in source.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
        else:
            parts.append(seg)
    return "/".join(parts)


def _run_detectors(blocks: list[TfBlock]) -> list[IacDetection]:
    return _detect_databricks(blocks) + _detect_bedrock(blocks) + _detect_google(blocks)


def _detect_instance(
    mod: TfModule, env: dict, prefix: str, call: Optional[TfBlock],
    modules: dict[str, TfModule], depth: int,
) -> list[IacDetection]:
    blocks = _expand(mod.blocks, env)
    dets = _run_detectors(blocks)
    for d in dets:
        if prefix:
            d.symbol = prefix + d.symbol
            d.id = agent_id(d.path, d.symbol)
        if call is not None:
            d.evidence.append(Evidence(
                "IAC_MODULE_CALL", call.line,
                f'instance of module "{call.name}" called from {call.path}:{call.line}'))
    if depth >= 4:
        return dets
    for c in mod.module_calls:
        src = _lit(_resolve(c.attrs.get("source"), env))
        if not src or not src.startswith("."):
            continue
        target = modules.get(_norm(mod.dir, src))
        if target is None:
            continue
        inputs = {k: _resolve(v, env) for k, v in c.attrs.items() if k not in _CALL_META}
        child_env = _make_env(target.variables, [inputs], target.locals)
        dets += _detect_instance(target, child_env, f"{prefix}module.{c.name}.", c, modules, depth + 1)
    return dets


def detect_iac_tree(dirs: dict[str, Iterable[tuple[str, str]]]) -> list[IacDetection]:
    """Agent candidates for a whole tree of Terraform directories.

    ``dirs`` maps a directory (repository-relative, "" for the root) to its
    ``(relative_path, content)`` files (``.tf`` and ``.tfvars``). Directories
    used as the ``source`` of a local module call are detected once per call,
    with the call's inputs; every other directory is a root module.
    """
    modules = {d: _parse_module(d, files) for d, files in dirs.items()}
    used_as_source: set[str] = set()
    for mod in modules.values():
        env = _make_env(mod.variables, [mod.tfvars], mod.locals)
        for c in mod.module_calls:
            src = _lit(_resolve(c.attrs.get("source"), env))
            if src and src.startswith(".") and _norm(mod.dir, src) in modules:
                used_as_source.add(_norm(mod.dir, src))
    dets: list[IacDetection] = []
    for d in sorted(modules):
        if d in used_as_source:
            continue
        mod = modules[d]
        env = _make_env(mod.variables, [mod.tfvars], mod.locals)
        dets += _detect_instance(mod, env, "", None, modules, 0)
    return dets


def detect_iac_module(files: Iterable[tuple[str, str]]) -> list[IacDetection]:
    """Agent candidates for one Terraform module: every ``.tf`` in a directory."""
    files = list(files)
    dir_ = files[0][0].rsplit("/", 1)[0] if files and "/" in files[0][0] else ""
    return detect_iac_tree({dir_: files})


def detect_iac_agents(content: str, relative_path: str) -> list[IacDetection]:
    """Agent candidates for a single Terraform file (a one-file module)."""
    return detect_iac_module([(relative_path, content)])


# --- terraform show -json (plan / state) input -----------------------------------


def _overlay_refs(attrs: dict, expressions: dict) -> None:
    """Put configuration references back onto planned values so resources link.

    Planned values are fully resolved but a value that is unknown until apply
    (a role ARN created in the same plan) is simply absent; the configuration
    keeps the expression's ``references``. A reference to a managed resource
    always wins (it is the link the detectors follow); ``var.``/``local.``
    references only fill in a missing value, as an unresolved ``Ref``.
    """
    for key, expr in expressions.items():
        if isinstance(expr, dict) and ("references" in expr or "constant_value" in expr):
            refs = [r for r in expr.get("references", []) if isinstance(r, str)]
            managed = next((r for r in refs if _MANAGED_REF.match(r)), None)
            if managed:
                attrs[key] = Ref(managed)
            elif key not in attrs and refs:
                attrs[key] = Ref(refs[0])
        elif isinstance(expr, list):                       # nested block(s)
            target = attrs.get(key)
            if not isinstance(target, list):
                target = [] if target is None else [target]
                attrs[key] = target
            for i, sub in enumerate(expr):
                if not isinstance(sub, dict):
                    continue
                if i >= len(target):
                    target.append({})
                if isinstance(target[i], dict):
                    _overlay_refs(target[i], sub)


def detect_iac_plan(doc: dict, plan_path: str) -> list[IacDetection]:
    """Agent candidates from ``terraform show -json`` output (a plan or a state).

    Resources are grouped by module address, each group detected as one
    module with the address as the symbol prefix. There is no ``file:line``
    in a plan, so evidence anchors at the plan file itself.
    """
    values_root = (doc.get("planned_values") or doc.get("values") or {}).get("root_module") or {}
    config_root = (doc.get("configuration") or {}).get("root_module") or {}
    groups: dict[str, list[TfBlock]] = {}

    def walk_values(mod: dict, addr: str) -> None:
        for r in mod.get("resources", []) or []:
            if not isinstance(r, dict) or "type" not in r or "name" not in r:
                continue
            type_ = f"data.{r['type']}" if r.get("mode") == "data" else r["type"]
            vals = r.get("values")
            attrs = dict(vals) if isinstance(vals, dict) else {}
            index = r.get("index")
            inst = "" if index is None else (f'["{index}"]' if isinstance(index, str) else f"[{index}]")
            groups.setdefault(addr, []).append(TfBlock(type_, r["name"], 1, attrs, plan_path, inst))
        for cm in mod.get("child_modules", []) or []:
            if isinstance(cm, dict):
                walk_values(cm, cm.get("address", addr))

    walk_values(values_root, "")

    def walk_config(cfg: dict, addr: str) -> None:
        by: dict[tuple[str, str], list[TfBlock]] = {}
        for b in groups.get(addr, []):
            by.setdefault((b.type, b.name), []).append(b)
        for r in cfg.get("resources", []) or []:
            if not isinstance(r, dict):
                continue
            key = (f"data.{r['type']}" if r.get("mode") == "data" else r.get("type", ""), r.get("name", ""))
            for b in by.get(key, []):
                _overlay_refs(b.attrs, r.get("expressions") or {})
        for name, call in (cfg.get("module_calls") or {}).items():
            child = f"{addr}.module.{name}" if addr else f"module.{name}"
            for g in list(groups):
                if g == child or g.startswith(child + "["):
                    walk_config((call or {}).get("module") or {}, g)

    walk_config(config_root, "")

    dets: list[IacDetection] = []
    for addr in sorted(groups):
        for d in _run_detectors(groups[addr]):
            if addr:
                d.symbol = f"{addr}.{d.symbol}"
                d.id = agent_id(d.path, d.symbol)
            d.evidence.append(Evidence("IAC_PLAN_SOURCE", 1,
                                       f"from Terraform plan {plan_path}" + (f", module {addr}" if addr else "")))
            dets.append(d)
    return dets
