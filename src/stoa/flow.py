"""Intra-file taint engine (`stoa.flow`, Part I §0.2).

A deliberately small, honest dataflow engine over the tree-sitter AST. Scope
for v0.2 is a *single file*: assignment chains, f-string/template/`.format`/`%`
/concatenation, list/dict construction, subscript/attribute of a tainted base,
and same-file direct-call argument passing plus return values. No cross-file,
no class-hierarchy resolution, no dynamic dispatch.

Rules supply two predicates — ``is_source(node) -> tag|None`` and
``is_sink(node) -> tag|None`` — and get back :class:`Flow` objects, each a
source → (≤5 propagation) → sink chain with a confidence tier. All snippets are
run through the redaction pipeline here, so no consumer ever sees a raw secret.

Confidence tiers (uniform across AI rules):
* ``high``   — unbroken chain within one function.
* ``medium`` — chain crosses a same-file function boundary.
* ``low``    — reserved for the regex fallback when the AST is unavailable
  (produced by the caller, not this engine).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .ast_layer import ParsedFile, node_text
from .redaction import redact_line

Predicate = Callable[[object], Optional[str]]

MAX_PROPAGATION = 5

_TRANSPARENT_CALLS = {"json.loads", "JSON.parse", "json.load"}


@dataclass
class FlowStep:
    role: str  # "source" | "propagation" | "sink"
    line: int
    snippet: str


@dataclass
class Flow:
    steps: list[FlowStep]
    confidence: str
    source_tag: str
    sink_tag: str
    crossed_function: bool = False

    @property
    def source_line(self) -> int:
        return self.steps[0].line

    @property
    def sink_line(self) -> int:
        return self.steps[-1].line


def _kind(language: str) -> str:
    return "py" if language == "python" else "js"


_ASSIGN_TYPES = {
    "py": {"assignment", "augmented_assignment"},
    "js": {"variable_declarator", "assignment_expression", "augmented_assignment_expression"},
}
_CALL_TYPE = {"py": "call", "js": "call_expression"}
_FUNC_TYPES = {
    "py": {"function_definition"},
    "js": {"function_declaration", "arrow_function", "function_expression",
           "method_definition", "generator_function_declaration"},
}
_MEMBER_TYPES = {"py": {"attribute"}, "js": {"member_expression"}}
_SUBSCRIPT_TYPES = {"py": {"subscript"}, "js": {"subscript_expression"}}
_STRING_INTERP = {"py": "string", "js": "template_string"}
_CONCAT_TYPES = {"py": {"binary_operator"}, "js": {"binary_expression"}}
_COLLECTION_TYPES = {
    "py": {"list", "dictionary", "tuple", "set", "pair"},
    "js": {"array", "object", "pair"},
}


def _field(node, name: str):
    return node.child_by_field_name(name)


def _assign_target_value(node, kind: str):
    """Return (target_name, value_node) for an assignment-like node, or None."""
    if kind == "py":
        left, right = _field(node, "left"), _field(node, "right")
    else:
        if node.type == "variable_declarator":
            left, right = _field(node, "name"), _field(node, "value")
        else:
            left, right = _field(node, "left"), _field(node, "right")
    if left is None or right is None:
        return None
    if left.type != "identifier":
        return None  # tuple/pattern targets are out of scope
    return left.text.decode("utf-8", "replace"), right


def enclosing_function(node, kind: str):
    """The nearest ancestor function node, or None for module scope."""
    types = _FUNC_TYPES[kind]
    cur = node.parent
    while cur is not None:
        if cur.type in types:
            return cur
        cur = cur.parent
    return None


def _func_key(func_node) -> str:
    return "module" if func_node is None else f"fn@{func_node.start_byte}"


def referenced_names(node, kind: str) -> set[str]:
    """Value-use identifiers in a subtree (excludes attribute/keyword names)."""
    names: set[str] = set()
    stack = [node]
    while stack:
        cur = stack.pop()
        if cur.type == "identifier":
            parent = cur.parent
            if parent is not None:
                if parent.type in _MEMBER_TYPES[kind] and _field(parent, "attribute") == cur:
                    continue  # the ".name" part of an attribute
                if kind == "py" and parent.type == "keyword_argument" and _field(parent, "name") == cur:
                    continue  # the "kw=" name in kw=value
            names.add(cur.text.decode("utf-8", "replace"))
        stack.extend(cur.children)
    return names


def _base_identifier(node, kind: str) -> Optional[str]:
    """Leftmost base identifier of a member/subscript/call chain."""
    cur = node
    while cur is not None:
        if cur.type == "identifier":
            return cur.text.decode("utf-8", "replace")
        if cur.type in _MEMBER_TYPES[kind] or cur.type in _SUBSCRIPT_TYPES[kind]:
            cur = _field(cur, "object") or _field(cur, "value")
        elif cur.type == _CALL_TYPE[kind]:
            cur = _field(cur, "function")
        elif cur.type == "await_expression":
            cur = cur.children[-1] if cur.children else None
        else:
            return None
    return None


def _callee_text(call_node, kind: str, source: bytes) -> str:
    fn = _field(call_node, "function")
    return node_text(fn, source) if fn is not None else ""


def _has_operator(node, op: str) -> bool:
    return any(c.type == op for c in node.children)


def _propagating_sources(value_node, tainted: set[str], kind: str, source: bytes) -> set[str]:
    """Which tainted names flow into *value_node* via an allowed construct.

    Only the enumerated propagating shapes count (alias, interpolation, concat,
    format/%, method-on-tainted, transparent parse, collection literal,
    subscript/attribute of a tainted base) — never an arbitrary ``foo(tainted)``
    call, which might sanitize.
    """
    t = value_node.type

    # alias: y = x
    if t == "identifier":
        name = value_node.text.decode("utf-8", "replace")
        return {name} if name in tainted else set()

    # f-string / template literal interpolation
    if t == _STRING_INTERP[kind]:
        hit = referenced_names(value_node, kind) & tainted
        return hit

    # concatenation (+) and Python % formatting
    if t in _CONCAT_TYPES[kind] and (_has_operator(value_node, "+") or _has_operator(value_node, "%")):
        return referenced_names(value_node, kind) & tainted

    # collection literal carrying a tainted value (messages=[...] construction)
    if t in _COLLECTION_TYPES[kind]:
        return referenced_names(value_node, kind) & tainted

    # subscript / attribute of a tainted base: x[0], x.foo
    if t in _SUBSCRIPT_TYPES[kind] or t in _MEMBER_TYPES[kind]:
        base = _base_identifier(value_node, kind)
        return {base} if base in tainted else set()

    # calls: method-on-tainted-receiver, .format(), or transparent parse
    if t == _CALL_TYPE[kind]:
        callee = _callee_text(value_node, kind, source)
        args = _field(value_node, "arguments")
        arg_hits = referenced_names(args, kind) & tainted if args is not None else set()
        # .format() / .join() / .strip() etc. on a tainted receiver
        base = _base_identifier(value_node, kind)
        if base in tainted:
            return {base}
        if callee.endswith((".format", ".join", ".replace", ".map")) and arg_hits:
            return arg_hits
        if callee in _TRANSPARENT_CALLS and arg_hits:
            return arg_hits
    # await x
    if t == "await_expression" and value_node.children:
        return _propagating_sources(value_node.children[-1], tainted, kind, source)
    return set()


def _first_source_in(value_node, is_source: Predicate) -> Optional[str]:
    """Deepest-first search for a source match inside an RHS expression."""
    stack = [value_node]
    while stack:
        cur = stack.pop()
        tag = is_source(cur)
        if tag:
            return tag
        stack.extend(cur.children)
    return None


@dataclass
class _Taint:
    source_line: int
    source_snippet: str
    source_tag: str
    props: list[tuple[int, str]] = field(default_factory=list)
    crossed: bool = False


def find_flows(parsed: ParsedFile, is_source: Predicate, is_sink: Predicate) -> list[Flow]:
    """Return every source→sink flow in *parsed*, redacted and deterministic."""
    if not parsed.available:
        return []
    kind = _kind(parsed.language)
    source = parsed.source

    # Collect assignments grouped by enclosing function, in document order.
    assigns: list[tuple[str, str, object, int]] = []  # (func_key, target, value, line)
    for node in parsed.walk():
        if node.type in _ASSIGN_TYPES[kind]:
            tv = _assign_target_value(node, kind)
            if tv is None:
                continue
            target, value = tv
            fkey = _func_key(enclosing_function(node, kind))
            assigns.append((fkey, target, value, node.start_point[0] + 1))

    # Seed + fixpoint taint per function scope.
    taint: dict[tuple[str, str], _Taint] = {}

    def line_snip(line: int) -> str:
        return redact_line(parsed.line_text(line).strip())

    def propagate_round() -> bool:
        changed = False
        for fkey, target, value, line in assigns:
            key = (fkey, target)
            scope_tainted = {n for (fk, n) in taint if fk == fkey}
            if key not in taint:
                tag = _first_source_in(value, is_source)
                if tag:
                    taint[key] = _Taint(line, line_snip(line), tag)
                    changed = True
                    continue
            hits = _propagating_sources(value, {n for (fk, n) in taint if fk == fkey}, kind, source)
            if hits:
                origin_name = sorted(hits)[0]
                origin = taint.get((fkey, origin_name))
                if origin is None:
                    continue
                new_props = origin.props + [(line, line_snip(line))]
                existing = taint.get(key)
                if existing is None or len(new_props) < len(existing.props):
                    taint[key] = _Taint(
                        origin.source_line, origin.source_snippet, origin.source_tag,
                        new_props[:MAX_PROPAGATION], origin.crossed,
                    )
                    changed = True
        return changed

    for _ in range(6):  # bounded fixpoint
        if not propagate_round():
            break

    # Cross-function (medium): tainted arg passed to a same-file function seeds
    # that function's parameter; a function returning taint taints its callers.
    _cross_function(parsed, kind, source, assigns, taint, is_source, line_snip)

    # Detect sinks referencing a tainted var (document order → deterministic).
    flows: list[Flow] = []
    seen: set[tuple[int, int, str]] = set()
    for node in parsed.walk():
        sink_tag = is_sink(node)
        if not sink_tag:
            continue
        fkey = _func_key(enclosing_function(node, kind))
        names = referenced_names(node, kind)
        for name in sorted(names):
            info = taint.get((fkey, name)) or taint.get(("module", name))
            if info is None:
                continue
            sink_line = node.start_point[0] + 1
            dedup = (info.source_line, sink_line, sink_tag)
            if dedup in seen:
                continue
            seen.add(dedup)
            steps = [FlowStep("source", info.source_line, info.source_snippet)]
            for pline, psnip in info.props:
                if pline not in (info.source_line, sink_line):
                    steps.append(FlowStep("propagation", pline, psnip))
            steps.append(FlowStep("sink", sink_line, line_snip(sink_line)))
            flows.append(
                Flow(
                    steps=steps,
                    confidence="medium" if info.crossed else "high",
                    source_tag=info.source_tag,
                    sink_tag=sink_tag,
                    crossed_function=info.crossed,
                )
            )
            break  # one flow per sink is enough for a finding
    flows.sort(key=lambda f: (f.sink_line, f.source_line, f.sink_tag))
    return flows


def _cross_function(parsed, kind, source, assigns, taint, is_source, line_snip) -> None:
    """Bounded same-file caller↔callee taint (medium confidence)."""
    # Map function name -> (func_node, [param names]) for same-file resolution.
    funcs: dict[str, tuple[object, list[str]]] = {}
    for node in parsed.walk():
        if node.type in _FUNC_TYPES[kind]:
            name_node = _field(node, "name")
            params_node = _field(node, "parameters") or _field(node, "parameter")
            if name_node is None:
                continue
            params: list[str] = []
            if params_node is not None:
                for child in params_node.children:
                    if child.type == "identifier":
                        params.append(child.text.decode("utf-8", "replace"))
            funcs[name_node.text.decode("utf-8", "replace")] = (node, params)

    changed = True
    rounds = 0
    while changed and rounds < 3:
        changed = False
        rounds += 1
        for node in parsed.walk():
            if node.type != _CALL_TYPE[kind]:
                continue
            callee = _base_identifier(_field(node, "function"), kind) if _field(node, "function") else None
            fn = _field(node, "function")
            callee_name = fn.text.decode("utf-8", "replace") if fn is not None else ""
            if callee_name not in funcs:
                continue
            fnode, params = funcs[callee_name]
            args_node = _field(node, "arguments")
            if args_node is None:
                continue
            caller_key = _func_key(enclosing_function(node, kind))
            # Positional args only (best-effort).
            arg_exprs = [c for c in args_node.children if c.is_named]
            for i, arg in enumerate(arg_exprs):
                if i >= len(params):
                    break
                names = referenced_names(arg, kind) if arg.type != "identifier" else {arg.text.decode()}
                for nm in names:
                    if (caller_key, nm) in taint:
                        pkey = (_func_key(fnode), params[i])
                        if pkey not in taint:
                            base = taint[(caller_key, nm)]
                            taint[pkey] = _Taint(base.source_line, base.source_snippet,
                                                 base.source_tag, list(base.props), crossed=True)
                            changed = True
