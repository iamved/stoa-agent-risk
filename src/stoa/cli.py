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
    scan.add_argument("--taxonomy", metavar="PATH", default=None,
                      help="Custom dimension taxonomy TOML (replaces the default)")

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
    init.add_argument("target", choices=["github"], help="Integration to initialize")
    init.add_argument("--force", action="store_true",
                      help="Overwrite existing files")

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
        if args.command == "approve":
            return _run_approve_command(args)
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
        taxonomy_path=Path(args.taxonomy) if args.taxonomy else None,
    )
    result = run_scan(options, config)

    json_path = Path(args.json)
    html_path = Path(args.html)
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
    created: list[str] = []
    skipped: list[str] = []
    overwritten: list[str] = []
    template_root = resources.files("stoa") / "templates"
    for destination, template_name in INIT_FILES.items():
        target = Path(destination)
        content = (template_root / template_name).read_text(encoding="utf-8")
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


if __name__ == "__main__":
    sys.exit(main())
