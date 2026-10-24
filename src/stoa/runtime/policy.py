"""Local policy evaluation for guarded tool calls (`stoa.policy.toml`).

A policy is a list of rules. Each rule has a ``when`` expression that
selects the calls it applies to, an ``expr`` that must hold, and what to do
when it does not (``on_fail``): ``observe`` (record only), ``require_approval``
(ask the registered approval hook, else record and continue) or ``deny``.
A rule only blocks a call when it sets ``enforce = true`` and the SDK was
configured with ``fail_open=False`` or the rule itself is enforced; the
file's ``[defaults] mode`` ("observe" or "enforce") is the starting point.

Expressions are evaluated by a small AST walker, never ``eval``: names,
attribute and item access, constants, comparisons (including ``in``),
``and`` / ``or`` / ``not``, and arithmetic on numbers. Unknown names
evaluate to ``None`` and the rule reports ``error`` instead of raising.
The namespace a rule sees::

    tool            the guarded tool's name
    args            the call's arguments (the redacted view: numbers, bools,
                    and hashed strings are what a rule can test)
    side_effect     "read" | "write" | "payment" | "delete" | "external_send"
    amount          the numeric argument named by limit_field, or None
    approval        {"granted": bool, "span_id": str | None}
    agent           {"id", "name", "declared_tools": [...], "max_per_action": {...} | None}
    session         {"id": str | None}

Loading is fail-open: a missing or malformed file means no rules and one
warning. The file is TOML (the stdlib reads it; the rest of Stoa's config
is TOML too).

Example::

    version = 1
    [defaults]
    mode = "observe"

    [[rules]]
    id = "refund-cap"
    when = 'tool == "issue_refund"'
    expr = "amount <= 500"
    on_fail = "require_approval"

    [[rules]]
    id = "payment-needs-approval"
    when = 'side_effect == "payment"'
    expr = "approval.granted == true"
    on_fail = "deny"
    enforce = true

    [[rules]]
    id = "allowlist"
    when = "true"
    expr = "tool in agent.declared_tools"
    on_fail = "observe"
"""

from __future__ import annotations

import ast
import operator
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

POLICY_NAME = "stoa.policy.toml"
DECISIONS = ("allow", "deny", "require_approval", "observe", "mask")
ON_FAIL = ("observe", "require_approval", "deny")
# A structured policy's action, as the decision the runtime acts on.
_ON_FAIL_FOR = {"block": "deny", "escalate": "require_approval", "mask": "mask", "log": "observe", "allow": "allow"}


class StoaDenied(Exception):
    """Raised into the caller when an enforced rule denies a guarded call."""

    def __init__(self, rule_id: str, reason: str) -> None:
        super().__init__(f"stoa policy {rule_id}: {reason}")
        self.rule_id = rule_id
        self.reason = reason


@dataclass
class Rule:
    id: str
    when: str = "true"
    expr: str = "true"
    on_fail: str = "observe"
    enforce: bool = False
    reason: str = ""
    # A structured policy (stoa-policy/0.1) carries its spec; the expression
    # fields above are then unused and the condition decides.
    spec: object | None = None


@dataclass
class Policy:
    path: str | None = None
    mode: str = "observe"
    rules: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def loaded(self) -> bool:
        return self.path is not None


@dataclass
class Decision:
    rule_id: str
    decision: str  # allow | deny | require_approval | observe | mask
    enforced: bool
    reason: str = ""
    error: str | None = None
    # The policy's own action word (allow | block | escalate | mask | log) for structured policies.
    action: str | None = None


# --- safe expression evaluation ---------------------------------------------------------

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Mod: operator.mod}
_CMP = {
    ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge,
    ast.In: lambda a, b: b is not None and a in b, ast.NotIn: lambda a, b: b is None or a not in b,
}
_CONSTANTS = {"true": True, "false": False, "null": None, "none": None, "True": True, "False": False, "None": None}


class UnknownName(Exception):
    pass


def _lookup(value, name: str):
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def evaluate(expr: str, namespace: dict):
    """Evaluate ``expr`` against ``namespace``. Raises ``UnknownName`` for a
    name the namespace lacks and ``ValueError`` for syntax the walker does
    not allow; the policy layer turns both into a rule ``error``."""
    tree = ast.parse(expr.strip() or "true", mode="eval")

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in _CONSTANTS:
                return _CONSTANTS[node.id]
            if node.id not in namespace:
                raise UnknownName(node.id)
            return namespace[node.id]
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise ValueError("private attributes are not allowed in policy expressions")
            return _lookup(walk(node.value), node.attr)
        if isinstance(node, ast.Subscript):
            container = walk(node.value)
            key = walk(node.slice)
            try:
                return container[key]
            except (KeyError, IndexError, TypeError):
                return None
        if isinstance(node, (ast.List, ast.Tuple)):
            return [walk(e) for e in node.elts]
        if isinstance(node, ast.BoolOp):
            values = [walk(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not walk(node.operand)
            if isinstance(node.op, ast.USub):
                return -walk(node.operand)
            raise ValueError("unsupported unary operator")
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            left, right = walk(node.left), walk(node.right)
            if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
                return None
            return _BIN[type(node.op)](left, right)
        if isinstance(node, ast.Compare):
            left = walk(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = walk(comparator)
                if type(op) not in _CMP:
                    raise ValueError("unsupported comparison")
                if type(op) in (ast.Lt, ast.LtE, ast.Gt, ast.GtE) and (left is None or right is None):
                    return False
                try:
                    if not _CMP[type(op)](left, right):
                        return False
                except TypeError:
                    return False
                left = right
            return True
        raise ValueError(f"unsupported expression element: {type(node).__name__}")

    return walk(tree)


# --- loading -----------------------------------------------------------------------------


def find_policy(start: str | Path | None = None) -> Path | None:
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / POLICY_NAME
        if candidate.is_file():
            return candidate
    return None


def load_policy(path: str | Path | None = None) -> Policy:
    """Never raises: a missing file is an empty policy; a malformed one is
    an empty policy with a warning recorded on it and warned once."""
    try:
        resolved = Path(path) if path else find_policy()
        if resolved is None or not resolved.is_file():
            return Policy()
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        policy = Policy(warnings=[f"policy file unreadable: {exc}"])
        warnings.warn(f"stoa.runtime: {policy.warnings[0]}; no policy applied.", RuntimeWarning, stacklevel=2)
        return policy
    policy = Policy(path=str(resolved))
    mode = (data.get("defaults") or {}).get("mode", "observe")
    policy.mode = mode if mode in ("observe", "enforce") else "observe"
    if data.get("policies"):
        from ..policy.schema import parse_policy_document

        document = parse_policy_document(data, str(resolved))
        for problem in document.problems:
            policy.warnings.append(f"{problem['at']}: {problem['message']}")
        for spec in document.policies:
            policy.rules.append(Rule(id=spec.id, on_fail=_ON_FAIL_FOR[spec.action], enforce=spec.enforced(policy.mode), reason=spec.rationale, spec=spec))
    for index, raw in enumerate(data.get("rules") or []):
        if not isinstance(raw, dict) or not raw.get("id"):
            policy.warnings.append(f"rules[{index}]: missing id; ignored")
            continue
        on_fail = raw.get("on_fail", "observe")
        if on_fail not in ON_FAIL:
            policy.warnings.append(f"rules[{index}] ({raw['id']}): on_fail must be one of {ON_FAIL}; ignored")
            continue
        for key in ("when", "expr"):
            try:
                ast.parse(str(raw.get(key, "true")), mode="eval")
            except SyntaxError as exc:
                policy.warnings.append(f"rules[{index}] ({raw['id']}): {key} does not parse ({exc.msg}); ignored")
                break
        else:
            policy.rules.append(Rule(
                id=str(raw["id"]), when=str(raw.get("when", "true")), expr=str(raw.get("expr", "true")),
                on_fail=on_fail, enforce=bool(raw.get("enforce", policy.mode == "enforce")),
                reason=str(raw.get("reason", "")),
            ))
    for text in policy.warnings:
        warnings.warn(f"stoa.runtime: {text}", RuntimeWarning, stacklevel=2)
    return policy


# --- evaluation ---------------------------------------------------------------------------


def _scoped(spec, namespace: dict, trigger: str) -> bool:
    scope = spec.scope or {}
    agent = namespace.get("agent") or {}
    wanted = scope.get("agent", "*")
    if wanted not in ("*", agent.get("id"), agent.get("name")):
        return False
    if scope.get("tool") and scope["tool"] != namespace.get("tool"):
        return False
    return spec.trigger in ("any", trigger)


def decide(policy: Policy, namespace: dict, *, fail_open: bool = True, trigger: str = "tool_call", store=None, killswitch=None, now=None) -> list[Decision]:
    """Every rule's decision for one call, in file order. A rule that does
    not apply (``when`` false, or a structured policy out of scope) is left
    out. ``enforced`` is true only when the rule says ``enforce`` (or the
    SDK runs fail-closed) and the decision is ``deny`` or ``require_approval``;
    everything else is recorded, never acted on."""
    out: list[Decision] = []
    for rule in policy.rules:
        spec = rule.spec
        if spec is not None:
            if not _scoped(spec, namespace, trigger):
                continue
            from ..policy.conditions import evaluate_condition

            fired, reason = evaluate_condition(spec.condition, {**namespace, "_scope_tool": bool((spec.scope or {}).get("tool"))}, store=store, killswitch=killswitch, now=now, expr_eval=evaluate)
            if fired is None:
                out.append(Decision(rule.id, "observe", False, rule.reason, error=reason, action=spec.action))
                continue
            if not fired:
                out.append(Decision(rule.id, "allow", False, reason, action="allow"))
                continue
            decision = _ON_FAIL_FOR[spec.action]
            enforced = decision in ("deny", "require_approval") and (rule.enforce or not fail_open)
            out.append(Decision(rule.id, decision, enforced, reason or rule.reason, action=spec.action))
            continue
        try:
            if not evaluate(rule.when, namespace):
                continue
            holds = bool(evaluate(rule.expr, namespace))
        except UnknownName as exc:
            out.append(Decision(rule.id, "observe", False, rule.reason, error=f"unknown name {exc}"))
            continue
        except Exception as exc:  # noqa: BLE001
            out.append(Decision(rule.id, "observe", False, rule.reason, error=f"expression error: {exc}"))
            continue
        if holds:
            out.append(Decision(rule.id, "allow", False, rule.reason))
            continue
        enforced = rule.on_fail == "deny" and (rule.enforce or not fail_open)
        out.append(Decision(rule.id, rule.on_fail, enforced, rule.reason or f"{rule.expr} did not hold"))
    return out
