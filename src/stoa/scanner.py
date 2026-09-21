"""Scan orchestration: traversal → detection → suppression → git → diff → gate."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import diff as diff_module
from . import git_metadata
from .agent_detection import detect_agents
from .iac import detect_iac_plan, detect_iac_tree
from .imports import build_import_graph
from .tools import bind_agent_tools, collect_tools, detect_ai008
from .ai_rules import detect_ai005, detect_ai_correlations
from .ai_taint import detect_ai_taint
from .ast_layer import AstCache
from .autonomy import infer_autonomy
from .dimensions import (
    observed_controls,
    assess_agent,
    dimension_summary,
    load_taxonomy,
    set_finding_dimensions,
)
from .config import StoaConfig, load_config
from .contradiction_rules import detect_agent_contradictions, detect_stale_declarations
from .declarations import (
    Declarations,
    agent_declaration_to_dict,
    evidence_to_dict,
    governance_to_dict,
    risk_register_entry_to_dict,
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
    tf_plan: Path | None = None  # `terraform show -json` output; replaces .tf-based agent discovery


# Names too generic to disambiguate agents on their own (Task 1). A bare
# framework token like these tells a reader nothing when three agents share it.
_GENERIC_AGENT_NAMES = frozenset({
    "agent", "bot", "assistant", "crew", "executor", "chain", "runnable",
    "app", "graph", "workflow", "pipeline", "handler", "main",
})


def _disambiguate_agent_names(agents: list[AgentCandidate]) -> None:
    """Assign each candidate a human-facing display_name (Task 1).

    Qualify with the source-file stem when the raw name is generic or collides
    with another candidate in the same scan: `payments·agent`, `devops·agent`.
    Unique, specific names are left as-is. Deterministic: depends only on the
    (name, path) set, not on scan order. `name`/`symbol` are untouched so
    `stoa diff` (which keys on `id`) never churns on a label change.
    """
    from pathlib import PurePosixPath

    counts: dict[str, int] = {}
    for agent in agents:
        counts[agent.name] = counts.get(agent.name, 0) + 1

    for agent in agents:
        generic = agent.name.lower() in _GENERIC_AGENT_NAMES
        collides = counts.get(agent.name, 0) > 1
        if generic or collides:
            stem = PurePosixPath(agent.path).stem
            agent.display_name = f"{stem}·{agent.name}" if stem else agent.name
        else:
            agent.display_name = agent.name


_NEIGHBOR_CONTROLS = frozenset({"authentication", "validation", "rate_limit", "observability"})


def _detect_from_plan(plan_path: Path, root: Path, warnings: list[str]):
    """Load `terraform show -json` output and run IaC detection over it."""
    import json as _json

    try:
        doc = _json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warnings.append(f"--tf-plan {plan_path}: could not read plan JSON ({exc.__class__.__name__}); "
                        "no IaC agents from plan")
        return []
    if not isinstance(doc, dict):
        warnings.append(f"--tf-plan {plan_path}: not a Terraform plan document; no IaC agents from plan")
        return []
    try:
        rel = Path(plan_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = Path(plan_path).name                     # outside the repo: keep output repo-relative
    return detect_iac_plan(doc, rel)


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
    # Tools as first-class objects (0.7.4): every tool definition in the repo,
    # then bound to agents through the one-hop import graph.
    import_graph = build_import_graph(file_contents)
    tool_index = collect_tools(file_contents)
    # Controls stated explicitly by infrastructure (IaC), keyed by agent id,
    # injected into dimension scoring alongside code-observed controls.
    iac_controls: dict[str, set[str]] = {}
    tf_modules: dict[str, list[tuple[str, str]]] = {}          # directory -> [(path, content)]
    tf_findings_by_path: dict[str, list[Finding]] = {}

    for source in files:
        content = file_contents.get(source.relative_path)
        if content is None:
            continue


        suppressions = parse_suppressions(content, source.relative_path)
        warnings.extend(suppressions.warnings)

        if source.language == "terraform":
            # IaC collector: agents *configured* in infrastructure code. The
            # core regex rules (hardcoded secrets, insecure endpoints) still
            # apply to HCL — a literal API key in a .tf is a leak like any
            # other, redacted at match time exactly as in code. AI taint and
            # CTRL prompts are code concepts and stay off for this file type.
            # Agent detection itself runs per *module* (all .tf in a directory)
            # after the loop, because real deployments split the agent, its
            # IAM, and its guardrail across files.
            tf_findings = detect_risks(
                content, source.relative_path, source.language, source.is_testlike, config,
            )
            for finding in tf_findings:
                suppressed, reason = suppressions.check(finding.rule_id, finding.line)
                finding.suppressed = suppressed
                finding.suppression_reason = reason
            all_findings.extend(tf_findings)
            if config.iac_enabled:
                module_dir = source.relative_path.rsplit("/", 1)[0] if "/" in source.relative_path else ""
                tf_modules.setdefault(module_dir, []).append((source.relative_path, content))
                tf_findings_by_path[source.relative_path] = tf_findings
            continue

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
            bound_tools = bind_agent_tools(content, source.relative_path, tool_index, import_graph)
            capabilities = sorted(
                set(detect_capabilities(content)) | {c for t in bound_tools for c in t.capabilities}
            )
            permission_tags = detect_permission_tags(content, capabilities)
            integrations, call_sites = detect_integrations(content)
            for t in bound_tools:
                for integ in t.integrations:
                    if integ not in integrations:
                        integrations.append(integ)
            integrations.sort()
            tool_records = [t.to_dict() for t in bound_tools]
            tool_findings = detect_ai008(bound_tools, content, config)
            candidate_findings.extend(tool_findings)
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
                prompts = prompts + list(tool_findings)
                candidate_findings.extend(prompts[:len(prompts) - len(tool_findings)])
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
                        tools=tool_records,
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

    if options.tf_plan is not None:
        # A plan carries fully resolved values and module instances; it replaces
        # file-based discovery so the same resource is never counted twice.
        iac_detections = _detect_from_plan(options.tf_plan, root, warnings) if config.iac_enabled else []
    else:
        iac_detections = detect_iac_tree(tf_modules) if tf_modules else []
    for det in iac_detections:
        agents.append(
            AgentCandidate(
                id=det.id,
                name=det.name,
                symbol=det.symbol,
                path=det.path,
                language="terraform",
                confidence=det.confidence,
                detection_score=det.detection_score,
                evidence=det.evidence,
                providers=det.providers,
                frameworks=det.frameworks,
                integrations=det.integrations,
                capabilities=det.capabilities,
                permission_tags=[],
                call_sites={},
                findings=sorted(
                    tf_findings_by_path.get(det.path, []),
                    key=lambda f: (f.line, f.rule_id, f.fingerprint),
                ),
                source=det.source,
                discovery_tier=det.discovery_tier,
                platform=det.platform,
                tools=det.tools,
            )
        )
        iac_controls[det.id] = det.controls
        agent_content[det.path] = file_contents.get(det.path, "")
        agent_providers[det.path] = sorted(
            set(agent_providers.get(det.path, [])) | set(det.providers)
        )

    _disambiguate_agent_names(agents)

    repo_name = root.name
    git_ref: str | None = None
    head_commit = None
    if use_git:
        repo_name = git_metadata.repository_name(root)
        git_ref = git_metadata.head_ref(root)
        head_commit = git_metadata.head_commit(root)
        attribution_cache: dict[str, tuple[str | None, object]] = {}
        for agent in agents:
            if agent.path not in attribution_cache:
                attribution_cache[agent.path] = git_metadata.file_attribution(
                    root, agent.path
                )
            author, commit = attribution_cache[agent.path]
            agent.last_touched_by = author
            agent.last_commit = commit  # type: ignore[assignment]
    if config.repository_name:
        repo_name = config.repository_name

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

    for agent in agents:
        agent.autonomy_level = infer_autonomy(agent, agent_content.get(agent.path, ""))

    # Declared metadata (schema 1.2, Assurance layer) — opt-in-by-presence.
    # No stoa-declared.toml → every declared field stays absent, zero change
    # to existing output.
    declarations, decl_warnings = Declarations.load(
        options.declarations_path or (root / "stoa-declared.toml")
    )
    business = governance = evidence = None
    unknown_ids: list[str] = []
    risk_register: list[dict] = []
    try:
        declarations_path_str = str(declarations.path.relative_to(root))
    except ValueError:
        declarations_path_str = declarations.path.name
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
        if declarations.risk_register:
            known_agent_ids = {a.id for a in agents}
            for entry in declarations.risk_register:
                _, _, agent_part = entry.risk_id.partition("/")
                if agent_part and agent_part not in known_agent_ids:
                    decl_warnings.append(
                        f"{declarations_path_str}: risk_register entry {entry.risk_id!r} names an "
                        "agent id not found in this scan"
                    )
                risk_register.append(risk_register_entry_to_dict(entry))
    warnings.extend(decl_warnings)

    # Contradiction detector (Assurance layer Phase 4) — declared vs. scanned.
    # Runs after autonomy inference and declared-metadata attachment, before
    # dimension tagging, so DECL findings get dimension-tagged like any other.
    for agent in agents:
        contradictions = detect_agent_contradictions(
            agent, declarations_path_str, declarations.exists, config,
        )
        if contradictions:
            agent.findings = sorted(
                agent.findings + contradictions,
                key=lambda f: (f.line, f.rule_id, f.fingerprint),
            )
            all_findings.extend(contradictions)
    if declarations.exists and unknown_ids:
        stale_findings = detect_stale_declarations(unknown_ids, declarations_path_str, config)
        all_findings.extend(stale_findings)

    dim_summary: dict | None = None
    if not options.no_dimensions:
        taxonomy = load_taxonomy(options.taxonomy_path or config.dimensions_taxonomy)
        set_finding_dimensions(all_findings, taxonomy)
        # Controls one import hop away (the route/middleware that fronts an
        # agent) are credited to it — the agent is covered by them even though
        # its own file never names them. IaC agents keep their stated controls.
        neighbor_cache: dict[str, set[str]] = {}
        for agent in agents:
            set_finding_dimensions(agent.findings, taxonomy)
            extra = iac_controls.get(agent.id)
            if agent.source == "code":
                if agent.path not in neighbor_cache:
                    found: set[str] = set()
                    for other in import_graph.get(agent.path, ()):
                        # operational controls travel across the import edge;
                        # approval is agent-local semantics and does not
                        found |= observed_controls(file_contents.get(other, "")) & _NEIGHBOR_CONTROLS
                    neighbor_cache[agent.path] = found
                extra = neighbor_cache[agent.path]
            agent.dimension_assessment = assess_agent(
                agent,
                agent_content.get(agent.path, ""),
                agent_providers.get(agent.path, []),
                taxonomy,
                extra_controls=extra,
            )
        dim_summary = dimension_summary(agents, taxonomy)

    agents.sort(key=lambda a: (a.path, a.symbol))
    all_findings.sort(key=lambda f: (f.path, f.line, f.rule_id, f.fingerprint))

    return ScanResult(
        repository=RepositoryInfo(
            name=repo_name,
            root=".",
            git_ref=git_ref,
            base_ref=options.base,
            head_commit=head_commit,
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
        risk_register=risk_register,
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
