"""GitHub Actions output: workflow-command annotations and job summaries.

Annotation messages contain rule titles and remediations only — never code
snippets or credential fragments. All values are escaped per the GitHub
workflow-command rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import TextIO

from .models import ScanResult
from .report_html import is_high_exposure
from .report_json import _atomic_write

ANNOTATION_LEVELS = {
    "critical": "error",
    "high": "warning",
    "medium": "warning",
    "low": "notice",
    "info": "notice",
}


def escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value: str) -> str:
    return (
        escape_data(value).replace(":", "%3A").replace(",", "%2C")
    )


def emit_annotations(result: ScanResult, stream: TextIO) -> None:
    """Print one workflow command per unsuppressed finding."""
    for finding in result.unsuppressed_findings():
        level = ANNOTATION_LEVELS[finding.severity]
        message = escape_data(f"{finding.title}. {finding.remediation}")
        stream.write(
            f"::{level} file={escape_property(finding.path)},"
            f"line={finding.line},"
            f"title={escape_property(finding.rule_id)}::{message}\n"
        )


def render_summary(result: ScanResult) -> str:
    """GitHub-flavored Markdown job summary; contains no code or secrets."""
    new_counts = result.new_severity_counts()
    severity_counts = result.severity_counts()
    new_critical = new_counts.get("critical", 0)
    existing_critical = severity_counts.get("critical", 0) - new_critical
    high_confidence = sum(1 for a in result.agents if a.confidence == "high")
    high_exposure = sum(1 for a in result.agents if is_high_exposure(a))

    lines = [
        "## Stoa Agent Risk Scan",
        "",
        f"- **{len(result.agents)}** agent candidates",
        f"- **{high_confidence}** high-confidence candidates",
        f"- **{high_exposure}** high-exposure candidates",
    ]
    if result.diff_available:
        lines.append(f"- **{new_critical}** new critical findings")
        lines.append(f"- **{existing_critical}** existing critical findings")
    else:
        lines.append(f"- **{existing_critical}** critical findings")
    lines.append(f"- **{result.suppressed_count()}** suppressed findings")

    if result.diff_available:
        new_critical_findings = [
            f
            for f in result.unsuppressed_findings()
            if f.is_new and f.severity == "critical"
        ]
        if new_critical_findings:
            lines += ["", "### New critical findings", "", "| Rule | Location | Finding |", "|---|---|---|"]
            for finding in new_critical_findings:
                location = f"`{finding.path}:{finding.line}`".replace("|", "\\|")
                title = finding.title.replace("|", "\\|")
                lines.append(f"| {finding.rule_id} | {location} | {title} |")

    lines += ["", "Full details are available in the Stoa HTML report artifact.", ""]
    return "\n".join(lines)


def write_summary(result: ScanResult, output_path: Path) -> None:
    _atomic_write(output_path, render_summary(result))
