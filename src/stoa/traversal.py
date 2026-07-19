"""Deterministic repository traversal with gitignore-style exclusions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pathspec

from .config import StoaConfig
from .models import SkippedFile
from .rules import TESTLIKE_PATH

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}


@dataclass
class SourceFile:
    """A file selected for scanning."""

    absolute_path: Path
    relative_path: str
    language: str
    is_testlike: bool


def _load_ignore_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _build_spec(lines: list[str]) -> pathspec.PathSpec | None:
    lines = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    if not lines:
        return None
    if hasattr(pathspec, "GitIgnoreSpec"):
        return pathspec.GitIgnoreSpec.from_lines(lines)
    return pathspec.PathSpec.from_lines("gitwildmatch", lines)


def traverse(
    root: Path, config: StoaConfig
) -> tuple[list[SourceFile], list[SkippedFile]]:
    """Walk *root* and return (files to scan, skipped files), both sorted.

    Only the repository-root ``.gitignore`` and ``.stoaignore`` are consulted;
    nested ignore files are not merged (documented limitation).
    """
    root = root.resolve()
    ignore_spec = _build_spec(list(config.ignore_paths) + config.extra_excludes)
    gitignore_spec = (
        _build_spec(_load_ignore_lines(root / ".gitignore"))
        if config.respect_gitignore
        else None
    )
    stoaignore_spec = _build_spec(_load_ignore_lines(root / ".stoaignore"))
    include_spec = _build_spec(config.extra_includes)

    selected: list[SourceFile] = []
    skipped: list[SkippedFile] = []

    def is_ignored(rel: str) -> str | None:
        if ignore_spec and ignore_spec.match_file(rel):
            return "excluded by default or configured ignore pattern"
        if gitignore_spec and gitignore_spec.match_file(rel):
            return "excluded by .gitignore"
        if stoaignore_spec and stoaignore_spec.match_file(rel):
            return "excluded by .stoaignore"
        return None

    for dirpath, dirnames, filenames in os.walk(root, followlinks=config.follow_symlinks):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")

        kept_dirs = []
        for name in sorted(dirnames):
            child = os.path.join(dirpath, name)
            rel_child = f"{rel_dir}/{name}" if rel_dir else name
            if not config.follow_symlinks and os.path.islink(child):
                continue
            reason = is_ignored(rel_child + "/")
            if reason:
                # Prune the whole subtree; record the directory (not each file)
                # so verbose output stays readable and traversal stays fast.
                skipped.append(SkippedFile(rel_child + "/", reason))
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for name in sorted(filenames):
            rel_file = f"{rel_dir}/{name}" if rel_dir else name
            absolute = Path(dirpath) / name
            extension = os.path.splitext(name)[1].lower()
            if extension not in config.include_extensions:
                continue
            if not config.follow_symlinks and absolute.is_symlink():
                skipped.append(SkippedFile(rel_file, "symbolic link"))
                continue
            reason = is_ignored(rel_file)
            if reason:
                skipped.append(SkippedFile(rel_file, reason))
                continue
            if include_spec and not include_spec.match_file(rel_file):
                skipped.append(SkippedFile(rel_file, "not matched by --include patterns"))
                continue
            try:
                size = absolute.stat().st_size
            except OSError as exc:
                skipped.append(SkippedFile(rel_file, f"stat failed: {exc.__class__.__name__}"))
                continue
            if size > config.max_file_bytes:
                skipped.append(
                    SkippedFile(rel_file, f"file larger than {config.max_file_bytes} bytes")
                )
                continue
            selected.append(
                SourceFile(
                    absolute_path=absolute,
                    relative_path=rel_file,
                    language=LANGUAGE_BY_EXTENSION.get(extension, "unknown"),
                    is_testlike=bool(TESTLIKE_PATH.search(rel_file)),
                )
            )

    selected.sort(key=lambda f: f.relative_path)
    skipped.sort(key=lambda f: f.path)
    return selected, skipped


def read_source(source: SourceFile) -> str | None:
    """Read a source file once, tolerating malformed UTF-8 and I/O errors."""
    try:
        return source.absolute_path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return None
