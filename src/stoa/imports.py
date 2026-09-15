"""One-hop import graph between scanned files (0.7.3).

Used to attribute controls: an agent reached only through a route file that
carries authentication, rate limiting and logging is *covered* by those
controls, even though its own file never mentions them. Resolution is
deliberately simple — module paths by suffix for Python, relative specifiers
for JS/TS — and undirected: the file that imports the agent and the files the
agent imports are both one hop away.
"""

from __future__ import annotations

import posixpath
import re

_PY_IMPORT = re.compile(r"^[ \t]*(?:from[ \t]+([\w.]+)[ \t]+import\b|import[ \t]+([\w.]+))", re.MULTILINE)
_JS_IMPORT = re.compile(r"""(?:\bfrom[ \t]+|\brequire\(\s*|\bimport\(\s*|^[ \t]*import[ \t]+)['"](\.{1,2}/[^'"]+)['"]""",
                        re.MULTILINE)
_EXT = re.compile(r"\.(?:py|js|jsx|mjs|cjs|ts|tsx)$")
_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def build_import_graph(file_contents: dict[str, str]) -> dict[str, set[str]]:
    """path -> set of paths one import hop away (both directions)."""
    stems: dict[str, list[str]] = {}          # every suffix of a module path -> files
    exact: dict[str, str] = {}
    for path in file_contents:
        if not _EXT.search(path):
            continue
        stem = _EXT.sub("", path)
        names = [stem]
        if stem.endswith("/__init__"):
            names.append(stem[: -len("/__init__")])
        if stem.endswith("/index"):
            names.append(stem[: -len("/index")])
        for name in names:
            exact[name] = path
            parts = name.split("/")
            for i in range(len(parts)):
                stems.setdefault("/".join(parts[i:]), []).append(path)

    neighbors: dict[str, set[str]] = {p: set() for p in file_contents}

    def link(a: str, b: str) -> None:
        if a != b and b in neighbors:
            neighbors[a].add(b)
            neighbors[b].add(a)

    for path, content in file_contents.items():
        if path.endswith(".py"):
            for m in _PY_IMPORT.finditer(content):
                mod = (m.group(1) or m.group(2)).lstrip(".")
                if not mod:
                    continue
                rel = mod.replace(".", "/")
                targets = stems.get(rel, [])
                if not targets and "/" in rel:                  # `from a.b import c` where c is a module
                    targets = stems.get(rel.rsplit("/", 1)[0], [])
                for t in targets[:8]:
                    link(path, t)
        elif _EXT.search(path):
            base = posixpath.dirname(path)
            for m in _JS_IMPORT.finditer(content):
                target = posixpath.normpath(posixpath.join(base, m.group(1)))
                target = _EXT.sub("", target)
                for cand in (target, target + "/index"):
                    if cand in exact:
                        link(path, exact[cand])
                        break
    return neighbors
