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
_IDENT = re.compile(r"[A-Za-z_][\w-]*")
_HEREDOC_OPEN = re.compile(r"<<-?[ \t]*([A-Za-z_]\w*)[ \t]*\r?\n")


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
    path: str = ""                  # file that defines the block (module scope)


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


def extract_tf_blocks(text: str, path: str = "") -> list[TfBlock]:
    """Every ``resource "TYPE" "NAME" { ... }`` block in a Terraform file."""
    blocks = []
    for m in _RESOURCE_OPEN.finditer(text):
        brace = m.end() - 1
        end = _close(text, brace, "{", "}")
        blocks.append(TfBlock(
            type=m.group(1), name=m.group(2),
            line=text.count("\n", 0, m.start()) + 1,
            attrs=_body(text[brace + 1:end - 1]),
            path=path,
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
        symbol = f"{ep.type}.{ep.name}"
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


def _policy_doc(value: Any) -> Optional[dict]:
    """An IAM policy document from ``jsonencode({...})``, a JSON string, or a heredoc.

    A reference (``data.aws_iam_policy_document.x.json``, ``var.policy``) is
    unresolved and returns None — never guessed.
    """
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
            _apply(_policy_doc(p.attrs.get("policy")), p)
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
                _apply(_policy_doc(pol.attrs.get("policy")) if pol else None, pol or p)
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

        symbol = f"{ag.type}.{ag.name}"
        detections.append(IacDetection(
            id=agent_id(ag.path, symbol),
            name=display, symbol=symbol,
            confidence="high", detection_score=8,
            evidence=evidence, frameworks=[],
            providers=sorted(providers), integrations=sorted(integrations),
            capabilities=sorted(caps), controls=controls,
            platform="bedrock", path=ag.path,
        ))
    return detections


# --- entry points ------------------------------------------------------------


def detect_iac_module(files: Iterable[tuple[str, str]]) -> list[IacDetection]:
    """Agent candidates for one Terraform module: every ``.tf`` in a directory.

    ``files`` is ``(relative_path, content)`` pairs; order does not matter
    (blocks are processed in path order for determinism).
    """
    blocks: list[TfBlock] = []
    for path, content in sorted(files):
        blocks.extend(extract_tf_blocks(content, path))
    return _detect_databricks(blocks) + _detect_bedrock(blocks)


def detect_iac_agents(content: str, relative_path: str) -> list[IacDetection]:
    """Agent candidates for a single Terraform file (a one-file module)."""
    return detect_iac_module([(relative_path, content)])
