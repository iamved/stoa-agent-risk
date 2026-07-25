"""Declared-metadata layer: loader validation, stub generation, scan wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from stoa.config import ConfigError
from stoa.declarations import Declarations, generate_stub
from stoa.models import AgentCandidate, RepositoryInfo, ScanResult


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "stoa-declared.toml"
    path.write_text(content, encoding="utf-8")
    return path


# --- loader: missing / malformed ---------------------------------------------


def test_missing_file_is_empty_not_an_error(tmp_path):
    decl, warnings = Declarations.load(tmp_path / "stoa-declared.toml")
    assert not decl.exists
    assert decl.agents == {}
    assert warnings == []


def test_malformed_toml_raises_config_error(tmp_path):
    path = write(tmp_path, "this is not [valid toml")
    with pytest.raises(ConfigError):
        Declarations.load(path)


def test_agents_table_wrong_type_raises(tmp_path):
    path = write(tmp_path, 'agents = "not a table"\n')
    with pytest.raises(ConfigError):
        Declarations.load(path)


# --- loader: valid ------------------------------------------------------------


def test_valid_declaration_loads_cleanly(tmp_path):
    path = write(tmp_path, '''
version = 1

[business]
industries = ["fintech"]
max_customer_dependency = "high"

[agents."abc123"]
name = "billing_agent"
owner = "jane@acme.com"
purpose = "Reconcile payouts"
users = "internal"
production_status = "production"
autonomy_intent = "human_approved"
data_classes = ["financial", "personal"]

[agents."abc123".economic_authority]
max_per_action = {amount = 500, currency = "USD"}
''')
    decl, warnings = Declarations.load(path)
    assert warnings == []
    assert decl.exists
    agent = decl.agents["abc123"]
    assert agent.owner == "jane@acme.com"
    assert agent.autonomy_intent == "human_approved"
    assert agent.economic_authority.max_per_action == {"amount": 500, "currency": "USD"}
    assert decl.business["max_customer_dependency"] == "high"


# --- loader: semantic warnings, not fatal ------------------------------------


def test_invalid_autonomy_intent_is_a_warning():
    from stoa.declarations import _parse_agent_declaration
    decl, warnings = _parse_agent_declaration(
        Path("stoa-declared.toml"), "abc", {"autonomy_intent": "yolo"}
    )
    assert decl.autonomy_intent is None
    assert any("autonomy_intent" in w for w in warnings)


def test_invalid_max_customer_dependency_is_a_warning(tmp_path):
    path = write(tmp_path, '''
[business]
max_customer_dependency = "extreme"
''')
    decl, warnings = Declarations.load(path)
    assert "max_customer_dependency" not in decl.business
    assert any("max_customer_dependency" in w for w in warnings)


def test_unknown_top_level_key_is_a_warning(tmp_path):
    path = write(tmp_path, 'nonsense = true\n')
    decl, warnings = Declarations.load(path)
    assert any("unknown top-level key" in w for w in warnings)


def test_unknown_agent_key_is_a_warning(tmp_path):
    path = write(tmp_path, '''
[agents."abc123"]
name = "x"
made_up_field = 1
''')
    decl, warnings = Declarations.load(path)
    assert any("made_up_field" in w for w in warnings)


def test_malformed_amount_is_a_warning(tmp_path):
    path = write(tmp_path, '''
[agents."abc123"]
name = "x"

[agents."abc123".economic_authority]
max_per_action = {amount = "five hundred", currency = "USD"}
''')
    decl, warnings = Declarations.load(path)
    assert decl.agents["abc123"].economic_authority is None
    assert any("economic_authority" in w for w in warnings)


def test_amount_missing_currency_is_a_warning(tmp_path):
    path = write(tmp_path, '''
[agents."abc123"]
name = "x"

[agents."abc123".economic_authority]
max_per_action = {amount = 500}
''')
    decl, warnings = Declarations.load(path)
    assert decl.agents["abc123"].economic_authority is None
    assert any("economic_authority" in w for w in warnings)


def test_unknown_data_class_is_a_warning(tmp_path):
    path = write(tmp_path, '''
[agents."abc123"]
name = "x"
data_classes = ["financial", "made_up"]
''')
    decl, warnings = Declarations.load(path)
    assert decl.agents["abc123"].data_classes == ["financial"]
    assert any("data_classes" in w for w in warnings)


# --- unknown agent id cross-check (DECL007 precursor) ------------------------


def test_unknown_agent_ids_against_known_set(tmp_path):
    path = write(tmp_path, '''
[agents."abc123"]
name = "x"
[agents."def456"]
name = "y"
''')
    decl, _ = Declarations.load(path)
    assert decl.unknown_agent_ids({"abc123"}) == ["def456"]
    assert decl.unknown_agent_ids({"abc123", "def456"}) == []


# --- stub generation ----------------------------------------------------------


def test_generate_stub_includes_real_agent_ids_commented_out():
    stub = generate_stub([
        {"id": "abc123", "name": "billing_agent", "path": "agents/billing.py"},
        {"id": "def456", "name": "support_bot", "path": "agents/support.py"},
    ])
    assert 'version = 1' in stub
    assert '[agents."abc123"]' in stub
    assert '[agents."def456"]' in stub
    assert 'name = "billing_agent"' in stub
    assert '# owner = ""' in stub  # commented out — nothing pre-filled


def test_generate_stub_empty_agents_still_produces_valid_shell():
    stub = generate_stub([])
    assert "version = 1" in stub
    assert "# [business]" in stub


# --- scan wiring: opt-in-by-presence, --strict escalation via ScanResult -----


def test_no_declared_file_leaves_result_fields_none(tmp_path, monkeypatch):
    from stoa.scanner import ScanOptions, run_scan
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert result.business is None
    assert result.governance is None
    assert result.evidence is None
    assert result.declaration_warnings == []
    assert all(a.declared is None for a in result.agents)


def test_declared_agent_attaches_to_matching_scanned_agent(tmp_path):
    from stoa.scanner import ScanOptions, run_scan
    (tmp_path / "a.py").write_text(
        "from langchain.agents import AgentExecutor\n"
        "executor = AgentExecutor(agent=a, tools=[t])\n",
        encoding="utf-8",
    )
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert result.agents, "expected an agent candidate"
    agent_id = result.agents[0].id
    (tmp_path / "stoa-declared.toml").write_text(
        f'[agents."{agent_id}"]\nowner = "me@x.com"\n', encoding="utf-8"
    )
    result2 = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert result2.agents[0].declared["owner"] == "me@x.com"


def test_stale_declared_agent_id_produces_a_warning(tmp_path):
    from stoa.scanner import ScanOptions, run_scan
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "stoa-declared.toml").write_text(
        '[agents."doesnotexist"]\nname = "ghost"\n', encoding="utf-8"
    )
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    assert any("doesnotexist" in w for w in result.declaration_warnings)
    assert any("doesnotexist" in w for w in result.warnings)
