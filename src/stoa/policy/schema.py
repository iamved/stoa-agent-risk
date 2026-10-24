"""``stoa-policy/0.1``: what a policy is, and how a file of them is read.

One file, TOML, at the repository root (``stoa.policy.toml``)::

    version = "stoa-policy/0.1"
    [defaults]
    mode = "observe"          # observe | enforce; the starting point for every policy

    [[policies]]
    id = "POL-PAY-001"
    title = "Approval required above threshold"
    scope = { agent = "account-actions", tool = "issue_refund" }
    trigger = "tool_call"     # input | tool_call | output | any
    condition = { amount_gt = 200 }
    action = "escalate"       # allow | block | escalate | mask | log
    escalate_to = "console"
    fail = "closed"           # closed: the action is enforced; open: recorded only
    evidence = ["amount", "currency", "approval_span_id"]
    maps_to = { dimension = "unreviewed-high-impact-action", owasp_llm = "LLM06", eu_ai_act = "Art. 14" }
    rationale = "Declared human_approved; AI003 found no approval on the money path."

Conditions (one key per table, or ``all`` / ``any`` lists of tables):
``amount_gt``, ``amount_gte``, ``window_sum_gt {field, window, value}``,
``window_count_gt {window, value}``, ``field_in {field, values}``,
``field_not_in {field, values}``, ``regex_match {field, pattern}``,
``approval_missing``, ``killswitch``, ``classifier {name, threshold}``,
``expr`` (the runtime's expression language, for anything else).

The file's older ``[[rules]]`` form (``when`` / ``expr`` / ``on_fail``)
stays valid; the runtime reads both. Validation never raises: it returns a
list of problems with the key path each one is at.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

POLICY_SCHEMA = "stoa-policy/0.1"
TRIGGERS = ("input", "tool_call", "output", "any")
ACTIONS = ("allow", "block", "escalate", "mask", "log")
FAILS = ("open", "closed")
MODES = ("observe", "enforce")
CONDITION_KEYS = (
    "amount_gt", "amount_gte", "window_sum_gt", "window_count_gt", "field_in", "field_not_in",
    "regex_match", "approval_missing", "killswitch", "classifier", "expr", "all", "any",
)
WINDOW_RE = re.compile(r"^(\d+)([smhd])$")
ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+)+$|^[a-z][a-z0-9-]*$")
CLASSIFIERS = ("prompt_injection", "pii")


@dataclass
class PolicySpec:
    id: str
    title: str = ""
    scope: dict = field(default_factory=lambda: {"agent": "*"})  # {agent, tool?}
    trigger: str = "tool_call"
    condition: dict = field(default_factory=dict)
    action: str = "log"
    escalate_to: str | None = None
    fail: str = "open"
    evidence: list = field(default_factory=list)
    maps_to: dict = field(default_factory=dict)
    rationale: str = ""
    recommended_because: list = field(default_factory=list)
    pack: str | None = None
    enforce: bool | None = None  # None: from fail + defaults.mode

    def enforced(self, mode: str) -> bool:
        """Whether the action changes behavior: an explicit ``enforce``, else
        ``fail = "closed"`` under enforce mode, else never."""
        if self.enforce is not None:
            return self.enforce
        return mode == "enforce" and self.fail == "closed"

    def to_dict(self) -> dict:
        out = {
            "id": self.id, "title": self.title, "scope": dict(self.scope), "trigger": self.trigger,
            "condition": self.condition, "action": self.action, "fail": self.fail,
        }
        if self.escalate_to:
            out["escalate_to"] = self.escalate_to
        if self.evidence:
            out["evidence"] = list(self.evidence)
        if self.maps_to:
            out["maps_to"] = dict(self.maps_to)
        if self.rationale:
            out["rationale"] = self.rationale
        if self.recommended_because:
            out["recommended_because"] = list(self.recommended_because)
        if self.pack:
            out["pack"] = self.pack
        if self.enforce is not None:
            out["enforce"] = self.enforce
        return out


@dataclass
class PolicyDocument:
    version: str = POLICY_SCHEMA
    mode: str = "observe"
    policies: list = field(default_factory=list)
    path: str | None = None
    problems: list = field(default_factory=list)  # {"at": key path, "message": text}
    extra: dict = field(default_factory=dict)  # tables the runtime does not own ([rules], [alerts])

    @property
    def ok(self) -> bool:
        return not self.problems

    def by_id(self, policy_id: str) -> PolicySpec | None:
        return next((p for p in self.policies if p.id == policy_id), None)


# --- validation -----------------------------------------------------------------------------


def _problem(problems: list, at: str, message: str) -> None:
    problems.append({"at": at, "message": message})


def validate_condition(cond, at: str, problems: list) -> None:
    if not isinstance(cond, dict):
        _problem(problems, at, "condition must be a table")
        return
    if not cond:
        _problem(problems, at, "condition is empty")
        return
    for key, value in cond.items():
        where = f"{at}.{key}"
        if key not in CONDITION_KEYS:
            _problem(problems, where, f"unknown condition; expected one of {', '.join(CONDITION_KEYS)}")
        elif key in ("amount_gt", "amount_gte"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                _problem(problems, where, "must be a number")
        elif key in ("window_sum_gt", "window_count_gt"):
            if not isinstance(value, dict):
                _problem(problems, where, "must be a table with window and value")
                continue
            if not isinstance(value.get("window"), str) or not WINDOW_RE.match(value["window"]):
                _problem(problems, f"{where}.window", "must be like 60s, 15m, 24h or 7d")
            if isinstance(value.get("value"), bool) or not isinstance(value.get("value"), (int, float)):
                _problem(problems, f"{where}.value", "must be a number")
            if key == "window_sum_gt" and not isinstance(value.get("field"), str):
                _problem(problems, f"{where}.field", "must name the numeric field to sum")
        elif key in ("field_in", "field_not_in"):
            if not isinstance(value, dict) or not isinstance(value.get("field"), str) or not isinstance(value.get("values"), list):
                _problem(problems, where, "must be a table with field and values")
        elif key == "regex_match":
            if not isinstance(value, dict) or not isinstance(value.get("field"), str) or not isinstance(value.get("pattern"), str):
                _problem(problems, where, "must be a table with field and pattern")
            else:
                try:
                    re.compile(value["pattern"])
                except re.error as exc:
                    _problem(problems, f"{where}.pattern", f"invalid regex: {exc}")
        elif key in ("approval_missing", "killswitch"):
            if not isinstance(value, bool):
                _problem(problems, where, "must be true or false")
        elif key == "classifier":
            if not isinstance(value, dict) or value.get("name") not in CLASSIFIERS:
                _problem(problems, where, f"must be a table with name in {CLASSIFIERS}")
            elif "threshold" in value and (isinstance(value["threshold"], bool) or not isinstance(value["threshold"], (int, float))):
                _problem(problems, f"{where}.threshold", "must be a number between 0 and 1")
        elif key == "expr":
            if not isinstance(value, str):
                _problem(problems, where, "must be an expression string")
        elif key in ("all", "any"):
            if not isinstance(value, list) or not value:
                _problem(problems, where, "must be a non-empty list of conditions")
            else:
                for index, sub in enumerate(value):
                    validate_condition(sub, f"{where}[{index}]", problems)


def validate_policy(raw, at: str, problems: list) -> PolicySpec | None:
    if not isinstance(raw, dict):
        _problem(problems, at, "policy must be a table")
        return None
    unknown = set(raw) - {"id", "title", "scope", "trigger", "condition", "action", "escalate_to", "fail", "evidence", "maps_to", "rationale", "recommended_because", "pack", "enforce"}
    for key in sorted(unknown):
        _problem(problems, f"{at}.{key}", "unknown key")
    policy_id = raw.get("id")
    if not isinstance(policy_id, str) or not policy_id:
        _problem(problems, f"{at}.id", "required")
        policy_id = "?"
    elif not ID_RE.match(policy_id):
        _problem(problems, f"{at}.id", "use UPPER-CASE-WORDS like POL-PAY-001 or lower-case-words")
    scope = raw.get("scope", {"agent": "*"})
    if not isinstance(scope, dict) or not isinstance(scope.get("agent", "*"), str) or ("tool" in scope and not isinstance(scope["tool"], str)):
        _problem(problems, f"{at}.scope", "must be a table like { agent = \"*\", tool = \"issue_refund\" }")
        scope = {"agent": "*"}
    scope = {"agent": scope.get("agent", "*"), **({"tool": scope["tool"]} if scope.get("tool") else {})}
    trigger = raw.get("trigger", "tool_call")
    if trigger not in TRIGGERS:
        _problem(problems, f"{at}.trigger", f"must be one of {TRIGGERS}")
    action = raw.get("action", "log")
    if action not in ACTIONS:
        _problem(problems, f"{at}.action", f"must be one of {ACTIONS}")
    fail = raw.get("fail", "open")
    if fail not in FAILS:
        _problem(problems, f"{at}.fail", f"must be one of {FAILS}")
    if action == "escalate" and raw.get("escalate_to") not in (None, "console", "hook", "slack"):
        _problem(problems, f"{at}.escalate_to", "must be console, hook or slack")
    validate_condition(raw.get("condition", {}), f"{at}.condition", problems)
    for key in ("evidence", "recommended_because"):
        if key in raw and (not isinstance(raw[key], list) or not all(isinstance(x, str) for x in raw[key])):
            _problem(problems, f"{at}.{key}", "must be a list of strings")
    maps_to = raw.get("maps_to", {})
    if not isinstance(maps_to, dict):
        _problem(problems, f"{at}.maps_to", "must be a table")
        maps_to = {}
    if "enforce" in raw and not isinstance(raw["enforce"], bool):
        _problem(problems, f"{at}.enforce", "must be true or false")
    return PolicySpec(
        id=policy_id, title=str(raw.get("title", "")), scope=scope, trigger=trigger if trigger in TRIGGERS else "tool_call",
        condition=raw.get("condition", {}) if isinstance(raw.get("condition", {}), dict) else {}, action=action if action in ACTIONS else "log",
        escalate_to=raw.get("escalate_to"), fail=fail if fail in FAILS else "open", evidence=list(raw.get("evidence") or []) if isinstance(raw.get("evidence"), list) else [],
        maps_to=dict(maps_to), rationale=str(raw.get("rationale", "")), recommended_because=list(raw.get("recommended_because") or []) if isinstance(raw.get("recommended_because"), list) else [],
        pack=raw.get("pack"), enforce=raw.get("enforce") if isinstance(raw.get("enforce"), bool) else None,
    )


def parse_policy_document(data: dict, path: str | None = None) -> PolicyDocument:
    problems: list = []
    document = PolicyDocument(path=path, problems=problems)
    version = data.get("version", POLICY_SCHEMA)
    if version not in (POLICY_SCHEMA, 1):  # 1 is the pre-0.1 rules-only file
        _problem(problems, "version", f"expected {POLICY_SCHEMA!r}")
    document.version = POLICY_SCHEMA if version == 1 else str(version)
    defaults = data.get("defaults") or {}
    mode = defaults.get("mode", "observe") if isinstance(defaults, dict) else "observe"
    if mode not in MODES:
        _problem(problems, "defaults.mode", f"must be one of {MODES}")
        mode = "observe"
    document.mode = mode
    seen: set[str] = set()
    for index, raw in enumerate(data.get("policies") or []):
        spec = validate_policy(raw, f"policies[{index}]", problems)
        if spec is None:
            continue
        if spec.id in seen:
            _problem(problems, f"policies[{index}].id", f"duplicate id {spec.id}")
        seen.add(spec.id)
        document.policies.append(spec)
    for key in ("rules", "alerts"):
        if key in data:
            document.extra[key] = data[key]
    for key in data:
        if key not in ("version", "defaults", "policies", "rules", "alerts"):
            _problem(problems, key, "unknown top-level key")
    return document


def validate_document(text: str, path: str | None = None) -> PolicyDocument:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return PolicyDocument(path=path, problems=[{"at": "file", "message": f"not valid TOML: {exc}"}])
    return parse_policy_document(data, path)


def find_policy_file(start: str | Path | None = None) -> Path | None:
    here = Path(start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / "stoa.policy.toml"
        if candidate.is_file():
            return candidate
    return None


def load_policy_document(path: str | Path) -> PolicyDocument:
    path = Path(path)
    try:
        return validate_document(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        return PolicyDocument(path=str(path), problems=[{"at": "file", "message": f"cannot read: {exc}"}])


# --- serialization ----------------------------------------------------------------------------


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml_value(v)}" for k, v in value.items()) + " }"
    return '""'


def policy_to_toml(document: PolicyDocument, *, header: str = "") -> str:
    """Render a document as the file the runtime reads. Deterministic."""
    lines = [f'version = "{POLICY_SCHEMA}"', "", "[defaults]", f'mode = "{document.mode}"', ""]
    if header:
        lines = [f"# {line}" if line else "#" for line in header.splitlines()] + [""] + lines
    for spec in document.policies:
        lines.append("[[policies]]")
        for key, value in spec.to_dict().items():
            if key == "condition" and isinstance(value, dict) and any(isinstance(v, (dict, list)) and k in ("all", "any") for k, v in value.items()):
                lines.append(f"condition = {_toml_value(value)}")
            else:
                lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
