"""Determinism / parity suite (Part I invariant #2).

Byte-identical JSON and HTML across repeated runs on identical input, and
schema-1.1 backward compatibility: a scan producing no AI findings serializes
exactly as schema 1.0 did aside from the version string.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import EXAMPLE_REPO, fake_openai_key

from stoa.config import StoaConfig
from stoa.report_html import render_html
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan


def _scan(root, **kw):
    return run_scan(ScanOptions(root=Path(root), no_git=True, **kw))


def test_json_byte_identical_across_runs():
    a = json.dumps(build_document(_scan(EXAMPLE_REPO), StoaConfig()), indent=2)
    b = json.dumps(build_document(_scan(EXAMPLE_REPO), StoaConfig()), indent=2)
    assert a == b


def test_html_byte_identical_across_runs():
    a = render_html(_scan(EXAMPLE_REPO), StoaConfig())
    b = render_html(_scan(EXAMPLE_REPO), StoaConfig())
    assert a == b


def test_schema_version_is_1_1():
    doc = build_document(_scan(EXAMPLE_REPO), StoaConfig())
    assert doc["schema_version"] == "1.1"


def test_v01_findings_carry_no_new_fields(tmp_path: Path):
    """Additive promise: a plain v0.1 finding (SEC001) carries no 1.1 fields."""
    (tmp_path / "conf.py").write_text(
        f'API_TOKEN = "{fake_openai_key()}"\n', encoding="utf-8"
    )
    doc = build_document(_scan(tmp_path), StoaConfig())
    all_findings = [f for a in doc["agents"] for f in a["findings"]] + doc["repository_findings"]
    sec = [f for f in all_findings if f["rule_id"] == "SEC001"]
    assert sec, "expected a SEC001 finding"
    new_keys = {"id", "canonical_name", "owasp", "flow", "gate_eligible",
                "dimensions", "supersedes", "message"}
    for finding in sec:
        assert new_keys.isdisjoint(finding.keys()), finding


def test_experimental_ast_flag_off_by_default_no_degraded_key():
    doc = build_document(_scan(EXAMPLE_REPO), StoaConfig())
    assert "degraded_files" not in doc


def test_experimental_ast_records_degraded(tmp_path: Path):
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def f(:\n  x =\n", encoding="utf-8")
    result = _scan(tmp_path, experimental_ast=True)
    doc = build_document(result, StoaConfig())
    assert doc["degraded_files"] == ["broken.py"]


def test_experimental_ast_adds_no_new_findings(tmp_path: Path):
    src = f'api_key = "{fake_openai_key()}"\n'
    (tmp_path / "a.py").write_text(src, encoding="utf-8")
    without = _scan(tmp_path)
    with_ast = _scan(tmp_path, experimental_ast=True)
    assert len(without.findings) == len(with_ast.findings)
    assert {f.rule_id for f in with_ast.findings} == {f.rule_id for f in without.findings}
