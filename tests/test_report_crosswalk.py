"""Feature 2: the explainable HTML report sections.

Exec summary, OWASP coverage strip (gaps visible), framework-stamped
dimension table (tags + gloss + evidence chips), NIST roll-up — all rendering
offline, degrading cleanly when the crosswalk is absent, and obeying the
says/never-says vocabulary within the generated sections.
"""

from __future__ import annotations

import re
from pathlib import Path

from stoa.config import StoaConfig, load_config
from stoa.report_html import render_html
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
BANNED = ("compliant", "protected", "covered", "mitigated", "safe", "secure")


def _render(example: str) -> str:
    root = REPO_ROOT / example
    config = load_config(root)
    result = run_scan(ScanOptions(root=root, no_git=True), config)
    return render_html(result, config)


def _section(html: str, heading: str) -> str:
    """Extract one <section> by its <h2> text (the new crosswalk sections)."""
    m = re.search(
        rf'<section>(?:(?!</section>).)*?<h2>{re.escape(heading)}</h2>.*?</section>',
        html, re.DOTALL,
    )
    assert m, f"section {heading!r} not found"
    return m.group(0)


def test_report_has_all_four_new_sections():
    html = _render("examples/meridian-ops")
    assert "<h2>Executive summary</h2>" in html
    assert "<h2>OWASP LLM Top 10 (2025) coverage</h2>" in html
    assert "<h2>Dimensions × frameworks</h2>" in html
    assert "<h2>NIST AI RMF alignment</h2>" in html


def test_exec_summary_names_top_finding_with_ruleref():
    section = _section(_render("examples/meridian-ops"), "Executive summary")
    assert "agent candidate" in section
    assert "Most important:" in section
    # rule · file:line reference present
    assert re.search(r'[A-Z]{2,5}\d{3} · [^<]+:\d+', section)


def test_owasp_strip_shows_all_ten_and_keeps_gaps_visible():
    section = _section(_render("examples/sparkwing"),
                       "OWASP LLM Top 10 (2025) coverage")
    for n in range(1, 11):
        assert f"LLM{n:02d}" in section
    # classes with no Stoa detector must remain visible as not-assessed
    assert "not-assessed" in section
    assert "owasp-notassessed" in section


def test_owasp_strip_states_are_honest_for_a_known_scan():
    # Sparkwing fires AI001 (LLM01) -> assessed; LLM04/07/08 have no detector.
    section = _section(_render("examples/sparkwing"),
                       "OWASP LLM Top 10 (2025) coverage")
    # LLM01 cell should be assessed
    llm01 = re.search(r'LLM01.*?</div>\s*</div>', section, re.DOTALL)
    assert llm01 and "assessed" in llm01.group(0)
    # LLM04 (Data and Model Poisoning) has no rule -> not-assessed
    llm04 = re.search(r'LLM04.*?class="state">([a-z-]+)', section, re.DOTALL)
    assert llm04 and llm04.group(1) == "not-assessed"


def test_dimension_table_carries_tags_gloss_and_evidence_chips():
    section = _section(_render("examples/meridian-ops"), "Dimensions × frameworks")
    assert "xwalk-owasp" in section     # OWASP tags
    assert "xwalk-eu" in section        # EU AI Act tags
    assert "evchip" in section          # RULE · file:line evidence chips
    assert re.search(r'evchip">[A-Z]{2,5}\d{3} · [^<]+:\d+', section)


def test_control_credit_chips_render_for_well_controlled_agent():
    # Meridian's compliance agent has observed controls -> credit chips exist.
    section = _section(_render("examples/meridian-ops"), "Dimensions × frameworks")
    assert "evchip credit" in section
    assert "observed</span>" in section


def test_nist_rollup_is_report_level_map_measure_manage():
    section = _section(_render("examples/meridian-ops"), "NIST AI RMF alignment")
    assert "MAP" in section and "MEASURE" in section and "MANAGE" in section
    assert "not a certification" in section


def test_new_sections_obey_says_never_says():
    """Vocabulary lint scoped to the crosswalk-generated sections (the rest of
    the report contains vendored library text + pre-existing rule messages)."""
    html = _render("examples/meridian-ops")
    for heading in ("Executive summary", "OWASP LLM Top 10 (2025) coverage",
                    "Dimensions × frameworks", "NIST AI RMF alignment"):
        section = _section(html, heading)
        text = re.sub(r"<[^>]+>", " ", section).lower()
        words = set(re.findall(r"[a-z]+", text))
        for banned in BANNED:
            assert banned not in words, f"{heading!r} uses banned word {banned!r}"


def test_report_renders_offline_no_external_refs_in_new_sections():
    html = _render("examples/meridian-ops")
    for heading in ("Executive summary", "OWASP LLM Top 10 (2025) coverage",
                    "Dimensions × frameworks", "NIST AI RMF alignment"):
        section = _section(html, heading)
        assert "http://" not in section and "https://" not in section
        assert "<script" not in section.lower()


def test_report_degrades_when_crosswalk_missing(tmp_path, monkeypatch):
    """A broken override path -> new sections omitted, report still renders."""
    (tmp_path / "app.py").write_text(
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
    )
    config = StoaConfig(crosswalk_path=tmp_path / "nonexistent.toml")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True), config)
    html = render_html(result, config)
    assert "<h2>Executive summary</h2>" not in html   # gracefully skipped
    assert "<h2>Agent risk map</h2>" in html          # rest of report intact


def test_report_deterministic_with_crosswalk_sections():
    a = _render("examples/sparkwing")
    b = _render("examples/sparkwing")
    assert a == b
