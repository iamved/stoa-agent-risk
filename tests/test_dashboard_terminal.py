"""The terminal overview: the same envelope the dashboard reads, as plain text."""

from __future__ import annotations

import json
from pathlib import Path

from stoa.cli import main
from stoa.dashboard.terminal import render_overview

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "ui" / "fixtures"


def _envelope(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.envelope.json").read_text())


def test_overview_reports_the_registrys_own_numbers():
    env = _envelope("meridian-pay")
    text = render_overview(env)
    counts = env["registry"]["summary"]["findings"]
    assert f"{counts['critical']} critical, {counts['high']} high" in text
    assert "meridian-pay @ e4f5a6b" in text
    assert "Agents    5 (5 high confidence)" in text
    assert "Drift     vs a1b2c3d: 1 agent added; unapproved drift up to high" in text
    # Two records of one agent read as one agent with a record count.
    assert "Agents    5, from 6 discovered records" in render_overview(_envelope("two-stacks"))
    # Only dimensions above low are listed, elevated first.
    exposure = text.split("Exposure above low")[1].split("Top findings")[0]
    assert "elevated" in exposure and " low " not in exposure
    # Every finding is counted once even though agents in a file share them.
    total = sum(counts.values())
    assert f"Top findings (5 of {total})" in text


def test_top_findings_show_one_per_rule_before_repeating():
    # The first run has four distinct rules: each is listed, then one repeats, in severity order.
    rules = [line.split()[1] for line in render_overview(_envelope("first-run")).splitlines()
             if line.startswith("  ") and len(line.split()) >= 3 and line.split()[0] in ("critical", "high", "medium", "low", "info")]
    assert len(rules) == 5 and len(set(rules)) == 4
    # The demo has more than five rules, so no rule repeats.
    demo = [line.split()[1] for line in render_overview(_envelope("meridian-pay")).splitlines()
            if line.startswith("  ") and len(line.split()) >= 3 and line.split()[0] in ("critical", "high", "medium", "low", "info")]
    assert len(demo) == 5 and len(set(demo)) == 5


def test_next_steps_name_only_what_is_missing():
    first_run = render_overview(_envelope("first-run"))
    for command in ("stoa init declarations", "--diff-against", "stoa init underwriting"):
        assert command in first_run
    # The demo has declarations, a baseline and business context: nothing to suggest.
    assert "Next" not in render_overview(_envelope("meridian-pay"))
    assert "Next" not in render_overview(_envelope("first-run"), next_steps=False)


def test_no_agents_says_so_instead_of_listing_nothing():
    text = render_overview(_envelope("no-agents"))
    assert "Agents    0" in text and "Findings  none" in text
    assert "No agents were found" in text and "Top findings" not in text


def test_overview_is_deterministic_and_plain_text():
    env = _envelope("hostile")
    assert render_overview(env) == render_overview(env)
    assert "\x1b[" not in render_overview(env)


def test_scan_appends_the_overview_and_quiet_suppresses_it(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    example = str(REPO_ROOT / "examples" / "meridian-pay")
    main(["scan", example, "--no-git"])
    out = capsys.readouterr().out
    assert out.startswith("stoa ") and "Agent candidates:" in out  # the existing summary is unchanged
    assert "Top findings" in out and "Exposure above low" in out
    main(["scan", example, "--no-git", "--quiet"])
    assert "Top findings" not in capsys.readouterr().out
    main(["scan", example, "--no-git", "--github-annotations"])
    assert "\nNext\n" not in capsys.readouterr().out


def test_dashboard_summary_flag(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STOA_DASHBOARD_TEMPLATE", str(tmp_path / "absent.html"))
    # The summary needs no compiled UI: it prints even when the HTML cannot be built.
    code = main(["dashboard", str(FIXTURES / "first-run.envelope.json"), "--summary"])
    assert code == 3
    assert "acme-support @ e4f5a6b" in capsys.readouterr().out


def test_a_config_without_intake_is_not_told_to_start_over():
    env = _envelope("first-run")
    env["assessment"]["identity_source"] = "applicant"
    text = render_overview(env)
    assert "[intake]" in text and "stoa init underwriting" not in text
