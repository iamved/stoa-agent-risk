"""Self-contained, XSS-safe HTML report.

The report is summary-first: an agent risk map a non-engineer can read at a
glance, with every detail one click away inside ``<details>`` elements — no
JavaScript, a restrictive CSP, no external resources. Every repository-derived
value passes through :func:`html_text` before interpolation.
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

# Display-only exposure tiers derived from the static exposure score.
EXPOSURE_TIERS = (
    (14, "severe", "Severe exposure"),
    (7, "elevated", "Elevated exposure"),
    (3, "moderate", "Moderate exposure"),
    (0, "low", "Low exposure"),
)
EXPOSURE_METER_MAX = 20


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


def exposure_tier(agent: AgentCandidate) -> tuple[str, str]:
    """(tier slug, human label) for the agent's static exposure."""
    score = exposure_score(agent)
    for threshold, slug, label in EXPOSURE_TIERS:
        if score >= threshold:
            return slug, label
    return "low", "Low exposure"


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
section > p.note { color: #5a6272; font-size: 13px; margin: 4px 0 12px; }
.cards { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.card { background: #fff; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 12px 16px; min-width: 130px; }
.card .num { font-size: 22px; font-weight: 700;
  font-variant-numeric: tabular-nums; }
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
details { border-radius: 8px; }
details.block { background: #fff; border: 1px solid #e3e6ec;
  padding: 10px 16px; margin: 10px 0; }
summary { cursor: pointer; font-weight: 600; font-size: 13.5px; }
summary .count { color: #5a6272; font-weight: 400; }
details ul.evidence { margin: 8px 0 4px; padding-left: 22px; font-size: 13px; }
footer { margin-top: 44px; padding-top: 14px; border-top: 1px solid #e3e6ec;
  color: #5a6272; font-size: 12px; }
.pill-list { margin: 0; padding: 0; list-style: none; }
.pill-list li { display: inline-block; background: #f1f3f6; border-radius: 8px;
  padding: 0 7px; margin: 1px 2px 1px 0; font-size: 12px; }
.pill-list li.hot { background: #fde8e8; color: #b42318; font-weight: 600; }
.warn-box { background: #fff8e6; border: 1px solid #f2d98c; border-radius: 8px;
  padding: 10px 14px; font-size: 13px; margin: 12px 0; }
.empty { color: #5a6272; font-size: 13px; font-style: italic; }

/* --- agent risk map --------------------------------------------------- */
.risk-map { display: grid; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  gap: 14px; margin-top: 12px; }
.agent-card { background: #fff; border: 1px solid #e3e6ec; border-radius: 10px;
  border-left: 5px solid #98a2b3; padding: 14px 16px 12px;
  box-shadow: 0 1px 2px rgba(23,28,38,0.04); }
.agent-card.tier-severe { border-left-color: #b42318; }
.agent-card.tier-elevated { border-left-color: #b54708; }
.agent-card.tier-moderate { border-left-color: #93700b; }
.agent-card.tier-low { border-left-color: #98a2b3; }
.agent-card .top { display: flex; justify-content: space-between;
  align-items: baseline; gap: 10px; }
.agent-card .name { font-size: 15.5px; font-weight: 700; word-break: break-word; }
.agent-card .tier { font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.04em; white-space: nowrap; }
.tier-severe .tier { color: #b42318; }
.tier-elevated .tier { color: #b54708; }
.tier-moderate .tier { color: #93700b; }
.tier-low .tier { color: #5a6272; }
.agent-card .meta { color: #5a6272; font-size: 12px; margin: 2px 0 8px; }
.meter { height: 6px; background: #eef0f4; border-radius: 4px; overflow: hidden;
  margin: 2px 0 10px; }
.meter > span { display: block; height: 100%; border-radius: 4px; }
.tier-severe .meter > span { background: #b42318; }
.tier-elevated .meter > span { background: #b54708; }
.tier-moderate .meter > span { background: #93700b; }
.tier-low .meter > span { background: #98a2b3; }
.agent-card .chips { display: flex; flex-wrap: wrap; gap: 4px; margin: 0 0 8px; }
.fchip { display: inline-block; font-size: 11.5px; font-weight: 600;
  border-radius: 9px; padding: 1px 8px; }
.fchip.ok { background: #e8f5ef; color: #14714f; }
.agent-card details { margin-top: 4px; border-top: 1px solid #eef0f4; padding-top: 8px; }
.agent-card summary { font-size: 12.5px; color: #465063; }
.agent-card details h4 { font-size: 12px; margin: 10px 0 4px;
  text-transform: uppercase; letter-spacing: 0.03em; color: #5a6272; }
.agent-card .detail-note { font-size: 12px; color: #5a6272; margin: 6px 0 0; }
.kv { font-size: 12.5px; color: #1a1d23; margin: 2px 0; }
.kv .k { color: #5a6272; }

/* --- exposure bar chart ----------------------------------------------- */
.chart { background: #fff; border: 1px solid #e3e6ec; border-radius: 10px;
  padding: 16px 18px 10px; margin-top: 12px; }
.chart-row { display: grid; grid-template-columns: 150px 1fr 34px;
  align-items: center; gap: 10px; margin: 7px 0; }
.chart-label { font-size: 12.5px; font-weight: 600; text-align: right;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.chart-track { background: #eef0f4; border-radius: 4px; height: 16px; overflow: hidden; }
.chart-track > span { display: block; height: 100%; border-radius: 4px; min-width: 3px; }
.chart-val { font-size: 12.5px; font-weight: 700; color: #465063;
  font-variant-numeric: tabular-nums; text-align: right; }
.bar-severe { background: #b42318; }
.bar-elevated { background: #c2660a; }
.bar-moderate { background: #93700b; }
.bar-low { background: #8a94a6; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 12px 2px 4px;
  font-size: 11.5px; color: #5a6272; }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend i { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }
.sevbar { display: flex; height: 22px; border-radius: 5px; overflow: hidden;
  border: 1px solid #e3e6ec; margin-top: 4px; }
.sevbar > span { display: flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: #fff; min-width: 26px; }
.sevbar .s-critical { background: #b42318; }
.sevbar .s-high { background: #c2660a; }
.sevbar .s-medium { background: #b8901a; }
.sevbar .s-low { background: #7c8aa0; }
.sevbar .s-info { background: #3b6fce; }
.chart-caption { font-size: 11.5px; color: #5a6272; margin: 8px 0 0; }
"""

BAR_CLASS = {
    "severe": "bar-severe",
    "elevated": "bar-elevated",
    "moderate": "bar-moderate",
    "low": "bar-low",
}


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

    # Executive summary stat tiles -----------------------------------------
    parts.append("<section><h2>At a glance</h2>")
    if result.diff_available:
        parts.append(
            '<p class="note">Findings below cover the full repository; only newly '
            "introduced findings affect the gate.</p>"
        )
    cards = [
        (len(result.agents), "Agent candidates", False),
        (len(high_exposure_agents), "High-exposure candidates", False),
        (critical, "Critical findings", critical > 0),
        (new_critical, "New critical findings", new_critical > 0)
        if result.diff_available
        else None,
        (result.suppressed_count(), "Suppressed findings", False),
        (result.files_scanned, "Files scanned", False),
    ]
    parts.append('<div class="cards">')
    for card in cards:
        if card is None:
            continue
        number, label, alert = card
        cls = "card alert" if alert else "card"
        parts.append(
            f'<div class="{cls}"><div class="num">{html_text(number)}</div>'
            f'<div class="lbl">{html_text(label)}</div></div>'
        )
    parts.append("</div></section>")

    # New critical findings (diff mode) -------------------------------------
    if result.diff_available:
        parts.append(_new_critical_section(result))

    # Findings-by-severity bar ----------------------------------------------
    if result.unsuppressed_findings():
        parts.append(_severity_bar(severity_counts))

    # Agent risk map ---------------------------------------------------------
    parts.append("<section><h2>Agent risk map</h2>")
    parts.append(
        '<p class="note">Each candidate, ranked by static exposure: high-impact '
        "capabilities, sensitive integrations, and finding severity. Static "
        "evidence does not prove runtime reachability.</p>"
    )
    if result.agents:
        ranked = sorted(
            result.agents, key=lambda a: (-exposure_score(a), a.path, a.symbol)
        )
        parts.append(_exposure_chart(ranked))
        parts.append(
            '<p class="note" style="margin-top:18px">Expand any candidate below '
            "for the evidence, capabilities, integrations, and findings.</p>"
        )
        parts.append('<div class="risk-map">')
        for agent in ranked:
            parts.append(_agent_card(agent, result.diff_available))
        parts.append("</div>")
    else:
        parts.append('<p class="empty">No agent candidates were detected.</p>')
    parts.append("</section>")

    # Finding sections, collapsed by default ---------------------------------
    active = result.unsuppressed_findings()
    security = [
        f for f in active
        if f.category in ("secret", "injection", "ai-output", "ai-disclosure",
                          "ai-prompt", "ai-supplychain")
    ]
    reliability = [f for f in active if f.category in ("reliability", "network")]
    prompts = [
        f for f in active
        if f.category in ("control", "ai-agency", "ai-stability")
    ]
    suppressed = [f for f in result.findings if f.suppressed]

    parts.append("<section><h2>All findings</h2>")
    parts.append(
        '<p class="note">Everything the scan found, grouped. Sections are '
        "collapsed so the report leads with the map; nothing is omitted.</p>"
    )
    has_critical = any(f.severity == "critical" for f in security)
    parts.append(_collapsed_findings("Security findings", security, result.diff_available, open_=has_critical))
    parts.append(_collapsed_findings("Reliability findings", reliability, result.diff_available))
    parts.append(
        _collapsed_findings(
            "Review prompts",
            prompts,
            result.diff_available,
            note=(
                "Review prompts are observations, not confirmed vulnerabilities: a "
                "control was not observed in the scanned file, but may exist elsewhere."
            ),
        )
    )
    parts.append(_suppressed_details(suppressed))
    parts.append("</section>")

    parts.append(
        "<footer>Stoa performs static, pattern-based analysis. Findings and agent "
        "classifications should be reviewed by an engineer. Runtime behavior and "
        "organization-wide controls may not be visible in the scanned repository."
        "</footer>\n</main>\n</body>\n</html>\n"
    )
    return "".join(parts)


def _exposure_chart(ranked: list[AgentCandidate]) -> str:
    """A ranked horizontal bar chart of static exposure, colored by tier.

    Bars are labeled by name and score and ordered high→low, so tier color is
    reinforced by position and number (never color alone).
    """
    max_score = max((exposure_score(a) for a in ranked), default=1) or 1
    rows = []
    for agent in ranked:
        score = exposure_score(agent)
        tier_slug, tier_label = exposure_tier(agent)
        pct = max(round(score * 100 / max_score), 3)
        rows.append(
            '<div class="chart-row">'
            f'<div class="chart-label" title="{html_text(agent.path)}">'
            f"{html_text(agent.name)}</div>"
            f'<div class="chart-track" role="img" '
            f'aria-label="{html_text(agent.name)}: {html_text(tier_label)}, score {score}">'
            f'<span class="{BAR_CLASS[tier_slug]}" style="width: {pct}%"></span></div>'
            f'<div class="chart-val">{html_text(score)}</div>'
            "</div>"
        )
    legend = (
        '<div class="legend">'
        '<span><i class="bar-severe"></i>Severe</span>'
        '<span><i class="bar-elevated"></i>Elevated</span>'
        '<span><i class="bar-moderate"></i>Moderate</span>'
        '<span><i class="bar-low"></i>Low</span>'
        "</div>"
    )
    return (
        f'<div class="chart">{"".join(rows)}{legend}'
        '<p class="chart-caption">Static exposure combines high-impact '
        "capabilities, sensitive integrations, and finding severity per "
        "candidate. Higher means more to review first, not a proven exploit.</p>"
        "</div>"
    )


def _severity_bar(severity_counts: dict[str, int]) -> str:
    """A single proportional bar of unsuppressed findings by severity."""
    order = ("critical", "high", "medium", "low", "info")
    total = sum(severity_counts.get(s, 0) for s in order)
    if total == 0:
        return ""
    segments = []
    for sev in order:
        count = severity_counts.get(sev, 0)
        if not count:
            continue
        width = count * 100 / total
        segments.append(
            f'<span class="s-{sev}" style="flex: {width}" '
            f'title="{count} {sev}">{count}</span>'
        )
    return (
        '<section><h2>Findings by severity</h2>'
        f'<div class="sevbar">{"".join(segments)}</div>'
        '<div class="legend">'
        '<span><i class="bar-severe"></i>Critical</span>'
        '<span><i style="background:#c2660a"></i>High</span>'
        '<span><i style="background:#b8901a"></i>Medium</span>'
        '<span><i style="background:#7c8aa0"></i>Low</span>'
        '<span><i style="background:#3b6fce"></i>Info</span>'
        "</div></section>"
    )


def _agent_card(agent: AgentCandidate, diff_available: bool) -> str:
    tier_slug, tier_label = exposure_tier(agent)
    score = exposure_score(agent)
    meter_pct = min(score, EXPOSURE_METER_MAX) * 100 // EXPOSURE_METER_MAX

    hot_caps = sorted(HIGH_IMPACT_CAPABILITIES.intersection(agent.capabilities))
    other_caps = sorted(set(agent.capabilities) - set(hot_caps))
    shown = hot_caps[:4]
    hidden_count = len(hot_caps) - len(shown) + len(other_caps)

    active = [f for f in agent.findings if not f.suppressed]
    counts: dict[str, int] = {}
    for finding in active:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    if counts:
        chips = "".join(
            f'<span class="fchip sev-{html_text(sev)}">{counts[sev]} {html_text(sev)}</span>'
            for sev in ("critical", "high", "medium", "low", "info")
            if counts.get(sev)
        )
    else:
        chips = '<span class="fchip ok">no findings</span>'

    cap_pills = "".join(f'<li class="hot">{html_text(c)}</li>' for c in shown)
    if not shown and agent.integrations:
        cap_pills = "".join(f"<li>{html_text(i)}</li>" for i in agent.integrations[:4])
    more = f"<li>+{hidden_count} more</li>" if hidden_count > 0 else ""

    detail = _agent_card_details(agent, diff_available)

    return (
        f'<div class="agent-card tier-{tier_slug}">'
        '<div class="top">'
        f'<span class="name">{html_text(agent.name)}</span>'
        f'<span class="tier">{html_text(tier_label)}</span>'
        "</div>"
        f'<p class="meta"><code>{html_text(agent.path)}</code> · '
        f"{_confidence_label(agent.confidence)} confidence</p>"
        f'<div class="meter" role="img" aria-label="Static exposure score {score}">'
        f'<span style="width: {meter_pct}%"></span></div>'
        f'<div class="chips">{chips}</div>'
        f'<ul class="pill-list">{cap_pills}{more}</ul>'
        f"{detail}"
        "</div>"
    )


def _agent_card_details(agent: AgentCandidate, diff_available: bool) -> str:
    parts = ["<details><summary>Details &amp; evidence</summary>"]

    parts.append("<h4>Detected because</h4><ul class=\"evidence\">")
    for evidence in agent.evidence:
        parts.append(
            f"<li>{html_text(evidence.description)} at line {html_text(evidence.line)}</li>"
        )
    parts.append("</ul>")
    parts.append(
        f'<p class="kv"><span class="k">Detection score:</span> '
        f"{html_text(agent.detection_score)} · "
        f'<span class="k">symbol:</span> <code>{html_text(agent.symbol)}</code></p>'
    )

    if agent.frameworks or agent.providers:
        parts.append("<h4>Stack</h4>")
        parts.append(
            f'<p class="kv"><span class="k">Frameworks:</span> '
            f"{html_text(', '.join(agent.frameworks)) if agent.frameworks else '—'} · "
            f'<span class="k">Providers:</span> '
            f"{html_text(', '.join(agent.providers)) if agent.providers else '—'}</p>"
        )

    parts.append("<h4>Capabilities (static evidence)</h4>")
    if agent.capabilities:
        pills = "".join(
            f'<li class="{"hot" if c in HIGH_IMPACT_CAPABILITIES else ""}">{html_text(c)}</li>'
            for c in agent.capabilities
        )
        parts.append(f'<ul class="pill-list">{pills}</ul>')
    else:
        parts.append('<p class="kv">None observed.</p>')

    parts.append("<h4>Integrations · call sites</h4>")
    if agent.call_sites:
        pills = "".join(
            f"<li>{html_text(name)} × {html_text(count)}</li>"
            for name, count in agent.call_sites.items()
        )
        parts.append(f'<ul class="pill-list">{pills}</ul>')
    else:
        parts.append('<p class="kv">None observed.</p>')

    ownership = []
    if agent.codeowners:
        ownership.append(
            '<span class="k">Codeowners:</span> '
            + html_text(", ".join(agent.codeowners))
        )
    ownership.append(
        '<span class="k">Last touched by:</span> '
        + (html_text(agent.last_touched_by) if agent.last_touched_by else "unknown")
    )
    if agent.last_commit:
        ownership.append(
            f'<code>{html_text(agent.last_commit.hash)}</code> {html_text(agent.last_commit.date)}'
        )
    parts.append(f'<h4>Attribution</h4><p class="kv">{" · ".join(ownership)}</p>')

    active = [f for f in agent.findings if not f.suppressed]
    parts.append("<h4>Findings in this file</h4>")
    if active:
        rows = "".join(
            "<tr>"
            f"<td>{_severity_badge(f.severity)}"
            + (" <strong>(new)</strong>" if diff_available and f.is_new else "")
            + "</td>"
            f"<td><code>{html_text(f.rule_id)}</code></td>"
            f"<td>{html_text(f.line)}</td>"
            f"<td>{html_text(f.title)}<br><code>{html_text(f.snippet)}</code><br>"
            f"{html_text(f.remediation)}</td>"
            "</tr>"
            for f in active
        )
        parts.append(
            '<div class="table-wrap"><table><thead><tr><th>Severity</th><th>Rule</th>'
            f"<th>Line</th><th>Finding</th></tr></thead><tbody>{rows}</tbody></table></div>"
        )
    else:
        parts.append('<p class="kv">None.</p>')

    parts.append("</details>")
    return "".join(parts)


def _new_critical_section(result: ScanResult) -> str:
    new_critical_findings = [
        f for f in result.unsuppressed_findings() if f.is_new and f.severity == "critical"
    ]
    parts = ["<section><h2>New critical findings</h2>"]
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
    return "".join(parts)


def _collapsed_findings(
    title: str,
    findings: list[Finding],
    diff_available: bool,
    note: str | None = None,
    open_: bool = False,
) -> str:
    open_attr = " open" if open_ and findings else ""
    parts = [
        f'<details class="block"{open_attr}><summary>{html_text(title)} '
        f'<span class="count">({len(findings)})</span></summary>'
    ]
    if note:
        parts.append(f'<p class="note">{html_text(note)}</p>')
    if not findings:
        parts.append('<p class="empty">None.</p></details>')
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
        '<div class="table-wrap" style="margin-top: 8px;"><table><thead><tr>'
        "<th>Severity</th><th>Rule</th><th>Location</th><th>Confidence</th>"
        "<th>Finding</th><th>Remediation</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></details>"
    )
    return "".join(parts)


def _suppressed_details(suppressed: list[Finding]) -> str:
    parts = [
        f'<details class="block"><summary>Suppressed findings '
        f'<span class="count">({len(suppressed)})</span></summary>'
    ]
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
            '<div class="table-wrap" style="margin-top: 8px;"><table><thead><tr>'
            "<th>Rule</th><th>Location</th><th>Finding</th><th>Reason</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
    else:
        parts.append('<p class="empty">None.</p>')
    parts.append("</details>")
    return "".join(parts)


def write_html(result: ScanResult, config: StoaConfig, output_path: Path) -> None:
    """Render and atomically write the HTML report."""
    _atomic_write(output_path, render_html(result, config))
