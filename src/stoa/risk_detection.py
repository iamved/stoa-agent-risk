"""Risk-rule detection with immediate secret redaction.

Findings carry redacted snippets only; the raw source line never leaves this
module once a secret has been matched.
"""

from __future__ import annotations

from .config import StoaConfig
from .models import Finding, finding_fingerprint
from .redaction import redact_line, redact_secret, shannon_entropy
from .rules import (
    COMMENT_ONLY_LINE,
    CONTROL_PATTERNS,
    HTTP_URL,
    LOCAL_HTTP_HOST,
    OBSERVABILITY_CONSTRUCT,
    OUTGOING_REQUEST_CALL,
    PASSWORD_ASSIGNMENT,
    PASSWORD_SAFE_CONTEXT,
    PLACEHOLDER_SECRET,
    RULES,
    SECRET_PATTERN,
    SQL_INTERPOLATION_PATTERNS,
    SWALLOWED_CATCH_JS,
    SWALLOWED_EXCEPT_PY,
    TIMEOUT_ARG,
)

MIN_SECRET_ENTROPY = 3.0
SNIPPET_MAX_LENGTH = 200


class _FindingBuilder:
    """Builds findings with stable, collision-free fingerprints per file."""

    def __init__(self, relative_path: str, config: StoaConfig) -> None:
        self.relative_path = relative_path
        self.config = config
        self.findings: list[Finding] = []
        self._context_counts: dict[str, int] = {}

    def add(
        self,
        rule_id: str,
        line: int,
        column: int,
        redacted_snippet: str,
        confidence: str,
        severity: str | None = None,
    ) -> None:
        if not self.config.rule_enabled(rule_id):
            return
        spec = RULES[rule_id]
        normalized = " ".join(redacted_snippet.split())
        key = f"{rule_id}:{normalized}"
        count = self._context_counts.get(key, 0)
        self._context_counts[key] = count + 1
        context = normalized if count == 0 else f"{normalized}#{count}"
        sev = severity or self.config.effective_severity(rule_id)
        self.findings.append(
            Finding(
                fingerprint=finding_fingerprint(rule_id, self.relative_path, context),
                rule_id=rule_id,
                title=spec.title,
                category=spec.category,
                severity=sev,
                confidence=confidence,
                path=self.relative_path,
                line=line,
                column=column,
                snippet=normalized[:SNIPPET_MAX_LENGTH],
                remediation=spec.remediation,
                # Every finding carries a message so JSON consumers never see a
                # null; core rules template it from title + remediation.
                message=f"{spec.title} ({self.relative_path}:{line}). {spec.remediation}",
            )
        )


def detect_risks(
    content: str,
    relative_path: str,
    language: str,
    is_testlike: bool,
    config: StoaConfig,
) -> list[Finding]:
    """Run all per-file risk rules over one file's content."""
    builder = _FindingBuilder(relative_path, config)
    lines = content.splitlines()

    for number, raw_line in enumerate(lines, start=1):
        is_comment = bool(COMMENT_ONLY_LINE.match(raw_line))
        _detect_secrets(builder, raw_line, number, is_comment, is_testlike, config)
        _detect_passwords(builder, raw_line, number, is_comment, is_testlike, config)
        if not is_comment:
            _detect_sql_interpolation(builder, raw_line, number, is_testlike)
            _detect_insecure_http(builder, raw_line, number, is_testlike)
            _detect_missing_timeout(builder, lines, raw_line, number)

    _detect_swallowed_exceptions(builder, content, language, is_testlike)
    return builder.findings


def _detect_secrets(
    builder: _FindingBuilder,
    raw_line: str,
    number: int,
    is_comment: bool,
    is_testlike: bool,
    config: StoaConfig,
) -> None:
    """SEC001: redact immediately; never retain or emit the raw value."""
    matches = list(SECRET_PATTERN.finditer(raw_line))
    if not matches:
        return
    redacted = redact_line(raw_line)
    for match in matches:
        token = match.group(0)
        confidence = "high"
        if PLACEHOLDER_SECRET.search(token) or PLACEHOLDER_SECRET.search(raw_line):
            confidence = "low"
        elif shannon_entropy(token) < MIN_SECRET_ENTROPY:
            confidence = "low"
        elif is_comment:
            confidence = "low"
        elif is_testlike:
            confidence = "medium"
        builder.add(
            rule_id="SEC001",
            line=number,
            column=match.start() + 1,
            redacted_snippet=redacted.strip(),
            confidence=confidence,
        )


def _detect_passwords(
    builder: _FindingBuilder,
    raw_line: str,
    number: int,
    is_comment: bool,
    is_testlike: bool,
    config: StoaConfig,
) -> None:
    """SEC002: literal password assignments only, never lookups or placeholders."""
    match = PASSWORD_ASSIGNMENT.search(raw_line)
    if not match:
        return
    value = match.group(2)
    if not value or PASSWORD_SAFE_CONTEXT.search(raw_line):
        return
    if PLACEHOLDER_SECRET.search(value) or value.lower() in {"password", "secret", "none", "null"}:
        return
    if value.startswith(("$", "{", "%", "<")) or "${" in value or "{}" in value:
        return
    confidence = "high"
    if is_comment or is_testlike or shannon_entropy(value) < 2.0:
        confidence = "low"
    severity = None
    if confidence == "high" and "SEC002" not in builder.config.severity_overrides:
        severity = "critical"
    # The password literal is not an API-key shape, so redact_line() alone
    # leaves it intact — redact the matched value explicitly (P0: no secret,
    # including passwords, may reach any artifact).
    snippet = redact_line(raw_line).replace(value, redact_secret(value)).strip()
    builder.add(
        rule_id="SEC002",
        line=number,
        column=match.start() + 1,
        redacted_snippet=snippet,
        confidence=confidence,
        severity=severity,
    )


def _detect_sql_interpolation(
    builder: _FindingBuilder, raw_line: str, number: int, is_testlike: bool
) -> None:
    """SEC003: interpolated SQL; static analysis cannot prove exploitability."""
    for pattern in SQL_INTERPOLATION_PATTERNS:
        match = pattern.search(raw_line)
        if match:
            builder.add(
                rule_id="SEC003",
                line=number,
                column=match.start() + 1,
                redacted_snippet=redact_line(raw_line).strip(),
                confidence="low" if is_testlike else "medium",
            )
            return


def _detect_insecure_http(
    builder: _FindingBuilder, raw_line: str, number: int, is_testlike: bool
) -> None:
    """NET001: plain HTTP to a non-local host. Skipped in test paths, where
    ``http://`` URLs are almost always mocks/fixtures — the dominant NET001
    false positive on real repos."""
    if is_testlike:
        return
    for match in HTTP_URL.finditer(raw_line):
        host = match.group(1)
        if LOCAL_HTTP_HOST.match(host):
            continue
        builder.add(
            rule_id="NET001",
            line=number,
            column=match.start() + 1,
            redacted_snippet=redact_line(raw_line).strip(),
            confidence="medium",
        )
        return


def _detect_missing_timeout(
    builder: _FindingBuilder, lines: list[str], raw_line: str, number: int
) -> None:
    """NET002: no request timeout observed at this call site (review prompt)."""
    if not OUTGOING_REQUEST_CALL.search(raw_line):
        return
    # Examine the call line plus a window for a multi-line timeout kwarg;
    # eight lines covers realistic keyword-argument-per-line call styles.
    window = "\n".join(lines[number - 1 : number + 8])
    if TIMEOUT_ARG.search(window):
        return
    builder.add(
        rule_id="NET002",
        line=number,
        column=(OUTGOING_REQUEST_CALL.search(raw_line).start() + 1),
        redacted_snippet=redact_line(raw_line).strip(),
        confidence="low",
    )


def _detect_swallowed_exceptions(
    builder: _FindingBuilder, content: str, language: str, is_testlike: bool
) -> None:
    """REL001: except/catch blocks that silently discard errors. Skipped in
    test paths (swallowing is common and low-signal there); low severity by
    default elsewhere — a code smell, rarely a security issue."""
    if is_testlike:
        return
    pattern = SWALLOWED_EXCEPT_PY if language == "python" else SWALLOWED_CATCH_JS
    for match in pattern.finditer(content):
        line = content.count("\n", 0, match.start()) + 1
        snippet = match.group(0).splitlines()[0].strip()
        builder.add(
            rule_id="REL001",
            line=line,
            column=1,
            redacted_snippet=redact_line(snippet),
            confidence="high",
        )


# Which repo-level control satisfies each CTRL rule.
CTRL_REPO_KEY = {"CTRL001": "authentication", "CTRL002": "validation",
                 "CTRL003": "rate_limit"}


def detect_control_prompts(
    content: str,
    relative_path: str,
    symbol: str,
    anchor_line: int,
    config: StoaConfig,
    repo_controls: set[str] | None = None,
) -> list[Finding]:
    """CTRL001–003: at most one review prompt per agent candidate and category.

    A prompt fires only when the control is observed neither in this file nor
    anywhere in the repository (``repo_controls``) — auth, validation, and rate
    limiting usually live in middleware, so a per-file check alone produces
    false "not observed" prompts on real codebases.
    """
    repo_controls = repo_controls or set()
    builder = _FindingBuilder(relative_path, config)
    for rule_id, pattern in CONTROL_PATTERNS.items():
        if pattern.search(content):
            continue
        if CTRL_REPO_KEY.get(rule_id) in repo_controls:
            continue  # observed elsewhere in the repository
        builder.add(
            rule_id=rule_id,
            line=anchor_line,
            column=1,
            redacted_snippet=f"{RULES[rule_id].title} for candidate {symbol}",
            confidence="low",
        )
    return builder.findings


def scan_repo_controls(contents: list[str]) -> set[str]:
    """Which control types are observed anywhere in the repository."""
    joined = "\n".join(contents)
    observed: set[str] = set()
    for rule_id, key in CTRL_REPO_KEY.items():
        if CONTROL_PATTERNS[rule_id].search(joined):
            observed.add(key)
    if OBSERVABILITY_CONSTRUCT.search(joined):
        observed.add("observability")
    return observed
