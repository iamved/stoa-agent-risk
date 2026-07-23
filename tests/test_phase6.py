"""Phase 6: dimension matrix HTML, anchor resolution, SARIF dimension tags."""

from __future__ import annotations

import re
from pathlib import Path

from stoa.config import StoaConfig
from stoa.report_html import render_html
from stoa.sarif import build_sarif
from stoa.scanner import ScanOptions, run_scan

RISKY = (
    "from langchain.agents import create_react_agent\n"
    "from langchain_openai import ChatOpenAI\n"
    "llm = ChatOpenAI(model='gpt-4o')\n"
    "@tool\n"
    "def act(response, order_id):\n"
    "    reply = response.choices[0].message.content\n"
    "    subprocess.run(reply, shell=True)\n"
    "    stripe.Refund.create(payment_intent=order_id, amount=100)\n"
    "agent = create_react_agent(llm, tools=[act])\n"
    "r = agent.invoke({'input': 'x'})\n"
)


def _result(tmp_path):
    (tmp_path / "a.py").write_text(RISKY, encoding="utf-8")
    return run_scan(ScanOptions(root=tmp_path, no_git=True))


def test_matrix_renders_with_no_script(tmp_path):
    html = render_html(_result(tmp_path), StoaConfig())
    assert "Dimension exposure" in html
    assert "<script" not in html.lower()
    assert "Content-Security-Policy" in html


def test_matrix_cell_anchors_resolve(tmp_path):
    html = render_html(_result(tmp_path), StoaConfig())
    # every href="#dim-<id>" must have a matching id="dim-<id>"
    hrefs = set(re.findall(r'href="#(dim-[0-9a-f]+)"', html))
    ids = set(re.findall(r'id="(dim-[0-9a-f]+)"', html))
    assert hrefs, "expected dimension cell anchors"
    assert hrefs.issubset(ids), f"dangling anchors: {hrefs - ids}"


def test_matrix_encodes_state_not_color_alone(tmp_path):
    html = render_html(_result(tmp_path), StoaConfig())
    # glyphs (non-color encoding) present
    assert "●" in html or "◐" in html
    assert "proxy signals only" in html


def test_matrix_absent_when_no_dimensions(tmp_path):
    (tmp_path / "a.py").write_text(RISKY, encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True, no_dimensions=True))
    html = render_html(result, StoaConfig())
    assert "Dimension exposure" not in html


def test_sarif_structure_and_dimension_tags(tmp_path):
    sarif = build_sarif(_result(tmp_path))
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "Stoa"
    results = run["results"]
    assert results
    # AI002 exec -> error level, with a dimension tag
    ai002 = [r for r in results if r["ruleId"] == "STOA-LLM02-OUTPUT-EXEC"]
    assert ai002 and ai002[0]["level"] == "error"
    tagged = [r for r in results if any(t.startswith("stoa-dim:") for t in r["properties"]["tags"])]
    assert tagged


def test_sarif_deterministic(tmp_path):
    import json
    a = json.dumps(build_sarif(_result(tmp_path)))
    b = json.dumps(build_sarif(_result(tmp_path)))
    assert a == b
