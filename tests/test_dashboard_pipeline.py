"""M2 pipeline: safe embedding, hash-pinned CSP, redaction, determinism,
template resolution, and the CLI surface (`stoa dashboard`, `stoa scan`)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import fake_openai_key, init_git_repo, run_git
from stoa.cli import main
from stoa.dashboard.inject import (
    PLACEHOLDER,
    DashboardError,
    content_security_policy,
    escape_json_for_script,
    inline_hashes,
    render_dashboard,
)
from stoa.dashboard.template import TEMPLATE_ENV, DashboardTemplateMissing, load_template

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "ui" / "fixtures"
REAL_TEMPLATE = REPO_ROOT / "src" / "stoa" / "templates" / "dashboard.html"

HOSTILE = "</script><script>alert(1)</script><!-- x -->\u2028\u2029&amp;"

FAKE_TEMPLATE = (
    '<!doctype html><html><head><meta charset="utf-8" />'
    "<script>console.log('boot')</script>"
    '<style rel="stylesheet">body{margin:0}</style></head><body>'
    '<div id="root"></div>'
    '<script id="stoa-data" type="application/json">__STOA_DASHBOARD_DATA__</script>'
    '<script type="module" crossorigin>document.getElementById("root").textContent="ok"</script>'
    "</body></html>"
)


@pytest.fixture
def fake_template(monkeypatch, tmp_path) -> Path:
    path = tmp_path / "template.html"
    path.write_text(FAKE_TEMPLATE, encoding="utf-8")
    monkeypatch.setenv(TEMPLATE_ENV, str(path))
    return path


def _envelope(**extra) -> dict:
    env = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())
    env.update(extra)
    return env


# --- escaping ---------------------------------------------------------------


def test_escape_neutralizes_tag_closers_and_separators():
    text = escape_json_for_script({"s": HOSTILE})
    for raw in ("<", ">", "&", "\u2028", "\u2029"):
        assert raw not in text
    assert "\\u003c/script\\u003e" in text
    assert json.loads(text) == {"s": HOSTILE}


def test_render_keeps_script_count_and_payload_inert(fake_template):
    html = render_dashboard(_envelope(), FAKE_TEMPLATE.replace("__STOA_DASHBOARD_DATA__", PLACEHOLDER))
    hostile = _envelope()
    hostile["registry"]["warnings"].append(HOSTILE)
    html = render_dashboard(hostile)
    assert html.count("<script") == FAKE_TEMPLATE.count("<script")
    assert "</script><script>alert(1)</script>" not in html
    assert HOSTILE not in html
    assert PLACEHOLDER not in html
    embedded = re.search(r'<script id="stoa-data" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert embedded is not None
    assert json.loads(embedded.group(1))["registry"]["warnings"][-1] == HOSTILE


def test_render_requires_exactly_one_placeholder():
    with pytest.raises(DashboardError):
        render_dashboard(_envelope(), FAKE_TEMPLATE.replace(PLACEHOLDER, "x"))
    with pytest.raises(DashboardError):
        render_dashboard(_envelope(), FAKE_TEMPLATE + PLACEHOLDER)
    with pytest.raises(DashboardError):
        render_dashboard(_envelope(), FAKE_TEMPLATE.replace('<meta charset="utf-8" />', ""))


# --- CSP ----------------------------------------------------------------------


def test_csp_pins_every_inline_script_and_style_and_nothing_else():
    scripts, styles = inline_hashes(FAKE_TEMPLATE)
    assert len(scripts) == 2  # boot + module; the JSON data tag is not executable
    assert len(styles) == 1
    csp = content_security_policy(FAKE_TEMPLATE)
    assert csp.startswith("default-src 'none'; ")
    assert "connect-src 'none'" in csp
    assert "unsafe-inline" not in csp
    for h in scripts:
        assert h in csp
    html = render_dashboard(_envelope(), FAKE_TEMPLATE)
    meta = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)" />', html)
    assert meta is not None and meta.group(1) == csp
    assert html.index("Content-Security-Policy") < html.index("<script")


def test_csp_hash_matches_real_template_if_built():
    if not REAL_TEMPLATE.is_file():
        pytest.skip("dashboard template not built in this checkout")
    template = REAL_TEMPLATE.read_text(encoding="utf-8")
    scripts, styles = inline_hashes(template)
    assert scripts and styles
    assert template.count(PLACEHOLDER) == 1
    assert len(template.encode("utf-8")) < 1_500_000, "compiled template exceeds the 1.5 MB budget"
    assert "unsafe-inline" not in content_security_policy(template)
    html = render_dashboard(_envelope(), template)
    assert len(html.encode("utf-8")) < 1_500_000 + len(escape_json_for_script(_envelope()).encode("utf-8"))


# --- redaction and determinism ------------------------------------------------


def test_planted_secret_never_reaches_the_html():
    key = fake_openai_key()
    env = _envelope()
    env["registry"]["agents"][0]["findings"][0]["snippet"] = f'api_key = "{key}"'
    env["registry"]["warnings"].append(f"token {key} leaked")
    html = render_dashboard(env, FAKE_TEMPLATE)
    assert key not in html
    assert "[REDACTED:" in html


def test_render_is_byte_identical_for_same_inputs():
    env = _envelope()
    assert render_dashboard(env, FAKE_TEMPLATE) == render_dashboard(json.loads(json.dumps(env)), FAKE_TEMPLATE)


# --- template resolution ------------------------------------------------------


def test_template_env_override_and_missing(monkeypatch, tmp_path):
    monkeypatch.setenv(TEMPLATE_ENV, str(tmp_path / "nope.html"))
    with pytest.raises(DashboardTemplateMissing):
        load_template()
    (tmp_path / "t.html").write_text("<x>", encoding="utf-8")
    monkeypatch.setenv(TEMPLATE_ENV, str(tmp_path / "t.html"))
    assert load_template() == "<x>"


# --- CLI ----------------------------------------------------------------------


def test_dashboard_command_from_envelope_and_registry(fake_template, tmp_path, capsys):
    out = tmp_path / "d.html"
    assert main(["dashboard", str(FIXTURES / "meridian-pay.envelope.json"), "--out", str(out)]) == 0
    html = out.read_text(encoding="utf-8")
    assert '"schema":"stoa-dashboard/1.0"' in html
    assert "meridian-pay" in html

    out2 = tmp_path / "r.html"
    assert main([
        "dashboard", str(FIXTURES / "meridian-pay.baseline.json"),
        "--baseline", str(FIXTURES / "meridian-pay.baseline.json"),
        "--out", str(out2), "--root", str(tmp_path),
    ]) == 0
    html2 = out2.read_text(encoding="utf-8")
    assert '"diff":{"schema":"stoa-diff/1.0"' in html2
    assert '"agents_changed":0' in html2


def test_dashboard_command_rejects_bad_input(fake_template, tmp_path, capsys):
    assert main(["dashboard", str(tmp_path / "missing.json")]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert main(["dashboard", str(bad)]) == 2
    bad.write_text('{"hello": 1}')
    assert main(["dashboard", str(bad)]) == 2
    assert "schema_version" in capsys.readouterr().err


def test_dashboard_command_without_template_is_a_clean_error(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(TEMPLATE_ENV, str(tmp_path / "absent.html"))
    assert main(["dashboard", str(FIXTURES / "meridian-pay.envelope.json"), "--out", str(tmp_path / "x.html")]) == 3
    assert "STOA_DASHBOARD_TEMPLATE" in capsys.readouterr().err


def test_scan_writes_dashboard_and_history(fake_template, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "agent.py").write_text("from openai import OpenAI\nclient = OpenAI()\n")
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", "init")
    monkeypatch.chdir(repo)
    assert main(["scan", ".", "--quiet", "--json", "r.json", "--html", "r.html", "--dashboard", "d.html"]) == 0
    assert (repo / "d.html").is_file()
    history = list((repo / ".stoa" / "history").glob("*.json"))
    assert len(history) == 1
    entry = json.loads(history[0].read_text())
    assert entry["schema"] == "stoa-history-entry/1.0"
    html = (repo / "d.html").read_text(encoding="utf-8")
    assert '"history":[{"schema":"stoa-history-entry/1.0"' in html

    (repo / "d.html").unlink()
    assert main(["scan", ".", "--quiet", "--json", "r.json", "--html", "r.html",
                 "--dashboard", "d.html", "--no-dashboard"]) == 0
    assert not (repo / "d.html").exists()


def test_scan_without_template_warns_and_still_succeeds(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv(TEMPLATE_ENV, str(tmp_path / "absent.html"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "agent.py").write_text("from openai import OpenAI\nclient = OpenAI()\n")
    monkeypatch.chdir(repo)
    assert main(["scan", ".", "--no-git", "--json", "r.json", "--html", "r.html", "--dashboard", "d.html"]) == 0
    captured = capsys.readouterr()
    assert "dashboard skipped" in captured.err
    assert not (repo / "d.html").exists()
    assert "Reports: r.html, r.json" in captured.out


# --- the dashboard's data as a file, for a page to open from disk -------------


def test_dashboard_json_out_is_the_redacted_envelope_and_needs_no_template(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(TEMPLATE_ENV, str(tmp_path / "absent.html"))
    env = _envelope()
    env["registry"]["warnings"].append(f"leaked {fake_openai_key()}")
    (tmp_path / "in.json").write_text(json.dumps(env), encoding="utf-8")
    # No template in this checkout: the HTML fails cleanly, the JSON is still written.
    assert main(["dashboard", "in.json", "--json-out", "data.json"]) == 3
    written = (tmp_path / "data.json").read_text(encoding="utf-8")
    assert fake_openai_key() not in written
    data = json.loads(written)
    assert data["schema"] == "stoa-dashboard/1.0" and "demo" not in data
    assert data["registry"]["repository"]["name"] == "meridian-pay"


def test_demo_flag_marks_the_page_and_nothing_else_does(fake_template, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fixture = str(FIXTURES / "meridian-pay.envelope.json")
    assert main(["dashboard", fixture, "--demo", "--out", "demo.html"]) == 0
    assert main(["dashboard", fixture, "--out", "plain.html"]) == 0
    assert '"demo":true' in (tmp_path / "demo.html").read_text(encoding="utf-8")
    assert '"demo"' not in (tmp_path / "plain.html").read_text(encoding="utf-8")


def test_scan_writes_dashboard_json(fake_template, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    example = str(REPO_ROOT / "examples" / "sparkwing")
    assert main(["scan", example, "--no-git", "--quiet", "--dashboard-json", "data.json"]) in (0, 1)
    data = json.loads((tmp_path / "data.json").read_text(encoding="utf-8"))
    assert data["schema"] == "stoa-dashboard/1.0"
    # A customer's scan is never marked as demo data.
    assert "demo" not in data


def test_dashboard_json_with_no_dashboard_is_a_usage_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    example = str(REPO_ROOT / "examples" / "sparkwing")
    assert main(["scan", example, "--no-git", "--no-dashboard", "--dashboard-json", "data.json"]) == 2
    assert "--dashboard-json" in capsys.readouterr().err
    assert not (tmp_path / "data.json").exists()
