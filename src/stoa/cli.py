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

# Sidebar entries `stoa dashboard --hide` can leave out. Overview always stays.
HIDEABLE_SCREENS = ("inventory", "scope", "risk", "controls", "policies", "passports", "audit", "loss", "insurance")

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
                      help="Legacy summary report path (default: stoa-report.html)")
    scan.add_argument("--dashboard", metavar="PATH", default="stoa-dashboard.html",
                      help="Self-contained dashboard path (default: stoa-dashboard.html)")
    scan.add_argument("--no-dashboard", action="store_true",
                      help="Do not write the dashboard")
    scan.add_argument("--dashboard-json", metavar="PATH", default=None,
                      help="Also write the dashboard's data as JSON, to open in a dashboard "
                           "page you already have (it is read in the browser, never uploaded)")
    scan.add_argument("--open", action="store_true",
                      help="Open the dashboard in the default browser after the scan")
    scan.add_argument("--no-history", action="store_true",
                      help="Do not record this scan under .stoa/history/")
    scan.add_argument("--underwriting-config", metavar="PATH", default=None,
                      help="Applicant identity, performance figures and declared schedule for the "
                           "dashboard's AI Risk Insurance assessment (default: .stoa/underwriting.toml if present)")
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
    scan.add_argument("--tf-plan", metavar="PATH", default=None,
                      help="Discover IaC agents from `terraform show -json` output (fully "
                           "resolved values) instead of from .tf files")
    scan.add_argument("--taxonomy", metavar="PATH", default=None,
                      help="Custom dimension taxonomy TOML (replaces the default)")
    scan.add_argument("--runtime-baseline", metavar="PATH", default=None,
                      help="With --with-runtime: a runtime-baseline JSON for RT008")
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

    dashboard = subparsers.add_parser(
        "dashboard", help="Build the self-contained dashboard from an existing registry")
    dashboard.add_argument("input", metavar="REGISTRY",
                           help="stoa-registry.json (or a stoa-dashboard envelope)")
    dashboard.add_argument("--baseline", metavar="REGISTRY", default=None,
                           help="Registry to diff against (drift screen)")
    dashboard.add_argument("--runtime", metavar="TRACES_DIR", default=None,
                           help="Local stoa-trace files: adds the Runtime screen and observed evidence")
    dashboard.add_argument("--runtime-baseline", metavar="PATH", default=None,
                           help="With --runtime: a committed runtime-baseline JSON for drift and RT008")
    dashboard.add_argument("--policy", metavar="PATH", default=None,
                           help="With --runtime: the stoa.policy.toml to show beside the outcomes (default: search upward)")
    dashboard.add_argument("--approvals", metavar="PATH", default=".stoa/approvals.toml")
    dashboard.add_argument("--root", metavar="DIR", default=".",
                           help="Repository root holding .stoa/history/ (default: .)")
    dashboard.add_argument("--out", metavar="PATH", default="stoa-dashboard.html")
    dashboard.add_argument("--json-out", metavar="PATH", default=None,
                           help="Also write the dashboard's data as JSON, to open in a dashboard "
                                "page you already have (it is read in the browser, never uploaded)")
    dashboard.add_argument("--summary", action="store_true",
                           help="Print the scan at a glance in the terminal as well")
    dashboard.add_argument("--demo", action="store_true",
                           help="Mark the page as demo data; it then offers to open a real scan")
    dashboard.add_argument("--hide", metavar="SCREEN", action="append", default=None, choices=sorted(HIDEABLE_SCREENS),
                           help="Leave a screen out of the page (repeatable): " + ", ".join(sorted(HIDEABLE_SCREENS)))
    dashboard.add_argument("--open", action="store_true", help="Open in the default browser")
    dashboard.add_argument("--config", metavar="PATH", default=None)
    dashboard.add_argument("--taxonomy", metavar="PATH", default=None)
    dashboard.add_argument("--underwriting-config", metavar="PATH", default=None,
                           help="Applicant identity, performance figures and declared schedule "
                                "(default: <root>/.stoa/underwriting.toml if present)")

    init = subparsers.add_parser("init", help="Generate integration files")
    init.add_argument("target", choices=["github", "declarations", "runtime", "underwriting"],
                      help="Integration to initialize. 'declarations' requires a prior "
                           "`stoa scan` — it stubs out stoa-declared.toml with real agent ids. "
                           "'runtime' scaffolds [runtime] config + an instrumentation example. "
                           "'underwriting' scaffolds .stoa/underwriting.toml, the business facts "
                           "behind the dashboard's insurance assessment and loss outlook.")
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
    export_kind = export.add_mutually_exclusive_group(required=True)
    export_kind.add_argument("--assurance", action="store_true",
                             help="Export the 18-area assurance packet")
    export_kind.add_argument("--underwriting", "--underwriting-demo",
                             dest="underwriting", action="store_true",
                             help="Export a pre-filled AI Model Risk Assessment form "
                                  "(modeled on the aiSure template)")
    export.add_argument("--underwriting-config", metavar="PATH", default=None,
                        help="TOML with the applicant's [identity] and real "
                             "[[performance]] metrics for --underwriting "
                             "(default: sample figures, clearly labeled)")
    export.add_argument("--format", choices=["json", "md"], default="md",
                        help="Output format for --assurance (default: md)")
    export.add_argument("--out", metavar="PATH", default=None,
                        help="Write output to PATH (default: stdout, or "
                             "stoa-underwriting.html for --underwriting)")
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
        help="Analyze local runtime traces (stoa-trace/1.1) against the registry",
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
    rt_merge.add_argument("--baseline", metavar="PATH", default=None,
                          help="runtime-baseline JSON; widens what RT008 counts as known")

    rt_verify = rt_sub.add_parser(
        "verify", help="Check every trace file's hash chain and signatures"
    )
    rt_verify.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_verify.add_argument("--key", metavar="SPEC", default=None,
                           help="Signing key spec (hmac:..., file:...) for HMAC-signed traces; "
                                "defaults to $STOA_SIGNING_KEY")
    rt_verify.add_argument("--out", metavar="PATH", default=None,
                           help="Write the runtime-chain/1.0 report JSON here")

    rt_tail = rt_sub.add_parser(
        "tail", help="Print spans from a trace directory as they are written"
    )
    rt_tail.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_tail.add_argument("--follow", "-f", action="store_true", help="Keep watching for new spans")
    rt_tail.add_argument("--lines", "-n", type=int, default=20, help="How many recent spans to show first")

    rt_mcp = rt_sub.add_parser(
        "mcp-proxy", help="Run an MCP stdio server behind a recording, policy-applying proxy"
    )
    rt_mcp.add_argument("--upstream", metavar="COMMAND", required=True, help="The MCP server command to run")
    rt_mcp.add_argument("--agent", metavar="ID_OR_NAME", default=None)
    rt_mcp.add_argument("--trace-dir", metavar="DIR", default=None, help="Defaults to $STOA_TRACE_DIR")
    rt_mcp.add_argument("--policy", metavar="PATH", default=None)
    rt_mcp.add_argument("--side-effect", metavar="TOOL=EFFECT", action="append", default=[],
                        help="Declare a tool's side effect, e.g. issue_refund=payment (repeatable)")
    rt_mcp.add_argument("--limit-field", metavar="TOOL=FIELD", action="append", default=[],
                        help="The numeric argument that is a tool's amount, e.g. issue_refund=amount")

    rt_alerts = rt_sub.add_parser(
        "alerts", help="Evaluate alert rules over a trace window and deliver them (local; no server)"
    )
    rt_alerts.add_argument("traces_dir", metavar="TRACES_DIR", nargs="?", default=None)
    rt_alerts.add_argument("--registry", metavar="PATH", default=None)
    rt_alerts.add_argument("--baseline", metavar="PATH", default=None, help="runtime-baseline JSON for drift-based rules")
    rt_alerts.add_argument("--policy", metavar="PATH", default=None, help="stoa.policy.toml with an [alerts] block (default: search upward)")
    rt_alerts.add_argument("--deliver", action="store_true", help="Send to the configured channels (default: print and write only)")
    rt_alerts.add_argument("--state", metavar="PATH", default=".stoa/alerts-state.json", help="Dedupe state file")
    rt_alerts.add_argument("--out", metavar="PATH", default=None, help="Write the runtime-alerts/1.0 JSON here")
    rt_alerts.add_argument("--dashboard-url", metavar="URL", default=None, help="Link to put in every alert")
    rt_alerts.add_argument("--test", metavar="RULE_ID", default=None, help="Fire one synthetic alert for RULE_ID to the configured channels")

    rt_reconcile = rt_sub.add_parser(
        "reconcile", help="Declared vs used vs dormant tools, per agent"
    )
    rt_reconcile.add_argument("traces_dir", metavar="TRACES_DIR")
    rt_reconcile.add_argument("--registry", metavar="PATH", required=True)
    rt_reconcile.add_argument("--since", metavar="DAYS", type=int, default=30,
                              help="A declared tool unseen for this many days is dormant (default 30)")
    rt_reconcile.add_argument("--out", metavar="PATH", default=None,
                              help="Write the runtime-reconcile/1.0 JSON here")

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

    # --- stoa policy: policy as code (stoa-policy/0.1)
    policy = subparsers.add_parser("policy", help="Validate, recommend and inspect agent policies (stoa.policy.toml)")
    pol_sub = policy.add_subparsers(dest="policy_command")
    pol_validate = pol_sub.add_parser("validate", help="Check a policy file against stoa-policy/0.1")
    pol_validate.add_argument("path", metavar="FILE", nargs="?", default="stoa.policy.toml")
    pol_recommend = pol_sub.add_parser("recommend", help="Write a policy file from the registry and declarations")
    pol_recommend.add_argument("--registry", metavar="PATH", default="stoa-registry.json")
    pol_recommend.add_argument("--out", metavar="PATH", default="stoa.policy.toml")
    pol_recommend.add_argument("--mode", choices=["observe", "enforce"], default="observe")
    pol_recommend.add_argument("--force", action="store_true", help="Overwrite an existing file")
    pol_test = pol_sub.add_parser("test", help="Replay scenarios (JSONL) through the policies and report per policy")
    pol_test.add_argument("scenarios", metavar="SCENARIOS.jsonl")
    pol_test.add_argument("--policies", metavar="PATH", default="stoa.policy.toml")
    pol_test.add_argument("--registry", metavar="PATH", default=None)
    pol_test.add_argument("--out", metavar="PATH", default=".stoa/policy-test.json", help="Write the policy-test/0.1 result here (the passport reads it)")
    pol_test.add_argument("--fail-on-mismatch", action="store_true", help="Exit 1 when any expectation is not met")
    pol_packs = pol_sub.add_parser("packs", help="List the shipped policy packs")
    pol_packs.add_argument("name", nargs="?", default=None, help="Print one pack's policies")

    # --- stoa passport: one page per agent
    passport = subparsers.add_parser("passport", help="Write an agent passport (stoa-passport/0.1) as HTML or JSON")
    passport.add_argument("--agent-id", metavar="ID_OR_NAME", required=True)
    passport.add_argument("--registry", metavar="PATH", default="stoa-registry.json")
    passport.add_argument("--runtime", metavar="TRACES_DIR", default=None, help="Local traces, for the observed section and policy outcomes")
    passport.add_argument("--policy", metavar="PATH", default=None)
    passport.add_argument("--baseline", metavar="REGISTRY", default=None, help="Registry to diff against, for the drift section")
    passport.add_argument("--out", metavar="PATH", default=None, help="Default: passport-<agent>.html")
    passport.add_argument("--json", action="store_true", help="Write JSON instead of HTML")

    # --- stoa kill: the kill switch state file the SDK reads
    kill = subparsers.add_parser("kill", help="Set, release or drill the kill switch for an agent")
    kill.add_argument("--agent-id", metavar="ID_OR_NAME", required=True, help="An agent id or declared name, or * for every agent")
    kill.add_argument("--reason", metavar="TEXT", default="")
    kill.add_argument("--by", metavar="HANDLE", default=None, help="Who is pulling it (default: $USER)")
    kill.add_argument("--release", action="store_true", help="Clear the flag instead of setting it")
    kill.add_argument("--drill", action="store_true", help="Set the flag, time the first blocked span, release, record the result")
    kill.add_argument("--traces", metavar="DIR", default="stoa-traces", help="With --drill: where blocked spans will appear")
    kill.add_argument("--timeout", type=float, default=30.0)
    kill.add_argument("--state", metavar="PATH", default=None, help="Kill switch file (default: .stoa/killswitch.json upward from here)")

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
        if args.command == "dashboard":
            return _run_dashboard_command(args)
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
        if args.command == "policy":
            return _run_policy_command(args)
        if args.command == "passport":
            return _run_passport_command(args)
        if args.command == "kill":
            return _run_kill_command(args)
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
    if args.dashboard_json and args.no_dashboard:
        print("stoa: --dashboard-json needs the dashboard; drop --no-dashboard", file=sys.stderr)
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
        tf_plan=Path(args.tf_plan) if args.tf_plan else None,
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

        from .dashboard import build_runtime_slot
        from .report_json import build_document

        document = build_document(result, config)
        baseline = _load_registry(args.runtime_baseline) if getattr(args, "runtime_baseline", None) else None
        enriched, runtime_slot = build_runtime_slot(
            args.with_runtime, document, config, baseline=baseline,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
        for warning in runtime_slot["analysis"]["header"]["warnings"]:
            print(f"stoa: warning: {warning}", file=sys.stderr)
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

    dashboard_path = None
    envelope = None
    base_doc = None
    base_doc_resolved = False
    if not args.no_dashboard and config.dashboard_enabled:
        from .report_json import build_document as _build_document
        document = enriched if args.with_runtime else _build_document(result, config)
        if args.diff_against:
            base_doc = _scan_ref_registry(Path(args.path), args.diff_against, config)
            base_doc_resolved = True
        dashboard_path, envelope = _write_scan_dashboard(
            result, config, args, document, base_doc, root.resolve(),
            runtime_slot=runtime_slot if args.with_runtime else None,
        )

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
        _print_scan_summary(result, args, json_path, html_path, dashboard_path)
        if envelope is not None:
            from .dashboard.terminal import render_overview
            overview = render_overview(envelope, header=False, next_steps=not args.github_annotations)
            if overview:
                print("\n" + overview, end="")
    if dashboard_path is not None and args.open:
        _open_in_browser(dashboard_path)
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
        return _scan_diff_against(result, config, args, base_doc if base_doc_resolved else None,
                                  base_doc_resolved)
    return EXIT_OK


def _write_scan_dashboard(result, config, args, document, base_doc, root: Path, runtime_slot: dict | None = None):
    """Write stoa-dashboard.html next to the registry; never fails the scan.

    Returns ``(path, envelope)``; the path is None when the template is absent."""
    from .dashboard import build_envelope, load_history, record_history
    from .dashboard.inject import write_dashboard, write_dashboard_json
    from .dashboard.template import DashboardTemplateMissing

    diff = None
    if args.diff_against and base_doc is not None:
        diff = diff_registries(base_doc, document, Approvals.load(Path(args.approvals)))
    history: list[dict] = []
    if not args.no_history and not args.no_git:
        record_history(root, document, config.dashboard_history_keep)
        history = load_history(root)
    envelope = build_envelope(
        document, diff=diff, baseline=base_doc if diff is not None else None, history=history,
        underwriting=_load_underwriting(root, args.underwriting_config),
        taxonomy_path=config.dimensions_taxonomy, crosswalk_path=config.crosswalk_path,
        runtime=runtime_slot,
    )
    if args.dashboard_json:
        write_dashboard_json(envelope, Path(args.dashboard_json))
    path = Path(args.dashboard)
    try:
        write_dashboard(envelope, path)
    except DashboardTemplateMissing as exc:
        print(f"stoa: warning: dashboard skipped: {exc}", file=sys.stderr)
        return None, envelope
    return path, envelope


def _load_underwriting(root: Path, explicit: str | None) -> dict | None:
    """Identity, metrics and schedule for the dashboard assessment; None when absent."""
    from .underwriting import load_intake, load_schedule, load_underwriting_config

    path = Path(explicit) if explicit else root / ".stoa" / "underwriting.toml"
    if not path.is_file():
        if explicit:
            print(f"stoa: warning: underwriting config not found: {explicit}", file=sys.stderr)
        return None
    identity, metrics = load_underwriting_config(path)
    return {"identity": identity or None, "metrics": metrics, "schedule": load_schedule(path),
            "intake": load_intake(path)}


def _open_in_browser(path: Path) -> None:
    import webbrowser
    try:
        webbrowser.open(Path(path).resolve().as_uri())
    except Exception as exc:  # noqa: BLE001 - opening a browser is best-effort
        print(f"stoa: could not open a browser: {exc}", file=sys.stderr)


def _run_dashboard_command(args: argparse.Namespace) -> int:
    """`stoa dashboard REGISTRY`: build the dashboard from an existing registry."""
    from .dashboard import build_envelope, load_history
    from .dashboard.inject import is_envelope, write_dashboard, write_dashboard_json
    from .dashboard.template import DashboardTemplateMissing

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"stoa: input not found: {args.input}", file=sys.stderr)
        return EXIT_USAGE
    try:
        document = json.loads(input_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"stoa: {args.input} is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if not isinstance(document, dict):
        print(f"stoa: {args.input} is not a registry document", file=sys.stderr)
        return EXIT_USAGE

    root = Path(args.root).resolve()
    if is_envelope(document):
        envelope = document
        if args.baseline:
            print("stoa: warning: --baseline ignored; the input is already a dashboard envelope",
                  file=sys.stderr)
    else:
        if "schema_version" not in document:
            print(f"stoa: {args.input} has no schema_version; expected stoa-registry.json",
                  file=sys.stderr)
            return EXIT_USAGE
        config = load_config(root, Path(args.config) if args.config else None)
        diff = None
        base_doc = None
        if args.baseline:
            baseline_path = Path(args.baseline)
            if not baseline_path.is_file():
                print(f"stoa: baseline not found: {args.baseline}", file=sys.stderr)
                return EXIT_USAGE
            base_doc = json.loads(baseline_path.read_text(encoding="utf-8"))
            diff = diff_registries(base_doc, document, Approvals.load(Path(args.approvals)))
        runtime_slot = None
        if args.runtime:
            from datetime import datetime, timezone

            from .dashboard import build_runtime_slot

            rt_baseline = _load_registry(args.runtime_baseline) if args.runtime_baseline else None
            document, runtime_slot = build_runtime_slot(
                args.runtime, document, config, baseline=rt_baseline, registry_path=str(input_path),
                generated_at=datetime.now(timezone.utc).isoformat(), policy_path=args.policy,
            )
            for warning in runtime_slot["analysis"]["header"]["warnings"]:
                print(f"stoa: warning: {warning}", file=sys.stderr)
        envelope = build_envelope(
            document, diff=diff, baseline=base_doc, history=load_history(root),
            underwriting=_load_underwriting(root, args.underwriting_config),
            taxonomy_path=Path(args.taxonomy) if args.taxonomy else config.dimensions_taxonomy,
            crosswalk_path=config.crosswalk_path,
            runtime=runtime_slot,
        )

    if args.demo:
        envelope = {**envelope, "demo": True}
    if args.hide:
        envelope = {**envelope, "hidden_screens": sorted(set(args.hide))}
    if args.summary:
        from .dashboard.terminal import render_overview
        print(render_overview(envelope), end="")
    if args.json_out:
        write_dashboard_json(envelope, Path(args.json_out))
        print(f"stoa: wrote {args.json_out}")
    out = Path(args.out)
    try:
        write_dashboard(envelope, out)
    except DashboardTemplateMissing as exc:
        print(f"stoa: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"stoa: wrote {out}")
    if args.open:
        _open_in_browser(out)
    return EXIT_OK


def _scan_diff_against(result, config, args, base_doc=None, base_doc_resolved=False) -> int:
    """`stoa scan --diff-against REF`: diff the fresh scan against a git ref."""
    from .report_json import build_document
    head_doc = build_document(result, config)
    if not base_doc_resolved:
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

    if args.underwriting:
        from .underwriting import (
            UnderwritingConfigError,
            load_underwriting_config,
            render_underwriting_html,
        )

        identity, metrics = None, None
        if args.underwriting_config:
            try:
                identity, metrics = load_underwriting_config(Path(args.underwriting_config))
            except UnderwritingConfigError as exc:
                print(f"stoa: {exc}", file=sys.stderr)
                return EXIT_USAGE
        out_path = Path(args.out) if args.out else Path("stoa-underwriting.html")
        _atomic_write(out_path, render_underwriting_html(document, identity, metrics))
        source = "applicant config" if args.underwriting_config else "sample figures"
        print(f"stoa: wrote {out_path} (underwriting-evidence form · {source})")
        return EXIT_OK

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


def _run_init_underwriting(args: argparse.Namespace) -> int:
    target = Path(".stoa") / "underwriting.toml"
    if target.exists() and not args.force:
        print(f"skipped:     {target} (already exists; use --force to overwrite)")
        return EXIT_OK
    existed = target.exists()
    content = (resources.files("stoa") / "templates" / "underwriting.toml").read_text(encoding="utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"{'overwritten:' if existed else 'created:    '} {target}")
    print("\nEvery field is commented out, so nothing changes until you fill it in. "
          "The next `stoa scan` picks the file up automatically. It is embedded in "
          "stoa-dashboard.html, so keep it to facts you would share with a broker.")
    return EXIT_OK


def _print_scan_summary(
    result: ScanResult, args: argparse.Namespace, json_path: Path, html_path: Path,
    dashboard_path: Path | None = None,
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
    outputs = [str(dashboard_path)] if dashboard_path is not None else []
    outputs += [str(html_path), str(json_path)]
    print("Reports: " + ", ".join(outputs))
    if args.verbose and result.skipped_files:
        print(f"Skipped {len(result.skipped_files)} files:")
        for skipped in result.skipped_files:
            print(f"  {skipped.path}: {skipped.reason}")


def _run_init_command(args: argparse.Namespace) -> int:
    if args.target == "declarations":
        return _run_init_declarations(args)
    if args.target == "runtime":
        return _run_init_runtime(args)
    if args.target == "underwriting":
        return _run_init_underwriting(args)
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
trace_dir = "stoa-traces"    # where the SDK writes stoa-trace/1.1 JSONL
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

# agent_id: the id or declared name from stoa-registry.json ("stoa runtime
# map" can suggest one if you skip it). No configure() call = tracing stays
# dormant. signing_key (or $STOA_SIGNING_KEY) signs the trace chain.
stoa_rt.configure(trace_dir="stoa-traces", agent_id="<agent-id-from-registry>",
                  signing_key=None)


@stoa_rt.guard(side_effect="payment", limit_field="amount", approval_field="approval",
               capability="payment_access", integration="stripe")
def issue_refund(order_id: str, amount: float, approval: str | None = None):
    ...  # your side-effecting action; the span records tool, amount, side effect


def handle_request(ticket):
    with stoa_rt.session(user_ref=ticket.customer_id) as s:
        with stoa_rt.model_call("openai", "gpt-4o") as m:
            reply = ...  # your model call; content is never recorded
            m.record(tokens_in=0, tokens_out=0)
        approval = s.approval(actor="ops-oncall", channel="slack", granted=True)
        issue_refund(ticket.order_id, 42.0, approval=approval)
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


def _run_policy_command(args: argparse.Namespace) -> int:
    from .policy import PACK_NAMES, load_pack, load_policy_document, policy_to_toml, recommend
    from .policy.conditions import condition_text
    from .policy.recommend import render_gaps

    if args.policy_command == "validate":
        document = load_policy_document(args.path)
        for problem in document.problems:
            print(f"  {problem['at']}: {problem['message']}")
        if document.ok:
            print(f"stoa policy: {args.path} is valid stoa-policy/0.1: {len(document.policies)} policies, mode {document.mode}")
            return EXIT_OK
        print(f"stoa policy: {len(document.problems)} problem(s) in {args.path}", file=sys.stderr)
        return EXIT_GATE_FAILED
    if args.policy_command == "recommend":
        registry = _load_registry(args.registry)
        out = Path(args.out)
        if out.exists() and not args.force:
            print(f"stoa policy: {out} exists; pass --force to overwrite", file=sys.stderr)
            return EXIT_USAGE
        document, gaps = recommend(registry, mode=args.mode)
        header = (f"Recommended by stoa policy recommend from {args.registry}.\n"
                  "Each policy says why under recommended_because. Observe first; set enforce = true per policy,\n"
                  "or [defaults] mode = \"enforce\", when a policy has earned it.")
        _atomic_write(out, policy_to_toml(document, header=header))
        print(f"stoa policy: wrote {out} with {len(document.policies)} policies (mode {document.mode})")
        for p in document.policies:
            print(f"  {p.id:<24} {p.action:<9} {p.scope.get('agent', '*'):<20} {condition_text(p.condition)}")
        print()
        print(render_gaps(gaps), end="")
        return EXIT_OK
    if args.policy_command == "test":
        from datetime import datetime, timezone

        from .policy.test import load_scenarios, render_policy_test, run_policy_test

        scenarios, problems = load_scenarios(args.scenarios)
        for problem in problems:
            print(f"stoa policy test: warning: {problem}", file=sys.stderr)
        registry_path = args.registry or ("stoa-registry.json" if Path("stoa-registry.json").is_file() else None)
        if args.registry and not Path(args.registry).is_file():
            print(f"stoa policy test: registry not found: {args.registry}", file=sys.stderr)
            return EXIT_USAGE
        if registry_path is None:
            print("stoa policy test: warning: no registry; declared tools and limits are unknown, so allow-list policies fire on every call", file=sys.stderr)
        doc = run_policy_test(scenarios, args.policies, registry_path=registry_path, generated_at=datetime.now(timezone.utc).isoformat())
        if args.out:
            _atomic_write(Path(args.out), json.dumps(doc, indent=2) + "\n")
        print(render_policy_test(doc), end="")
        if args.fail_on_mismatch and doc["matched"] < doc["expected"]:
            return EXIT_GATE_FAILED
        return EXIT_OK
    if args.policy_command == "packs":
        names = [args.name] if args.name else list(PACK_NAMES)
        for name in names:
            if name not in PACK_NAMES:
                print(f"stoa policy: no pack {name!r}; packs: {', '.join(PACK_NAMES)}", file=sys.stderr)
                return EXIT_USAGE
            pack = load_pack(name)
            print(f"{name} ({len(pack.policies)} policies, default mode {pack.mode})")
            for p in pack.policies:
                print(f"  {p.id:<14} {p.action:<9} {p.trigger:<9} {condition_text(p.condition)}")
                if args.name:
                    print(f"      {p.rationale}")
        return EXIT_OK
    print("stoa policy: choose a subcommand (validate, recommend, test, packs)", file=sys.stderr)
    return EXIT_USAGE


def _run_passport_command(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone

    from .dashboard import build_runtime_slot
    from .passport import build_passport, render_passport_html

    registry = _load_registry(args.registry)
    policies = None
    if args.runtime:
        config = load_config(Path.cwd(), None)
        registry, slot = build_runtime_slot(args.runtime, registry, config, registry_path=args.registry, generated_at=datetime.now(timezone.utc).isoformat(), policy_path=args.policy)
        policies = slot.get("policies")
    diff = None
    if args.baseline:
        diff = diff_registries(_load_registry(args.baseline), registry, Approvals.load(Path(".stoa/approvals.toml")))
    agents = registry.get("agents") or []
    match = next((a for a in agents if a["id"] == args.agent_id or (a.get("declared") or {}).get("name") == args.agent_id or a.get("name") == args.agent_id or a.get("display_name") == args.agent_id), None)
    if match is None:
        print(f"stoa passport: no agent {args.agent_id!r}; agents: {', '.join((a.get('declared') or {}).get('name') or a.get('display_name') or a['id'] for a in agents)}", file=sys.stderr)
        return EXIT_USAGE
    passport = build_passport(registry, match["id"], diff=diff, policies=policies)
    name = passport["agent"]["name"]
    out = Path(args.out) if args.out else Path(f"passport-{name}.{'json' if args.json else 'html'}")
    company = (_load_underwriting(Path.cwd(), None) or {}).get("identity", {}).get("company")
    _atomic_write(out, json.dumps(passport, indent=2, ensure_ascii=False) + "\n" if args.json else render_passport_html(passport, company=company))
    print(f"stoa passport: wrote {out} ({passport['validity']['status']}, verify {passport['verify_hash']})")
    return EXIT_OK


def _run_kill_command(args: argparse.Namespace) -> int:
    import getpass

    from .policy.killswitch import drill, find_state, kill, release

    by = args.by or getpass.getuser()
    state = Path(args.state) if args.state else find_state()
    if args.release:
        had = release(args.agent_id, by=by, path=state)
        print(f"stoa kill: released {args.agent_id}" + ("" if had else " (it was not set)"))
        return EXIT_OK
    if args.drill:
        from .runtime.reader import TraceReader

        traces = Path(args.traces)
        seen_before = {(s["_trace_file"], s["_trace_line"]) for s in TraceReader(traces).spans()} if traces.is_dir() else set()

        def blocked_seen() -> bool:
            if not traces.is_dir():
                return False
            for span in TraceReader(traces).spans():
                if (span["_trace_file"], span["_trace_line"]) in seen_before:
                    continue
                if span.get("enforcement") == "denied" and "POL-BASE-001" in str((span.get("attrs") or {}).get("policy_rules", "")):
                    return True
            return False

        print(f"stoa kill: drill on {args.agent_id}; waiting up to {args.timeout:g}s for the first blocked call under {traces}")
        result = drill(args.agent_id, by=by, wait_for_stop=blocked_seen, timeout=args.timeout, path=state)
        if result["timed_out"]:
            print("stoa kill: no blocked call seen before the timeout; is the agent running with the baseline pack?", file=sys.stderr)
            return EXIT_GATE_FAILED
        print(f"stoa kill: stopped in {result['seconds_to_stop']}s; recorded in {state}")
        return EXIT_OK
    kill(args.agent_id, reason=args.reason or "set from the command line", by=by, path=state)
    print(f"stoa kill: {args.agent_id} is stopped (reason: {args.reason or 'set from the command line'}); release with --release")
    return EXIT_OK


def _run_runtime_alerts(args: argparse.Namespace) -> int:
    """`stoa runtime alerts`: rules over the analysis, drift and chain; local delivery."""
    from datetime import datetime, timezone

    from .runtime.alerts import deliver, evaluate_alerts, load_alert_config, load_state, save_state, synthetic_alert
    from .runtime.policy import find_policy

    policy_path = args.policy or find_policy()
    config = load_alert_config(policy_path)
    for warning in config.warnings:
        print(f"stoa: warning: {warning}", file=sys.stderr)
    if args.test:
        try:
            document = synthetic_alert(args.test, config)
        except KeyError:
            print(f"stoa: no alert rule {args.test!r}; rules: {', '.join(r.id for r in config.rules)}", file=sys.stderr)
            return EXIT_USAGE
        for record in deliver(document, config, dashboard_url=args.dashboard_url):
            print(f"  {record['channel']}: {'ok' if record['ok'] else 'failed'} ({record['detail']})")
        return EXIT_OK
    if not args.traces_dir:
        print("stoa runtime alerts: TRACES_DIR is required unless --test is given", file=sys.stderr)
        return EXIT_USAGE
    from .runtime.analysis import analyze_traces
    from .runtime.chain import verify_dir
    from .runtime.drift import compute_drift

    registry = _load_registry(args.registry) if args.registry else None
    generated_at = datetime.now(timezone.utc).isoformat()
    analysis = analyze_traces(args.traces_dir, registry, generated_at=generated_at, registry_path=args.registry)
    drift = None
    if args.baseline:
        baseline = _load_registry(args.baseline)
        cfg = load_config(Path.cwd(), None)
        drift = compute_drift(analysis, baseline, registry, ratio_threshold=cfg.runtime_drift_ratio_threshold, min_count=cfg.runtime_drift_min_count, approval_drop=cfg.runtime_drift_approval_drop, generated_at=generated_at)
    chain = verify_dir(args.traces_dir).to_dict()
    state_path = Path(args.state)
    state = load_state(state_path)
    document = evaluate_alerts(analysis, drift=drift, chain=chain, registry=registry, config=config, state=state)
    save_state(state_path, state)
    if args.out:
        _atomic_write(Path(args.out), json.dumps(document, indent=2) + "\n")
    for alert in document["alerts"]:
        print(f"  {alert['severity']:<8} {alert['rule_id']:<28} {alert['agent']}: {alert['summary']}")
    print(f"stoa runtime alerts: {len(document['alerts'])} alert(s), {document['deduplicated']} deduplicated")
    if args.deliver and document["alerts"]:
        for record in deliver(document, config, dashboard_url=args.dashboard_url):
            print(f"  delivered via {record['channel']}: {'ok' if record['ok'] else 'failed'} ({record['detail']})")
    return EXIT_OK


def _run_runtime_tail(args: argparse.Namespace) -> int:
    """Print one line per span, newest last; with --follow keep reading."""
    import time

    from .runtime.reader import TraceReader

    def line_for(span: dict) -> str:
        parts = [span.get("end_ts") or span.get("start_ts") or "", f"{span.get('kind', ''):<10}", span.get("agent_id") or "-"]
        if span.get("tool"):
            parts.append(span["tool"])
        if span.get("model"):
            parts.append(span["model"])
        amount = span.get("amount")
        if isinstance(amount, dict):
            parts.append(f"{amount.get('amount')} {amount.get('currency')}")
        if span.get("enforcement"):
            parts.append(span["enforcement"])
        flags = (span.get("attrs") or {}).get("flags")
        if flags:
            parts.append("flags=" + ",".join(flags))
        if span.get("status") == "error":
            parts.append("error")
        return "  ".join(str(p) for p in parts)

    seen: dict[str, int] = {}
    first = True
    while True:
        reader = TraceReader(args.traces_dir)
        fresh = []
        for span in reader.spans():
            key = span["_trace_file"]
            if span["_trace_line"] > seen.get(key, 0):
                fresh.append(span)
                seen[key] = span["_trace_line"]
        if first and args.lines >= 0:
            fresh = fresh[-args.lines:]
        for span in fresh:
            print(line_for(span))
        sys.stdout.flush()
        first = False
        if not args.follow:
            return EXIT_OK
        time.sleep(0.5)


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
        print("stoa runtime: choose a subcommand (analyze, map, merge, baseline, drift, verify, reconcile)", file=sys.stderr)
        return EXIT_USAGE

    if args.runtime_command == "tail":
        return _run_runtime_tail(args)

    if args.runtime_command == "alerts":
        return _run_runtime_alerts(args)

    if args.runtime_command == "mcp-proxy":
        from . import runtime as stoa_rt
        from .runtime.integrations.mcp_proxy import McpProxy

        pairs = lambda items: dict(item.split("=", 1) for item in items if "=" in item)  # noqa: E731
        stoa_rt.configure(args.trace_dir, agent_id=args.agent, policy=args.policy)
        proxy = McpProxy(args.upstream, agent_id=None, side_effects=pairs(args.side_effect), limit_fields=pairs(args.limit_field))
        try:
            return proxy.run()
        finally:
            stoa_rt.shutdown()

    if args.runtime_command == "verify":
        from .runtime.chain import verify_dir

        report = verify_dir(args.traces_dir, args.key)
        if args.out:
            _atomic_write(Path(args.out), json.dumps(report.to_dict(), indent=2) + "\n")
        if not report.files:
            print(f"stoa runtime verify: no trace files under {args.traces_dir}")
            return EXIT_USAGE
        for item in report.files:
            grade = f"{item.key_grade}" + (f", signed {item.signed}" if item.signed else "")
            if item.unchained:
                print(f"  {item.file}: pre-1.1 file, no chain to verify ({item.records} record(s))")
            elif item.ok:
                print(f"  {item.file}: ok, {item.records} record(s), {grade}")
            else:
                print(f"  {item.file}: BROKEN at line {item.first_break}: {item.break_reason}")
        print("stoa runtime verify: " + ("all chains intact" if report.ok else f"{len(report.broken)} file(s) broken"))
        return EXIT_OK if report.ok else EXIT_GATE_FAILED

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

    if args.runtime_command == "reconcile":
        from .runtime.reconcile import reconcile, render_reconcile

        doc = reconcile(registry, analysis, dormant_days=args.since, generated_at=generated_at)
        if args.out:
            _atomic_write(Path(args.out), json.dumps(doc, indent=2) + "\n")
        print(render_reconcile(doc), end="")
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
        baseline = _load_registry(args.baseline) if getattr(args, "baseline", None) else None
        enriched = merge_runtime_into_registry(registry, analysis, config, baseline)
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
