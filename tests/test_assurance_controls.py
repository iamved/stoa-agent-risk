"""Assurance layer Phase 3: semantic permission tags, CTRL005-007."""

from __future__ import annotations

from stoa.config import StoaConfig
from stoa.integration_detection import detect_permission_tags
from stoa.scanner import ScanOptions, run_scan


# --- semantic permission tags -------------------------------------------------


def test_move_funds_tag_detected():
    assert "move_funds" in detect_permission_tags("stripe.Transfer.create(amount=100)", [])


def test_approve_transactions_tag_detected():
    assert "approve_transactions" in detect_permission_tags(
        "stripe.PaymentIntent.confirm(pi_id)", []
    )


def test_sign_contracts_tag_detected():
    assert "sign_contracts" in detect_permission_tags("docusign.send_envelope(env)", [])


def test_delete_tag_detected():
    assert "delete" in detect_permission_tags('cursor.execute("DELETE FROM users")', [])
    assert "delete" in detect_permission_tags("shutil.rmtree(path)", [])


def test_communicate_is_an_alias_over_existing_capabilities():
    assert "communicate" in detect_permission_tags("x", ["email_send"])
    assert "communicate" in detect_permission_tags("x", ["messaging"])
    assert "communicate" not in detect_permission_tags("x", ["database_write"])


def test_no_tags_on_benign_content():
    assert detect_permission_tags("x = 1 + 1", []) == []


# --- CTRL005: rate limiting absent on a high-impact-capability loop ---------


def _scan_ctrl(tmp_path, source: str):
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True), StoaConfig())
    assert result.agents, "expected an agent candidate"
    return {f.rule_id for f in result.agents[0].findings}


def test_ctrl005_fires_on_unbounded_high_impact_loop(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def process(orders):\n"
        "    for order in orders:\n"
        "        stripe.Refund.create(payment_intent=order.id, amount=order.amount)\n"
    )
    assert "CTRL005" in _scan_ctrl(tmp_path, source)


def test_ctrl005_silent_when_sleep_present_in_loop(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def process(orders):\n"
        "    for order in orders:\n"
        "        time.sleep(1)\n"
        "        stripe.Refund.create(payment_intent=order.id, amount=order.amount)\n"
    )
    assert "CTRL005" not in _scan_ctrl(tmp_path, source)


def test_ctrl005_silent_when_no_loop(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def process(order):\n"
        "    stripe.Refund.create(payment_intent=order.id, amount=order.amount)\n"
    )
    assert "CTRL005" not in _scan_ctrl(tmp_path, source)


# --- CTRL006: sandboxing absent on an exec path ------------------------------


def test_ctrl006_fires_on_unsandboxed_exec_path(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    subprocess.run(resp.choices[0].message.content, shell=True)\n"
    )
    assert "CTRL006" in _scan_ctrl(tmp_path, source)


def test_ctrl006_silent_when_sandbox_construct_present(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    subprocess.run(resp.choices[0].message.content, shell=True, env={})\n"
    )
    assert "CTRL006" not in _scan_ctrl(tmp_path, source)


def test_ctrl006_silent_when_no_exec_sink(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        "def handle(prompt):\n"
        "    resp = llm.invoke(prompt)\n"
        "    return resp.choices[0].message.content\n"
    )
    assert "CTRL006" not in _scan_ctrl(tmp_path, source)


# --- CTRL007: no kill-switch signal (weakest signal, info-only) -------------


def test_ctrl007_fires_when_no_flag_construct(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
    )
    assert "CTRL007" in _scan_ctrl(tmp_path, source)


def test_ctrl007_silent_when_feature_flag_present(tmp_path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n"
        'feature_flag_enabled("agent_x")\n'
    )
    assert "CTRL007" not in _scan_ctrl(tmp_path, source)
