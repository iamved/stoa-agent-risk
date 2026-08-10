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
    assert 'class="verdict"' in html                        # verdict-first hero
    assert "<h2>Standards</h2>" in html                      # OWASP chip line
    assert "<h2>Risk dimensions</h2>" in html                # merged dim section
    assert "<h2>NIST AI RMF alignment</h2>" in html          # in the appendix


def test_verdict_names_top_finding_with_ruleref():
    html = _render("examples/meridian-ops")
    m = re.search(r'<div class="verdict">.*?</div></section>', html, re.DOTALL)
    assert m, "verdict section not found"
    verdict = m.group(0)
    assert "agent candidate" in verdict
    assert "Top risk:" in verdict
    # rule · file:line reference present
    assert re.search(r'[A-Z]{2,5}\d{3} · [^<]+:\d+', verdict)


def test_owasp_strip_shows_all_ten_and_keeps_gaps_visible():
    section = _section(_render("examples/sparkwing"), "Standards")
    for n in range(1, 11):
        assert f"LLM{n:02d}" in section
    # classes with no Stoa detector must remain visible as not-assessed
    assert "not-assessed" in section
    assert "owasp-notassessed" in section


def test_owasp_strip_states_are_honest_for_a_known_scan():
    # Sparkwing fires AI001 (LLM01) -> assessed; LLM04/07/08 have no detector.
    section = _section(_render("examples/sparkwing"), "Standards")
    # LLM01 chip should be assessed
    llm01 = re.search(r'LLM01 <span class="st">([a-z-]+)', section)
    assert llm01 and llm01.group(1) == "assessed"
    # LLM04 (Data and Model Poisoning) has no rule -> not-assessed
    llm04 = re.search(r'LLM04 <span class="st">([a-z-]+)', section)
    assert llm04 and llm04.group(1) == "not-assessed"


def test_dimension_section_carries_gloss_first_then_tags_and_evidence():
    section = _section(_render("examples/meridian-ops"), "Risk dimensions")
    assert "dim-gloss" in section       # canonical plain-English gloss
    assert "xwalk-owasp" in section     # OWASP tags (after the gloss)
    assert "xwalk-eu" in section        # EU AI Act tags
    assert "evchip" in section          # RULE · file:line evidence chips
    assert re.search(r'evchip">[A-Z]{2,5}\d{3} · [^<]+:\d+', section)
    # gloss appears before the framework tags in each card (meaning, then provenance)
    card = re.search(r'<div class="dim-card [^>]*>.*?</div>\s*</div>', section, re.DOTALL)
    assert card and card.group(0).index("dim-gloss") < card.group(0).index("xwalk-owasp")


def test_control_credit_chips_render_for_well_controlled_agent():
    # Meridian's compliance agent has observed controls -> credit chips exist.
    section = _section(_render("examples/meridian-ops"), "Risk dimensions")
    assert "evchip credit" in section
    assert "observed</span>" in section


def test_nist_rollup_is_report_level_map_measure_manage():
    section = _section(_render("examples/meridian-ops"), "NIST AI RMF alignment")
    assert "MAP" in section and "MEASURE" in section and "MANAGE" in section
    assert "not a certification" in section


def test_new_sections_obey_says_never_says():
    """Vocabulary lint scoped to Stoa's generated framing (the crosswalk
    sections plus the verdict card). Echoed rule messages/remediations and
    vendored library text are pre-existing content, out of scope here."""
    html = _render("examples/meridian-ops")
    spans = [re.search(r'<div class="verdict">.*?</div></section>', html, re.DOTALL).group(0)]
    for heading in ("Standards", "Risk dimensions", "NIST AI RMF alignment"):
        spans.append(_section(html, heading))
    for span in spans:
        text = re.sub(r"<[^>]+>", " ", span).lower()
        words = set(re.findall(r"[a-z]+", text))
        for banned in BANNED:
            assert banned not in words, f"span uses banned word {banned!r}"


def test_report_renders_offline_no_external_refs_in_new_sections():
    html = _render("examples/meridian-ops")
    for heading in ("Standards", "Risk dimensions", "NIST AI RMF alignment"):
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
    # crosswalk-gated sections gracefully skipped
    assert "<h2>OWASP LLM Top 10 (2025) coverage</h2>" not in html
    assert "<h2>Dimensions × frameworks</h2>" not in html
    # verdict-first spine still renders
    assert 'class="verdict"' in html
    assert "<h2>Agents</h2>" in html


def test_report_deterministic_with_crosswalk_sections():
    a = _render("examples/sparkwing")
    b = _render("examples/sparkwing")
    assert a == b
