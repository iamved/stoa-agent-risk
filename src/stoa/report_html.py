"""Self-contained, XSS-safe HTML report.

The report is summary-first: an agent risk map a non-engineer can read at a
glance, with every detail one click away inside ``<details>`` elements — a
restrictive CSP, no external resources, and (per the module-level docstring
in ``report_graph``) at most a couple of small, byte-fixed scripts, each
allowed to execute only via an exact SHA-256 hash match in the CSP —
never ``'unsafe-inline'``. Every repository-derived value passes through
:func:`html_text` before interpolation.
"""

from __future__ import annotations

import base64
import hashlib
import json as _json
from itertools import groupby
from html import escape
from pathlib import Path

from . import __version__
from .config import StoaConfig
from .models import SEVERITIES, SEVERITY_ORDER, AgentCandidate, Finding, ScanResult
from .report_json import _atomic_write
from .rules import RULES, HIGH_IMPACT_CAPABILITIES, SENSITIVE_INTEGRATIONS

# --- "Download report" button ------------------------------------------
# The report's CSP has no script-src by default (``default-src 'none'``).
# This script is the one always-present exception (the architecture graph
# in report_graph.py is the other, conditional one) — its content is
# identical on every render, with no repo-derived data ever interpolated
# into it, so its SHA-256 hash is computed once at import time and used to
# allow exactly this script and nothing else via CSP hash-pinning.
_DOWNLOAD_JS = r"""
(function () {
  var btn = document.getElementById("stoa-download-report");
  if (!btn) return;
  btn.addEventListener("click", function () {
    var html = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
    var blob = new Blob([html], {type: "text/html"});
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "stoa-report.html";
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });
})();
"""


def _sha256_b64(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


DOWNLOAD_SCRIPT_HASH = _sha256_b64(_DOWNLOAD_JS)

# "Generate underwriting evidence" (Feature 3, DEMO): opens the pre-filled
# questionnaire embedded as a non-executing JSON blob in a new tab. Fixed
# content (no repo data), so it is CSP hash-pinned exactly like the download
# button — the report stays zero-network and script-safe.
_UNDERWRITING_JS = r"""
(function () {
  var btn = document.getElementById("stoa-underwriting-btn");
  var data = document.getElementById("stoa-uw-data");
  if (!btn || !data) return;
  btn.addEventListener("click", function () {
    var html = JSON.parse(data.textContent);
    var blob = new Blob([html], {type: "text/html"});
    window.open(URL.createObjectURL(blob), "_blank");
  });
})();
"""

UNDERWRITING_SCRIPT_HASH = _sha256_b64(_UNDERWRITING_JS)

SEVERITY_RANK_FOR_EXPOSURE = {"critical": 4, "high": 3, "medium": 1, "low": 0, "info": 0}

# AIUC-1-aligned display groups for the default taxonomy; a custom taxonomy
# with no `group` set on its dimensions simply renders without this row.
DIMENSION_GROUP_NAMES = {
    "A": "A · Data & Privacy",
    "B": "B · Security",
    "C": "C · Safety",
    "D": "D · Reliability",
    "E": "E · Accountability",
    "F": "F · Society",
}
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
header.page .inner { max-width: 1100px; margin: 0 auto; position: relative; }
header.page h1 { margin: 0 0 6px; font-size: 22px; font-weight: 650; }
header.page p { margin: 2px 0; color: #b8c0cf; font-size: 14px; }
header.page .headline { color: #f2f4f8; font-size: 15px; margin-top: 8px; }
.dl-btn { background: transparent;
  color: #f2f4f8; border: 1px solid #465063; border-radius: 6px;
  padding: 6px 14px; font-size: 12.5px; font-weight: 600; cursor: pointer;
  font-family: inherit; }
.dl-btn:hover { background: #232936; }
.hdr-actions { position: absolute; top: 0; right: 0; display: flex; gap: 8px; }
@media print { .dl-btn, .hdr-actions { display: none; } }
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

/* --- dimension exposure matrix --------------------------------------- */
.matrix { font-size: 12.5px; }
.matrix th.dim { writing-mode: vertical-rl; transform: rotate(180deg);
  white-space: nowrap; padding: 8px 4px; font-size: 11px; height: 88px; vertical-align: bottom; }
.matrix th.dim.proxy { background: repeating-linear-gradient(45deg, #fafbfc, #fafbfc 4px, #eef0f4 4px, #eef0f4 8px); }
.matrix th.dim-group { font-size: 10.5px; font-weight: 700; letter-spacing: 0.03em;
  color: #5a6272; background: #f3f5f8; border-left: 1px solid #e3e6ec; padding: 4px 6px; }
.matrix td.agent { font-weight: 600; white-space: nowrap; }
.matrix tr.org td { background: #f3f5f8; font-weight: 700; }
.matrix td.cell { text-align: center; font-weight: 700; }
.matrix td.cell a { text-decoration: none; display: block; }
.exp-elevated { color: #b3261e; }
.exp-moderate { color: #a05a00; }
.exp-low { color: #465063; }
.exp-none { color: #c4cbd6; }
.matrix td.cell .lvl { font-size: 9px; font-weight: 600; display: block;
  text-transform: uppercase; letter-spacing: 0.02em; }
.dim-legend { display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 2px;
  font-size: 11.5px; color: #5a6272; }
.dim-legend span { display: inline-flex; align-items: center; gap: 5px; }
.dim-drill { background: #fff; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 8px 14px; margin: 8px 0; }
.dim-drill summary { font-size: 13px; }
/* --- concise dimension exposure (redesign) --------------------------- */
.dim-sub { font-size: 12.5px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.04em; color: #5a6272; margin: 16px 0 8px; }
.dim-by { display: flex; flex-direction: column; gap: 4px; }
.dim-by-row { display: grid; grid-template-columns: 200px 96px 1fr; align-items: center;
  gap: 14px; padding: 9px 14px; background: #fff; border: 1px solid #e3e6ec;
  border-radius: 8px; border-left: 4px solid #d9dde3; }
.dim-by-row.lv-elevated { border-left-color: #b42318; }
.dim-by-row.lv-moderate { border-left-color: #b8901a; }
.dim-by-name { font-weight: 650; font-size: 13.5px; }
.dim-by-name .eyebrow { display: block; font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.05em; color: #8a94a6; }
.dim-by-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden;
  background: #eef0f4; max-width: 320px; }
.dim-by-bar > span { display: block; }
.dim-by-bar .b-elev { background: #b42318; }
.dim-by-bar .b-mod { background: #d29a1f; }
.dim-by-bar .b-low { background: #c2c8d0; }
.dim-by-counts { font-size: 12px; color: #5a6272; margin-left: 10px; white-space: nowrap;
  font-variant-numeric: tabular-nums; }
.dim-agents { display: flex; flex-direction: column; gap: 7px; }
.dim-agent-row { background: #fff; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 11px 15px; }
.dim-agent-row.worst { border-left: 4px solid #b42318; }
.dim-agent-head { display: flex; justify-content: space-between; align-items: baseline;
  gap: 10px; }
.dim-agent-name { font-weight: 700; font-size: 14.5px; }
.dim-agent-name a { color: inherit; text-decoration: none; border-bottom: 1px dotted #b8c0cf; }
.dim-agent-name a:hover { border-bottom-color: #465063; }
.dim-agent-detail { font-size: 12px; color: #2f6fb0; text-decoration: none; }
.dim-agent-detail:hover { text-decoration: underline; }
.dim-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; align-items: center; }
.dim-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px;
  font-weight: 600; border-radius: 20px; padding: 2px 11px; }
.dim-chip.chip-elev { background: #fde8e8; color: #b42318; }
.dim-chip.chip-mod { background: #fef7dc; color: #93700b; }
.dim-more { font-size: 11.5px; color: #8a94a6; }
.dim-clean { font-size: 12.5px; color: #14714f; margin-top: 6px; }
.dim-drill:target { border-color: #a05a00; box-shadow: 0 0 0 2px #a05a0033; }
.dim-drill table { margin-top: 8px; }
@media print {
  .risk-map, .chart, details.block { break-inside: avoid; }
  .dim-drill { display: block; }
  .dim-drill > summary { font-weight: 700; }
}
.graph-controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
  background: #fff; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 10px 14px; margin: 10px 0; font-size: 12.5px; color: #465063; }
.graph-controls select, .graph-controls input[type="text"] {
  font-size: 12.5px; border: 1px solid #e3e6ec; border-radius: 6px; padding: 3px 6px; }
.graph-layout { display: flex; gap: 12px; align-items: stretch; }
.graph-canvas { flex: 1 1 auto; height: 520px; background: #fff;
  border: 1px solid #e3e6ec; border-radius: 10px; min-width: 0; }
.graph-panel { flex: 0 0 280px; background: #fff; border: 1px solid #e3e6ec;
  border-radius: 10px; padding: 12px 14px; font-size: 12.5px; overflow-y: auto;
  max-height: 520px; }
.graph-panel h4 { margin: 10px 0 4px; font-size: 12px; text-transform: uppercase;
  letter-spacing: 0.03em; color: #5a6272; }
.graph-panel h4:first-child { margin-top: 0; }
@media (max-width: 760px) {
  .graph-layout { flex-direction: column; }
  .graph-panel { flex-basis: auto; max-height: 260px; }
}
/* Small-viewport reflow (down to ~380px): no fixed columns, no absolute
   header actions, tighter gutters. Keeps the page body from scrolling
   sideways. */
@media (max-width: 480px) {
  main { padding: 16px 12px 48px; }
  .hdr-actions { position: static; margin: 12px 0 0; flex-wrap: wrap; }
  header.page h1 { margin-top: 6px; }
  .dim-by-row { grid-template-columns: 1fr auto; }
  .dim-by-row > div:last-child { grid-column: 1 / -1; }
  .verdict .lede { font-size: 17px; }
  .cards { grid-template-columns: 1fr 1fr; }
  .fix-item .fh { flex-wrap: wrap; }
}
.autonomy-badge { display: inline-block; font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.02em; padding: 2px 8px;
  border-radius: 8px; margin: 2px 0 6px; }
.autonomy-crit { background: #fde8e8; color: #b42318; }
.autonomy-warn { background: #fdf0e0; color: #b54708; }
.autonomy-ok { background: #e8f5ef; color: #14714f; }
.autonomy-info { background: #e8f0fe; color: #1d4ed8; }
.autonomy-unknown { background: #f1f3f6; color: #5a6272; font-style: italic; }
.contradiction-list { display: flex; flex-direction: column; gap: 10px; }
.contradiction-card { background: #fff; border: 1px solid #e3e6ec;
  border-left: 5px solid #b42318; border-radius: 8px; padding: 12px 16px; }
.contradiction-card .top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.contradiction-card .rule { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas,
  monospace; font-weight: 700; font-size: 13px; color: #b42318; }
.contradiction-card p { margin: 4px 0; font-size: 13px; }
/* grouped contradictions (Task 3) */
.contra-group summary { cursor: pointer; font-size: 13px; font-weight: 600; }
.contra-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 4px; }
.chip-vs { display: inline-flex; align-items: center; gap: 6px; font-size: 12px;
  border-radius: 6px; padding: 3px 9px; }
.chip-declared { background: #eef2f6; color: #465063; }
.chip-observed { background: #fde8e8; color: #b42318; }
.chip-arrow { color: #8a94a6; font-size: 12px; }

/* --- verdict-first IA (report rebuild) -------------------------------- */
.verdict { background: #171c26; color: #f2f4f8; border-radius: 10px;
  padding: 20px 22px; margin: 0 0 16px; }
.verdict .lede { font-size: 19px; line-height: 1.4; font-weight: 600; margin: 0 0 8px;
  text-wrap: balance; }
.verdict .sub { font-size: 14px; line-height: 1.55; color: #c4ccd8; margin: 0; }
.verdict .sub .ruleref { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas,
  monospace; font-size: 12.5px; background: #2a313f; border-radius: 4px; padding: 1px 6px;
  color: #e6ebf2; }
.verdict a { color: #8fb8ec; }
.scoreboard { display: flex; flex-direction: column; gap: 10px; margin: 0 0 6px; }
.tier-bar { display: flex; height: 34px; border-radius: 8px; overflow: hidden;
  border: 1px solid #e3e6ec; background: #eef0f4; }
.tier-seg { display: flex; align-items: center; justify-content: center; color: #fff;
  font-size: 12.5px; font-weight: 700; min-width: 0; }
.tier-seg.t-severe { background: #7a1d16; }
.tier-seg.t-elevated { background: #b42318; }
.tier-seg.t-moderate { background: #d29a1f; }
.tier-seg.t-low { background: #9aa4b2; }
.tier-legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: #5a6272; }
.tier-legend span { display: inline-flex; align-items: center; gap: 6px; }
.tier-key { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
.ribbon { font-size: 13px; color: #3a4150; background: #fff;
  border: 1px solid #e3e6ec; border-radius: 8px; padding: 9px 14px;
  font-variant-numeric: tabular-nums; }
.ribbon b { color: #1a1d23; }
.ribbon .dot { color: #c2c8d0; margin: 0 6px; }
.fix-list { display: flex; flex-direction: column; gap: 10px; }
.fix-item { background: #fff; border: 1px solid #e3e6ec; border-left: 4px solid #b42318;
  border-radius: 8px; padding: 12px 15px; }
.fix-item.sev-high { border-left-color: #d29a1f; }
.fix-item .fh { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.fix-item .ft { font-size: 14.5px; font-weight: 650; }
.fix-item .impact { font-size: 13px; color: #3a4150; margin: 6px 0; }
.fix-item .remedy { font-size: 13px; color: #14714f; margin: 6px 0; }
.fix-item .remedy b { color: #0f5a3e; }
.fix-item pre { background: #f6f7f9; border: 1px solid #e9ebef; border-radius: 6px;
  padding: 8px 10px; overflow-x: auto; font-size: 12px; margin: 6px 0; }
.fix-item .refline { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px; color: #5a6272; display: flex; flex-wrap: wrap; gap: 6px; }
.fix-item .refline .r { background: #f1f3f6; border-radius: 4px; padding: 1px 6px; }
.fix-item .pointer { font-size: 12.5px; color: #5a6272; }
.fix-item .pointer a { color: #2f6fb0; }
.appendix { margin-top: 20px; border-top: 1px solid #e3e6ec; padding-top: 8px; }
.appendix > summary { cursor: pointer; font-size: 15px; font-weight: 650; padding: 8px 0; }

/* --- ≤5-page compression + explainability --------------------------- */
.how-to-read { font-size: 12.5px; color: #5a6272; margin: 0 0 14px; line-height: 1.5; }
.how-to-read b { color: #1a1d23; }
section > .cap, p.cap { font-size: 12px; color: #7c8aa0; margin: -2px 0 10px;
  letter-spacing: 0.01em; }
p.cap a { color: #2f6fb0; text-decoration: none; }
abbr[title] { text-decoration: underline dotted; text-underline-offset: 2px;
  cursor: help; }
/* agents compact strip */
.agent-strip { display: flex; flex-direction: column; gap: 2px; }
.agent-line { display: grid; grid-template-columns: 1fr 1.4fr auto auto; gap: 12px;
  align-items: center; padding: 7px 12px; background: #fff; border: 1px solid #e3e6ec;
  border-radius: 8px; border-left: 4px solid #7a1d16; font-size: 13px; }
.al-name { font-weight: 650; }
.al-file { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px; color: #5a6272; }
.al-tier { font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.03em; color: #7a1d16; }
.al-score { font-variant-numeric: tabular-nums; font-weight: 700; color: #1a1d23; }
/* dimension cards (single surviving dimension section) */
.dim-cards { display: flex; flex-direction: column; gap: 7px; }
.dim-card { background: #fff; border: 1px solid #e3e6ec; border-left: 4px solid #d9dde3;
  border-radius: 8px; padding: 10px 14px; }
.dim-card.lv-elevated { border-left-color: #b42318; }
.dim-card.lv-moderate { border-left-color: #d29a1f; }
.dim-card-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.dim-card-head strong { font-size: 14px; }
.dim-counts { font-size: 12px; color: #7c8aa0; margin-left: auto;
  font-variant-numeric: tabular-nums; }
.dim-gloss { font-size: 13px; color: #2b2f36; margin: 6px 0 4px; line-height: 1.5; }
.dim-tags { display: flex; flex-wrap: wrap; gap: 4px; margin: 2px 0; }
.dim-ev { margin-top: 4px; }
.dim-ev summary { font-size: 12px; color: #5a6272; cursor: pointer; }
.ev-wrap { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.proxy-strip { font-size: 12.5px; color: #5a6272; background: #f4f6f8;
  border: 1px solid #e9ebef; border-radius: 8px; padding: 8px 12px; margin-top: 7px; }
.proxy-key { font-weight: 700; color: #465063; margin-right: 4px; }
/* standards: one line of chips */
.owasp-line { display: flex; flex-wrap: wrap; gap: 6px; }
.owasp-chip { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px; font-weight: 700; border-radius: 6px; padding: 2px 8px;
  text-decoration: none; border: 1px solid transparent; }
.owasp-chip .st { font-weight: 600; text-transform: uppercase; font-size: 9.5px;
  letter-spacing: 0.03em; opacity: 0.85; }
.owasp-chip.owasp-assessed { background: #fef7dc; color: #93700b; border-color: #ead98c; }
.owasp-chip.owasp-partial { background: #e8f0fe; color: #1d4ed8; }
.owasp-chip.owasp-proxy { background: #eef2f6; color: #465063; }
.owasp-chip.owasp-notassessed { background: #f1f3f6; color: #7c8aa0; }
/* fix-first compaction */
.fix-snip { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11.5px; background: #f1f3f6; border-radius: 4px; padding: 1px 5px; }
.fix-item .why { margin-top: 6px; }
.fix-item .why summary { font-size: 12px; color: #5a6272; cursor: pointer; }
.fix-item .why p { font-size: 12.5px; color: #3a4150; margin: 6px 0 0; }

/* --- crosswalk / explainability (Feature 2) --------------------------- */
.exec-summary { background: #fff; border: 1px solid #e3e6ec; border-left: 4px solid #2f6fb0;
  border-radius: 8px; padding: 14px 18px; margin: 6px 0 4px; }
.exec-summary p { margin: 0 0 8px; font-size: 14px; line-height: 1.55; }
.exec-summary p:last-child { margin-bottom: 0; }
.exec-summary .callout { font-weight: 600; color: #1a1d23; }
.exec-summary .callout .ruleref { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas,
  monospace; font-size: 12.5px; background: #f1f3f6; border-radius: 4px; padding: 1px 5px; }
.owasp-strip { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; }
.owasp-cell { flex: 1 1 150px; min-width: 150px; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 8px 10px; background: #fff; }
.owasp-cell .code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-weight: 700; font-size: 12px; }
.owasp-cell .name { font-size: 11.5px; color: #5a6272; display: block; margin: 1px 0 5px; }
.owasp-cell .state { font-size: 10.5px; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.03em; border-radius: 10px; padding: 1px 7px; display: inline-block; }
.owasp-assessed { border-left: 3px solid #b8901a; }
.owasp-assessed .state { background: #fef7dc; color: #93700b; }
.owasp-proxy .state { background: #eef2f6; color: #465063; }
.owasp-partial .state { background: #e8f0fe; color: #1d4ed8; }
.owasp-notassessed { opacity: 0.72; }
.owasp-notassessed .state { background: #f1f3f6; color: #7c8aa0; }
.xwalk-tag { display: inline-block; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas,
  monospace; font-size: 11px; font-weight: 600; border-radius: 6px; padding: 1px 6px;
  margin: 1px 2px 1px 0; }
.xwalk-owasp { background: #eaf1fb; color: #1d4ed8; }
.xwalk-eu { background: #f0ecfa; color: #5b3a9e; }
.evchip { display: inline-block; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas,
  monospace; font-size: 11px; background: #f1f3f6; color: #465063; border-radius: 6px;
  padding: 1px 6px; margin: 1px 2px 1px 0; }
.evchip.credit { background: #e8f5ef; color: #14714f; }
.xwalk-table td { vertical-align: top; }
.xwalk-table .sowhat { font-size: 12.5px; color: #1a1d23; }
.nist-rollup { background: #fafbfc; border: 1px solid #e3e6ec; border-radius: 8px;
  padding: 12px 16px; margin: 12px 0 4px; font-size: 13px; line-height: 1.6; }
.nist-rollup strong { color: #1a1d23; }
"""

_EXP_GLYPH = {"elevated": "●", "moderate": "◐", "low": "○",
              "none-observed": "·", "not-assessable": "∅"}
_EXP_CLASS = {"elevated": "exp-elevated", "moderate": "exp-moderate",
              "low": "exp-low", "none-observed": "exp-none", "not-assessable": "exp-none"}
_EXP_LABEL = {"elevated": "elev", "moderate": "mod", "low": "low",
              "none-observed": "", "not-assessable": "n/a"}

BAR_CLASS = {
    "severe": "bar-severe",
    "elevated": "bar-elevated",
    "moderate": "bar-moderate",
    "low": "bar-low",
}


def render_html(
    result: ScanResult, config: StoaConfig, document: dict | None = None
) -> str:
    """Render the report. ``document``, when given, is a pre-built (possibly
    runtime-enriched) registry dict used for the architecture-graph section —
    `stoa scan --with-runtime` passes the enriched document so observed and
    delegates edges render; plain scans pass nothing and behave as before."""
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

    # Crosswalk / explainability (Feature 2) + underwriting demo (Feature 3).
    # Loaded up-front so the CSP can declare the underwriting script hash, and
    # the report document is built once here and reused for graph + demo.
    crosswalk = None
    try:
        from .crosswalk import load_crosswalk
        crosswalk = load_crosswalk(config.crosswalk_path)
    except Exception:  # noqa: BLE001 - explainability is additive, never fatal
        crosswalk = None

    underwriting_html = None
    if crosswalk is not None:
        try:
            from .report_json import build_document
            from .underwriting import render_underwriting_html
            report_document = document if document is not None else build_document(result, config)
            underwriting_html = render_underwriting_html(report_document)
        except Exception:  # noqa: BLE001 - demo export never breaks the report
            underwriting_html = None

    script_hashes = [f"'sha256-{DOWNLOAD_SCRIPT_HASH}'"]
    cytoscape_version = None
    if not config.no_graph:
        from .report_graph import CYTOSCAPE_VERSION, csp_script_src

        script_hashes.append(csp_script_src())
        cytoscape_version = CYTOSCAPE_VERSION
    if underwriting_html is not None:
        script_hashes.append(f"'sha256-{UNDERWRITING_SCRIPT_HASH}'")
    script_src = " script-src " + " ".join(script_hashes) + ";"
    parts.append(
        "<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta http-equiv=\"Content-Security-Policy\" "
        "content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:;"
        f"{script_src}\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>Stoa Agent Risk Report — {html_text(result.repository.name)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
    )
    parts.append(
        '<header class="page"><div class="inner">'
        '<div class="hdr-actions">'
        '<button type="button" id="stoa-download-report" class="dl-btn">'
        "Download report</button>"
        + ('<button type="button" id="stoa-underwriting-btn" class="dl-btn">'
           "Generate underwriting evidence</button>" if underwriting_html is not None else "")
        + "</div>"
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

    # Report presentation thresholds (Task 4). Additive/optional: degrades to
    # built-in defaults if a bad override path is given.
    rcfg = None
    try:
        from .report_config import load_report_config
        rcfg = load_report_config(config.report_config_path)
    except Exception:  # noqa: BLE001 - presentation config never breaks the report
        from .report_config import default_report_config
        rcfg = default_report_config()

    # ---- Verdict-first information architecture --------------------------
    # 1 Verdict · 2 Scoreboard · 3 Fix first · 4 Contradictions · 5 Agents ·
    # 6 Risk dimensions · 7 Standards · 8 Appendix (NIST + all findings + graph).
    fix_items = _fix_first_items(result, rcfg) if crosswalk is not None or True else []

    # 1 · Verdict + one-line "how to read this"
    parts.append(_verdict_section(result, crosswalk, fix_items))
    parts.append(
        '<p class="how-to-read"><abbr title="what the code makes possible, not '
        'what has been proven to happen">Exposure</abbr> = what the code makes '
        "possible, not what has happened. <b>Fix first</b> clears the criticals; "
        "<b>Contradictions</b> shows where your declarations don't match the code.</p>"
    )
    if result.diff_available:
        parts.append(
            '<p class="cap">only newly introduced findings affect the gate</p>'
        )

    # 2 · Scoreboard
    parts.append(_scoreboard_section(result))
    if result.diff_available:
        parts.append(_new_critical_section(result))

    # 3 · Fix first
    parts.append(_fix_first_section(result, crosswalk, rcfg, fix_items))

    # 4 · Contradictions — Stoa's differentiator, lifted to the front
    parts.append(_contradictions_section(result, rcfg))

    # 5 · Agents — compact strip in the body (severe tier only, ≤4 lines); the
    #     full 12-agent detail moves to the appendix, collapsed.
    ranked = sorted(result.agents, key=lambda a: (-exposure_score(a), a.path, a.symbol))
    severe = [a for a in ranked if exposure_tier(a)[0] == "severe"][:4]
    parts.append("<section><h2>Agents</h2>"
                 '<p class="cap">which agents carry the risk</p>')
    if ranked:
        parts.append('<div class="agent-strip">')
        for a in severe:
            slug, label = exposure_tier(a)
            parts.append(
                f'<div class="agent-line"><span class="al-name">{html_text(a.label)}</span>'
                f'<span class="al-file">{html_text(a.path)}</span>'
                f'<span class="al-tier tier-{slug}">{html_text(label)}</span>'
                f'<span class="al-score">{exposure_score(a)}</span></div>'
            )
        parts.append("</div>")
        rest = len(ranked) - len(severe)
        if rest > 0:
            parts.append(
                f'<p class="cap"><a href="#appendix-agents">{rest} more agents — '
                "elevated and below ▸</a></p>"
            )
    else:
        parts.append('<p class="empty">No agent candidates were detected.</p>')
    parts.append("</section>")

    # 6 · Risk dimensions (the single surviving dimension section)
    if result.dimension_summary is not None and result.agents:
        parts.append(_dimension_matrix(result, crosswalk, config))

    # 7 · Standards (OWASP LLM Top 10 coverage — one line of chips, gaps visible)
    if crosswalk is not None:
        parts.append(_owasp_strip(result, config, crosswalk))

    # 8 · Appendix (collapsed): NIST roll-up, full agents, all findings, graph.
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

    parts.append('<details class="appendix"><summary>Appendix — full agent detail, '
                 "all findings, standards alignment, and architecture</summary>")

    # Full 12-agent list with all detail (moved out of the body).
    parts.append('<section id="appendix-agents"><h2>All agents</h2>')
    parts.append('<div class="risk-map">')
    for agent in ranked:
        parts.append(_agent_card(agent, result.diff_available))
    parts.append("</div></section>")

    if crosswalk is not None and result.agents:
        parts.append(_nist_rollup())

    parts.append("<section><h2>All findings</h2>"
                 '<p class="cap">every finding, grouped — nothing omitted</p>')
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

    # Architecture graph (demoted into the appendix)
    if not config.no_graph:
        from .graph_model import build_graph, overlay_runtime
        from .report_graph import render_graph_section
        from .report_json import build_document

        graph_document = document if document is not None else build_document(result, config)
        graph = build_graph(graph_document)
        runtime_block = graph_document.get("runtime")
        if runtime_block:
            graph = overlay_runtime(graph, graph_document)
        parts.append(render_graph_section(graph))
        if runtime_block:
            window = runtime_block.get("window") or {}
            parts.append(
                '<p class="note">Runtime overlay: thick edges were observed in '
                "traces (corroborating static detection); dashed edges exist only "
                "in runtime evidence. Window "
                f"{html_text(window.get('start') or '?')} → "
                f"{html_text(window.get('end') or '?')}, "
                f"{html_text(runtime_block.get('span_count', 0))} span(s), "
                f"{html_text(runtime_block.get('agents_covered', 0))} of "
                f"{html_text(runtime_block.get('agents_total', 0))} agent(s) covered. "
                "Observed means observed in this window — never a claim about "
                "future behavior.</p>"
            )
    parts.append("</details>")

    parts.append(
        "<footer>Stoa performs static, pattern-based analysis: findings are "
        "intra-file (data flows through other files are not traced), runtime "
        "behavior is not observed, and organization-wide controls may not be "
        "visible in the scanned repository. Findings and agent classifications "
        "should be reviewed by an engineer."
        + (
            "" if cytoscape_version is None else
            " The architecture graph is rendered with "
            f"<a href=\"https://js.cytoscape.org/\">Cytoscape.js</a> {cytoscape_version} "
            "(MIT License, vendored — no network request is made)."
        )
        + "</footer>\n</main>\n"
    )
    # Underwriting demo (Feature 3): the pre-filled form embedded as a
    # non-executing JSON blob, opened in a new tab by the hash-pinned script.
    # Every '<' is escaped to < so the embedded form's own <script>/
    # </script> (and any repo-derived value) is fully inert inside the data
    # tag — it cannot close the tag early or be miscounted as executable.
    # JSON.parse restores the original characters client-side.
    if underwriting_html is not None:
        uw_json = _json.dumps(underwriting_html).replace("<", "\\u003c")
        parts.append(
            f'<script type="application/json" id="stoa-uw-data">{uw_json}</script>\n'
            f"<script>{_UNDERWRITING_JS}</script>\n"
        )
    parts.append(f"<script>{_DOWNLOAD_JS}</script>\n</body>\n</html>\n")
    return "".join(parts)



_EXP_RANK = {"elevated": 3, "moderate": 2, "low": 1, "none-observed": 0,
             "not-assessable": 0}


def _dimension_matrix(result: ScanResult, crosswalk=None, config=None) -> str:
    """The single surviving dimension section (the by-agent chips, the 12 agent
    drill-downs, and the standalone framework table were all deleted — the same
    data lived four times). One card per dimension, worst-first: plain-English
    gloss FIRST (the canonical taxonomy definition, ≤140 chars — never a
    concatenation of finding sentences), then max exposure + framework tags,
    then evidence behind an expander. Proxy-tier dimensions merge into one
    compact strip. Presentation only; scores untouched."""
    summary = result.dimension_summary
    dim_meta = {d["id"]: d for d in summary["dimensions"]}

    # Canonical per-dimension glosses from the taxonomy definition field.
    definitions: dict[str, str] = {}
    try:
        from .dimensions import load_taxonomy
        tax = load_taxonomy(config.dimensions_taxonomy if config else None)
        definitions = {d.id: d.definition for d in tax.dimensions}
    except Exception:  # noqa: BLE001 - fall back to the summary rows without glosses
        definitions = {}

    # Per-dimension framework tags + evidence, from firing findings (deduped).
    owasp_by_dim: dict[str, set[str]] = {}
    eu_by_dim: dict[str, set[str]] = {}
    evidence_by_dim: dict[str, list] = {}
    for f in result.findings:
        if f.suppressed:
            continue
        entry = crosswalk.entry(f.rule_id) if crosswalk else None
        for did in f.dimensions:
            if entry and entry.owasp_llm_2025:
                owasp_by_dim.setdefault(did, set()).add(entry.owasp_llm_2025)
            if entry and entry.eu_ai_act:
                eu_by_dim.setdefault(did, set()).add(entry.eu_ai_act)
            evidence_by_dim.setdefault(did, []).append(f)
    controls_by_dim: dict[str, set[str]] = {}
    for agent in result.agents:
        if not agent.dimension_assessment:
            continue
        for e in agent.dimension_assessment["dimensions"]:
            if e["controls_observed"]:
                controls_by_dim.setdefault(e["id"], set()).update(e["controls_observed"])

    def _owasp_key(c):
        return (0, int(c[3:])) if c.startswith("LLM") and c[3:].isdigit() else (1, c)

    def _gloss(did):
        g = definitions.get(did) or dim_meta.get(did, {}).get("statement", "")
        return (g[:137] + "…") if len(g) > 140 else g

    def _tags(did):
        owasp = "".join(
            f'<span class="xwalk-tag xwalk-owasp">{html_text(c)}</span>'
            for c in sorted(owasp_by_dim.get(did, set()), key=_owasp_key))
        eu = "".join(
            f'<span class="xwalk-tag xwalk-eu">{html_text(a)}</span>'
            for a in sorted(eu_by_dim.get(did, set())))
        return owasp + eu

    def _evidence(did):
        seen, chips = set(), []
        for f in sorted(evidence_by_dim.get(did, []), key=lambda f: (f.path, f.line, f.rule_id)):
            key = (f.rule_id, f.path, f.line)
            if key in seen:
                continue
            seen.add(key)
            chips.append(f'<span class="evchip">{html_text(f.rule_id)} · '
                         f'{html_text(f.path)}:{html_text(f.line)}</span>')
        for c in sorted(controls_by_dim.get(did, set())):
            chips.append(f'<span class="evchip credit">{html_text(c)} observed</span>')
        return chips

    proxy_merge = True  # rcfg.dimension_proxy_merge, threaded via caller default
    dims = sorted(
        summary["dimensions"],
        key=lambda d: (-_EXP_RANK.get(d["max_exposure"], 0),
                       -d.get("agents_elevated", 0), d["id"]),
    )
    primary = [d for d in dims if d["assessability"] != "proxy"]
    proxy = [d for d in dims if d["assessability"] == "proxy"]

    parts = ['<section><h2>Risk dimensions</h2>'
             '<p class="cap">what kinds of risk, and which rules they map to</p>'
             '<div class="dim-cards">']
    for d in primary:
        did = d["id"]
        lv = d["max_exposure"]
        elev = d.get("agents_elevated", 0)
        mod = d.get("agents_moderate", 0)
        chips = _evidence(did)
        ev = ""
        if chips:
            ev = (f'<details class="dim-ev"><summary>{len(chips)} evidence item'
                  f'{"s" if len(chips) != 1 else ""}</summary>'
                  f'<div class="ev-wrap">{"".join(chips)}</div></details>')
        gloss = _gloss(did)
        parts.append(
            f'<div class="dim-card lv-{lv}"><div class="dim-card-head">'
            f'<strong>{html_text(d["name"])}</strong> {_exposure_badge(lv)}'
            f'<span class="dim-counts">{elev} elevated · {mod} moderate</span></div>'
            + (f'<p class="dim-gloss">{html_text(gloss)}</p>' if gloss else "")
            + (f'<div class="dim-tags">{_tags(did)}</div>' if _tags(did) else "")
            + ev + "</div>"
        )
    parts.append("</div>")

    # Proxy-tier dimensions: one compact strip, not full cards.
    if proxy:
        names = " · ".join(
            f'<abbr title="indirect signal only; capped at moderate — runtime '
            f'evaluation required">{html_text(d["name"])}</abbr> '
            f'({html_text(d["max_exposure"])})' for d in proxy)
        parts.append(
            f'<div class="proxy-strip"><span class="proxy-key">Proxy-tier</span> '
            f'{names} — indirect signals only, capped at moderate.</div>')

    parts.append(
        '<div class="dim-legend">'
        '<span><span class="exp-elevated">●</span> elevated</span>'
        '<span><span class="exp-moderate">◐</span> moderate</span>'
        '<span><span class="exp-low">○</span> low</span>'
        '<span>proxy signals only — runtime evaluation required</span></div>'
    )
    parts.append("</section>")
    return "".join(parts)


def _exposure_badge(exp: str) -> str:
    return (f'<span class="{_EXP_CLASS.get(exp, "exp-none")}">'
            f'{_EXP_GLYPH.get(exp, "·")} {html_text(exp)}</span>')


# --- crosswalk / explainability layer (Feature 2) ---------------------------
# All static HTML; no new scripts, so the report's zero-network hash-pinned CSP
# is untouched. Every function degrades to "" if the crosswalk can't load, so
# the report renders exactly as before when the annotation layer is absent.

def _fired_rules(result: ScanResult) -> set[str]:
    return {f.rule_id for f in result.findings if not f.suppressed}


# Capability blast-radius weights (Task 2, Fix-first ranking). Shell/code/money
# outrank messaging. Used only for ordering — never for scoring.
_CAP_BLAST = {
    "shell_execution": 5, "code_execution": 5, "payment_access": 5,
    "database_write": 4, "filesystem_write": 3, "source_control": 3,
    "cloud_resource_access": 3, "email_send": 2, "messaging": 2,
}
_FIX_SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}


def _agents_by_tier(result: ScanResult) -> dict[str, int]:
    counts = {"severe": 0, "elevated": 0, "moderate": 0, "low": 0}
    for a in result.agents:
        slug, _ = exposure_tier(a)
        counts[slug] = counts.get(slug, 0) + 1
    return counts


def _finding_blast(result: ScanResult, finding: Finding) -> int:
    """Max capability blast-weight among agents sharing this finding's file."""
    best = 1
    for a in result.agents:
        if a.path == finding.path:
            for cap in a.capabilities:
                best = max(best, _CAP_BLAST.get(cap, 1))
    return best


def _verdict_section(result: ScanResult, crosswalk, fix_items: list) -> str:
    """One generated verdict sentence: agent count, worst-tier count, and the
    theme of the risk; then a subline naming the top concrete risk + fix count.
    Deterministic — derived only from the (deterministic) registry."""
    agents = result.agents
    n = len(agents)
    if n == 0:
        return ('<section><div class="verdict"><p class="lede">No agent candidates '
                "were detected in this repository.</p></div></section>")
    tiers = _agents_by_tier(result)
    worst = tiers["severe"] + tiers["elevated"]

    # Theme: dominant high-impact capability among top-tier agents, paired with
    # the elevated dimension it most often drives.
    top_agents = [a for a in agents if exposure_tier(a)[0] in ("severe", "elevated")]
    cap_counts: dict[str, int] = {}
    for a in top_agents:
        for cap in HIGH_IMPACT_CAPABILITIES.intersection(a.capabilities):
            cap_counts[cap] = cap_counts.get(cap, 0) + 1
    theme = ""
    if cap_counts:
        top_caps = sorted(cap_counts, key=lambda c: (-cap_counts[c], c))[:2]
        phrases = {
            "payment_access": "move money", "shell_execution": "execute shell commands",
            "code_execution": "execute code", "database_write": "write to databases",
            "filesystem_write": "write to the filesystem", "source_control": "push to source control",
            "cloud_resource_access": "control cloud resources", "email_send": "send email",
            "messaging": "send messages",
        }
        verbs = [phrases.get(c, c.replace("_", " ")) for c in top_caps]
        theme = " and ".join(verbs)

    lede = (f"Stoa found <strong>{n}</strong> agent candidate{'s' if n != 1 else ''}"
            f" — <strong>{worst}</strong> at elevated exposure or above")
    if theme:
        lede += f", with agents that can {theme} running on autonomy their declarations may not grant"
    lede += "."

    sub = ""
    if fix_items:
        top = fix_items[0]
        entry = crosswalk.entry(top["rule_id"]) if crosswalk else None
        owasp = f" · {html_text(entry.owasp_llm_2025)}" if entry and entry.owasp_llm_2025 else ""
        n_fix = len(fix_items)
        sub = (f'Top risk: <span class="ruleref">{html_text(top["rule_id"])} · '
               f'{html_text(top["path"])}:{html_text(top["line"])}{owasp}</span> — '
               f'{html_text(top["title"])}. '
               f'<a href="#fix-first">{n_fix} fix{"es" if n_fix != 1 else ""}</a> '
               "clear every critical finding.")
    else:
        sub = "No critical findings require a fix in this scan."

    return (f'<section><div class="verdict"><p class="lede">{lede}</p>'
            f'<p class="sub">{sub}</p></div></section>')


def _scoreboard_section(result: ScanResult) -> str:
    """One hero scoreboard: agents-by-exposure-tier stacked bar + a single
    findings ribbon. Every number is labeled precisely and reconciles."""
    tiers = _agents_by_tier(result)
    n = sum(tiers.values()) or 1
    order = [("severe", "Severe"), ("elevated", "Elevated"),
             ("moderate", "Moderate"), ("low", "Low")]
    segs = []
    for slug, label in order:
        c = tiers[slug]
        if not c:
            continue
        pct = c * 100 / n
        segs.append(f'<div class="tier-seg t-{slug}" style="width:{pct:.4f}%" '
                    f'title="{label}: {c}">{c if pct >= 6 else ""}</div>')
    key_color = {"severe": "#7a1d16", "elevated": "#b42318",
                 "moderate": "#d29a1f", "low": "#9aa4b2"}
    legend = "".join(
        f'<span><span class="tier-key" style="background:{key_color[slug]}"></span>'
        f'{label} <strong>{tiers[slug]}</strong></span>'
        for slug, label in order
    )

    sc = result.severity_counts()
    active_total = sum(sc.get(s, 0) for s in SEVERITIES)
    parts = [f'{sc.get(s, 0)} {s}' for s in reversed(SEVERITIES) if sc.get(s, 0)]
    breakdown = " · ".join(parts) if parts else "none"
    integrations = len({i for a in result.agents for i in a.integrations})
    ribbon = (
        f'<div class="ribbon"><b>{active_total}</b> active finding'
        f'{"s" if active_total != 1 else ""} — {breakdown}'
        f'<span class="dot">·</span><b>{result.suppressed_count()}</b> suppressed'
        f'<span class="dot">·</span><b>{integrations}</b> integration'
        f'{"s" if integrations != 1 else ""}'
        f'<span class="dot">·</span><b>{result.files_scanned}</b> files scanned</div>'
    )
    # Severity legend as one hoverable line (defined once, in Stoa's terms).
    sev_defs = {
        "critical": "exploitable now, or a gate-eligible contradiction",
        "high": "a serious exposure that should be repaired",
        "medium": "worth review; not an immediate exposure",
        "low": "minor or informational",
    }
    sev_legend = " ".join(
        f'<abbr title="{sev_defs[s]}">{s}</abbr>' for s in ("critical", "high", "medium", "low")
    )
    return (
        '<section><h2>Scoreboard</h2>'
        '<p class="cap">how much risk, and where it sits · severity: '
        f'{sev_legend}</p>'
        f'<div class="scoreboard"><div class="tier-bar">{"".join(segs)}</div>'
        f'<div class="tier-legend">{legend}</div>{ribbon}</div></section>'
    )


def _fix_first_items(result: ScanResult, rcfg) -> list:
    """The remediation work-list: active findings at/above the floor severity,
    merged when they share a rule class AND remediation, ranked by
    severity × blast radius, capped. Deterministic ordering throughout."""
    floor = _FIX_SEV_RANK.get(rcfg.fix_first_min_severity, 3)
    eligible = [
        f for f in result.findings
        if not f.suppressed and _FIX_SEV_RANK.get(f.severity, 0) >= floor
    ]
    # merge by (rule_id, remediation) — same class + same fix = one item
    groups: dict[tuple, list] = {}
    for f in eligible:
        groups.setdefault((f.rule_id, f.remediation), []).append(f)

    items = []
    for (rule_id, remediation), fs in groups.items():
        fs.sort(key=lambda f: (f.path, f.line))
        head = fs[0]
        blast = max(_finding_blast(result, f) for f in fs)
        sev_rank = max(_FIX_SEV_RANK.get(f.severity, 0) for f in fs)
        items.append({
            "rule_id": rule_id,
            "title": head.title,
            "severity": "critical" if sev_rank >= 4 else "high" if sev_rank == 3 else head.severity,
            "remediation": remediation,
            "snippet": head.snippet,
            "message": head.message,
            "path": head.path,
            "line": head.line,
            "sites": [(f.path, f.line) for f in fs],
            "count": len(fs),
            "is_contradiction": rule_id.startswith("DECL") or rule_id.startswith("RT"),
            "_rank": (sev_rank, blast, -len(fs)),
        })
    items.sort(key=lambda it: (-it["_rank"][0], -it["_rank"][1], it["_rank"][2],
                               it["rule_id"], it["path"], it["line"]))
    return items[: rcfg.fix_first_max]


def _fix_first_section(result: ScanResult, crosswalk, rcfg, items: list) -> str:
    if not items:
        return ""
    rows = []
    for it in items:
        entry = crosswalk.entry(it["rule_id"]) if crosswalk else None
        owasp = entry.owasp_llm_2025 if entry else ""
        article = entry.eu_ai_act if entry else ""
        sev_cls = "sev-high" if it["severity"] == "high" else ""
        loc = f'{html_text(it["path"])}:{html_text(it["line"])}'
        if it["count"] > 1:
            loc += f' <span class="r">+{it["count"] - 1} more</span>'
        ref = [f'<span class="r">{html_text(it["rule_id"])}</span>',
               f'<span class="r">{loc}</span>']
        if owasp:
            ref.append(f'<span class="r">{html_text(owasp)}</span>')
        if article:
            ref.append(f'<span class="r">{html_text(article)}</span>')
        refline = f'<div class="refline">{"".join(ref)}</div>'

        if it["is_contradiction"]:
            # Task 3 dedup: Contradictions owns the full detail; here, a pointer.
            body = ('<p class="pointer">A declared-vs-observed contradiction — '
                    'full detail in <a href="#contradictions">Contradictions</a>.</p>')
            rows.append(
                f'<div class="fix-item {sev_cls}"><div class="fh">'
                f'<span class="ft">{html_text(it["title"])}</span>'
                f'{_severity_badge(it["severity"])}</div>{body}{refline}</div>'
            )
            continue

        # 4 lines: title+chip · one-line impact (≤140, never the title) · Fix ·
        # meta. The impact is the crosswalk gloss (the plain-English "so what").
        gloss = (entry.so_what if entry and entry.so_what else "")
        impact = gloss or it["title"]
        if impact.strip().lower() == it["title"].strip().lower():
            impact = it["message"] or impact
        if len(impact) > 140:
            impact = impact[:137] + "…"
        snippet = ""
        if it["snippet"] and it["snippet"] != "[REDACTED]" and len(it["snippet"]) <= 60:
            snippet = f'<code class="fix-snip">{html_text(it["snippet"])}</code>'
        # methodology + flow detail live behind an expander, not inline
        why = it["message"]
        why_block = ""
        if why and why.strip().lower() != impact.strip().lower():
            why_block = (f'<details class="why"><summary>Why this fired</summary>'
                         f'<p>{html_text(why)}</p></details>')
        rows.append(
            f'<div class="fix-item {sev_cls}"><div class="fh">'
            f'<span class="ft">{html_text(it["title"])}</span>'
            f'{_severity_badge(it["severity"])}</div>'
            f'<p class="impact">{html_text(impact)}{(" " + snippet) if snippet else ""}</p>'
            f'<p class="remedy"><b>Fix:</b> {html_text(it["remediation"])}</p>'
            f'{refline}{why_block}</div>'
        )
    return (
        '<section id="fix-first"><h2>Fix first</h2>'
        '<p class="cap">what to repair, in order</p>'
        f'<div class="fix-list">{"".join(rows)}</div></section>'
    )


def _owasp_strip(result: ScanResult, config, crosswalk) -> str:
    """All 10 OWASP LLM Top 10 (2025) classes, each stamped assessed / proxy /
    partial / not-assessed. Gaps (classes with no Stoa detector) stay visible —
    that honesty is required, not optional."""
    from .crosswalk import OWASP_LLM_2025
    from .dimensions import load_taxonomy

    # which rules map to each OWASP class, and which of them can Stoa detect
    class_to_rules: dict[str, list[str]] = {}
    for rule_id in RULES:
        code = crosswalk.entry(rule_id).owasp_llm_2025
        if code:
            class_to_rules.setdefault(code, []).append(rule_id)

    fired = _fired_rules(result)
    # proxy dimensions from the taxonomy — a class is "proxy-only" when the
    # only firing evidence for it lands solely on proxy-tier dimensions.
    try:
        tax = load_taxonomy(config.dimensions_taxonomy)
        proxy_dims = {d.id for d in tax.dimensions if d.assessability == "proxy"}
    except Exception:  # noqa: BLE001 - strip still renders without tier info
        proxy_dims = set()
    fired_dims_by_rule: dict[str, set[str]] = {}
    for f in result.findings:
        if not f.suppressed:
            fired_dims_by_rule.setdefault(f.rule_id, set()).update(f.dimensions)

    def state(code: str) -> tuple[str, str]:
        rules = class_to_rules.get(code)
        if not rules:
            return "not-assessed", "owasp-notassessed"
        fired_here = [r for r in rules if r in fired]
        if not fired_here:
            return "partial", "owasp-partial"
        dims = set()
        for r in fired_here:
            dims |= fired_dims_by_rule.get(r, set())
        if dims and dims <= proxy_dims:
            return "proxy", "owasp-proxy"
        return "assessed", "owasp-assessed"

    # One compact line of chips (not ten cards). Gaps stay visible as chips.
    titles = {
        "assessed": "a mapping rule fired in this scan",
        "partial": "Stoa can assess it, but nothing fired here",
        "proxy": "only a proxy-tier signal — runtime evaluation required",
        "not-assessed": "no Stoa detector — an honest coverage gap",
    }
    cells = []
    for code, name in OWASP_LLM_2025:
        label, cls = state(code)
        cells.append(
            f'<abbr class="owasp-chip {cls}" title="{code} {html_text(name)} — '
            f'{titles[label]}">{code} <span class="st">{label}</span></abbr>'
        )
    return (
        '<section><h2>Standards</h2>'
        '<p class="cap">which risk classes were assessed — gaps kept visible</p>'
        f'<div class="owasp-line">{"".join(cells)}</div></section>'
    )



def _nist_rollup() -> str:
    """One report-level NIST AI RMF paragraph — never per-rule tags."""
    return (
        '<section><h2>NIST AI RMF alignment</h2>'
        '<div class="nist-rollup">'
        "The evidence in this report maps to three NIST AI RMF functions. "
        "<strong>MAP</strong> — the agent inventory and the dimension matrix "
        "establish context: what agents exist and where their exposure sits. "
        "<strong>MEASURE</strong> — the findings and their file:line evidence, "
        "with OWASP and EU AI Act anchors, quantify and characterize that "
        "exposure. <strong>MANAGE</strong> — <code>stoa diff</code> gating and "
        "the assurance export carry that evidence into change control and "
        "external review. This is an alignment aid, not a certification claim; "
        "GOVERN is an organizational function outside a static scan's view."
        "</div></section>"
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


def _contradictions_section(result: ScanResult, rcfg=None) -> str:
    """Declared-vs-scanned mismatches (DECL001-007) — the headline for an
    assurance reviewer. Omitted entirely when no stoa-declared.toml was used
    at all; shown with a positive "none found" message when it was used but
    produced zero contradictions."""
    decl_findings = [
        f for f in result.findings if f.rule_id.startswith("DECL") and not f.suppressed
    ]
    used_declarations = any(a.declared is not None for a in result.agents) or bool(
        [f for f in result.findings if f.rule_id.startswith("DECL")]
    )
    if not used_declarations:
        return ""

    parts = [
        '<section id="contradictions"><h2>Contradictions</h2>',
        '<p class="cap">where declarations don\'t match the code — what a '
        "self-attested questionnaire can't catch</p>",
    ]
    if not decl_findings:
        parts.append('<p class="empty">No contradictions found.</p>')
    else:
        parts.append('<div class="contradiction-list">')
        # Group by rule class; classes with more members than the threshold
        # render as one expandable row instead of N repeated blocks (Task 2).
        threshold = rcfg.contradiction_group_threshold if rcfg else 3
        by_rule: dict[str, list] = {}
        for f in decl_findings:
            by_rule.setdefault(f.rule_id, []).append(f)
        # Order groups by worst severity then size, then rule id.
        def _grank(items):
            return (-max(SEVERITY_ORDER[f.severity] for f in items), -len(items))
        for rule_id in sorted(by_rule, key=lambda r: (_grank(by_rule[r]), r)):
            group = sorted(by_rule[rule_id],
                           key=lambda f: (-SEVERITY_ORDER[f.severity], f.path, f.line))
            if len(group) > threshold:
                parts.append(_contradiction_group(rule_id, group))
            else:
                for finding in group:
                    parts.append(_contradiction_card(finding))
        parts.append("</div>")
    parts.append("</section>")
    return "".join(parts)


def _contradiction_group(rule_id: str, group: list) -> str:
    """One collapsed row standing in for N identical-rule contradictions."""
    head = group[0]
    n = len(group)
    lines = "".join(
        f'<div class="chip-vs chip-observed"><code>{html_text(f.path)}:{f.line}</code></div>'
        for f in group
    )
    return (
        '<div class="contradiction-card contra-group"><details>'
        f'<summary><span class="rule">{html_text(rule_id)}</span> '
        f'{_severity_badge(head.severity)} — {n} agents: {html_text(head.title)}</summary>'
        f'<div class="contra-chips">{lines}</div></details></div>'
    )


def _contradiction_card(finding: Finding) -> str:
    declared_link = ""
    if finding.declared_ref:
        declared_link = (
            '<p class="kv"><span class="k">declared:</span> '
            f'<code>{html_text(finding.declared_ref["path"])}</code> '
            f'<code>{html_text(finding.declared_ref["key"])}</code></p>'
        )
    return (
        '<div class="contradiction-card">'
        f'<div class="top"><span class="rule">{html_text(finding.rule_id)}</span>'
        f"{_severity_badge(finding.severity)}</div>"
        f"<p>{html_text(finding.title)}</p>"
        f'<p class="kv"><span class="k">code:</span> '
        f"<code>{html_text(finding.path)}:{finding.line}</code></p>"
        f"{declared_link}"
        + (f'<p class="meta">{html_text(finding.message)}</p>' if finding.message else "")
        + "</div>"
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
        f'<span class="name">{html_text(agent.label)}</span>'
        f'<span class="tier">{html_text(tier_label)}</span>'
        "</div>"
        f'<p class="meta"><code>{html_text(agent.path)}</code> · '
        f"{_confidence_label(agent.confidence)} confidence</p>"
        f"{_autonomy_badge(agent)}"
        f'<div class="meter" role="img" aria-label="Static exposure score {score}">'
        f'<span style="width: {meter_pct}%"></span></div>'
        f'<div class="chips">{chips}</div>'
        f'<ul class="pill-list">{cap_pills}{more}</ul>'
        f"{detail}"
        "</div>"
    )


_AUTONOMY_LABELS = {
    "recommend_only": ("Recommend-only", "autonomy-info"),
    "human_approved": ("Human-approved", "autonomy-ok"),
    "bounded_autonomous": ("Bounded-autonomous", "autonomy-warn"),
    "unrestricted_autonomous": ("Unrestricted-autonomous", "autonomy-crit"),
    "indeterminate": ("Autonomy indeterminate", "autonomy-unknown"),
}


def _autonomy_badge(agent: AgentCandidate) -> str:
    if agent.autonomy_level is None:
        return ""
    level = agent.autonomy_level.get("level")
    label, css_class = _AUTONOMY_LABELS.get(level, (level, "autonomy-unknown"))
    title = ""
    if level == "indeterminate" and agent.autonomy_level.get("reason"):
        title = f' title="{html_text(agent.autonomy_level["reason"])}"'
    return f'<p class="autonomy-badge {css_class}"{title}>{html_text(label)}</p>'


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

    if agent.tools:
        parts.append("<h4>Tools (bound by this agent)</h4><table class=\"tools\"><thead><tr>"
                     "<th>tool</th><th>reach</th><th>defined at</th><th>retry</th><th>idempotency key</th></tr></thead><tbody>")
        for t in agent.tools:
            reach = ", ".join(t.get("capabilities") or []) or ("money action" if t.get("money_action") else "—")
            flags = []
            if t.get("money_action"):
                flags.append("money")
            if t.get("high_impact"):
                flags.append("high-impact")
            if not t.get("resolved", True):
                flags.append("name only")
            label = html_text(t["name"]) + (f' <span class="meta">({html_text(", ".join(flags))})</span>' if flags else "")
            parts.append(
                f"<tr><td><code>{label}</code></td><td>{html_text(reach)}</td>"
                f"<td><code>{html_text(t['path'])}:{html_text(t['line'])}</code></td>"
                f"<td>{html_text(t['retry']) if t.get('retry') else '—'}</td>"
                f"<td>{'yes' if t.get('idempotency_key') else ('no' if t.get('resolved', True) else 'unresolved')}</td></tr>"
            )
        parts.append("</tbody></table>")

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


def write_html(
    result: ScanResult, config: StoaConfig, output_path: Path,
    document: dict | None = None,
) -> None:
    """Render and atomically write the HTML report."""
    _atomic_write(output_path, render_html(result, config, document))
