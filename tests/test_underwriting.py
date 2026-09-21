"""Feature 3: the underwriting-evidence export.

The pre-filled AI Model Risk Assessment (modeled on the aiSure template) —
all five sections, scan-sourced technical fields, swappable identity, real
applicant-supplied performance metrics (or a labeled sample), offline +
CSP-clean, print-isolated. Plus the report button wiring and CLI export.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

import pytest

from stoa.cli import main
from stoa.config import load_config
from stoa.report_html import UNDERWRITING_SCRIPT_HASH, render_html
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan
from stoa.underwriting import (
    DEMO_IDENTITY,
    UnderwritingConfigError,
    load_underwriting_config,
    render_underwriting_html,
)

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


def test_identity_defaults_to_the_scanned_repository_never_a_fictional_applicant():
    default = render_underwriting_html(_document())
    # The applicant signs this form: an unfilled identity is derived from their
    # own repository and marked for confirmation, never an invented company.
    assert "Meridian Ops" in default
    assert "To be confirmed" in default
    for invented in DEMO_IDENTITY.values():
        if invented != "USD":
            assert invented not in default
    custom = render_underwriting_html(_document(), identity={"company": "Acme Partner Inc"})
    assert "Acme Partner Inc" in custom


def test_scan_sourced_fields_reflect_the_registry():
    doc = _document()
    html = render_underwriting_html(doc)
    n_agents = len(doc["agents"])
    assert f"{n_agents} agent candidate(s)" in html
    # Meridian fires AI002 -> robustness testing evidenced
    assert "AI001/AI002" in html
    # with no applicant metrics, the labeled sample table is shown
    assert "Ground-truth accuracy" in html and "97.4%" in html
    assert "sample values shown" in html  # honest about the placeholder


# --- applicant-supplied performance metrics ----------------------------------


def test_applicant_metrics_replace_the_sample_and_relabel():
    doc = _document()
    metrics = [
        {"metric": "Ground-truth accuracy", "value": "98.1%", "cadence": "Monthly"},
        {"metric": "False-positive rate", "value": "1.2%", "cadence": "Weekly"},
    ]
    html = render_underwriting_html(doc, metrics=metrics)
    assert "98.1%" in html and "1.2%" in html          # applicant's real figures
    assert "97.4%" not in html                          # sample no longer shown
    assert "provided by the applicant" in html          # relabeled
    assert "sample values shown" not in html


def test_config_loader_parses_identity_and_metrics(tmp_path):
    cfg = tmp_path / "uw.toml"
    cfg.write_text(
        '[identity]\ncompany = "Acme Payments Inc"\nunknown_key = "ignored"\n'
        '[[performance]]\nmetric = "Accuracy"\nvalue = "99%"\ncadence = "Daily"\n'
        '[[performance]]\nmetric = "Latency (p95)"\nvalue = "180 ms"\n'
    )
    identity, metrics = load_underwriting_config(cfg)
    assert identity == {"company": "Acme Payments Inc"}  # unknown key dropped
    assert metrics == [
        {"metric": "Accuracy", "value": "99%", "cadence": "Daily"},
        {"metric": "Latency (p95)", "value": "180 ms", "cadence": "—"},  # cadence optional
    ]


def test_config_loader_rejects_incomplete_metric(tmp_path):
    cfg = tmp_path / "bad.toml"
    cfg.write_text('[[performance]]\nmetric = "Accuracy"\n')  # no value
    with pytest.raises(UnderwritingConfigError, match="metric.*value"):
        load_underwriting_config(cfg)


def test_config_loader_missing_file(tmp_path):
    with pytest.raises(UnderwritingConfigError, match="not found"):
        load_underwriting_config(tmp_path / "nope.toml")


def test_shipped_example_config_is_valid():
    identity, metrics = load_underwriting_config(
        REPO_ROOT / "examples" / "underwriting-config.example.toml")
    assert identity["company"] == "Acme Payments Inc"
    assert metrics and all(r["metric"] and r["value"] for r in metrics)


def test_insurance_requirements_sized_from_exposure():
    doc = _document()
    html = render_underwriting_html(doc)
    # Meridian has multiple elevated dimensions -> the higher demo limit
    assert "US$ 25,000,000" in html
    assert "Aggregate Deductible" in html
    assert "Coverage trigger" in html


def test_form_hygiene_template_attribution_and_confirm_note():
    """No 'DEMO' framing, but the form stays honest: it attributes the aiSure
    template (not impersonating Munich RE) and flags that identity and figures
    are applicant-confirmed (sample numbers aren't presented as audited)."""
    html = render_underwriting_html(_document())
    normalized = " ".join(html.split())
    assert "DEMO" not in normalized and "Fictional" not in normalized
    assert "modeled on the aiSure" in normalized          # template attribution
    assert "confirmed by the applicant" in normalized      # applicant-to-confirm
    assert "applicant to supply" in normalized             # on the perf table


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
    assert "aiSure" in embedded and DEMO_IDENTITY["company"] not in embedded
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


def test_cli_export_underwriting_sample(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    doc = _document("examples/sparkwing")
    (tmp_path / "reg.json").write_text(json.dumps(doc))
    # --underwriting-demo is kept as an alias for --underwriting
    code = main(["export", "reg.json", "--underwriting-demo", "--out", "uw.html"])
    assert code == 0
    out = (tmp_path / "uw.html").read_text()
    assert "aiSure" in out and "AI Model Risk Assessment" in out
    assert "97.4%" in out and "sample values shown" in out   # labeled sample
    assert "sample figures" in capsys.readouterr().out


def test_cli_export_underwriting_with_applicant_config(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reg.json").write_text(json.dumps(_document("examples/sparkwing")))
    (tmp_path / "uw.toml").write_text(
        '[identity]\ncompany = "Acme Payments Inc"\n'
        '[[performance]]\nmetric = "Ground-truth accuracy"\nvalue = "98.1%"\n'
    )
    code = main(["export", "reg.json", "--underwriting",
                 "--underwriting-config", "uw.toml", "--out", "uw.html"])
    assert code == 0
    out = (tmp_path / "uw.html").read_text()
    assert "Acme Payments Inc" in out and "98.1%" in out
    assert "provided by the applicant" in out
    assert "97.4%" not in out                                # sample gone
    assert "applicant config" in capsys.readouterr().out


def test_cli_export_underwriting_bad_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reg.json").write_text(json.dumps(_document("examples/sparkwing")))
    (tmp_path / "uw.toml").write_text('[[performance]]\nmetric = "x"\n')  # no value
    code = main(["export", "reg.json", "--underwriting",
                 "--underwriting-config", "uw.toml", "--out", "uw.html"])
    assert code == 2  # usage error, clear message


def test_cli_export_requires_a_kind(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reg.json").write_text(json.dumps(_document("examples/sparkwing")))
    # neither --assurance nor --underwriting -> argparse usage error (exit 2)
    with pytest.raises(SystemExit) as exc:
        main(["export", "reg.json"])
    assert exc.value.code == 2


# --- determinism --------------------------------------------------------------


def test_underwriting_deterministic():
    doc = _document()
    assert render_underwriting_html(doc) == render_underwriting_html(doc)


# --- answers are claimed only on evidence -------------------------------------


def _field(assessment: dict, key: str) -> dict:
    return next(f for section in assessment["sections"] for f in section["fields"] if f["key"] == key)


def test_drift_is_claimed_only_when_reach_is_compared_between_scans():
    from stoa.underwriting import build_assessment

    lone = _field(build_assessment(_document()), "drift")
    assert (lone["value"], lone["source"]) == ("To be confirmed", "sample")
    assert "--diff-against" in lone["note"]
    tracked = _field(build_assessment(_document(), drift_tracked=True), "drift")
    assert (tracked["value"], tracked["source"]) == ("Yes", "scan")


def test_monitoring_is_not_claimed_for_a_scan_with_no_agents():
    from stoa.underwriting import build_assessment, derive_from_registry

    empty = {"repository": {"name": "acme-billing"}, "agents": [], "repository_findings": []}
    assert derive_from_registry(empty)["monitoring"] is None
    field = _field(build_assessment(empty), "monitoring")
    assert (field["value"], field["source"]) == ("To be confirmed", "sample")
    # With agents and no CTRL004 gap it is still answered from the scan.
    assert _field(build_assessment(_document()), "monitoring")["source"] == "scan"


def test_form_never_claims_the_scan_runs_in_ci():
    from stoa.underwriting import build_assessment

    assert "in CI" not in _field(build_assessment(_document()), "code_quality")["note"]
    assert "in CI" not in render_underwriting_html(_document())


def test_indicative_trigger_carries_no_demo_wording():
    from stoa.underwriting import derive_from_registry

    assert "fraud" not in derive_from_registry(_document())["trigger"].lower()
