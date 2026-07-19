"""The ``stoa`` command-line interface.

Exit codes:
    0  scan completed and the gate passed
    1  findings exceeded the configured gate
    2  invalid arguments or configuration
    3  scanner execution error
"""

from __future__ import annotations

import argparse
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .config import FAIL_LEVELS, ConfigError, load_config
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

    init = subparsers.add_parser("init", help="Generate integration files")
    init.add_argument("target", choices=["github"], help="Integration to initialize")
    init.add_argument("--force", action="store_true",
                      help="Overwrite existing files")

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
    except ConfigError as exc:
        print(f"stoa: configuration error: {exc}", file=sys.stderr)
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
    )
    result = run_scan(options, config)

    json_path = Path(args.json)
    html_path = Path(args.html)
    write_json(result, config, json_path)
    write_html(result, config, html_path)
    if args.summary_file:
        write_summary(result, Path(args.summary_file))
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
