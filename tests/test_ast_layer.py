"""AST layer: parsing, document-order traversal, degraded fallback, caching."""

from __future__ import annotations

from stoa.ast_layer import AstCache, node_text, parse

PY = "x = request.get_json()['t']\nsubprocess.run(x, shell=True)\n"
JS = "const x = req.body.t;\neval(x);\n"
TS = "const x: string = req.body.t;\neval(x);\n"
TSX = "const C = () => { const x = req.body.t; return <div>{x}</div>; };\n"


def test_parses_all_languages():
    for path, lang, src in [
        ("a.py", "python", PY),
        ("a.js", "javascript", JS),
        ("a.ts", "typescript", TS),
        ("a.tsx", "typescript", TSX),
    ]:
        parsed = parse(path, lang, src)
        assert parsed.available, f"{path} should parse cleanly"
        assert not parsed.degraded


def test_walk_is_document_order_and_deterministic():
    parsed = parse("a.py", "python", PY)
    first = [n.type for n in parsed.walk()]
    second = [n.type for n in parsed.walk()]
    assert first == second
    assert first[0] == "module"
    # 'subprocess' identifier appears after 'request' identifier (document order)
    idents = [
        node_text(n, parsed.source)
        for n in parsed.walk()
        if n.type == "identifier"
    ]
    assert idents.index("request") < idents.index("subprocess")


def test_unknown_language_degrades_gracefully():
    parsed = parse("a.rb", "ruby", "puts 'hi'")
    assert parsed.degraded
    assert parsed.root is None
    assert not parsed.available
    assert "grammar" in parsed.degraded_reason


def test_syntax_error_marks_degraded_but_keeps_tree():
    parsed = parse("a.py", "python", "def broken(:\n    x =\n")
    assert parsed.degraded
    assert parsed.root is not None  # partial tree still available


def test_malformed_utf8_does_not_crash():
    parsed = parse("a.py", "python", "x = 'caf\udce9'\n")
    assert parsed.root is not None


def test_line_text_is_one_indexed():
    parsed = parse("a.py", "python", PY)
    assert parsed.line_text(2) == "subprocess.run(x, shell=True)"
    assert parsed.line_text(999) == ""


def test_cache_returns_same_object():
    cache = AstCache()
    a = cache.get("a.py", "python", PY)
    b = cache.get("a.py", "python", PY)
    assert a is b
    cache.clear()
    c = cache.get("a.py", "python", PY)
    assert c is not a


def test_find_predicate():
    parsed = parse("a.py", "python", PY)
    calls = parsed.find(lambda n: n.type == "call")
    assert len(calls) == 2  # request.get_json() and subprocess.run(...)
