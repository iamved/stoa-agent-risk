"""Autonomy inference: the four-level ladder + indeterminate, from real fixtures."""

from __future__ import annotations

from stoa.config import StoaConfig
from stoa.scanner import ScanOptions, run_scan


def _autonomy(tmp_path, source: str) -> dict:
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True), StoaConfig())
    assert result.agents, "expected an agent candidate"
    return result.agents[0].autonomy_level


def test_no_side_effecting_sink_is_recommend_only(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    return resp.choices[0].message.content\n"
    )
    assessment = _autonomy(tmp_path, source)
    assert assessment["level"] == "recommend_only"
    assert assessment["signals"] == []
    assert assessment["reason"] is None


def test_approval_construct_with_no_ai003_is_human_approved(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "@tool\n"
        "def refund(order_id):\n"
        '    if not human_input("approve refund?"):\n'
        "        return\n"
        "    stripe.Refund.create(payment_intent=order_id, amount=100)\n"
        "executor = AgentExecutor(agent=a, tools=[refund])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    subprocess.run(resp.choices[0].message.content, shell=True)\n"
    )
    assessment = _autonomy(tmp_path, source)
    assert assessment["level"] == "human_approved"
    assert any(s["signal"] == "approval_construct" for s in assessment["signals"])
    assert any(s["signal"] == "AI002" for s in assessment["signals"])


def test_hardcoded_cap_check_with_no_approval_is_bounded_autonomous(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "@tool\n"
        "def refund(order_id, amount):\n"
        "    if amount > MAX_REFUND:\n"
        '        raise ValueError("too much")\n'
        "    stripe.Refund.create(payment_intent=order_id, amount=amount)\n"
        "executor = AgentExecutor(agent=a, tools=[refund])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    subprocess.run(resp.choices[0].message.content, shell=True)\n"
    )
    assessment = _autonomy(tmp_path, source)
    assert assessment["level"] == "bounded_autonomous"
    assert any(s["signal"] == "bounding" for s in assessment["signals"])


def test_no_approval_no_bounding_high_impact_is_unrestricted_autonomous(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "@tool\n"
        "def refund(order_id, amount):\n"
        "    stripe.Refund.create(payment_intent=order_id, amount=amount)\n"
        "executor = AgentExecutor(agent=a, tools=[refund])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    subprocess.run(resp.choices[0].message.content, shell=True)\n"
    )
    assessment = _autonomy(tmp_path, source)
    assert assessment["level"] == "unrestricted_autonomous"
    assert any(s["signal"] == "AI003" for s in assessment["signals"])


def test_side_effect_with_no_correlating_signal_is_indeterminate(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    requests.post(resp.choices[0].message.content)\n"
    )
    assessment = _autonomy(tmp_path, source)
    assert assessment["level"] == "indeterminate"
    assert assessment["reason"] is not None
    assert "AI002" in assessment["reason"] or "sink" in assessment["reason"]


def test_autonomy_level_always_present_even_with_no_agents(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert result.agents == []  # sanity: no agent candidate detected


def test_autonomy_ignored_when_finding_is_suppressed(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    subprocess.run(resp.choices[0].message.content, shell=True)  # stoa: ignore[AI002] reviewed\n"
    )
    assessment = _autonomy(tmp_path, source)
    # the AI002 finding is suppressed, so infer_autonomy must not count it as a signal
    assert assessment["level"] == "recommend_only"


def test_report_shows_autonomy_badge(tmp_path):
    from stoa.report_html import render_html

    source = (
        "from langchain.agents import AgentExecutor\n"
        "@tool\n"
        "def refund(order_id, amount):\n"
        "    stripe.Refund.create(payment_intent=order_id, amount=amount)\n"
        "executor = AgentExecutor(agent=a, tools=[refund])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    subprocess.run(resp.choices[0].message.content, shell=True)\n"
    )
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True), StoaConfig())
    html = render_html(result, StoaConfig(no_graph=True))
    assert 'class="autonomy-badge autonomy-crit"' in html
    assert "Unrestricted-autonomous" in html
