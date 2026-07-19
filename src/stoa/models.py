"""Typed internal data model for Stoa scan results.

All models are plain dataclasses so the JSON layer can serialize them
deterministically without any third-party dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Optional

SEVERITIES = ("info", "low", "medium", "high", "critical")
SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITIES)}

CONFIDENCES = ("low", "medium", "high")
CONFIDENCE_ORDER = {name: index for index, name in enumerate(CONFIDENCES)}


def severity_at_least(severity: str, threshold: str) -> bool:
    """Return True when *severity* is at or above *threshold*."""
    return SEVERITY_ORDER[severity] >= SEVERITY_ORDER[threshold]


def agent_id(relative_path: str, qualified_symbol: str) -> str:
    """Stable agent-candidate identifier derived from source identity only."""
    return sha256(f"{relative_path}:{qualified_symbol}".encode()).hexdigest()[:12]


def finding_fingerprint(rule_id: str, relative_path: str, normalized_context: str) -> str:
    """Stable finding identifier that survives pure line-number movement.

    The context passed in must already be redacted; fingerprints are computed
    only over safe, normalized text.
    """
    return sha256(f"{rule_id}:{relative_path}:{normalized_context}".encode()).hexdigest()[:16]


@dataclass
class Evidence:
    """One reason a file or symbol was classified as an agent candidate."""

    rule_id: str
    line: int
    description: str


@dataclass
class Finding:
    """A single risk finding tied to a location in the repository."""

    fingerprint: str
    rule_id: str
    title: str
    category: str
    severity: str
    confidence: str
    path: str
    line: int
    column: int
    snippet: str
    remediation: str
    suppressed: bool = False
    suppression_reason: Optional[str] = None
    is_new: bool = False


@dataclass
class CommitInfo:
    """Abbreviated metadata about the most recent relevant commit."""

    hash: str
    date: str


@dataclass
class AgentCandidate:
    """A likely AI agent detected through weighted static evidence."""

    id: str
    name: str
    symbol: str
    path: str
    language: str
    confidence: str
    detection_score: int
    evidence: list[Evidence] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    integrations: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    call_sites: dict[str, int] = field(default_factory=dict)
    last_touched_by: Optional[str] = None
    last_commit: Optional[CommitInfo] = None
    codeowners: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def highest_severity(self) -> Optional[str]:
        active = [f.severity for f in self.findings if not f.suppressed]
        if not active:
            return None
        return max(active, key=lambda s: SEVERITY_ORDER[s])


@dataclass
class SkippedFile:
    """A file the traversal saw but did not scan, and why."""

    path: str
    reason: str


@dataclass
class RepositoryInfo:
    """Sanitized repository-level metadata."""

    name: str
    root: str = "."
    git_ref: Optional[str] = None
    base_ref: Optional[str] = None


@dataclass
class ScanResult:
    """Complete result of one scan, before serialization."""

    repository: RepositoryInfo
    files_scanned: int
    agents: list[AgentCandidate] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    skipped_files: list[SkippedFile] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diff_available: bool = False

    def unsuppressed_findings(self) -> list[Finding]:
        return [f for f in self.findings if not f.suppressed]

    def severity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.unsuppressed_findings():
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    def new_severity_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.unsuppressed_findings():
            if finding.is_new:
                counts[finding.severity] = counts.get(finding.severity, 0) + 1
        return counts

    def suppressed_count(self) -> int:
        return sum(1 for f in self.findings if f.suppressed)
