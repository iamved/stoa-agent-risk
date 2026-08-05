"""The ``stoa`` command-line interface.

Exit codes:
    0  scan completed and the gate passed
    1  findings exceeded the configured gate
    2  invalid arguments or configuration
    3  scanner execution error
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .approvals import Approval, Approvals
from .config import FAIL_LEVELS, ConfigError, load_config
from .dimensions import TaxonomyError
from .registry_diff import (
    TaxonomyMismatch,
    diff_registries,
    dimension_increase_exceeds,
    render_changelog,
)
from .report_json import _atomic_write
from .github import emit_annotations, write_summary
from .models import SEVERITIES, ScanResult
from .report_html import write_html
from .report_json import write_json
from .scanner import ScanOptions, gate_findings, run_scan

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2
EXIT_ERROR = 3

INIT_FILES = {
    ".github/workflows/stoa.yml": "stoa.yml",
    ".stoaignore": "stoaignore",
    "stoa.toml": "stoa.toml",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stoa",
        description=(
            "Local-first AI agent inventory and risk scanner. Identifies agent "
            "candidates with supporting evidence, maps capabilities and "
            "integrations, and gates newly introduced high-confidence critical risks."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"stoa {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command")

    scan = subparsers.add_parser("scan", help="Scan a repository")
    scan.add_argument("path", nargs="?", default=".", help="Repository root (default: .)")
    scan.add_argument("--html", metavar="PATH", default="stoa-report.html",
                      help="HTML report path (default: stoa-report.html)")
    scan.add_argument("--json", metavar="PATH", default="stoa-registry.json",
                      help="JSON output path (default: stoa-registry.json)")
    scan.add_argument("--base", metavar="GIT_REF", default=None,
                      help="Base git ref for diff-aware gating (e.g. origin/main)")
    scan.add_argument("--strict", action="store_true",
                      help="Fail on all unsuppressed high-confidence critical findings")
    scan.add_argument("--fail-on", choices=FAIL_LEVELS, default=None,
                      help="Fail on all findings at or above this severity")
    scan.add_argument("--fail-on-new", choices=FAIL_LEVELS, default=None,
                      help="Fail only on new findings relative to --base")
    scan.add_argument("--github-annotations", action="store_true",
                      help="Emit GitHub workflow-command annotations")
    scan.add_argument("--summary-file", metavar="PATH", default=None,
                      help="Write a GitHub job summary (Markdown) to PATH")
    scan.add_argument("--sarif", metavar="PATH", default=None,
                      help="Write a SARIF 2.1.0 log (with stoa-dim:* tags) to PATH")
    scan.add_argument("--config", metavar="PATH", default=None,
                      help="Path to stoa.toml (default: <root>/stoa.toml)")
    scan.add_argument("--no-git", action="store_true",
                      help="Disable git metadata collection")
    scan.add_argument("--include", metavar="PATH_PATTERN", action="append", default=[],
                      help="Only scan paths matching this pattern (repeatable)")
    scan.add_argument("--exclude", metavar="PATH_PATTERN", action="append", default=[],
                      help="Additionally exclude paths matching this pattern (repeatable)")
    scan.add_argument("--verbose", action="store_true", help="Verbose output")
    scan.add_argument("--quiet", action="store_true", help="Only print gate failures and errors")
    scan.add_argument("--experimental-ast", action="store_true",
                      help="(deprecated no-op) the AST layer is on by default")
    scan.add_argument("--no-ast", action="store_true",
                      help="Disable the tree-sitter AST layer and all flow-based "
                           "(AI001/AI002/AI004/AI006) rules; run regex-only")
    scan.add_argument("--no-dimensions", action="store_true",
                      help="Skip the dimension exposure assessment and matrix")
    scan.add_argument("--no-graph", action="store_true",
                      help="Skip the architecture graph section in the HTML report")
    scan.add_argument("--taxonomy", metavar="PATH", default=None,
                      help="Custom dimension taxonomy TOML (replaces the default)")
    scan.add_argument("--with-runtime", metavar="TRACES_DIR", default=None,
                      help="Enrich the registry/report with local runtime traces "
                           "(stoa-trace/1.0) after the scan — additive, shadow mode")

    scan.add_argument("--diff-against", metavar="GIT_REF", default=None,
                      help="Scan the worktree, then diff agent reach against GIT_REF")
    scan.add_argument("--diff-json", metavar="PATH", default=None,
                      help="With --diff-against: write the stoa-diff/1.0 JSON")
    scan.add_argument("--diff-md", metavar="PATH", default=None,
                      help="With --diff-against: write the Markdown changelog")
    scan.add_argument("--fail-on-drift", choices=["none", "low", "medium", "high"], default="none",
                      help="With --diff-against: fail if unapproved drift ≥ this level")
    scan.add_argument("--fail-on-dimension-increase", metavar="DIM=LEVEL", default=None)
    scan.add_argument("--approvals", metavar="PATH", default=".stoa/approvals.toml")

    init = subparsers.add_parser("init", help="Generate integration files")
    init.add_argument("target", choices=["github", "declarations", "runtime"],
                      help="Integration to initialize. 'declarations' requires a prior "
                           "`stoa scan` — it stubs out stoa-declared.toml with real agent ids. "
                           "'runtime' scaffolds [runtime] config + an instrumentation example.")
    init.add_argument("--force", action="store_true",
                      help="Overwrite existing files")
    init.add_argument("--registry", metavar="PATH", default="stoa-registry.json",
                      help="With 'declarations': registry to read agent ids from")

    diff = subparsers.add_parser("diff", help="Diff agent reach between two registries")
    diff.add_argument("base", nargs="?", help="Base stoa-registry.json (omit in --base-ref mode)")
    diff.add_argument("head", nargs="?", help="Head registry (default: scan the worktree)")
    diff.add_argument("--base-ref", metavar="GIT_REF", default=None,
                      help="Reconstruct the base by scanning GIT_REF in a temp worktree")
    diff.add_argument("--json", metavar="PATH", default=None, help="Write the stoa-diff/1.0 JSON")
    diff.add_argument("--md", metavar="PATH", default=None, help="Write the Markdown changelog")
    diff.add_argument("--summary", action="store_true", help="One-line terminal summary only")
    diff.add_argument("--fail-on-drift", choices=["none", "low", "medium", "high"], default="none")
    diff.add_argument("--fail-on-dimension-increase", metavar="DIM=LEVEL", default=None)
    diff.add_argument("--approvals", metavar="PATH", default=".stoa/approvals.toml")
    diff.add_argument("--config", metavar="PATH", default=None)
    diff.add_argument("--no-git", action="store_true")

    graph = subparsers.add_parser("graph", help="Render the architecture graph")
    graph.add_argument("registry", nargs="?", default=None,
                       help="stoa-registry.json to render (default: scan the worktree)")
    graph.add_argument("--format", choices=["mermaid"], default="mermaid",
                       help="Output format (default: mermaid)")
    graph.add_argument("--out", metavar="PATH", default=None,
                       help="Write output to PATH (default: stdout)")
    graph.add_argument("--focus", metavar="AGENT_ID", default=None,
                       help="Render only this node's direct neighbors")
    graph.add_argument("--config", metavar="PATH", default=None)
    graph.add_argument("--no-git", action="store_true")

    export = subparsers.add_parser("export", help="Export a downstream artifact (assurance packet)")
    export.add_argument("registry", nargs="?", default=None,
                        help="stoa-registry.json to export from (default: scan the worktree)")
    export.add_argument("--assurance", action="store_true", required=True,
                        help="Export the 14-area assurance packet (the only export kind today)")
    export.add_argument("--format", choices=["json", "md"], default="md",
                        help="Output format (default: md)")
    export.add_argument("--out", metavar="PATH", default=None,
                        help="Write output to PATH (default: stdout)")
    export.add_argument("--config", metavar="PATH", default=None)
    export.add_argument("--no-git", action="store_true")

    approve = subparsers.add_parser("approve", help="Record an intentional drift approval")
    approve.add_argument("--agent", metavar="NAME", help="Agent name (informational)")
    approve.add_argument("--agent-id", metavar="ID", help="Stable agent id to bind to")
    approve.add_argument("--capability", metavar="VALUE", default=None)
    approve.add_argument("--integration", metavar="VALUE", default=None)
    approve.add_argument("--provider", metavar="VALUE", default=None)
    approve.add_argument("--new-agent", action="store_true")
    approve.add_argument("--reason", metavar="TEXT", default="")
    approve.add_argument("--by", metavar="HANDLE", default="")
    approve.add_argument("--expires", metavar="YYYY-MM-DD", default=None)
    approve.add_argument("--list", action="store_true", help="List active/stale/expired approvals")
    approve.add_argument("--approvals", metavar="PATH", default=".stoa/approvals.toml")

    # --- stoa runtime: the trace overlay (shadow mode — observe, never enforce)
    runtime = subparsers.add_parser(
        "runtime",
        help="Analyze local runtime traces (stoa-trace/1.0) against the registry",
    )
    rt_sub = runtime.add_subparsers(dest="runtime_command")

    rt_analyze = rt_sub.add_parser(
        "analyze", help="Summarize observed agent behavior from local trace files"
    )
    rt_analyze.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_analyze.add_argument("--registry", metavar="PATH", default=None,
                            help="stoa-registry.json to correlate against")
    rt_analyze.add_argument("--out", metavar="PATH", default="stoa-runtime.json")
    rt_analyze.add_argument("--quiet", action="store_true")

    rt_map = rt_sub.add_parser(
        "map", help="Suggest registry agent ids for unmatched trace spans"
    )
    rt_map.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_map.add_argument("--registry", metavar="PATH", required=True)

    rt_merge = rt_sub.add_parser(
        "merge", help="Enrich a registry with runtime_evidence blocks (additive)"
    )
    rt_merge.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_merge.add_argument("--registry", metavar="PATH", required=True)
    rt_merge.add_argument("--out", metavar="PATH", default="stoa-registry-enriched.json")
    rt_merge.add_argument("--in-place", action="store_true",
                          help="Overwrite --registry instead of writing --out")
    rt_merge.add_argument("--config", metavar="PATH", default=None,
                          help="stoa.toml with [runtime] suppression/severity settings")

    rt_baseline = rt_sub.add_parser(
        "baseline", help="Compute a behavioral baseline (commit it like approvals)"
    )
    rt_baseline.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_baseline.add_argument("--registry", metavar="PATH", default=None)
    rt_baseline.add_argument("--out", metavar="PATH", default=".stoa/baseline.json")

    rt_drift = rt_sub.add_parser(
        "drift", help="Compare live behavior to a committed baseline (shadow mode)"
    )
    rt_drift.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_drift.add_argument("--baseline", metavar="PATH", default=".stoa/baseline.json")
    rt_drift.add_argument("--registry", metavar="PATH", default=None)
    rt_drift.add_argument("--out", metavar="PATH", default=None,
                          help="Write the runtime-drift/1.0 JSON here")
    rt_drift.add_argument("--fail-on-drift", choices=["info", "medium", "high"],
                          default=None,
                          help="Exit 1 at/above this drift class (default: report-only)")
    rt_drift.add_argument("--config", metavar="PATH", default=None,
                          help="stoa.toml with [runtime.drift] thresholds")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return EXIT_USAGE

    try:
        if args.command == "scan":
            return _run_scan_command(args)
        if args.command == "init":
            return _run_init_command(args)
        if args.command == "diff":
            return _run_diff_command(args)
        if args.command == "graph":
            return _run_graph_command(args)
        if args.command == "export":
            return _run_export_command(args)
        if args.command == "approve":
            return _run_approve_command(args)
        if args.command == "runtime":
            return _run_runtime_command(args)
    except ConfigError as exc:
        print(f"stoa: configuration error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except TaxonomyError as exc:
        print(f"stoa: taxonomy error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except TaxonomyMismatch as exc:
        print(f"stoa: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("stoa: interrupted", file=sys.stderr)
        return EXIT_ERROR
    except Exception as exc:  # noqa: BLE001 - top-level boundary, no traceback for users
        print(f"stoa: scan failed: {exc.__class__.__name__}: {exc}", file=sys.stderr)
        if getattr(args, "verbose", False):
            raise
        return EXIT_ERROR
    return EXIT_USAGE


def _run_scan_command(args: argparse.Namespace) -> int:
    root = Path(args.path)
    if not root.is_dir():
        print(f"stoa: not a directory: {args.path}", file=sys.stderr)
        return EXIT_USAGE
    if args.quiet and args.verbose:
        print("stoa: --quiet and --verbose are mutually exclusive", file=sys.stderr)
        return EXIT_USAGE

    fail_on = args.fail_on
    if args.strict:
        fail_on = "critical"

    config = load_config(root.resolve(), Path(args.config) if args.config else None)
    options = ScanOptions(
        root=root,
        base=args.base,
        no_git=args.no_git,
        config_path=Path(args.config) if args.config else None,
        include=args.include,
        exclude=args.exclude,
        fail_on=fail_on,
        fail_on_new=args.fail_on_new,
        verbose=args.verbose,
        experimental_ast=args.experimental_ast,
        no_ast=args.no_ast,
        no_dimensions=args.no_dimensions,
        no_graph=args.no_graph,
        taxonomy_path=Path(args.taxonomy) if args.taxonomy else None,
    )
    result = run_scan(options, config)

    json_path = Path(args.json)
    html_path = Path(args.html)
    if args.with_runtime:
        # Runtime overlay ride-along: scan as normal, then enrich the just-
        # built document with local trace evidence before writing. Fail-open:
        # missing/empty traces warn and still produce a valid (merely
        # runtime-thin) registry — never a failed scan.
        from datetime import datetime, timezone

        from .report_json import build_document
        from .runtime.analysis import analyze_traces
        from .runtime.merge import merge_runtime_into_registry

        document = build_document(result, config)
        analysis = analyze_traces(
            args.with_runtime, document,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        for warning in analysis["header"]["warnings"]:
            print(f"stoa: warning: {warning}", file=sys.stderr)
        enriched = merge_runtime_into_registry(document, analysis, config)
        text = json.dumps(enriched, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        _atomic_write(json_path, text)
        write_html(result, config, html_path, document=enriched)
    else:
        write_json(result, config, json_path)
        write_html(result, config, html_path)
    if args.summary_file:
        write_summary(result, Path(args.summary_file))
    if args.sarif:
        from .sarif import write_sarif
        write_sarif(result, Path(args.sarif))
    if args.github_annotations:
        emit_annotations(result, sys.stdout)

    for warning in result.warnings:
        print(f"stoa: warning: {warning}", file=sys.stderr)

    if args.strict and result.declaration_warnings:
        print(
            f"stoa: --strict: {len(result.declaration_warnings)} stoa-declared.toml "
            "issue(s) treated as errors (see warnings above)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    tripped = gate_findings(result, config)
    if not args.quiet:
        _print_scan_summary(result, args, json_path, html_path)
    if tripped:
        print(
            f"stoa: gate failed: {len(tripped)} finding"
            f"{'s' if len(tripped) != 1 else ''} at or above the configured threshold:",
            file=sys.stderr,
        )
        for finding in tripped:
            print(
                f"  {finding.severity.upper()} {finding.rule_id} "
                f"{finding.path}:{finding.line} {finding.title}",
                file=sys.stderr,
            )
        return EXIT_GATE_FAILED

    if args.diff_against:
        return _scan_diff_against(result, config, args)
    return EXIT_OK


def _scan_diff_against(result, config, args) -> int:
    """`stoa scan --diff-against REF`: diff the fresh scan against a git ref."""
    from .report_json import build_document
    head_doc = build_document(result, config)
    base_doc = _scan_ref_registry(Path(args.path), args.diff_against, config)
    if base_doc is None:
        print(f"stoa: warning: base ref {args.diff_against!r} unresolvable — "
              "drift gate skipped", file=sys.stderr)
        return EXIT_OK
    return _emit_diff(base_doc, head_doc, approvals_path=Path(args.approvals),
                      json_out=args.diff_json, md_out=args.diff_md, summary_only=False,
                      fail_on_drift=args.fail_on_drift,
                      dim_gate=args.fail_on_dimension_increase)


def _scan_ref_registry(root: Path, ref: str, config):
    """Scan REF in a temp git worktree with the current scanner; None if unresolvable."""
    import subprocess
    import tempfile
    from .report_json import build_document
    root = root.resolve()
    check = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                           capture_output=True, text=True)
    if check.returncode != 0:
        return None
    tmp = tempfile.mkdtemp(prefix="stoa-diff-")
    try:
        add = subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", tmp, ref],
                             capture_output=True, text=True)
        if add.returncode != 0:
            return None
        base_result = run_scan(ScanOptions(root=Path(tmp), no_git=True), config)
        return build_document(base_result, config)
    finally:
        subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", tmp],
                       capture_output=True, text=True)


def _emit_diff(base_doc, head_doc, *, approvals_path, json_out, md_out, summary_only,
               fail_on_drift, dim_gate) -> int:
    from .registry_diff import DRIFT_ORDER
    approvals = Approvals.load(approvals_path)
    diff = diff_registries(base_doc, head_doc, approvals)
    if json_out:
        _atomic_write(Path(json_out), json.dumps(diff, indent=2, ensure_ascii=False) + "\n")
    if md_out:
        _atomic_write(Path(md_out), render_changelog(diff, fail_on_drift))

    s = diff["summary"]
    if not summary_only:
        print(f"stoa diff: {s['agents_changed']} changed, {s['agents_added']} added, "
              f"{s['agents_removed']} removed · max drift {s['max_drift_severity']} "
              f"(unapproved {s['unapproved_max_drift_severity']})", file=sys.stderr)
    else:
        print(f"drift {s['max_drift_severity']} (unapproved {s['unapproved_max_drift_severity']})")

    tripped = False
    if fail_on_drift != "none":
        if DRIFT_ORDER.index(s["unapproved_max_drift_severity"]) >= DRIFT_ORDER.index(fail_on_drift):
            tripped = True
            print(f"stoa: gate failed: unapproved drift {s['unapproved_max_drift_severity']} "
                  f">= {fail_on_drift}", file=sys.stderr)
    if dim_gate and "=" in dim_gate:
        dim_id, level = dim_gate.split("=", 1)
        if dimension_increase_exceeds(diff, dim_id, level):
            tripped = True
            print(f"stoa: gate failed: dimension {dim_id} increased to ≥ {level}", file=sys.stderr)
    return EXIT_GATE_FAILED if tripped else EXIT_OK


def _run_diff_command(args: argparse.Namespace) -> int:
    config = load_config(Path(".").resolve(), Path(args.config) if args.config else None)
    if args.base_ref:
        head_doc = _load_or_scan_head(args, config)
        base_doc = _scan_ref_registry(Path("."), args.base_ref, config)
        if base_doc is None:
            print(f"stoa: warning: base ref {args.base_ref!r} unresolvable — "
                  "drift gate skipped", file=sys.stderr)
            return EXIT_OK
    else:
        if not args.base:
            print("stoa: diff needs BASE and HEAD registries, or --base-ref", file=sys.stderr)
            return EXIT_USAGE
        base_doc = json.loads(Path(args.base).read_text(encoding="utf-8"))
        head_doc = _load_or_scan_head(args, config)
    return _emit_diff(base_doc, head_doc, approvals_path=Path(args.approvals),
                      json_out=args.json, md_out=args.md, summary_only=args.summary,
                      fail_on_drift=args.fail_on_drift,
                      dim_gate=args.fail_on_dimension_increase)


def _load_or_scan_head(args, config) -> dict:
    from .report_json import build_document
    if getattr(args, "head", None):
        return json.loads(Path(args.head).read_text(encoding="utf-8"))
    result = run_scan(ScanOptions(root=Path("."), no_git=args.no_git), config)
    return build_document(result, config)


def _run_graph_command(args: argparse.Namespace) -> int:
    from .graph_mermaid import render_mermaid
    from .graph_model import build_graph, overlay_runtime
    from .report_json import build_document

    config = load_config(Path(".").resolve(), Path(args.config) if args.config else None)
    if args.registry:
        registry_path = Path(args.registry)
        if not registry_path.is_file():
            print(f"stoa: registry not found: {args.registry}", file=sys.stderr)
            return EXIT_USAGE
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        result = run_scan(ScanOptions(root=Path("."), no_git=args.no_git), config)
        document = build_document(result, config)

    graph = build_graph(document)
    if document.get("runtime"):  # enriched registry: overlay observed evidence
        graph = overlay_runtime(graph, document)
    if graph.is_empty:
        print("stoa: no agent candidates detected — nothing to graph", file=sys.stderr)

    if args.focus and not any(n.id == args.focus for n in graph.nodes):
        print(f"stoa: warning: focus id not found in graph: {args.focus}", file=sys.stderr)

    output = render_mermaid(graph, focus=args.focus)
    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"stoa: wrote {args.out}")
    else:
        print(output, end="")
    return EXIT_OK


def _run_export_command(args: argparse.Namespace) -> int:
    # TODO(assurance-sign): a --sign flag belongs here once a signing
    # mechanism (e.g. `stoa attest`) exists in this repo. It doesn't today —
    # deliberately deferred rather than half-implemented.
    from datetime import datetime, timezone

    from .assurance import build_assurance_packet, render_assurance_markdown
    from .report_json import build_document

    config = load_config(Path(".").resolve(), Path(args.config) if args.config else None)
    if args.registry:
        registry_path = Path(args.registry)
        if not registry_path.is_file():
            print(f"stoa: registry not found: {args.registry}", file=sys.stderr)
            return EXIT_USAGE
        document = json.loads(registry_path.read_text(encoding="utf-8"))
    else:
        result = run_scan(ScanOptions(root=Path("."), no_git=args.no_git), config)
        document = build_document(result, config)

    git_sha = (document.get("repository") or {}).get("git_ref")
    scan_timestamp = datetime.now(timezone.utc).isoformat()
    packet = build_assurance_packet(document, git_sha=git_sha, scan_timestamp=scan_timestamp)

    if args.format == "json":
        output = json.dumps(packet, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    else:
        output = render_assurance_markdown(packet)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"stoa: wrote {args.out}")
    else:
        print(output, end="")

    if packet["header"]["contradiction_count"]:
        print(
            f"stoa: {packet['header']['contradiction_count']} contradiction(s) found "
            "(see the Contradictions section)",
            file=sys.stderr,
        )
    return EXIT_OK


def _run_approve_command(args: argparse.Namespace) -> int:
    approvals = Approvals.load(Path(args.approvals))
    if args.list:
        recs = approvals.records()
        if not recs:
            print("No approvals recorded.")
            return EXIT_OK
        for r in recs:
            status = "expired" if r.is_expired() else "active"
            print(f"  [{status}] {r.agent_name or r.agent_id} · {r.kind}={r.value} "
                  f"· by {r.approved_by} · {r.reason}")
        return EXIT_OK

    kind, value = None, None
    for k, v in (("capability", args.capability), ("integration", args.integration),
                 ("provider", args.provider)):
        if v:
            kind, value = k, v
    if args.new_agent:
        kind, value = "new-agent", args.agent
    if not kind or not value:
        print("stoa: approve needs one of --capability/--integration/--provider/--new-agent",
              file=sys.stderr)
        return EXIT_USAGE
    if not args.agent_id and not args.agent:
        print("stoa: approve needs --agent or --agent-id", file=sys.stderr)
        return EXIT_USAGE

    approval = Approval(
        agent_id=args.agent_id or args.agent, agent_name=args.agent or "",
        kind=kind, value=value, reason=args.reason, approved_by=args.by,
        expires=args.expires,
    )
    approvals.add(approval)
    approvals.write()
    print(f"Recorded approval: {approval.agent_name or approval.agent_id} · "
          f"{kind}={value} · by {args.by or '(unset)'}")
    print(f"Wrote {args.approvals} — commit it; the CODEOWNERS reviewer for .stoa/ "
          "gates the PR.")
    return EXIT_OK


def _run_init_declarations(args: argparse.Namespace) -> int:
    from .declarations import generate_stub

    registry_path = Path(args.registry)
    if not registry_path.is_file():
        print(
            f"stoa: init declarations needs a registry — run `stoa scan` first "
            f"(looked for {args.registry})",
            file=sys.stderr,
        )
        return EXIT_USAGE
    document = json.loads(registry_path.read_text(encoding="utf-8"))
    target = Path("stoa-declared.toml")
    if target.exists() and not args.force:
        print(f"skipped:     {target} (already exists; use --force to overwrite)")
        return EXIT_OK
    existed = target.exists()
    target.write_text(generate_stub(document.get("agents", [])), encoding="utf-8")
    print(f"{'overwritten:' if existed else 'created:    '} {target}")
    print(f"\n{len(document.get('agents', []))} agent id(s) stubbed from {args.registry}. "
          "Uncomment and fill in what you know; commit the file — it's reviewed like code.")
    return EXIT_OK


def _print_scan_summary(
    result: ScanResult, args: argparse.Namespace, json_path: Path, html_path: Path
) -> None:
    counts = result.severity_counts()
    parts = [
        f"{counts.get(severity, 0)} {severity}"
        for severity in reversed(SEVERITIES)
        if counts.get(severity, 0)
    ]
    high_confidence = sum(1 for a in result.agents if a.confidence == "high")
    print(f"stoa {__version__} — scanned {result.files_scanned} files")
    print(f"Agent candidates: {len(result.agents)} ({high_confidence} high confidence)")
    print(
        "Findings: "
        + (", ".join(parts) if parts else "none")
        + f" ({result.suppressed_count()} suppressed)"
    )
    if result.diff_available:
        new_counts = result.new_severity_counts()
        new_parts = [
            f"{new_counts.get(severity, 0)} {severity}"
            for severity in reversed(SEVERITIES)
            if new_counts.get(severity, 0)
        ]
        print(
            f"New findings vs {result.repository.base_ref}: "
            + (", ".join(new_parts) if new_parts else "none")
        )
    print(f"Reports: {html_path}, {json_path}")
    if args.verbose and result.skipped_files:
        print(f"Skipped {len(result.skipped_files)} files:")
        for skipped in result.skipped_files:
            print(f"  {skipped.path}: {skipped.reason}")


def _run_init_command(args: argparse.Namespace) -> int:
    if args.target == "declarations":
        return _run_init_declarations(args)
    if args.target == "runtime":
        return _run_init_runtime(args)
    created: list[str] = []
    skipped: list[str] = []
    overwritten: list[str] = []
    template_root = resources.files("stoa") / "templates"
    for destination, template_name in INIT_FILES.items():
        target = Path(destination)
        content = (template_root / template_name).read_text(encoding="utf-8")
        content = content.replace("{{VERSION}}", __version__)
        if target.exists():
            if not args.force:
                skipped.append(destination)
                continue
            overwritten.append(destination)
        else:
            created.append(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    for name in created:
        print(f"created:     {name}")
    for name in overwritten:
        print(f"overwritten: {name}")
    for name in skipped:
        print(f"skipped:     {name} (already exists; use --force to overwrite)")
    if skipped and not args.force:
        print(
            "\nProtect .github/workflows/stoa.yml, stoa.toml, and .stoaignore with "
            "CODEOWNERS and branch protection so pull requests cannot weaken the gate."
        )
    elif created or overwritten:
        print(
            "\nNext: commit these files. Protect them with CODEOWNERS and branch "
            "protection so pull requests cannot weaken the gate."
        )
    return EXIT_OK


_RUNTIME_TOML_STUB = """\
# Runtime trace overlay (shadow mode: observe only, never enforce).
# All optional; delete this section and the overlay is fully dormant.
[runtime]
trace_dir = "stoa-traces"    # where the SDK writes stoa-trace/1.0 JSONL
redaction = "redacted"       # "content" opts into recording payloads (redaction_hook applies)
exporter = "jsonl"           # "otlp" is reserved for a future release
suppress = []                # e.g. ["RT002:<agent_id>"] — counted, never hidden

[runtime.drift]              # `stoa runtime drift` thresholds (hand-recomputable)
ratio_threshold = 3.0        # flag a category when its frequency shifts 3x either way…
min_count = 20               # …and it has at least this many observations now
approval_drop = 0.10         # flag when high-impact approval rate drops by this much

[runtime.dimensions]         # runtime-tier re-bucketing (docs/runtime.md)
error_rate_elevated = 0.10
error_rate_moderate = 0.02
"""

_RUNTIME_EXAMPLE = '''\
"""Minimal stoa.runtime instrumentation example (see docs/runtime.md).

Traces are JSONL files on your own filesystem — nothing leaves your
infrastructure, and prompt/response content is never recorded unless you
opt in with capture_content=True.
"""
from stoa import runtime as stoa_rt

# agent_id: the 12-hex id from stoa-registry.json ("stoa runtime map" can
# suggest one if you skip it). No configure() call = tracing stays dormant.
stoa_rt.configure(trace_dir="stoa-traces", agent_id="<agent-id-from-registry>")


@stoa_rt.stoa_trace(kind="agent_run")
def handle_request(ticket):
    with stoa_rt.stoa_span("llm_call", provider="openai", model="gpt-4o",
                           attrs={"prompt": "recorded as hash+length only"}):
        ...  # your model call
    with stoa_rt.stoa_span("action", capability="payment_access",
                           integration="stripe", amount=42.0, currency="USD",
                           approval_span_id=None):  # link an approval span id here
        ...  # your side-effecting action
'''


def _run_init_runtime(args: argparse.Namespace) -> int:
    """Scaffold [runtime] config + a minimal instrumentation example."""
    created: list[str] = []
    skipped: list[str] = []

    toml_path = Path("stoa.toml")
    if toml_path.exists():
        text = toml_path.read_text(encoding="utf-8")
        if "[runtime]" in text and not args.force:
            skipped.append("stoa.toml ([runtime] section already present)")
        else:
            toml_path.write_text(text.rstrip() + "\n\n" + _RUNTIME_TOML_STUB,
                                 encoding="utf-8")
            created.append("stoa.toml ([runtime] section appended)")
    else:
        toml_path.write_text(_RUNTIME_TOML_STUB, encoding="utf-8")
        created.append("stoa.toml")

    example_path = Path("stoa_runtime_example.py")
    if example_path.exists() and not args.force:
        skipped.append(str(example_path))
    else:
        example_path.write_text(_RUNTIME_EXAMPLE, encoding="utf-8")
        created.append(str(example_path))

    for name in created:
        print(f"created:     {name}")
    for name in skipped:
        print(f"skipped:     {name} (already exists; use --force to overwrite)")
    print(
        "\nShadow mode: the SDK only observes — it never blocks or alters agent "
        "behavior, and traces never leave your filesystem. Next: instrument an "
        "agent, run it, then `stoa runtime analyze stoa-traces --registry "
        "stoa-registry.json`."
    )
    return EXIT_OK


def _load_registry(path_str: str) -> dict:
    path = Path(path_str)
    if not path.is_file():
        raise ConfigError(f"registry not found: {path}")
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"cannot read registry {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError(f"registry {path} is not a JSON object")
    return document


def _run_runtime_command(args: argparse.Namespace) -> int:
    """`stoa runtime …` — lazy-imports stoa.runtime so the static toolchain
    can never be affected by the overlay (see docs/design/runtime-overlay.md).
    Shadow mode: analyze/map/merge only observe; nothing here gates."""
    from datetime import datetime, timezone

    from .runtime.analysis import analyze_traces

    if args.runtime_command is None:
        print("stoa runtime: choose a subcommand (analyze, map, merge)", file=sys.stderr)
        return EXIT_USAGE

    registry = None
    registry_path = getattr(args, "registry", None)
    if registry_path:
        registry = _load_registry(registry_path)

    generated_at = datetime.now(timezone.utc).isoformat()
    analysis = analyze_traces(
        args.traces_dir, registry,
        generated_at=generated_at, registry_path=registry_path,
    )
    for warning in analysis["header"]["warnings"]:
        print(f"stoa: warning: {warning}", file=sys.stderr)
    window = analysis["window"]

    if args.runtime_command == "analyze":
        text = json.dumps(analysis, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        _atomic_write(Path(args.out), text)
        if not args.quiet:
            print(
                f"stoa runtime: {window['span_count']} span(s) · "
                f"{len(analysis['agents'])} matched agent(s) · "
                f"{len(analysis['unmatched_agents'])} unmatched · "
                f"{len(analysis['no_runtime_evidence'])} with no runtime evidence"
            )
            print(f"Analysis: {args.out}")
        return EXIT_OK

    if args.runtime_command == "map":
        unmatched = analysis["unmatched_agents"]
        if not unmatched:
            print("stoa runtime map: every span carries a known registry agent id")
            return EXIT_OK
        for entry in unmatched:
            print(f"{entry['key']}  ({entry['span_count']} span(s); {entry['reason']})")
            if entry["suggested_matches"]:
                for match in entry["suggested_matches"]:
                    print(f"  → suggest agent_id={match['agent_id']}  "
                          f"{match['name']} ({match['path']})")
            else:
                print("  → no suggestion; pass agent_id explicitly in the SDK")
        return EXIT_OK

    if args.runtime_command == "merge":
        from .runtime.merge import merge_runtime_into_registry

        config = load_config(Path.cwd(), Path(args.config) if args.config else None)
        enriched = merge_runtime_into_registry(registry, analysis, config)
        out_path = Path(registry_path) if args.in_place else Path(args.out)
        text = json.dumps(enriched, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        _atomic_write(out_path, text)
        runtime_block = enriched["runtime"]
        print(
            f"stoa runtime: merged {runtime_block['span_count']} span(s) into "
            f"{runtime_block['agents_covered']}/{runtime_block['agents_total']} agent(s) "
            f"· {runtime_block['rt_findings']} RT finding(s)"
        )
        print(f"Enriched registry: {out_path}")
        return EXIT_OK

    if args.runtime_command == "baseline":
        from .runtime.drift import build_baseline

        baseline = build_baseline(analysis, generated_at=generated_at)
        text = json.dumps(baseline, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(out_path, text)
        print(
            f"stoa runtime: baseline over {window['span_count']} span(s), "
            f"{len(baseline['agents'])} agent(s)"
        )
        print(f"Baseline: {out_path} — commit it; it is reviewed like code.")
        return EXIT_OK

    if args.runtime_command == "drift":
        from .runtime.drift import (
            DRIFT_ORDER,
            BaselineVersionMismatch,
            compute_drift,
        )

        baseline_path = Path(args.baseline)
        if not baseline_path.is_file():
            raise ConfigError(
                f"baseline not found: {baseline_path} "
                "(run `stoa runtime baseline` first)"
            )
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ConfigError(f"cannot read baseline {baseline_path}: {exc}") from exc

        config = load_config(
            Path.cwd(), Path(args.config) if args.config else None
        )
        try:
            drift = compute_drift(
                analysis, baseline, registry,
                ratio_threshold=config.runtime_drift_ratio_threshold,
                min_count=config.runtime_drift_min_count,
                approval_drop=config.runtime_drift_approval_drop,
                generated_at=generated_at,
            )
        except BaselineVersionMismatch as exc:
            print(f"stoa: {exc}", file=sys.stderr)
            return EXIT_USAGE
        if args.out:
            text = json.dumps(drift, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
            _atomic_write(Path(args.out), text)
        summary = drift["summary"]
        print(
            f"stoa runtime drift: {summary['events']} event(s) · "
            + " · ".join(f"{n} {cls}" for cls, n in summary["by_class"].items())
            + f" · max {summary['max_drift_class']}"
        )
        for event in drift["events"]:
            print(f"  [{event['class']}] {event['kind']} — agent {event['agent_id']}")
        if args.fail_on_drift and summary["max_drift_class"] != "none":
            if DRIFT_ORDER.index(summary["max_drift_class"]) >= DRIFT_ORDER.index(args.fail_on_drift):
                print(
                    f"stoa: drift gate failed: {summary['max_drift_class']} >= "
                    f"{args.fail_on_drift}",
                    file=sys.stderr,
                )
                return EXIT_GATE_FAILED
        return EXIT_OK

    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
