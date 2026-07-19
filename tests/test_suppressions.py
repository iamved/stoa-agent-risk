"""Inline, preceding-line, file-wide, .stoaignore, and config suppression."""

from __future__ import annotations

from pathlib import Path

import pytest

from stoa.config import ConfigError, StoaConfig, load_config
from stoa.scanner import ScanOptions, run_scan
from stoa.suppressions import parse_suppressions


def test_inline_python_suppression():
    content = 'query = f"SELECT * FROM {table}"  # stoa: ignore[SEC003] internal enum\n'
    suppressions = parse_suppressions(content, "src/a.py")
    assert suppressions.check("SEC003", 1) == (True, "internal enum")
    assert suppressions.check("SEC001", 1) == (False, None)


def test_inline_javascript_suppression():
    content = 'const url = "http://example-service.corp.com"; // stoa: ignore[NET001]\n'
    suppressions = parse_suppressions(content, "src/a.js")
    assert suppressions.check("NET001", 1) == (True, None)


def test_preceding_line_suppression():
    content = "# stoa: ignore[SEC003] trusted table\n" 'q = f"SELECT * FROM {t}"\n'
    suppressions = parse_suppressions(content, "src/a.py")
    assert suppressions.check("SEC003", 2) == (True, "trusted table")


def test_file_wide_suppression():
    content = "# stoa: ignore-file[CTRL001,CTRL002]\ncode = 1\n"
    suppressions = parse_suppressions(content, "src/a.py")
    assert suppressions.check("CTRL001", 99)[0] is True
    assert suppressions.check("CTRL002", 12)[0] is True
    assert suppressions.check("CTRL003", 12)[0] is False


def test_unknown_rule_id_warned_and_ignored():
    content = "x = 1  # stoa: ignore[NOPE123]\n"
    suppressions = parse_suppressions(content, "src/a.py")
    assert suppressions.by_line == {}
    assert any("NOPE123" in w for w in suppressions.warnings)


def test_empty_rule_list_is_not_blanket_ignore():
    content = "x = 1  # stoa: ignore[]\n"
    suppressions = parse_suppressions(content, "src/a.py")
    assert suppressions.by_line == {}
    assert suppressions.warnings


def test_scan_reports_suppressed_counts(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        'q = f"SELECT * FROM users WHERE id = {x}"  # stoa: ignore[SEC003] safe\n',
        encoding="utf-8",
    )
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert result.suppressed_count() == 1
    suppressed = [f for f in result.findings if f.suppressed]
    assert suppressed[0].rule_id == "SEC003"
    assert suppressed[0].suppression_reason == "safe"


def test_suppression_only_covers_named_rule(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        'q = f"SELECT * FROM users WHERE pw = {pw}"; password = "s3cureH0rse9"'
        "  # stoa: ignore[SEC003]\n",
        encoding="utf-8",
    )
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    by_rule = {f.rule_id: f for f in result.findings}
    assert by_rule["SEC003"].suppressed is True
    assert by_rule["SEC002"].suppressed is False


def test_stoaignore_excludes_paths(tmp_path: Path):
    (tmp_path / ".stoaignore").write_text("legacy/**\n", encoding="utf-8")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "old.py").write_text('q = f"SELECT * FROM t WHERE id = {x}"\n', encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert result.findings == []
    assert any(
        s.path in ("legacy/", "legacy/old.py") and ".stoaignore" in s.reason
        for s in result.skipped_files
    )


def test_config_disables_rule(tmp_path: Path):
    (tmp_path / "stoa.toml").write_text("[rules]\nSEC003 = false\n", encoding="utf-8")
    (tmp_path / "app.py").write_text('q = f"SELECT * FROM t WHERE id = {x}"\n', encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert [f for f in result.findings if f.rule_id == "SEC003"] == []


def test_config_severity_override(tmp_path: Path):
    (tmp_path / "stoa.toml").write_text('[severity]\nREL001 = "low"\n', encoding="utf-8")
    (tmp_path / "app.py").write_text("try:\n    x()\nexcept Exception:\n    pass\n", encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    rel = [f for f in result.findings if f.rule_id == "REL001"]
    assert rel and rel[0].severity == "low"


def test_invalid_rule_id_in_config_rejected(tmp_path: Path):
    (tmp_path / "stoa.toml").write_text("[rules]\nBOGUS999 = true\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_invalid_severity_in_config_rejected(tmp_path: Path):
    (tmp_path / "stoa.toml").write_text('[severity]\nSEC001 = "fatal"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_suppressed_findings_kept_in_json_by_default():
    assert StoaConfig().include_suppressed_in_json is True
