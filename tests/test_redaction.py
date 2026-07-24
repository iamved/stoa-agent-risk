"""P0: a detected secret must never appear in any generated artifact."""

from __future__ import annotations

import io
import json
from pathlib import Path

from conftest import fake_anthropic_key, fake_openai_key

from stoa.config import StoaConfig
from stoa.github import emit_annotations, render_summary
from stoa.redaction import redact_secret
from stoa.report_html import render_html
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan


def _scan_repo_with_secret(tmp_path: Path, secret: str):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        f'import requests\napi_key = "{secret}"\n', encoding="utf-8"
    )
    return run_scan(ScanOptions(root=tmp_path, no_git=True))


def test_secret_absent_from_all_artifacts(tmp_path: Path):
    secret = fake_openai_key()
    result = _scan_repo_with_secret(tmp_path, secret)
    config = StoaConfig()

    json_text = json.dumps(build_document(result, config))
    assert secret not in json_text
    assert "[REDACTED:" in json_text

    html_text = render_html(result, config)
    assert secret not in html_text

    annotations = io.StringIO()
    emit_annotations(result, annotations)
    assert secret not in annotations.getvalue()
    assert "::error" in annotations.getvalue()

    summary = render_summary(result)
    assert secret not in summary


def test_secret_absent_from_terminal_snippets(tmp_path: Path):
    secret = fake_openai_key()
    result = _scan_repo_with_secret(tmp_path, secret)
    for finding in result.findings:
        assert secret not in finding.snippet
        assert secret not in (finding.suppression_reason or "")


def test_fingerprint_stable():
    secret = fake_openai_key()
    assert redact_secret(secret) == redact_secret(secret)


def test_distinct_secrets_distinct_fingerprints():
    first = redact_secret(fake_openai_key())
    second = redact_secret(fake_anthropic_key())
    assert first.split("[REDACTED:")[1] != second.split("[REDACTED:")[1]


def test_redacted_form_keeps_short_prefix():
    secret = fake_openai_key()
    redacted = redact_secret(secret)
    assert redacted.startswith(secret[:6])
    assert secret[8:] not in redacted


def test_sec002_password_value_is_redacted(tmp_path):
    """P0 regression: a hardcoded password must not leak into any artifact."""
    import json as _json
    from stoa.report_html import render_html
    from stoa.report_json import build_document
    from stoa.scanner import ScanOptions, run_scan

    pw = "Sup3rS3cretPr0d!2026x"
    (tmp_path / "c.py").write_text(f'DB_PASSWORD = "{pw}"\n', encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    sec = [f for f in result.findings if f.rule_id == "SEC002"]
    assert sec, "expected SEC002"
    assert pw not in sec[0].snippet and "[REDACTED:" in sec[0].snippet
    assert pw not in _json.dumps(build_document(result, StoaConfig()))
    assert pw not in render_html(result, StoaConfig())
