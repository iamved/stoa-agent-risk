"""Feature 3: the underwriting-evidence demo export.

The pre-filled Munich RE aiSure questionnaire — all five sections, scan-
sourced technical fields, swappable demo identity, offline + CSP-clean,
print-isolated, and clearly a demo. Plus the report button wiring (embedded
blob + hash-pinned open script) and the CLI export.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from stoa.cli import main
from stoa.config import load_config
from stoa.report_html import UNDERWRITING_SCRIPT_HASH, render_html
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan
from stoa.underwriting import DEMO_IDENTITY, render_underwriting_html

REPO_ROOT = Path(__file__).resolve().parents[1]


def _document(example: str = "examples/meridian-ops") -> dict:
    root = REPO_ROOT / example
    config = load_config(root)
    return build_document(run_scan(ScanOptions(root=root, no_git=True), config), config)


# --- structure & prefill ------------------------------------------------------


def test_all_five_sections_present():
    html = render_underwriting_html(_document())
    for section in ("1. General Information", "2. Model Development",
                    "3. Customer Onboarding", "4. Data Submission Requirements",
                    "5. Declaration"):
        assert section in html


def test_identity_prefilled_and_swappable():
    default = render_underwriting_html(_document())
    assert DEMO_IDENTITY["company"] in default
    custom = render_underwriting_html(_document(), identity={"company": "Acme Partner Inc"})
    assert "Acme Partner Inc" in custom
    assert DEMO_IDENTITY["company"] not in custom


def test_scan_sourced_fields_reflect_the_registry():
    doc = _document()
    html = render_underwriting_html(doc)
    n_agents = len(doc["agents"])
    assert f"{n_agents} agent candidate(s)" in html
    # Meridian fires AI002 -> robustness testing evidenced
    assert "AI001/AI002" in html
    # performance sample table present
    assert "Ground-truth accuracy" in html and "97.4%" in html


def test_insurance_requirements_sized_from_exposure():
    doc = _document()
    html = render_underwriting_html(doc)
    # Meridian has multiple elevated dimensions -> the higher demo limit
    assert "US$ 25,000,000" in html
    assert "Aggregate Deductible" in html
    assert "Coverage trigger" in html


def test_clearly_a_demo():
    html = render_underwriting_html(_document())
    normalized = " ".join(html.split())  # collapse source-wrapping whitespace
    assert "DEMO ARTIFACT" in normalized
    assert "Fictional company" in normalized
    assert "Not a real insurance submission" in normalized


# --- offline / CSP / print ----------------------------------------------------


def test_offline_no_external_resources():
    html = render_underwriting_html(_document())
    assert "http://" not in html and "https://" not in html
    assert "@import" not in html
    # exactly one inline script (the print helper), CSP-declared
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) == 1
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    assert f"sha256-{digest}" in html  # CSP hash matches the emitted script
    assert "'unsafe-inline'" not in html.split("script-src")[1].split(";")[0]


def test_print_stylesheet_isolates_the_form():
    html = render_underwriting_html(_document())
    assert "@media print" in html
    # the Download-PDF button is hidden when printing
    print_block = html.split("@media print", 1)[1]
    assert ".uw-print-btn { display: none" in print_block


# --- report button wiring -----------------------------------------------------


def test_report_embeds_button_blob_and_hashpinned_script():
    root = REPO_ROOT / "examples/meridian-ops"
    config = load_config(root)
    result = run_scan(ScanOptions(root=root, no_git=True), config)
    html = render_html(result, config)

    assert 'id="stoa-underwriting-btn"' in html
    assert "Generate underwriting evidence" in html
    # embedded, non-executing JSON blob
    m = re.search(r'<script type="application/json" id="stoa-uw-data">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "underwriting data blob not embedded"
    # </ is escaped so the inner form's <script> can't close the outer tag early
    assert "</script>" not in m.group(1) or "<\\/script>" in m.group(1)
    embedded = json.loads(m.group(1))
    assert "aiSure" in embedded and DEMO_IDENTITY["company"] in embedded
    # the open-in-new-tab script is CSP hash-pinned
    assert f"sha256-{UNDERWRITING_SCRIPT_HASH}" in html


def test_report_still_has_download_button_and_both_hashes():
    root = REPO_ROOT / "examples/sparkwing"
    config = load_config(root)
    result = run_scan(ScanOptions(root=root, no_git=True), config)
    html = render_html(result, config)
    assert 'id="stoa-download-report"' in html
    assert 'id="stoa-underwriting-btn"' in html
    # both action scripts declared in the CSP script-src
    script_src = html.split("script-src", 1)[1].split(";")[0]
    assert f"sha256-{UNDERWRITING_SCRIPT_HASH}" in script_src


# --- CLI ----------------------------------------------------------------------


def test_cli_export_underwriting_demo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    doc = _document("examples/sparkwing")
    (tmp_path / "reg.json").write_text(json.dumps(doc))
    code = main(["export", "reg.json", "--underwriting-demo", "--out", "uw.html"])
    assert code == 0
    out = (tmp_path / "uw.html").read_text()
    assert "aiSure" in out and "DEMO ARTIFACT" in out
    assert "wrote" in capsys.readouterr().out


def test_cli_export_requires_a_kind(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reg.json").write_text(json.dumps(_document("examples/sparkwing")))
    # neither --assurance nor --underwriting-demo -> argparse usage error (exit 2)
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["export", "reg.json"])
    assert exc.value.code == 2


# --- determinism --------------------------------------------------------------


def test_underwriting_deterministic():
    doc = _document()
    assert render_underwriting_html(doc) == render_underwriting_html(doc)
