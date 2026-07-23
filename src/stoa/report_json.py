"""Deterministic JSON serialization of scan results.

Output is stable across runs of the same tree: sorted arrays, no timestamps,
no absolute paths, no raw secrets (snippets are redacted upstream), and an
atomic file write.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import SCHEMA_VERSION, __version__
from .config import StoaConfig
from .models import SEVERITIES, AgentCandidate, Finding, ScanResult


def finding_to_dict(finding: Finding) -> dict:
    record = {
        "fingerprint": finding.fingerprint,
        "rule_id": finding.rule_id,
        "title": finding.title,
        "category": finding.category,
        "severity": finding.severity,
        "confidence": finding.confidence,
        "path": finding.path,
        "line": finding.line,
        "column": finding.column,
        "snippet": finding.snippet,
        "remediation": finding.remediation,
        "suppressed": finding.suppressed,
        "suppression_reason": finding.suppression_reason,
        "is_new": finding.is_new,
    }
    # Schema 1.1 additive fields — emitted only when populated, so a scan with
    # no AI findings serializes byte-identically to schema 1.0 (plus version).
    if finding.canonical_name is not None:
        record["id"] = finding.stable_id
        record["canonical_name"] = finding.canonical_name
    if finding.owasp is not None:
        record["owasp"] = finding.owasp
    if finding.variant is not None:
        record["variant"] = finding.variant
    if finding.flow:
        record["flow"] = [
            {"role": s.role, "line": s.line, "snippet": s.snippet} for s in finding.flow
        ]
    if finding.gate_eligible:
        record["gate_eligible"] = True
    if finding.dimensions:
        record["dimensions"] = sorted(finding.dimensions)
    if finding.supersedes:
        record["supersedes"] = sorted(finding.supersedes)
    if finding.evidence_tags:
        record["evidence_tags"] = sorted(finding.evidence_tags)
    if finding.message is not None:
        record["message"] = finding.message
    return record


def agent_to_dict(agent: AgentCandidate, include_suppressed: bool) -> dict:
    findings = [
        finding_to_dict(f)
        for f in agent.findings
        if include_suppressed or not f.suppressed
    ]
    return {
        "id": agent.id,
        "name": agent.name,
        "symbol": agent.symbol,
        "path": agent.path,
        "language": agent.language,
        "confidence": agent.confidence,
        "detection_score": agent.detection_score,
        "evidence": [
            {"rule_id": e.rule_id, "line": e.line, "description": e.description}
            for e in agent.evidence
        ],
        "providers": agent.providers,
        "frameworks": agent.frameworks,
        "integrations": agent.integrations,
        "capabilities": agent.capabilities,
        "call_sites": agent.call_sites,
        "last_touched_by": agent.last_touched_by,
        "last_commit": (
            {"hash": agent.last_commit.hash, "date": agent.last_commit.date}
            if agent.last_commit
            else None
        ),
        "codeowners": agent.codeowners,
        "findings": findings,
        "highest_severity": agent.highest_severity,
        **(
            {"dimension_assessment": agent.dimension_assessment}
            if agent.dimension_assessment is not None
            else {}
        ),
    }


def build_document(result: ScanResult, config: StoaConfig) -> dict:
    """Assemble the full schema-versioned document."""
    agent_paths = {agent.path for agent in result.agents}
    repository_findings = [
        f
        for f in result.findings
        if f.path not in agent_paths and (config.include_suppressed_in_json or not f.suppressed)
    ]
    severity_counts = result.severity_counts()
    new_counts = result.new_severity_counts()
    document = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "stoa", "version": __version__},
        "repository": {
            "name": result.repository.name,
            "root": result.repository.root,
            "git_ref": result.repository.git_ref,
            "base_ref": result.repository.base_ref,
        },
        "summary": {
            "files_scanned": result.files_scanned,
            "agent_candidates": len(result.agents),
            "high_confidence_candidates": sum(
                1 for a in result.agents if a.confidence == "high"
            ),
            "integrations": len({i for a in result.agents for i in a.integrations}),
            "findings": {
                severity: severity_counts.get(severity, 0) for severity in reversed(SEVERITIES)
            },
            "new_findings": {
                severity: new_counts.get(severity, 0) for severity in reversed(SEVERITIES)
            },
            "suppressed_findings": result.suppressed_count(),
        },
        "agents": [
            agent_to_dict(agent, config.include_suppressed_in_json)
            for agent in result.agents
        ],
        "repository_findings": [finding_to_dict(f) for f in repository_findings],
        "skipped_files": [
            {"path": s.path, "reason": s.reason} for s in result.skipped_files
        ],
        "warnings": list(result.warnings),
    }
    # Emitted only when AST analysis degraded on some file (keeps default
    # regex-mode output byte-identical to schema 1.0 aside from the version).
    if result.degraded_files:
        document["degraded_files"] = sorted(result.degraded_files)
    validate_document(document)
    return document


def validate_document(document: dict) -> None:
    """Sanity-check structure before writing; raises ValueError on defects."""
    required = {"schema_version", "tool", "repository", "summary", "agents", "repository_findings", "skipped_files"}
    missing = required - document.keys()
    if missing:
        raise ValueError(f"JSON document missing required keys: {sorted(missing)}")
    for agent in document["agents"]:
        if not agent.get("id") or not agent.get("path"):
            raise ValueError("Agent record missing id or path")
        if agent["path"].startswith("/") or ":\\" in agent["path"]:
            raise ValueError(f"Agent path is not repository-relative: {agent['path']}")


def write_json(result: ScanResult, config: StoaConfig, output_path: Path) -> None:
    """Serialize and atomically write the registry JSON."""
    document = build_document(result, config)
    text = json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    _atomic_write(output_path, text)


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    # Special files (e.g. /dev/null) can't be atomically replaced via a
    # temp-file rename; write to them directly so "discard" idioms work.
    try:
        if path.exists() and not path.is_file():
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False, suffix=".tmp"
    )
    try:
        with handle:
            handle.write(text)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
