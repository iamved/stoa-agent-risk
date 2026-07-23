"""Phase 4: dimension taxonomy, scoring, proxy cap, custom taxonomy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stoa.config import StoaConfig
from stoa.dimensions import (
    TaxonomyError,
    assess_agent,
    default_taxonomy,
    load_taxonomy,
)
from stoa.models import AgentCandidate, Finding
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan

RISKY_AGENT = (
    "from langchain.agents import create_react_agent\n"
    "from langchain_openai import ChatOpenAI\n"
    "llm = ChatOpenAI(model='gpt-4o')\n"
    "@tool\n"
    "def refund(response, order_id):\n"
    "    reply = response.choices[0].message.content\n"
    "    subprocess.run(reply, shell=True)\n"
    "    stripe.Refund.create(payment_intent=order_id, amount=100)\n"
    "agent = create_react_agent(llm, tools=[refund])\n"
    "r = agent.invoke({'input': 'x'})\n"
)


def _scan(tmp_path, **kw):
    (tmp_path / "a.py").write_text(RISKY_AGENT, encoding="utf-8")
    return run_scan(ScanOptions(root=tmp_path, no_git=True, **kw))


def test_dimension_assessment_present_on_agents(tmp_path):
    result = _scan(tmp_path)
    agent = result.agents[0]
    assert agent.dimension_assessment is not None
    ids = {d["id"] for d in agent.dimension_assessment["dimensions"]}
    assert "data-exfiltration" in ids and "unauthorized-action" in ids


def test_proxy_cap_invariant_property(tmp_path):
    """No proxy-tier dimension may ever serialize exposure 'elevated'."""
    result = _scan(tmp_path)
    for agent in result.agents:
        for d in agent.dimension_assessment["dimensions"]:
            if d["assessability"] == "proxy":
                assert d["exposure"] != "elevated", d


def test_proxy_cap_forced_even_with_huge_score():
    """A synthetic high score on a proxy dimension is capped at moderate."""
    tax = default_taxonomy()
    # AI007 -> behavioral-instability (proxy). Stack many to push score high.
    findings = [
        Finding(fingerprint=f"fp{i}", rule_id="AI007", title="t", category="ai-stability",
                severity="info", confidence="high", path="a.py", line=i, column=1,
                snippet="s", remediation="r")
        for i in range(50)
    ]
    agent = AgentCandidate(id="x", name="a", symbol="a", path="a.py", language="python",
                           confidence="high", detection_score=9, findings=findings)
    block = assess_agent(agent, "content", [], tax)
    behav = next(d for d in block["dimensions"] if d["id"] == "behavioral-instability")
    assert behav["assessability"] == "proxy"
    assert behav["exposure"] == "moderate"  # capped, never elevated


def test_controls_reduce_exposure(tmp_path):
    """Observed approval + logging lower unauthorized-action / operational exposure."""
    safe = RISKY_AGENT.replace(
        "    reply = response",
        "    logger.info('x')\n    if not interrupt({}).get('approved'):\n        return\n    reply = response",
    )
    (tmp_path / "a.py").write_text(safe, encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    agent = result.agents[0]
    ua = next(d for d in agent.dimension_assessment["dimensions"] if d["id"] == "unauthorized-action")
    assert "approval" in ua["controls_observed"]


def test_no_dimensions_flag_omits_block(tmp_path):
    result = _scan(tmp_path, no_dimensions=True)
    assert result.dimension_summary is None
    assert all(a.dimension_assessment is None for a in result.agents)
    doc = build_document(result, StoaConfig())
    assert "dimension_summary" not in doc


def test_dimension_output_deterministic(tmp_path):
    a = json.dumps(build_document(_scan(tmp_path), StoaConfig()))
    b = json.dumps(build_document(_scan(tmp_path), StoaConfig()))
    assert a == b


def test_custom_taxonomy_replaces_default(tmp_path):
    tax_file = tmp_path / "custom.toml"
    tax_file.write_text(
        '[taxonomy]\nid = "tiny"\nversion = "9.9"\n\n'
        '[[dimensions]]\nid = "danger"\nname = "Danger"\ndefinition = "x"\nassessability = "strong"\n\n'
        '[finding_weights]\ncritical = 40\nhigh = 25\nmedium = 12\nlow = 5\ninfo = 2\n'
        '[confidence_multipliers]\nhigh = 1.0\nmedium = 0.6\nlow = 0.3\n'
        '[scoring]\ncapability_weight = 18\nprovider_weight = 8\ncontrol_credit = 20\n'
        '[rule_dimensions]\nAI002 = ["danger"]\n',
        encoding="utf-8",
    )
    result = _scan(tmp_path, taxonomy_path=tax_file)
    agent = result.agents[0]
    assert agent.dimension_assessment["taxonomy"] == {"id": "tiny", "version": "9.9"}
    ids = {d["id"] for d in agent.dimension_assessment["dimensions"]}
    assert "danger" in ids


def test_unclassified_safety_net(tmp_path):
    """A taxonomy that maps no rule surfaces findings under 'unclassified'."""
    tax_file = tmp_path / "empty.toml"
    tax_file.write_text(
        '[taxonomy]\nid = "empty"\nversion = "1"\n\n'
        '[[dimensions]]\nid = "d1"\nname = "D1"\ndefinition = "x"\nassessability = "strong"\n\n'
        '[finding_weights]\ncritical = 40\nhigh = 25\nmedium = 12\nlow = 5\ninfo = 2\n'
        '[confidence_multipliers]\nhigh = 1.0\nmedium = 0.6\nlow = 0.3\n'
        '[scoring]\ncapability_weight = 18\nprovider_weight = 8\ncontrol_credit = 20\n',
        encoding="utf-8",
    )
    result = _scan(tmp_path, taxonomy_path=tax_file)
    agent = result.agents[0]
    ids = {d["id"] for d in agent.dimension_assessment["dimensions"]}
    assert "unclassified" in ids


def test_bad_taxonomy_raises():
    with pytest.raises(TaxonomyError):
        load_taxonomy(Path("/nonexistent/taxonomy.toml"))
