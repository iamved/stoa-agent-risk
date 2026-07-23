"""Tree-sitter AST layer (Part I §0.1).

A thin, deterministic wrapper over tree-sitter. Grammars are bundled in the
pinned ``tree-sitter-language-pack`` wheel, so nothing is downloaded at
runtime (local-first invariant).

The layer is optional-graceful: if a grammar is missing or a file fails to
parse cleanly, callers get a :class:`ParsedFile` with ``degraded=True`` and
rules fall back to regex-only mode (findings capped at ``low`` confidence).
Parse trees are cached per absolute path for the lifetime of a scan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable, Iterator, Optional

# Stoa language name -> tree-sitter grammar name.
_GRAMMAR_BY_LANGUAGE = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
}

# .tsx / .jsx need the JSX-aware grammar; scanner language is still js/ts.
_TSX_GRAMMAR = "tsx"


@dataclass
class ParsedFile:
    """A parsed source file, or a degraded placeholder when parsing failed."""

    path: str
    language: str
    source: bytes
    root: object | None = None  # tree_sitter.Node, or None when degraded
    degraded: bool = False
    degraded_reason: Optional[str] = None
    _lines: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.root is not None and not self.degraded

    def line_text(self, line: int) -> str:
        """1-indexed source line as text (for evidence snippets)."""
        if 1 <= line <= len(self._lines):
            return self._lines[line - 1]
        return ""

    def walk(self) -> Iterator[object]:
        """Yield every node in deterministic document (pre-order) order."""
        if self.root is None:
            return
        stack = [self.root]
        # Reverse children on push so pop yields them left-to-right.
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))

    def find(self, predicate: Callable[[object], bool]) -> list[object]:
        """All nodes matching *predicate*, in document order."""
        return [node for node in self.walk() if predicate(node)]


@lru_cache(maxsize=1)
def _parser_for(grammar: str):
    """Cache one parser per grammar for the process lifetime."""
    from tree_sitter_language_pack import get_parser

    return get_parser(grammar)


def _grammar_for(language: str, path: str) -> Optional[str]:
    if path.endswith((".tsx", ".jsx")):
        return _TSX_GRAMMAR
    return _GRAMMAR_BY_LANGUAGE.get(language)


def node_text(node: object, source: bytes) -> str:
    """UTF-8 text of a node, tolerating malformed bytes."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def parse(path: str, language: str, content: str) -> ParsedFile:
    """Parse *content* into a :class:`ParsedFile`; never raises on bad input."""
    source = content.encode("utf-8", errors="replace")
    lines = content.splitlines()
    grammar = _grammar_for(language, path)
    if grammar is None:
        return ParsedFile(
            path=path,
            language=language,
            source=source,
            degraded=True,
            degraded_reason=f"no grammar for language {language!r}",
            _lines=lines,
        )
    try:
        tree = _parser_for(grammar).parse(source)
    except Exception as exc:  # pragma: no cover - defensive; parser is robust
        return ParsedFile(
            path=path,
            language=language,
            source=source,
            degraded=True,
            degraded_reason=f"parse error: {exc.__class__.__name__}",
            _lines=lines,
        )
    root = tree.root_node
    # A tree with ERROR nodes still parses partially; mark degraded so any
    # rule using it drops confidence, but keep the (partial) tree usable.
    degraded = root.has_error
    return ParsedFile(
        path=path,
        language=language,
        source=source,
        root=root,
        degraded=degraded,
        degraded_reason="syntax errors present" if degraded else None,
        _lines=lines,
    )


class AstCache:
    """Per-scan cache of parsed files, keyed by absolute path."""

    def __init__(self) -> None:
        self._cache: dict[str, ParsedFile] = {}

    def get(self, path: str, language: str, content: str) -> ParsedFile:
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        parsed = parse(path, language, content)
        self._cache[path] = parsed
        return parsed

    def clear(self) -> None:
        self._cache.clear()
