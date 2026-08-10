"""Report page-budget acceptance tests (≤5 printed pages) + collapse-not-omit.

The browser-free checks (every finding survives, no duplicate renders) always
run. The print-height check needs a headless Chrome and is skipped when one
isn't available, so CI without a browser still passes the rest.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from stoa.config import load_config
from stoa.report_html import render_html
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples/meridian-ops"


def _render_and_doc():
    config = load_config(EXAMPLE)
    result = run_scan(ScanOptions(root=EXAMPLE, no_git=True), config)
    return render_html(result, config), build_document(result, config)


# --- collapse, never omit -----------------------------------------------------


def test_every_finding_id_survives_in_the_html():
    html, doc = _render_and_doc()
    findings = (
        [f for a in doc["agents"] for f in a["findings"]]
        + doc["repository_findings"]
    )
    assert findings
    missing = [f["rule_id"] + "@" + f["path"] + ":" + str(f["line"])
               for f in findings
               if f"{f['rule_id']}" not in html
               or f"{f['path']}:{f['line']}" not in html]
    assert not missing, f"findings dropped from the report: {missing[:5]}"


def test_dimension_data_renders_once_not_four_times():
    html, _ = _render_and_doc()
    # the deleted duplicates must be gone
    assert "By agent" not in html
    assert "Dimensions × frameworks" not in html
    assert 'class="dim-agent-row"' not in html
    assert "— dimension detail" not in html
    # exactly one dimensions section survives
    assert html.count("<h2>Risk dimensions</h2>") == 1


def test_no_section_leadin_paragraphs_remain():
    # the ~7 explanatory lead-in <p class="note"> paragraphs are gone from body
    html, _ = _render_and_doc()
    body = html.split('<details class="appendix"', 1)[0]
    assert 'class="note"' not in body  # replaced by short captions


# --- one canonical gloss, capped ---------------------------------------------


def test_each_dimension_gloss_is_single_and_capped():
    html, _ = _render_and_doc()
    section = re.search(r"<h2>Risk dimensions</h2>.*?</section>", html, re.DOTALL).group(0)
    glosses = re.findall(r'<p class="dim-gloss">(.*?)</p>', section)
    assert glosses
    for g in glosses:
        assert len(g) <= 140, f"gloss over 140 chars: {g!r}"
        # a single sentence/definition, not a concatenation of many
        assert g.count(". ") <= 1


# --- fix-first 4-line shape ---------------------------------------------------


def test_fix_first_impact_never_repeats_title():
    html, _ = _render_and_doc()
    section = re.search(r'<section id="fix-first">.*?</section>', html, re.DOTALL).group(0)
    for chunk in section.split('<div class="fix-item')[1:]:
        ft = re.search(r'class="ft">(.*?)</span>', chunk)
        impact = re.search(r'class="impact">(.*?)</p>', chunk, re.DOTALL)
        if ft and impact:
            title = ft.group(1).strip().lower()
            imp = re.sub(r"<[^>]+>", "", impact.group(1)).strip().lower()
            assert imp != title, f"impact repeats the title: {title!r}"


# --- print budget (needs headless Chrome) ------------------------------------


def _find_chrome():
    for c in ("google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(c)
        if p:
            return p
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if Path(mac).exists() else None


def test_print_height_under_five_pages(tmp_path):
    chrome = _find_chrome()
    if not chrome:
        pytest.skip("no headless Chrome available to measure print height")
    html, _ = _render_and_doc()
    src = tmp_path / "report.html"
    src.write_text(html, encoding="utf-8")
    pdf = tmp_path / "report.pdf"
    subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
         f"--print-to-pdf={pdf}", f"file://{src}"],
        check=True, capture_output=True, timeout=120,
    )
    data = pdf.read_bytes()
    pages = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    assert 1 <= pages <= 5, f"report is {pages} printed pages (budget: 5)"
