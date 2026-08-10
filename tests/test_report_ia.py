"""Verdict-first report IA rebuild: agent-name disambiguation (Task 1),
section order + scoreboard/verdict/fix-first (Task 2), dedup (Task 3), and the
report presentation config (Task 4)."""

from __future__ import annotations

import re
from pathlib import Path

from stoa.config import StoaConfig, load_config
from stoa.report_config import (
    ReportConfigError,
    default_report_config,
    load_report_config,
)
from stoa.report_html import render_html
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
BANNED = ("compliant", "protected", "covered", "mitigated", "safe", "secure")


def _scan(example: str = "examples/meridian-ops"):
    root = REPO_ROOT / example
    config = load_config(root)
    return run_scan(ScanOptions(root=root, no_git=True), config), config


def _render(example: str = "examples/meridian-ops") -> str:
    result, config = _scan(example)
    return render_html(result, config)


# --- Task 1: agent-name disambiguation ---------------------------------------


def test_no_duplicate_agent_labels():
    result, _ = _scan()
    labels = [a.label for a in result.agents]
    assert len(labels) == len(set(labels)), f"duplicate labels: {labels}"


def test_generic_and_colliding_names_qualified_by_file_stem():
    result, _ = _scan()
    by_label = {a.label: a for a in result.agents}
    # three bare framework tokens collided in meridian-ops -> file-qualified
    assert "payments·agent" in by_label
    assert "payments·executor" in by_label
    assert "devops·agent" in by_label
    # raw name and symbol are preserved (diff stability)
    assert by_label["payments·agent"].name == "agent"
    # a specific, unique name is left untouched
    assert "support_bot" in by_label


def test_display_name_in_registry_but_raw_name_preserved():
    result, config = _scan()
    doc = build_document(result, config)
    agent = next(a for a in doc["agents"] if a["display_name"] == "payments·agent")
    assert agent["name"] == "agent"        # raw, for diff stability
    assert agent["symbol"] == "agent"


def test_disambiguation_deterministic():
    a, _ = _scan()
    b, _ = _scan()
    assert [x.label for x in a.agents] == [x.label for x in b.agents]


def test_labels_appear_in_report_not_bare_agent():
    html = _render()
    assert "payments·agent" in html
    assert "devops·agent" in html


# --- Task 2: verdict-first section order -------------------------------------


def test_section_order_is_verdict_first():
    html = _render()
    order = [
        html.index('class="verdict"'),
        html.index("<h2>Scoreboard</h2>"),
        html.index('id="fix-first"'),
        html.index("<h2>Contradictions</h2>"),
        html.index("<h2>Agents</h2>"),
        html.index("<h2>OWASP LLM Top 10 (2025) coverage</h2>"),
        html.index('class="appendix"'),
    ]
    assert order == sorted(order), "sections are out of verdict-first order"


def test_no_standalone_at_a_glance_or_severity_sections():
    html = _render()
    assert "<h2>At a glance</h2>" not in html
    assert "<h2>Findings by severity</h2>" not in html


def test_all_findings_demoted_into_appendix():
    html = _render()
    appendix = html.split('class="appendix"', 1)[1]
    assert "<h2>All findings</h2>" in appendix
    assert "Architecture graph" in appendix  # graph demoted too


def test_scoreboard_tallies_reconcile():
    result, _ = _scan()
    html = render_html(result, load_config(REPO_ROOT / "examples/meridian-ops"))
    sc = result.severity_counts()
    active_total = sum(sc.values())
    ribbon = re.search(r'<div class="ribbon">.*?</div>', html, re.DOTALL).group(0)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", ribbon)).strip()
    # the headline total equals the sum of the per-severity counts
    assert f"{active_total} active finding" in text
    for sev in ("critical", "high", "medium", "low", "info"):
        if sc.get(sev, 0):
            assert f"{sc[sev]} {sev}" in text


def test_tier_bar_covers_every_agent():
    result, _ = _scan()
    html = render_html(result, load_config(REPO_ROOT / "examples/meridian-ops"))
    bar = re.search(r'<div class="tier-bar">(.*?)<div class="tier-legend">',
                    html, re.DOTALL).group(1)
    widths = [float(w) for w in re.findall(r"width:([\d.]+)%", bar)]
    assert abs(sum(widths) - 100.0) < 0.5  # the stacked bar spans all agents


# --- Task 2/3: fix-first + dedup ---------------------------------------------


def test_fix_first_present_and_capped():
    html = _render()
    section = re.search(r'<section id="fix-first">.*?</section>', html, re.DOTALL).group(0)
    items = section.count('class="fix-item')
    assert 1 <= items <= 5  # fix_first_max default
    # each item carries a rule · file:line · framework reference line
    assert re.search(r'refline">.*?[A-Z]{2,5}\d{3}.*?:\d+', section, re.DOTALL)


def test_fix_first_contradiction_points_to_contradictions_no_double_detail():
    html = _render()
    section = re.search(r'<section id="fix-first">.*?</section>', html, re.DOTALL).group(0)
    # a DECL/RT item renders only a pointer — no Fix prose, no snippet
    items = re.findall(r'<div class="fix-item.*?</div>\s*</div>', section, re.DOTALL)
    for item in items:
        if "DECL" in item or "RT0" in item:
            assert "full detail in" in item
            assert "<b>Fix:</b>" not in item
            assert "<pre>" not in item


def test_contradictions_grouped_not_repeated():
    html = _render()
    section = re.search(r'<section id="contradictions">.*?</section>', html, re.DOTALL).group(0)
    # meridian has many DECL006 (no-declaration) findings -> one grouped row
    if section.count("DECL006") > 0:
        assert "contra-group" in section
        # the group summary states an agent count rather than repeating blocks
        assert re.search(r"\d+ agents:", section)


# --- Task 4: report presentation config --------------------------------------


def test_default_report_config_values():
    rc = default_report_config()
    assert rc.fix_first_max == 5
    assert rc.fix_first_min_severity == "high"
    assert rc.agent_collapse_below_tier == "moderate"
    assert rc.contradiction_group_threshold == 3
    assert rc.dimension_proxy_merge is True


def test_report_config_override(tmp_path):
    override = tmp_path / "report.toml"
    override.write_text(
        '[report]\nid = "c"\nversion = "2.0"\n'
        '[collapse]\nfix_first_max = 2\nagent_collapse_below_tier = "elevated"\n'
    )
    rc = load_report_config(override)
    assert rc.fix_first_max == 2
    assert rc.agent_collapse_below_tier == "elevated"


def test_report_config_dot_stoa_autodetect(tmp_path):
    (tmp_path / ".stoa").mkdir()
    (tmp_path / ".stoa" / "report.toml").write_text(
        '[report]\nid = "c"\nversion = "1.0"\n[collapse]\nfix_first_max = 1\n'
    )
    config = load_config(tmp_path)
    assert config.report_config_path == (tmp_path / ".stoa" / "report.toml").resolve()


def test_report_config_bad_tier_rejected(tmp_path):
    bad = tmp_path / "r.toml"
    bad.write_text('[report]\nid="x"\nversion="1"\n[collapse]\nagent_collapse_below_tier="bogus"\n')
    import pytest
    with pytest.raises(ReportConfigError, match="agent_collapse_below_tier"):
        load_report_config(bad)


def test_fix_first_max_respected_by_report(tmp_path):
    # a strict override caps the fix list at 2 items
    (tmp_path / ".stoa").mkdir()
    (tmp_path / ".stoa" / "report.toml").write_text(
        '[report]\nid="c"\nversion="1.0"\n[collapse]\nfix_first_max = 2\n'
    )
    root = REPO_ROOT / "examples/meridian-ops"
    config = load_config(root)
    config.report_config_path = (tmp_path / ".stoa" / "report.toml").resolve()
    result = run_scan(ScanOptions(root=root, no_git=True), config)
    html = render_html(result, config)
    section = re.search(r'<section id="fix-first">.*?</section>', html, re.DOTALL).group(0)
    assert section.count('class="fix-item') == 2


# --- determinism + offline ----------------------------------------------------


def test_report_byte_identical_across_runs():
    assert _render("examples/sparkwing") == _render("examples/sparkwing")


def test_verdict_and_fixfirst_offline():
    html = _render()
    for marker in (r'<div class="verdict">.*?</div></section>',
                   r'<section id="fix-first">.*?</section>'):
        span = re.search(marker, html, re.DOTALL).group(0)
        assert "http://" not in span and "https://" not in span
