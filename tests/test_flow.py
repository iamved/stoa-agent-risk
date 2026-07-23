"""Intra-file taint engine: propagation shapes, confidence tiers, redaction."""

from __future__ import annotations

from conftest import fake_openai_key

from stoa.ast_layer import parse
from stoa.flow import find_flows


def _py_source(node):
    """Toy source predicate: a call to request.get_json()."""
    if node.type == "call":
        fn = node.child_by_field_name("function")
        if fn is not None and fn.text.decode().startswith("request.get_json"):
            return "request"
    return None


def _py_exec_sink(node):
    if node.type == "call":
        fn = node.child_by_field_name("function")
        callee = fn.text.decode() if fn is not None else ""
        if callee in ("subprocess.run", "os.system", "eval", "exec"):
            return "exec"
    return None


def flows(src, is_source, is_sink, lang="python", path="a.py"):
    parsed = parse(path, lang, src)
    return find_flows(parsed, is_source, is_sink)


def test_direct_chain_high_confidence():
    src = (
        "def h():\n"
        "    topic = request.get_json()['t']\n"
        "    cmd = topic.strip()\n"
        "    subprocess.run(cmd, shell=True)\n"
    )
    fs = flows(src, _py_source, _py_exec_sink)
    assert len(fs) == 1
    f = fs[0]
    assert f.confidence == "high"
    assert [s.role for s in f.steps] == ["source", "propagation", "sink"]
    assert f.source_line == 2 and f.sink_line == 4


def test_fstring_interpolation_propagates():
    src = (
        "def h():\n"
        "    topic = request.get_json()['t']\n"
        "    prompt = f'run {topic} now'\n"
        "    eval(prompt)\n"
    )
    fs = flows(src, _py_source, _py_exec_sink)
    assert len(fs) == 1 and fs[0].confidence == "high"


def test_no_flow_when_sanitizer_breaks_chain():
    # An arbitrary function call is NOT a propagating construct.
    src = (
        "def h():\n"
        "    topic = request.get_json()['t']\n"
        "    safe = sanitize(topic)\n"   # unknown function -> taint stops
        "    subprocess.run(safe, shell=True)\n"
    )
    assert flows(src, _py_source, _py_exec_sink) == []


def test_constant_is_not_tainted():
    src = "def h():\n    cmd = 'ls -la'\n    subprocess.run(cmd, shell=True)\n"
    assert flows(src, _py_source, _py_exec_sink) == []


def test_cross_function_is_medium_confidence():
    src = (
        "def run_cmd(c):\n"
        "    subprocess.run(c, shell=True)\n"
        "def h():\n"
        "    topic = request.get_json()['t']\n"
        "    run_cmd(topic)\n"
    )
    fs = flows(src, _py_source, _py_exec_sink)
    assert len(fs) == 1
    assert fs[0].confidence == "medium"
    assert fs[0].crossed_function is True


def test_messages_collection_construction_propagates():
    def sink(node):
        if node.type == "call":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.text.decode().endswith(".create"):
                return "model_call"
        return None

    src = (
        "def h():\n"
        "    topic = request.get_json()['t']\n"
        "    msgs = [{'role': 'user', 'content': topic}]\n"
        "    client.messages.create(messages=msgs)\n"
    )
    fs = flows(src, _py_source, sink)
    assert len(fs) == 1


def test_flow_snippets_are_redacted():
    key = fake_openai_key()

    def secret_source(node):
        if node.type == "string" and key in node.text.decode():
            return "secret"
        return None

    src = f"def h():\n    k = '{key}'\n    eval(k)\n"
    fs = flows(src, secret_source, _py_exec_sink)
    assert len(fs) == 1
    for step in fs[0].steps:
        assert key not in step.snippet
    assert "[REDACTED:" in fs[0].steps[0].snippet


def test_javascript_template_literal_flow():
    def js_source(node):
        if node.type == "member_expression" and node.text.decode().startswith("req.body"):
            return "req"
        return None

    def js_eval_sink(node):
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.text.decode() == "eval":
                return "exec"
        return None

    src = "function h() {\n  const x = req.body.t;\n  const p = `do ${x}`;\n  eval(p);\n}\n"
    fs = flows(src, js_source, js_eval_sink, lang="javascript", path="a.js")
    assert len(fs) == 1 and fs[0].confidence == "high"


def test_determinism_repeated_runs():
    src = (
        "def h():\n"
        "    a = request.get_json()['t']\n"
        "    b = f'x {a}'\n"
        "    eval(b)\n"
        "    os.system(a)\n"
    )
    first = flows(src, _py_source, _py_exec_sink)
    second = flows(src, _py_source, _py_exec_sink)
    assert [(s.sink_line, s.source_line) for s in first] == [
        (s.sink_line, s.source_line) for s in second
    ]


def test_degraded_parse_yields_no_flows():
    parsed = parse("a.rb", "ruby", "x = 1")
    assert find_flows(parsed, _py_source, _py_exec_sink) == []
