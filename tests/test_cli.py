"""CLI behavior: exit codes, outputs, init github, quiet/verbose."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import EXAMPLE_REPO, fake_openai_key

from stoa import __version__
from stoa.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert f"stoa {__version__}" in capsys.readouterr().out


def test_scan_report_only_exit_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = main(["scan", str(EXAMPLE_REPO), "--no-git"])
    assert code == 0
    assert (tmp_path / "stoa-report.html").is_file()
    assert (tmp_path / "stoa-registry.json").is_file()
    out = capsys.readouterr().out
    assert "Agent candidates" in out


def test_scan_json_structure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["scan", str(EXAMPLE_REPO), "--no-git", "--json", "out.json", "--html", "out.html"])
    document = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0"
    assert document["summary"]["agent_candidates"] >= 1
    assert document["agents"][0]["evidence"]
    assert (tmp_path / "out.html").is_file()


def test_gate_failure_exit_one(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(f'k = "{fake_openai_key()}"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(repo), "--no-git"]) == 0
    assert main(["scan", str(repo), "--no-git", "--fail-on", "critical"]) == 1
    assert main(["scan", str(repo), "--no-git", "--strict"]) == 1


def test_placeholder_key_does_not_gate(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_keys.py").write_text(
        'k = "sk-proj-fakekeyforexampleuseonly00000"\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert main(["scan", str(repo), "--no-git", "--fail-on", "critical"]) == 0


def test_bad_arguments_exit_two(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        main(["scan", ".", "--fail-on", "bogus"])
    assert excinfo.value.code == 2
    assert main(["scan", "does-not-exist"]) == 2


def test_invalid_config_exit_two(tmp_path, monkeypatch):
    (tmp_path / "stoa.toml").write_text("[rules]\nBOGUS999 = true\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", "."]) == 2


def test_quiet_mode_silent_on_pass(tmp_path, monkeypatch, capsys):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", ".", "--no-git", "--quiet"]) == 0
    assert capsys.readouterr().out == ""


def test_verbose_lists_skipped_files(tmp_path, monkeypatch, capsys):
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "big.py").write_text("x = 1\n" * 200_000, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert main(["scan", ".", "--no-git", "--verbose"]) == 0
    assert "big.py" in capsys.readouterr().out


def test_github_annotations_emitted(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(f'k = "{fake_openai_key()}"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    main(["scan", str(repo), "--no-git", "--github-annotations", "--quiet"])
    out = capsys.readouterr().out
    assert "::error file=app.py,line=1,title=SEC001::" in out
    assert fake_openai_key() not in out


def test_summary_file_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main(["scan", str(EXAMPLE_REPO), "--no-git", "--summary-file", "summary.md"])
    text = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "## Stoa Agent Risk Scan" in text
    assert "agent candidates" in text


def test_init_github_creates_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "github"]) == 0
    out = capsys.readouterr().out
    assert (tmp_path / ".github" / "workflows" / "stoa.yml").is_file()
    assert (tmp_path / ".stoaignore").is_file()
    assert (tmp_path / "stoa.toml").is_file()
    assert out.count("created:") == 3
    workflow = (tmp_path / ".github" / "workflows" / "stoa.yml").read_text(encoding="utf-8")
    assert f"stoa-agent-risk=={__version__}" in workflow
    assert "fetch-depth: 0" in workflow


def test_init_github_protects_existing_files(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "stoa.toml").write_text("fail_on = \"critical\"\n", encoding="utf-8")
    assert main(["init", "github"]) == 0
    out = capsys.readouterr().out
    assert "skipped:     stoa.toml" in out
    assert (tmp_path / "stoa.toml").read_text(encoding="utf-8") == 'fail_on = "critical"\n'


def test_init_github_force_overwrites(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "stoa.toml").write_text("custom = true\n", encoding="utf-8")
    assert main(["init", "github", "--force"]) == 0
    assert "overwritten: stoa.toml" in capsys.readouterr().out
    assert "custom" not in (tmp_path / "stoa.toml").read_text(encoding="utf-8")


def test_no_command_prints_help(capsys):
    assert main([]) == 2
    assert "stoa" in capsys.readouterr().out
