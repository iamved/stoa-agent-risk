"""Diff-aware finding classification.

Findings are marked ``is_new`` only when their line intersects a range of
added lines in ``git diff --unified=0 BASE...HEAD``. Deleted lines never
produce findings, and pure renames do not mark old findings as new because
unchanged lines carry no added-line ranges.

When the diff cannot be computed reliably, gating fails open: no finding is
marked new, and the uncertainty is reported as a scan warning.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .models import Finding

GIT_TIMEOUT_SECONDS = 30

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
NEW_FILE_HEADER = re.compile(r"^\+\+\+ (?:b/(.*)|(/dev/null))$")

AddedRanges = dict[str, list[tuple[int, int]]]


def compute_added_ranges(root: Path, base: str) -> tuple[AddedRanges | None, str | None]:
    """Return (per-file added-line ranges, warning). Ranges is None on failure."""
    verify = _run_git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if verify is None:
        return None, (
            f"Base ref {base!r} could not be resolved; diff-aware gating is "
            "disabled for this scan (failing open)."
        )
    output = _run_git(root, "diff", "--unified=0", "--find-renames", f"{base}...HEAD")
    if output is None:
        return None, (
            f"git diff against {base!r} failed; diff-aware gating is disabled "
            "for this scan (failing open)."
        )
    return _parse_unified_zero(output), None


def _parse_unified_zero(diff_text: str) -> AddedRanges:
    ranges: AddedRanges = {}
    current_file: str | None = None
    for line in diff_text.splitlines():
        header = NEW_FILE_HEADER.match(line)
        if header:
            current_file = header.group(1)  # None for /dev/null (deleted file)
            continue
        hunk = HUNK_HEADER.match(line)
        if hunk and current_file is not None:
            start = int(hunk.group(1))
            count = int(hunk.group(2)) if hunk.group(2) is not None else 1
            if count > 0:
                ranges.setdefault(current_file, []).append((start, start + count - 1))
    return ranges


def mark_new_findings(findings: list[Finding], ranges: AddedRanges) -> None:
    """Set ``is_new`` on findings whose line falls in an added range."""
    for finding in findings:
        file_ranges = ranges.get(finding.path)
        if not file_ranges:
            finding.is_new = False
            continue
        finding.is_new = any(start <= finding.line <= end for start, end in file_ranges)


def _run_git(root: Path, *args: str) -> str | None:
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
    return completed.stdout
