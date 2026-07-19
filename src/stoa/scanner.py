"""Scan orchestration: traversal → detection → suppression → git → diff → gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import diff as diff_module
from . import git_metadata
from .agent_detection import detect_agents
from .config import StoaConfig, load_config
from .integration_detection import (
    detect_capabilities,
    detect_integrations,
    detect_providers,
)
from .models import (
    AgentCandidate,
    Finding,
    RepositoryInfo,
    ScanResult,
    SkippedFile,
    severity_at_least,
)
from .risk_detection import detect_control_prompts, detect_risks
from .rules import RULES
from .suppressions import parse_suppressions
from .traversal import read_source, traverse


@dataclass
class ScanOptions:
    """Options resolved from the CLI before a scan starts."""

    root: Path
    base: str | None = None
    no_git: bool = False
    config_path: Path | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    fail_on: str | None = None
    fail_on_new: str | None = None
    verbose: bool = False


def run_scan(options: ScanOptions, config: StoaConfig | None = None) -> ScanResult:
    """Execute a full scan and return the in-memory result."""
    root = options.root.resolve()
    if config is None:
        config = load_config(root, options.config_path)
    if options.include:
        config.extra_includes.extend(options.include)
    if options.exclude:
        config.extra_excludes.extend(options.exclude)
    if options.fail_on is not None:
        config.fail_on = options.fail_on
    if options.fail_on_new is not None:
        config.fail_on_new = options.fail_on_new

    files, skipped = traverse(root, config)

    all_findings: list[Finding] = []
    agents: list[AgentCandidate] = []
    warnings: list[str] = []

    use_git = not options.no_git and git_metadata.is_git_repository(root)
    codeowners = git_metadata.load_codeowners(root)

    for source in files:
        content = read_source(source)
        if content is None:
            skipped.append(SkippedFile(source.relative_path, "unreadable"))
            continue

        suppressions = parse_suppressions(content, source.relative_path)
        warnings.extend(suppressions.warnings)

        file_findings = detect_risks(
            content,
            source.relative_path,
            source.language,
            source.is_testlike,
            config,
        )

        detections = detect_agents(content, source.relative_path, source.is_testlike)
        candidate_findings: list[Finding] = []
        file_agents: list[AgentCandidate] = []
        if detections:
            providers = detect_providers(content)
            capabilities = detect_capabilities(content)
            integrations, call_sites = detect_integrations(content)
            for detection in detections:
                if detection.confidence in ("medium", "high"):
                    prompts = detect_control_prompts(
                        content,
                        source.relative_path,
                        detection.symbol,
                        detection.evidence[0].line if detection.evidence else 1,
                        config,
                    )
                else:
                    prompts = []
                candidate_findings.extend(prompts)
                file_agents.append(
                    AgentCandidate(
                        id=detection.id,
                        name=detection.name,
                        symbol=detection.symbol,
                        path=source.relative_path,
                        language=source.language,
                        confidence=detection.confidence,
                        detection_score=detection.detection_score,
                        evidence=detection.evidence,
                        providers=providers,
                        frameworks=detection.frameworks,
                        integrations=integrations,
                        capabilities=capabilities,
                        call_sites=call_sites,
                        findings=prompts,
                    )
                )

        for finding in file_findings + candidate_findings:
            suppressed, reason = suppressions.check(finding.rule_id, finding.line)
            finding.suppressed = suppressed
            finding.suppression_reason = reason

        for agent in file_agents:
            agent.findings = sorted(
                agent.findings + file_findings,
                key=lambda f: (f.line, f.rule_id, f.fingerprint),
            )

        all_findings.extend(file_findings)
        all_findings.extend(candidate_findings)
        agents.extend(file_agents)

    repo_name = root.name
    git_ref: str | None = None
    if use_git:
        repo_name = git_metadata.repository_name(root)
        git_ref = git_metadata.head_ref(root)
        attribution_cache: dict[str, tuple[str | None, object]] = {}
        for agent in agents:
            if agent.path not in attribution_cache:
                attribution_cache[agent.path] = git_metadata.file_attribution(
                    root, agent.path
                )
            author, commit = attribution_cache[agent.path]
            agent.last_touched_by = author
            agent.last_commit = commit  # type: ignore[assignment]

    if codeowners:
        for agent in agents:
            agent.codeowners = git_metadata.codeowners_for(codeowners, agent.path)

    diff_available = False
    if options.base:
        ranges, warning = diff_module.compute_added_ranges(root, options.base)
        if ranges is None:
            if warning:
                warnings.append(warning)
        else:
            diff_module.mark_new_findings(all_findings, ranges)
            diff_available = True

    agents.sort(key=lambda a: (a.path, a.symbol))
    all_findings.sort(key=lambda f: (f.path, f.line, f.rule_id, f.fingerprint))

    return ScanResult(
        repository=RepositoryInfo(
            name=repo_name,
            root=".",
            git_ref=git_ref,
            base_ref=options.base,
        ),
        files_scanned=len(files),
        agents=agents,
        findings=all_findings,
        skipped_files=skipped,
        warnings=warnings,
        diff_available=diff_available,
    )


def gate_findings(result: ScanResult, config: StoaConfig) -> list[Finding]:
    """Findings that trip the configured gate.

    Only unsuppressed, gate-eligible (see RULES), high-confidence findings can
    fail a scan; review prompts and low-confidence matches never gate.
    """
    eligible = [
        f
        for f in result.findings
        if not f.suppressed and RULES[f.rule_id].gateable and f.confidence == "high"
    ]
    tripped: list[Finding] = []
    if config.fail_on != "none":
        tripped.extend(f for f in eligible if severity_at_least(f.severity, config.fail_on))
    if result.diff_available and config.fail_on_new != "none":
        tripped.extend(
            f
            for f in eligible
            if f.is_new and severity_at_least(f.severity, config.fail_on_new) and f not in tripped
        )
    unique: dict[str, Finding] = {f.fingerprint: f for f in tripped}
    return sorted(unique.values(), key=lambda f: (f.path, f.line, f.rule_id))
