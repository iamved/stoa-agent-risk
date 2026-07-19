"""Git attribution metadata: sanitized, best-effort, never fatal.

All subprocess calls use argument arrays (never ``shell=True``) and a
timeout. Any git failure degrades to ``None`` rather than crashing the scan.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pathspec

from .models import CommitInfo
from .rules import BOT_AUTHOR

GIT_TIMEOUT_SECONDS = 10

CODEOWNERS_LOCATIONS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")

_URL_CREDENTIALS = re.compile(r"//[^/@]+@")


def _run_git(root: Path, *args: str) -> str | None:
    """Run a git command; return stripped stdout or None on any failure."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def is_git_repository(root: Path) -> bool:
    return _run_git(root, "rev-parse", "--is-inside-work-tree") == "true"


def sanitize_remote_url(url: str) -> str:
    """Extract a safe repository name; strip credentials and tokens."""
    url = _URL_CREDENTIALS.sub("//", url.strip())
    name = url.rstrip("/").rsplit("/", 1)[-1]
    name = name.rsplit(":", 1)[-1]
    if name.endswith(".git"):
        name = name[: -len(".git")]
    return name


def repository_name(root: Path) -> str:
    """Repository name from the origin remote, falling back to the directory."""
    url = _run_git(root, "remote", "get-url", "origin")
    if url:
        name = sanitize_remote_url(url)
        if name:
            return name
    return root.resolve().name


def head_ref(root: Path) -> str | None:
    return _run_git(root, "rev-parse", "--short", "HEAD")


def file_attribution(root: Path, relative_path: str) -> tuple[str | None, CommitInfo | None]:
    """(last non-bot author name, last commit info) for one file.

    Fallback order for the author: last non-bot author, then last author,
    then None. Author emails are never collected.
    """
    output = _run_git(
        root, "log", "-5", "--format=%an%x1f%h%x1f%cI", "--", relative_path
    )
    if not output:
        return None, None
    entries: list[tuple[str, CommitInfo]] = []
    for line in output.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        author, commit_hash, date = parts
        entries.append((author, CommitInfo(hash=commit_hash, date=date)))
    if not entries:
        return None, None
    last_author, last_commit = entries[0]
    for author, _commit in entries:
        if not BOT_AUTHOR.search(author):
            return author, last_commit
    return last_author, last_commit


@dataclass
class CodeownersEntry:
    pattern: str
    owners: list[str]
    spec: pathspec.PathSpec


def load_codeowners(root: Path) -> list[CodeownersEntry]:
    """Parse the first CODEOWNERS file found.

    Supports the common gitignore-style subset of GitHub's pattern syntax
    (see README); the last matching entry wins, as on GitHub.
    """
    for location in CODEOWNERS_LOCATIONS:
        path = root / location
        if not path.is_file():
            continue
        entries: list[CodeownersEntry] = []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            pattern, owners = parts[0], parts[1:]
            try:
                if hasattr(pathspec, "GitIgnoreSpec"):
                    spec = pathspec.GitIgnoreSpec.from_lines([pattern])
                else:
                    spec = pathspec.PathSpec.from_lines("gitwildmatch", [pattern])
            except Exception:
                continue
            entries.append(CodeownersEntry(pattern=pattern, owners=owners, spec=spec))
        return entries
    return []


def codeowners_for(entries: list[CodeownersEntry], relative_path: str) -> list[str]:
    """Resolve owners for a file: the last matching pattern wins."""
    owners: list[str] = []
    for entry in entries:
        if entry.spec.match_file(relative_path):
            owners = entry.owners
    return owners
