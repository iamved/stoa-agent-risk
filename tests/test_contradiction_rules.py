"""Assurance layer Phase 4: the contradiction detector (DECL001-007)."""

from __future__ import annotations

from pathlib import Path

from stoa.config import StoaConfig
from stoa.scanner import ScanOptions, run_scan


def _scan(tmp_path: Path, sources: dict[str, str], declared: str | None = None):
    for name, content in sources.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    if declared is not None:
        (tmp_path / "stoa-declared.toml").write_text(declared, encoding="utf-8")
    return run_scan(ScanOptions(root=tmp_path, no_git=True), StoaConfig())


def _decl_findings(result, agent_index=0):
    return {f.rule_id: f for f in result.agents[agent_index].findings if f.rule_id.startswith("DECL")}


UNRESTRICTED = (
    "from langchain.agents import AgentExecutor\n"
    "@tool\n"
    "def refund(order_id, amount):\n"
    "    stripe.Refund.create(payment_intent=order_id, amount=amount)\n"
    "executor = AgentExecutor(agent=a, tools=[refund])\n"
    "def handle(prompt):\n"
    "    resp = llm.invoke(prompt)\n"
    "    subprocess.run(resp.choices[0].message.content, shell=True)\n"
)

MOVER = (
    "from langchain.agents import AgentExecutor\n"
    "@tool\n"
    "def payout(user_id, amount):\n"
    "    stripe.Payout.create(amount=amount)\n"
    "executor = AgentExecutor(agent=a, tools=[payout])\n"
)

LEAKY = (
    "from langchain.agents import AgentExecutor\n"
    "executor = AgentExecutor(agent=a, tools=[t])\n"
    'api_key = "sk-proj-Zx9mKq3vNp7rTb2wYc5dHj8fLg4sVn6a"\n'
)

PROD_NO_OBS = (
    "from langchain.agents import AgentExecutor\n"
    "@tool\n"
    "def act(x):\n"
    "    db.execute(x)\n"
    "executor = AgentExecutor(agent=a, tools=[act])\n"
)


def _agent_id(tmp_path, filename, source):
    (tmp_path / filename).write_text(source, encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True), StoaConfig())
    assert len(result.agents) == 1
    return result.agents[0].id


# --- DECL001: declared autonomy contradicts inferred autonomy ---------------


def test_decl001_fires_recommend_only_but_unrestricted(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", UNRESTRICTED)
    declared = f'[agents."{agent_id}"]\nautonomy_intent = "recommend_only"\n'
    result = _scan(tmp_path, {"a.py": UNRESTRICTED}, declared)
    findings = _decl_findings(result)
    assert "DECL001" in findings
    assert findings["DECL001"].severity == "critical"
    assert findings["DECL001"].declared_ref["key"].endswith(".autonomy_intent")


def test_decl001_absent_when_declared_matches_inferred(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", UNRESTRICTED)
    declared = f'[agents."{agent_id}"]\nautonomy_intent = "unrestricted_autonomous"\n'
    result = _scan(tmp_path, {"a.py": UNRESTRICTED}, declared)
    assert "DECL001" not in _decl_findings(result)


# --- DECL002: economic authority declared, no bounding on money path -------


def test_decl002_fires_when_no_bounding(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", MOVER)
    declared = (
        f'[agents."{agent_id}"]\n'
        f'[agents."{agent_id}".economic_authority]\n'
        "max_per_action = {amount = 500, currency = \"USD\"}\n"
    )
    result = _scan(tmp_path, {"a.py": MOVER}, declared)
    findings = _decl_findings(result)
    assert "DECL002" in findings
    assert findings["DECL002"].severity == "high"


# --- DECL003: money/contract permission, no declared economic authority ----


def test_decl003_fires_when_no_economic_authority_declared(tmp_path):
    result = _scan(tmp_path, {"a.py": MOVER})
    findings = _decl_findings(result)
    assert "DECL003" in findings


def test_decl003_absent_when_economic_authority_declared(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", MOVER)
    declared = (
        f'[agents."{agent_id}"]\n'
        f'[agents."{agent_id}".economic_authority]\n'
        "max_per_action = {amount = 500, currency = \"USD\"}\n"
    )
    result = _scan(tmp_path, {"a.py": MOVER}, declared)
    assert "DECL003" not in _decl_findings(result)


# --- DECL004: undeclared data class evidenced by a secret finding ----------


def test_decl004_fires_when_authentication_not_declared(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", LEAKY)
    declared = f'[agents."{agent_id}"]\ndata_classes = ["financial"]\n'
    result = _scan(tmp_path, {"a.py": LEAKY}, declared)
    findings = _decl_findings(result)
    assert "DECL004" in findings
    assert findings["DECL004"].rule_id == "DECL004"


def test_decl004_absent_when_authentication_declared(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", LEAKY)
    declared = f'[agents."{agent_id}"]\ndata_classes = ["financial", "authentication"]\n'
    result = _scan(tmp_path, {"a.py": LEAKY}, declared)
    assert "DECL004" not in _decl_findings(result)


# --- DECL005: production_status=production but CTRL004 fires ---------------


def test_decl005_fires_on_production_with_no_observability(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", PROD_NO_OBS)
    declared = f'[agents."{agent_id}"]\nproduction_status = "production"\n'
    result = _scan(tmp_path, {"a.py": PROD_NO_OBS}, declared)
    findings = _decl_findings(result)
    assert "DECL005" in findings


def test_decl005_absent_when_not_production(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", PROD_NO_OBS)
    declared = f'[agents."{agent_id}"]\nproduction_status = "dev"\n'
    result = _scan(tmp_path, {"a.py": PROD_NO_OBS}, declared)
    assert "DECL005" not in _decl_findings(result)


# --- DECL006: scanned agent has no declaration entry ------------------------


def test_decl006_fires_when_agent_undeclared_but_file_exists(tmp_path):
    declared = '[agents."deadbeef000000"]\nname = "someone_else"\n'
    result = _scan(tmp_path, {"a.py": PROD_NO_OBS}, declared)
    findings = _decl_findings(result)
    assert "DECL006" in findings


def test_decl006_absent_without_a_declarations_file(tmp_path):
    result = _scan(tmp_path, {"a.py": PROD_NO_OBS})
    assert "DECL006" not in _decl_findings(result)


# --- DECL007: declared id no longer matches any scanned agent --------------


def test_decl007_fires_as_a_repository_level_finding(tmp_path):
    declared = '[agents."deadbeef000000"]\nname = "ghost"\n'
    result = _scan(tmp_path, {"a.py": "x = 1\n"}, declared)
    decl007 = [f for f in result.findings if f.rule_id == "DECL007"]
    assert len(decl007) == 1
    assert decl007[0].path == "stoa-declared.toml"
    assert decl007[0].declared_ref["path"] == "stoa-declared.toml"


# --- shared invariants -------------------------------------------------------


def test_declared_ref_path_is_repository_relative(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", UNRESTRICTED)
    declared = f'[agents."{agent_id}"]\nautonomy_intent = "recommend_only"\n'
    result = _scan(tmp_path, {"a.py": UNRESTRICTED}, declared)
    findings = _decl_findings(result)
    ref_path = findings["DECL001"].declared_ref["path"]
    assert not ref_path.startswith("/")
    assert ref_path == "stoa-declared.toml"


def test_decl_findings_carry_both_code_and_declared_evidence(tmp_path):
    agent_id = _agent_id(tmp_path, "a.py", UNRESTRICTED)
    declared = f'[agents."{agent_id}"]\nautonomy_intent = "recommend_only"\n'
    result = _scan(tmp_path, {"a.py": UNRESTRICTED}, declared)
    f = _decl_findings(result)["DECL001"]
    assert f.path and f.line  # code evidence
    assert f.declared_ref["path"] and f.declared_ref["key"]  # declared evidence


def test_no_contradictions_without_a_declarations_file(tmp_path):
    result = _scan(tmp_path, {"a.py": UNRESTRICTED})
    assert not any(f.rule_id.startswith("DECL") for f in result.findings)


def test_report_shows_contradictions_section_with_both_evidence_links(tmp_path):
    from stoa.report_html import render_html

    agent_id = _agent_id(tmp_path, "a.py", UNRESTRICTED)
    declared = f'[agents."{agent_id}"]\nautonomy_intent = "recommend_only"\n'
    result = _scan(tmp_path, {"a.py": UNRESTRICTED}, declared)
    html = render_html(result, StoaConfig(no_graph=True))
    assert '<section id="contradictions">' in html
    assert "DECL001" in html
    assert "stoa-declared.toml" in html
    assert "a.py:" in html  # code-side evidence link


def test_report_omits_contradictions_section_without_declarations(tmp_path):
    from stoa.report_html import render_html

    result = _scan(tmp_path, {"a.py": UNRESTRICTED})
    html = render_html(result, StoaConfig(no_graph=True))
    assert '<section id="contradictions">' not in html


def test_gate_findings_treats_decl001_like_a_critical_finding(tmp_path):
    from stoa.scanner import gate_findings

    agent_id = _agent_id(tmp_path, "a.py", UNRESTRICTED)
    declared = f'[agents."{agent_id}"]\nautonomy_intent = "recommend_only"\n'
    (tmp_path / "stoa-declared.toml").write_text(declared, encoding="utf-8")
    config = StoaConfig(fail_on="critical")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True), config)
    tripped = gate_findings(result, config)
    assert any(f.rule_id == "DECL001" for f in tripped)
