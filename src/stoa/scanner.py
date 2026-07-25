"""Scan orchestration: traversal → detection → suppression → git → diff → gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import diff as diff_module
from . import git_metadata
from .agent_detection import detect_agents
from .ai_rules import detect_ai005, detect_ai_correlations
from .ai_taint import detect_ai_taint
from .ast_layer import AstCache
from .autonomy import infer_autonomy
from .dimensions import (
    assess_agent,
    dimension_summary,
    load_taxonomy,
    set_finding_dimensions,
)
from .config import StoaConfig, load_config
from .declarations import (
    Declarations,
    agent_declaration_to_dict,
    evidence_to_dict,
    governance_to_dict,
)
from .integration_detection import (
    detect_capabilities,
    detect_integrations,
    detect_permission_tags,
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
from .risk_detection import (
    detect_control_prompts,
    detect_ctrl005,
    detect_ctrl006,
    detect_risks,
    scan_repo_controls,
)
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
    experimental_ast: bool = False  # deprecated no-op: AST is on by default
    no_ast: bool = False  # opt out of the AST layer (regex-only, no taint rules)
    no_dimensions: bool = False
    no_graph: bool = False
    taxonomy_path: Path | None = None
    declarations_path: Path | None = None


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
    if options.no_graph:
        config.no_graph = True

    files, skipped = traverse(root, config)

    all_findings: list[Finding] = []
    agents: list[AgentCandidate] = []
    warnings: list[str] = []
    degraded_files: list[str] = []
    agent_content: dict[str, str] = {}
    agent_providers: dict[str, list[str]] = {}

    # AST layer is on by default; --no-ast (regex-only) disables it and the
    # taint rules. The legacy --experimental-ast flag is a no-op.
    ast_cache = None if options.no_ast else AstCache()

    use_git = not options.no_git and git_metadata.is_git_repository(root)
    codeowners = git_metadata.load_codeowners(root)

    # Pre-pass: read every file once and learn which controls exist anywhere
    # in the repo, so per-candidate CTRL prompts don't fire for controls that
    # live in middleware/infra (auth on a route decorator, centralized logging).
    file_contents: dict[str, str] = {}
    for source in files:
        content = read_source(source)
        if content is None:
            skipped.append(SkippedFile(source.relative_path, "unreadable"))
        else:
            file_contents[source.relative_path] = content
    repo_controls = scan_repo_controls(list(file_contents.values()))

    for source in files:
        content = file_contents.get(source.relative_path)
        if content is None:
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
        file_findings.extend(
            detect_ai005(content, source.relative_path, source.is_testlike, config)
        )

        providers = detect_providers(content)
        parsed_file = None
        if ast_cache is not None:
            parsed_file = ast_cache.get(source.relative_path, source.language, content)
            if parsed_file.degraded:
                degraded_files.append(source.relative_path)
            file_findings.extend(
                detect_ai_taint(
                    parsed_file, source.relative_path, source.is_testlike, config, providers
                )
            )

        detections = detect_agents(
            content, source.relative_path, source.is_testlike, parsed_file
        )
        candidate_findings: list[Finding] = []
        file_agents: list[AgentCandidate] = []
        if detections:
            capabilities = detect_capabilities(content)
            permission_tags = detect_permission_tags(content, capabilities)
            integrations, call_sites = detect_integrations(content)
            for detection in detections:
                if detection.confidence in ("medium", "high"):
                    anchor = detection.evidence[0].line if detection.evidence else 1
                    prompts = detect_control_prompts(
                        content,
                        source.relative_path,
                        detection.symbol,
                        anchor,
                        config,
                        repo_controls,
                    )
                    prompts += detect_ai_correlations(
                        content,
                        source.relative_path,
                        detection.symbol,
                        capabilities,
                        anchor,
                        config,
                        repo_controls,
                    )
                    prompts += detect_ctrl005(
                        parsed_file, source.relative_path, detection.symbol, config,
                    )
                    prompts += detect_ctrl006(
                        file_findings, content, source.relative_path,
                        detection.symbol, anchor, config,
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
                        permission_tags=permission_tags,
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
        if file_agents:
            agent_content[source.relative_path] = content
            agent_providers[source.relative_path] = providers

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

    all_findings = _apply_supersedes(all_findings)
    for agent in agents:
        agent.findings = _apply_supersedes(agent.findings)

    dim_summary: dict | None = None
    if not options.no_dimensions:
        taxonomy = load_taxonomy(options.taxonomy_path or config.dimensions_taxonomy)
        set_finding_dimensions(all_findings, taxonomy)
        for agent in agents:
            set_finding_dimensions(agent.findings, taxonomy)
            agent.dimension_assessment = assess_agent(
                agent,
                agent_content.get(agent.path, ""),
                agent_providers.get(agent.path, []),
                taxonomy,
            )
        dim_summary = dimension_summary(agents, taxonomy)

    for agent in agents:
        agent.autonomy_level = infer_autonomy(agent, agent_content.get(agent.path, ""))

    agents.sort(key=lambda a: (a.path, a.symbol))
    all_findings.sort(key=lambda f: (f.path, f.line, f.rule_id, f.fingerprint))

    # Declared metadata (schema 1.2, Assurance layer) — opt-in-by-presence.
    # No stoa-declared.toml → every declared field stays absent, zero change
    # to existing output.
    declarations, decl_warnings = Declarations.load(
        options.declarations_path or (root / "stoa-declared.toml")
    )
    business = governance = evidence = None
    if declarations.exists:
        unknown_ids = declarations.unknown_agent_ids({a.id for a in agents})
        if unknown_ids:
            decl_warnings.append(
                f"{declarations.path}: declared agent id(s) not found in this scan: "
                + ", ".join(unknown_ids)
            )
        for agent in agents:
            decl = declarations.agents.get(agent.id)
            if decl is not None:
                agent.declared = agent_declaration_to_dict(decl)
        if declarations.business:
            business = declarations.business
        if declarations.governance is not None:
            governance = governance_to_dict(declarations.governance)
        if declarations.evidence:
            evidence = evidence_to_dict(declarations.evidence)
    warnings.extend(decl_warnings)

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
        degraded_files=degraded_files,
        dimension_summary=dim_summary,
        business=business,
        governance=governance,
        evidence=evidence,
        declaration_warnings=decl_warnings,
    )


def _apply_supersedes(findings: list[Finding]) -> list[Finding]:
    """Drop findings that another finding supersedes at the same path+line.

    Implements the documented dedup relationships so one root cause yields one
    finding: AI002/sql ⊃ SEC003, AI005 insecure-endpoint ⊃ NET001,
    AI006 ⊃ AI004.
    """
    claimed: set[tuple[str, str, int]] = set()
    for finding in findings:
        for ruled in finding.supersedes:
            claimed.add((ruled, finding.path, finding.line))
    if not claimed:
        return findings
    return [f for f in findings if (f.rule_id, f.path, f.line) not in claimed]


def gate_findings(result: ScanResult, config: StoaConfig) -> list[Finding]:
    """Findings that trip the configured gate.

    Only unsuppressed, gate-eligible (see RULES), high-confidence findings can
    fail a scan; review prompts and low-confidence matches never gate.
    """
    def _is_eligible(f: Finding) -> bool:
        if f.suppressed:
            return False
        if f.gate_eligible:  # AI002 exec-class at high confidence
            return True
        if f.rule_id in config.gate_additional_rules and f.confidence == "high":
            return True
        if f.rule_id.startswith("AI"):
            # AI rules gate only via gate_eligible or an explicit opt-in, never
            # from RULES.gateable alone (an unproven pattern must not fail a build).
            return False
        return RULES[f.rule_id].gateable and f.confidence == "high"

    eligible = [f for f in result.findings if _is_eligible(f)]
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
