"""Diff-aware classification: added lines gate, existing debt does not."""

from __future__ import annotations

from pathlib import Path

from conftest import fake_openai_key, init_git_repo, run_git

from stoa.config import StoaConfig
from stoa.diff import compute_added_ranges, mark_new_findings
from stoa.models import Finding
from stoa.scanner import ScanOptions, gate_findings, run_scan


def _finding(path: str, line: int) -> Finding:
    return Finding(
        fingerprint=f"fp-{path}-{line}",
        rule_id="SEC001",
        title="t",
        category="secret",
        severity="critical",
        confidence="high",
        path=path,
        line=line,
        column=1,
        snippet="s",
        remediation="r",
    )


def _base_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "clean.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (repo / "legacy.py").write_text(
        f'old_key = "{fake_openai_key()}"\n', encoding="utf-8"
    )
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "base")
    return repo


def test_finding_on_added_line_is_new(tmp_path: Path):
    repo = _base_repo(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "feature")
    (repo / "clean.py").write_text(
        f'x = 1\ny = 2\nnew_key = "{fake_openai_key()}"\n', encoding="utf-8"
    )
    run_git(repo, "commit", "-aqm", "add key")

    result = run_scan(ScanOptions(root=repo, base="main"))
    assert result.diff_available
    by_path = {f.path: f for f in result.findings if f.rule_id == "SEC001"}
    assert by_path["clean.py"].is_new is True
    assert by_path["legacy.py"].is_new is False


def test_existing_debt_does_not_gate_new_only(tmp_path: Path):
    repo = _base_repo(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "feature")
    (repo / "unrelated.py").write_text("z = 3\n", encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-qm", "unrelated change")

    result = run_scan(ScanOptions(root=repo, base="main"))
    config = StoaConfig()  # fail_on none, fail_on_new critical
    assert gate_findings(result, config) == []


def test_new_secret_trips_gate(tmp_path: Path):
    repo = _base_repo(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "feature")
    (repo / "added.py").write_text(f'k = "{fake_openai_key()}"\n', encoding="utf-8")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-qm", "add secret")

    result = run_scan(ScanOptions(root=repo, base="main"))
    tripped = gate_findings(result, StoaConfig())
    assert len(tripped) == 1
    assert tripped[0].path == "added.py"


def test_deleted_insecure_line_creates_no_new_finding(tmp_path: Path):
    repo = _base_repo(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "feature")
    (repo / "legacy.py").write_text("clean = True\n", encoding="utf-8")
    run_git(repo, "commit", "-aqm", "remove key")

    result = run_scan(ScanOptions(root=repo, base="main"))
    assert [f for f in result.findings if f.path == "legacy.py" and f.rule_id == "SEC001"] == []
    assert gate_findings(result, StoaConfig()) == []


def test_pure_rename_not_marked_new(tmp_path: Path):
    repo = _base_repo(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "feature")
    run_git(repo, "mv", "legacy.py", "renamed.py")
    run_git(repo, "commit", "-qm", "rename")

    result = run_scan(ScanOptions(root=repo, base="main"))
    findings = [f for f in result.findings if f.path == "renamed.py" and f.rule_id == "SEC001"]
    assert findings and findings[0].is_new is False
    assert gate_findings(result, StoaConfig()) == []


def test_missing_base_fails_open_with_warning(tmp_path: Path):
    repo = _base_repo(tmp_path)
    result = run_scan(ScanOptions(root=repo, base="origin/does-not-exist"))
    assert result.diff_available is False
    assert any("failing open" in w for w in result.warnings)
    assert gate_findings(result, StoaConfig()) == []


def test_non_git_directory_fails_open(tmp_path: Path):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, base="main"))
    assert result.diff_available is False
    assert result.warnings


def test_mark_new_findings_range_intersection():
    ranges = {"a.py": [(10, 12)]}
    inside = _finding("a.py", 11)
    outside = _finding("a.py", 20)
    other = _finding("b.py", 11)
    mark_new_findings([inside, outside, other], ranges)
    assert inside.is_new is True
    assert outside.is_new is False
    assert other.is_new is False


def test_compute_added_ranges_parses_hunks(tmp_path: Path):
    repo = _base_repo(tmp_path)
    run_git(repo, "checkout", "-q", "-b", "feature")
    (repo / "clean.py").write_text("x = 1\ninserted = True\ny = 2\n", encoding="utf-8")
    run_git(repo, "commit", "-aqm", "insert line")
    ranges, warning = compute_added_ranges(repo, "main")
    assert warning is None
    assert ranges == {"clean.py": [(2, 2)]}
