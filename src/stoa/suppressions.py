"""Inline and file-wide suppression parsing.

Supported forms (Python ``#`` and JavaScript/TypeScript ``//`` comments):

    value = "..."  # stoa: ignore[SEC001] optional reason
    # stoa: ignore[SEC003] applies to the next line
    # stoa: ignore-file[CTRL001,CTRL002] whole-file suppression

Suppression always requires explicit rule IDs; there is no blanket
``ignore-all``. Unknown or malformed rule IDs are reported, never silently
accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .rules import RULES, VALID_RULE_ID

SUPPRESSION_COMMENT = re.compile(
    r"(?:#|//)\s*stoa:\s*(ignore|ignore-file)\[([^\]]*)\]\s*(.*?)\s*$"
)

COMMENT_ONLY = re.compile(r"^\s*(?:#|//)")


@dataclass
class FileSuppressions:
    """Parsed suppression directives for one file."""

    file_wide: dict[str, str | None] = field(default_factory=dict)
    by_line: dict[int, dict[str, str | None]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def check(self, rule_id: str, line: int) -> tuple[bool, str | None]:
        """Return (suppressed, reason) for a finding at *line*."""
        if rule_id in self.file_wide:
            return True, self.file_wide[rule_id]
        rules_for_line = self.by_line.get(line)
        if rules_for_line and rule_id in rules_for_line:
            return True, rules_for_line[rule_id]
        return False, None


def parse_suppressions(content: str, relative_path: str) -> FileSuppressions:
    """Extract suppression directives from source comments."""
    result = FileSuppressions()
    for number, raw_line in enumerate(content.splitlines(), start=1):
        match = SUPPRESSION_COMMENT.search(raw_line)
        if not match:
            continue
        kind, rule_list, reason_text = match.groups()
        reason = reason_text.strip() or None
        rule_ids = [r.strip() for r in rule_list.split(",") if r.strip()]
        if not rule_ids:
            result.warnings.append(
                f"{relative_path}:{number}: suppression comment lists no rule IDs; ignored"
            )
            continue
        valid: list[str] = []
        for rule_id in rule_ids:
            if not VALID_RULE_ID.match(rule_id) or rule_id not in RULES:
                result.warnings.append(
                    f"{relative_path}:{number}: unknown rule ID {rule_id!r} in suppression; ignored"
                )
                continue
            valid.append(rule_id)
        if not valid:
            continue
        if kind == "ignore-file":
            for rule_id in valid:
                result.file_wide.setdefault(rule_id, reason)
        else:
            targets = [number]
            if COMMENT_ONLY.match(raw_line):
                # A comment-only suppression also covers the following line.
                targets.append(number + 1)
            for target in targets:
                bucket = result.by_line.setdefault(target, {})
                for rule_id in valid:
                    bucket.setdefault(rule_id, reason)
    return result
