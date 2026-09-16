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
    if finding.declared_ref is not None:
        record["declared_ref"] = finding.declared_ref
    return record


def agent_to_dict(agent: AgentCandidate, include_suppressed: bool) -> dict:
    findings = [
        finding_to_dict(f)
        for f in agent.findings
        if include_suppressed or not f.suppressed
    ]
    record = {
        "id": agent.id,
        "name": agent.name,
        # Disambiguated human-facing label (Task 1). Additive: `name`/`symbol`
        # keep the raw inferred values so diff consumers are unaffected.
        "display_name": agent.label,
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
        "permission_tags": agent.permission_tags,
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
        **({"declared": agent.declared} if agent.declared is not None else {}),
        **(
            {"autonomy_level": agent.autonomy_level}
            if agent.autonomy_level is not None
            else {}
        ),
    }
    # Schema 1.6 provenance — emitted only for agents discovered outside
    # application code, so a code-only scan is byte-identical to 1.5 apart
    # from schema_version (the documented additive-minor precedent).
    # Schema 1.7 — the agent's tool inventory, emitted only when non-empty.
    if agent.tools:
        record["tools"] = agent.tools
    if agent.source != "code":
        record["source"] = agent.source
        record["discovery_tier"] = agent.discovery_tier
        if agent.platform:
            record["platform"] = agent.platform
    return record


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
    if result.dimension_summary is not None:
        document["dimension_summary"] = result.dimension_summary
    if result.business is not None:
        document["business"] = result.business
    if result.governance is not None:
        document["governance"] = result.governance
    if result.evidence is not None:
        document["evidence"] = result.evidence
    _annotate_crosswalk(document, config)
    validate_document(document)
    return document


def _annotate_crosswalk(document: dict, config: StoaConfig) -> None:
    """Apply the regulatory-crosswalk annotation layer (schema 1.5, additive).

    A pure post-pass so scoring and every earlier builder stay untouched: it
    stamps a ``crosswalk`` object on each finding, adds the top-level
    ``crosswalk`` version block, and unions each dimension's finding tags into
    a per-dimension roll-up on ``dimension_summary``. Presentation-only; never
    reads or writes any score.

    Degrades gracefully: the crosswalk is an additive annotation layer (unlike
    the load-bearing dimension taxonomy), so if it cannot load — a corrupt
    built-in or a bad override path — the document is emitted without crosswalk
    fields rather than failing the whole scan. Absence of the top-level
    ``crosswalk`` block is the signal that annotation was skipped.
    """
    from .crosswalk import CrosswalkError, load_crosswalk

    try:
        crosswalk = load_crosswalk(config.crosswalk_path)
    except CrosswalkError:
        return
    document["crosswalk"] = crosswalk.version_block()

    all_findings = (
        [f for a in document.get("agents", []) for f in a.get("findings", [])]
        + document.get("repository_findings", [])
    )
    # rule_id -> its (owasp, eu_ai_act) tags, for the dimension roll-up.
    rule_tags: dict[str, tuple[str, str]] = {}
    for finding in all_findings:
        entry = crosswalk.entry(finding["rule_id"])
        finding["crosswalk"] = entry.to_dict()
        rule_tags[finding["rule_id"]] = (entry.owasp_llm_2025, entry.eu_ai_act)

    summary = document.get("dimension_summary")
    if not summary:
        return
    # For each dimension, union the OWASP/EU tags of every rule that mapped to
    # it (via each finding's `dimensions` array). Roll-up lives on the summary
    # only — per-agent assessment blocks are left unchanged (minimal churn).
    dim_owasp: dict[str, set[str]] = {}
    dim_eu: dict[str, set[str]] = {}
    for finding in all_findings:
        owasp, eu = rule_tags.get(finding["rule_id"], ("", ""))
        for dim_id in finding.get("dimensions", []):
            if owasp:
                dim_owasp.setdefault(dim_id, set()).add(owasp)
            if eu:
                dim_eu.setdefault(dim_id, set()).add(eu)
    for dim in summary.get("dimensions", []):
        dim["crosswalk"] = {
            "owasp_llm_2025": sorted(dim_owasp.get(dim["id"], set()), key=_owasp_sort_key),
            "eu_ai_act": sorted(dim_eu.get(dim["id"], set())),
        }


def _owasp_sort_key(code: str) -> tuple:
    """Sort LLM01..LLM10 numerically, anything else last-alphabetical."""
    if code.startswith("LLM") and code[3:].isdigit():
        return (0, int(code[3:]))
    return (1, code)


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
    all_document_findings = (
        [f for a in document["agents"] for f in a["findings"]] + document["repository_findings"]
    )
    for finding in all_document_findings:
        ref = finding.get("declared_ref")
        if ref and (ref["path"].startswith("/") or ":\\" in ref["path"]):
            raise ValueError(f"declared_ref path is not repository-relative: {ref['path']}")


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
