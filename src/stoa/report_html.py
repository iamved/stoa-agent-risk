"""Self-contained, XSS-safe HTML report.

Every repository-derived value passes through :func:`html_text` before it is
interpolated. The report carries a restrictive CSP, uses no JavaScript, no
external resources, and expands evidence with ``<details>``/``<summary>``.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from . import __version__
from .config import StoaConfig
from .models import SEVERITY_ORDER, AgentCandidate, Finding, ScanResult
from .report_json import _atomic_write
from .rules import HIGH_IMPACT_CAPABILITIES, SENSITIVE_INTEGRATIONS

SEVERITY_RANK_FOR_EXPOSURE = {"critical": 4, "high": 3, "medium": 1, "low": 0, "info": 0}
CONFIDENCE_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}


def html_text(value: object) -> str:
    """Escape any repository-derived value for safe HTML interpolation."""
    return escape(str(value), quote=True)


def _severity_badge(severity: str) -> str:
    return f'<span class="badge sev-{html_text(severity)}">{html_text(severity)}</span>'


def _confidence_label(confidence: str) -> str:
    return html_text(CONFIDENCE_LABELS.get(confidence, confidence))


def exposure_score(agent: AgentCandidate) -> int:
    """Rank agents by static exposure signals; higher means more exposed."""
    score = 0
    score += 3 * len(HIGH_IMPACT_CAPABILITIES.intersection(agent.capabilities))
    score += 2 * len(SENSITIVE_INTEGRATIONS.intersection(agent.integrations))
    score += len(agent.integrations)
    highest = agent.highest_severity
    if highest:
        score += 2 * SEVERITY_RANK_FOR_EXPOSURE.get(highest, 0)
    if agent.confidence == "high":
        score += 2
    return score


def is_high_exposure(agent: AgentCandidate) -> bool:
    if HIGH_IMPACT_CAPABILITIES.intersection(agent.capabilities):
        return True
    if len(SENSITIVE_INTEGRATIONS.intersection(agent.integrations)) >= 2:
        return True
    highest = agent.highest_severity
    return highest in ("critical", "high")


_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
  Helvetica, Arial, sans-serif; color: #1a1d23; background: #f6f7f9;
  line-height: 1.5; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 20px 60px; }
header.page { background: #171c26; color: #f2f4f8; padding: 28px 20px; }
header.page .inner { max-width: 1100px; margin: 0 auto; }
header.page h1 { margin: 0 0 6px; font-size: 22px; font-weight: 650; }
header.page p { margin: 2px 0; color: #b8c0cf; font-size: 14px; }
header.page .headline { color: #f2f4f8; font-size: 15px; margin-top: 8px; }
h2 { font-size: 17px; margin: 34px 0 10px; }
section > p.note { color: #5a6272; font-size: 13px; margin: 4px 0 10px; }
.cards { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.card { background: #fff; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 12px 16px; min-width: 130px; }
.card .num { font-size: 22px; font-weight: 700; }
.card .lbl { font-size: 12px; color: #5a6272; }
.card.alert .num { color: #b42318; }
table { border-collapse: collapse; width: 100%; background: #fff;
  border: 1px solid #e3e6ec; border-radius: 8px; font-size: 13px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eef0f4;
  vertical-align: top; }
th { background: #fafbfc; font-size: 12px; color: #5a6272;
  text-transform: uppercase; letter-spacing: 0.03em; }
tr:last-child td { border-bottom: none; }
.table-wrap { overflow-x: auto; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px; background: #f1f3f6; padding: 1px 5px; border-radius: 4px;
  word-break: break-all; }
.badge { display: inline-block; padding: 1px 8px; border-radius: 10px;
  font-size: 11px; font-weight: 650; text-transform: uppercase; }
.sev-critical { background: #fde8e8; color: #b42318; }
.sev-high { background: #fdf0e0; color: #b54708; }
.sev-medium { background: #fef7dc; color: #93700b; }
.sev-low { background: #eef2f6; color: #465063; }
.sev-info { background: #e8f0fe; color: #1d4ed8; }
details { background: #fff; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 8px 14px; margin: 8px 0; }
summary { cursor: pointer; font-weight: 600; font-size: 13px; }
details ul { margin: 8px 0 4px; padding-left: 22px; font-size: 13px; }
footer { margin-top: 44px; padding-top: 14px; border-top: 1px solid #e3e6ec;
  color: #5a6272; font-size: 12px; }
.pill-list { margin: 0; padding: 0; list-style: none; }
.pill-list li { display: inline-block; background: #f1f3f6; border-radius: 8px;
  padding: 0 7px; margin: 1px 2px 1px 0; font-size: 12px; }
.warn-box { background: #fff8e6; border: 1px solid #f2d98c; border-radius: 8px;
  padding: 10px 14px; font-size: 13px; margin: 12px 0; }
.empty { color: #5a6272; font-size: 13px; font-style: italic; }
"""


def render_html(result: ScanResult, config: StoaConfig) -> str:
    parts: list[str] = []
    severity_counts = result.severity_counts()
    new_counts = result.new_severity_counts()
    new_critical = new_counts.get("critical", 0)
    critical = severity_counts.get("critical", 0)
    high_exposure_agents = [a for a in result.agents if is_high_exposure(a)]
    integrations = sorted({i for a in result.agents for i in a.integrations})

    scan_mode = (
        f"Diff-aware scan against base {html_text(result.repository.base_ref)}"
        if result.diff_available
        else "Full repository scan"
    )
    risk_phrase = (
        f"{new_critical} new critical risk{'s' if new_critical != 1 else ''}"
        if result.diff_available
        else f"{critical} critical finding{'s' if critical != 1 else ''}"
    )

    parts.append(
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta http-equiv=\"Content-Security-Policy\" "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:;\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>Stoa Agent Risk Report — {html_text(result.repository.name)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
    )
    parts.append(
        '<header class="page"><div class="inner">'
        "<h1>Stoa Agent Risk Report</h1>"
        f"<p>Repository: <strong>{html_text(result.repository.name)}</strong>"
        + (
            f" · ref <code>{html_text(result.repository.git_ref)}</code>"
            if result.repository.git_ref
            else ""
        )
        + f"</p><p>{html_text(scan_mode)} · Stoa v{html_text(__version__)}</p>"
        f'<p class="headline">{len(result.agents)} agent candidate'
        f"{'s' if len(result.agents) != 1 else ''} · "
        f"{len(integrations)} integration{'s' if len(integrations) != 1 else ''} · "
        f"{html_text(risk_phrase)}</p>"
        "</div></header>\n<main>\n"
    )

    if result.warnings:
        items = "".join(f"<li>{html_text(w)}</li>" for w in result.warnings)
        parts.append(f'<div class="warn-box"><strong>Scan warnings</strong><ul>{items}</ul></div>')

    # Executive summary -----------------------------------------------------
    parts.append("<section><h2>Executive summary</h2>")
    if result.diff_available:
        parts.append(
            '<p class="note">Findings below cover the full repository; only newly '
            "introduced findings affect the gate.</p>"
        )
    cards = [
        (len(result.agents), "Agent candidates", False),
        (sum(1 for a in result.agents if a.confidence == "high"), "High-confidence candidates", False),
        (len(high_exposure_agents), "High-exposure candidates", False),
        (critical, "Critical findings", critical > 0),
        (new_critical, "New critical findings", new_critical > 0),
        (result.suppressed_count(), "Suppressed findings", False),
        (result.files_scanned, "Files scanned", False),
    ]
    parts.append('<div class="cards">')
    for number, label, alert in cards:
        cls = "card alert" if alert else "card"
        parts.append(
            f'<div class="{cls}"><div class="num">{html_text(number)}</div>'
            f'<div class="lbl">{html_text(label)}</div></div>'
        )
    parts.append("</div></section>")

    # New critical findings -------------------------------------------------
    if result.diff_available:
        new_critical_findings = [
            f
            for f in result.unsuppressed_findings()
            if f.is_new and f.severity == "critical"
        ]
        parts.append("<section><h2>New critical findings</h2>")
        if new_critical_findings:
            rows = "".join(
                "<tr>"
                f"<td>{_severity_badge(f.severity)}</td>"
                f"<td><code>{html_text(f.rule_id)}</code></td>"
                f"<td><code>{html_text(f.path)}</code></td>"
                f"<td>{html_text(f.line)}</td>"
                f"<td>{html_text(f.title)}</td>"
                f"<td>{html_text(f.remediation)}</td>"
                "</tr>"
                for f in new_critical_findings
            )
            parts.append(
                '<div class="table-wrap"><table><thead><tr>'
                "<th>Severity</th><th>Rule</th><th>File</th><th>Line</th>"
                "<th>Finding</th><th>Remediation</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>"
            )
        else:
            parts.append(
                '<p class="empty">No new critical findings were introduced relative '
                "to the base branch.</p>"
            )
        parts.append("</section>")

    # Highest-exposure agents ----------------------------------------------
    parts.append("<section><h2>Highest-exposure agent candidates</h2>")
    parts.append(
        '<p class="note">Ranked by static evidence of high-impact capabilities, '
        "sensitive integrations, and finding severity. Static evidence does not "
        "prove runtime reachability.</p>"
    )
    ranked = sorted(result.agents, key=lambda a: (-exposure_score(a), a.path, a.symbol))[:10]
    if ranked:
        rows = []
        for agent in ranked:
            high_caps = sorted(HIGH_IMPACT_CAPABILITIES.intersection(agent.capabilities))
            sensitive = sorted(SENSITIVE_INTEGRATIONS.intersection(agent.integrations))
            ownership = []
            if agent.codeowners:
                ownership.append(", ".join(html_text(o) for o in agent.codeowners))
            ownership.append(
                f"Last touched by {html_text(agent.last_touched_by)}"
                if agent.last_touched_by
                else "Last touched by unknown"
            )
            highest = agent.highest_severity
            rows.append(
                "<tr>"
                f"<td><strong>{html_text(agent.name)}</strong><br>"
                f"<code>{html_text(agent.path)}</code></td>"
                f"<td>{_confidence_label(agent.confidence)}</td>"
                f"<td>{_pills(high_caps)}</td>"
                f"<td>{_pills(sensitive)}</td>"
                f"<td>{' · '.join(ownership)}</td>"
                f"<td>{_severity_badge(highest) if highest else '—'}</td>"
                "</tr>"
            )
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Agent</th><th>Confidence</th><th>High-impact capabilities</th>"
            "<th>Sensitive integrations</th><th>Codeowners / last touched by</th>"
            "<th>Highest finding</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    else:
        parts.append('<p class="empty">No agent candidates were detected.</p>')
    parts.append("</section>")

    # Agent inventory --------------------------------------------------------
    parts.append("<section><h2>Agent inventory</h2>")
    if result.agents:
        rows = []
        for agent in result.agents:
            rows.append(
                "<tr>"
                f"<td><strong>{html_text(agent.name)}</strong></td>"
                f"<td>{_confidence_label(agent.confidence)}</td>"
                f"<td><code>{html_text(agent.path)}</code></td>"
                f"<td>{_pills(agent.frameworks)}</td>"
                f"<td>{_pills(agent.providers)}</td>"
                f"<td>{_pills(agent.capabilities)}</td>"
                f"<td>{_pills(agent.integrations)}</td>"
                f"<td>{_pills(agent.codeowners) or '—'}</td>"
                f"<td>{html_text(agent.last_touched_by) if agent.last_touched_by else 'unknown'}</td>"
                f"<td>{_severity_badge(agent.highest_severity) if agent.highest_severity else '—'}</td>"
                "</tr>"
            )
        parts.append(
            '<div class="table-wrap"><table><thead><tr>'
            "<th>Agent candidate</th><th>Confidence</th><th>Path</th><th>Framework</th>"
            "<th>LLM providers</th><th>Capabilities</th><th>Integrations</th>"
            "<th>Codeowners</th><th>Last touched by</th><th>Highest severity</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )
        # Detection evidence
        parts.append("<h2>Detection evidence</h2>")
        for agent in result.agents:
            items = "".join(
                f"<li>{html_text(e.description)} at line {html_text(e.line)}</li>"
                for e in agent.evidence
            )
            parts.append(
                "<details><summary>"
                f"{html_text(agent.name)} — <code>{html_text(agent.path)}</code> "
                f"(score {html_text(agent.detection_score)}, "
                f"{_confidence_label(agent.confidence)} confidence)</summary>"
                f"<p>Detected because:</p><ul>{items}</ul></details>"
            )
    else:
        parts.append('<p class="empty">No agent candidates were detected.</p>')
    parts.append("</section>")

    # Findings ---------------------------------------------------------------
    active = result.unsuppressed_findings()
    security = [f for f in active if f.category in ("secret", "injection")]
    reliability = [f for f in active if f.category in ("reliability", "network")]
    prompts = [f for f in active if f.category == "control"]
    suppressed = [f for f in result.findings if f.suppressed]

    parts.append(_findings_section("Security findings", security, result.diff_available))
    parts.append(_findings_section("Reliability findings", reliability, result.diff_available))
    parts.append(
        _findings_section(
            "Review prompts",
            prompts,
            result.diff_available,
            note=(
                "Review prompts are observations, not confirmed vulnerabilities: a "
                "control was not observed in the scanned file, but may exist elsewhere."
            ),
        )
    )

    parts.append("<section><h2>Suppressed findings</h2>")
    parts.append(
        f'<p class="note">{len(suppressed)} finding'
        f"{'s' if len(suppressed) != 1 else ''} suppressed.</p>"
    )
    if suppressed:
        rows = "".join(
            "<tr>"
            f"<td><code>{html_text(f.rule_id)}</code></td>"
            f"<td><code>{html_text(f.path)}:{html_text(f.line)}</code></td>"
            f"<td>{html_text(f.title)}</td>"
            f"<td>{html_text(f.suppression_reason) if f.suppression_reason else '—'}</td>"
            "</tr>"
            for f in suppressed
        )
        parts.append(
            '<div class="table-wrap"><table><thead><tr><th>Rule</th><th>Location</th>'
            f"<th>Finding</th><th>Reason</th></tr></thead><tbody>{rows}</tbody></table></div>"
        )
    parts.append("</section>")

    parts.append(
        "<footer>Stoa performs static, pattern-based analysis. Findings and agent "
        "classifications should be reviewed by an engineer. Runtime behavior and "
        "organization-wide controls may not be visible in the scanned repository."
        "</footer>\n</main>\n</body>\n</html>\n"
    )
    return "".join(parts)


def _pills(values: list[str]) -> str:
    if not values:
        return ""
    items = "".join(f"<li>{html_text(v)}</li>" for v in values)
    return f'<ul class="pill-list">{items}</ul>'


def _findings_section(
    title: str, findings: list[Finding], diff_available: bool, note: str | None = None
) -> str:
    parts = [f"<section><h2>{html_text(title)}</h2>"]
    if note:
        parts.append(f'<p class="note">{html_text(note)}</p>')
    if not findings:
        parts.append('<p class="empty">None.</p></section>')
        return "".join(parts)
    ordered = sorted(
        findings,
        key=lambda f: (-SEVERITY_ORDER[f.severity], f.path, f.line, f.rule_id),
    )
    rows = []
    for finding in ordered:
        new_marker = " <strong>(new)</strong>" if diff_available and finding.is_new else ""
        rows.append(
            "<tr>"
            f"<td>{_severity_badge(finding.severity)}{new_marker}</td>"
            f"<td><code>{html_text(finding.rule_id)}</code></td>"
            f"<td><code>{html_text(finding.path)}:{html_text(finding.line)}</code></td>"
            f"<td>{_confidence_label(finding.confidence)}</td>"
            f"<td>{html_text(finding.title)}<br><code>{html_text(finding.snippet)}</code></td>"
            f"<td>{html_text(finding.remediation)}</td>"
            "</tr>"
        )
    parts.append(
        '<div class="table-wrap"><table><thead><tr>'
        "<th>Severity</th><th>Rule</th><th>Location</th><th>Confidence</th>"
        "<th>Finding</th><th>Remediation</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></section>"
    )
    return "".join(parts)


def write_html(result: ScanResult, config: StoaConfig, output_path: Path) -> None:
    """Render and atomically write the HTML report."""
    _atomic_write(output_path, render_html(result, config))
