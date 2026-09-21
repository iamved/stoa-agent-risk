"""Agent identity resolution: which scanned records are the same agent.

A false merge hides an agent from the person reading the dashboard, so most
of these tests are about what must NOT be joined."""

from __future__ import annotations

import json
from pathlib import Path

from stoa.dashboard.identity import normalize, resolve_agents

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "ui" / "fixtures"


def _code(agent_id: str, path: str, symbol: str = "graph", **extra) -> dict:
    stem = Path(path).stem
    return {"id": agent_id, "name": symbol, "display_name": f"{stem}·{symbol}", "symbol": symbol,
            "path": path, "source": "code", **extra}


def _infra(agent_id: str, name: str, platform: str = "bedrock", **extra) -> dict:
    return {"id": agent_id, "name": name, "display_name": name, "path": "infra/main.tf",
            "symbol": f"aws_bedrockagent_agent.{name.replace('-', '_')}", "source": "iac",
            "platform": platform, **extra}


def _registry(*agents: dict, repo: str = "meridian-pay") -> dict:
    return {"repository": {"name": repo}, "agents": list(agents)}


def _groups(registry: dict) -> list[set[str]]:
    return [{r["agent_id"] for r in u["records"]} for u in resolve_agents(registry)]


def test_normalize_follows_the_documented_rules():
    assert normalize("meridian-account-actions", "meridian") == "account_actions"
    assert normalize("account_actions_agent", "meridian") == "account_actions"
    assert normalize("Account-Actions-Agent") == "account_actions"
    assert normalize("front_agent·graph".split("·")[0]) == "front"
    # The project word is only a prefix, and a one-word name keeps its word.
    assert normalize("meridian", "meridian") == "meridian"
    assert normalize("agent") == "agent"


def test_name_match_joins_a_code_record_with_its_infrastructure_record():
    registry = _registry(_code("c1", "code/agents/account_actions_agent.py"),
                         _infra("i1", "meridian-account-actions"))
    [agent] = resolve_agents(registry)
    assert {r["agent_id"] for r in agent["records"]} == {"c1", "i1"}
    assert agent["linked_by"] == "name"
    assert [r["label"] for r in agent["records"]] == ["Defined in code", "Deployed on AWS"]
    assert agent["records"][0]["path"] == "code/agents/account_actions_agent.py"


def test_explicit_link_joins_what_names_cannot():
    code = _code("c1", "databricks/agents/support_agent.py", "agent",
                 declared={"name": "meridian-support", "same_as": ["i1", "i2", "gone"]})
    registry = _registry(code, _infra("i1", "meridian-support-chat", "databricks"),
                         _infra("i2", "meridian-support-ivr", "databricks"))
    [agent] = resolve_agents(registry)
    assert {r["agent_id"] for r in agent["records"]} == {"c1", "i1", "i2"}
    assert agent["linked_by"] == "declared"
    assert agent["name"] == "meridian-support"
    # Without the declaration the three stay apart: support != support_chat.
    code.pop("declared")
    assert _groups(registry) == [{"i1"}, {"i2"}, {"c1"}]


def test_an_unmatched_record_stays_its_own_agent():
    registry = _registry(_code("c1", "code/agents/front_agent.py"), _infra("i1", "meridian-billing"))
    agents = resolve_agents(registry)
    assert sorted(map(sorted, _groups(registry))) == [["c1"], ["i1"]]
    assert all(a["linked_by"] is None for a in agents)


def test_names_never_join_two_records_of_the_same_kind():
    # Two services each with a front agent are two agents.
    assert len(_groups(_registry(_code("c1", "svc_a/front_agent.py"), _code("c2", "svc_b/front_agent.py")))) == 2
    assert len(_groups(_registry(_infra("i1", "meridian-front"), _infra("i2", "front")))) == 2


def test_an_ambiguous_name_joins_nothing():
    registry = _registry(_code("c1", "svc_a/front_agent.py"), _code("c2", "svc_b/front_agent.py"),
                         _infra("i1", "meridian-front"))
    assert len(_groups(registry)) == 3


def test_generic_names_identify_nothing():
    registry = _registry(_code("c1", "app/agent.py", "agent"), _infra("i1", "agent"),
                         _code("c2", "app/main.py", "graph"), _infra("i2", "main"))
    assert len(_groups(registry)) == 4


def test_resolution_is_deterministic_and_loses_no_record():
    registry = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())["registry"]
    first = resolve_agents(registry)
    assert first == resolve_agents({**registry, "agents": list(reversed(registry["agents"]))})
    ids = [r["agent_id"] for u in first for r in u["records"]]
    assert sorted(ids) == sorted(a["id"] for a in registry["agents"])
    assert len(ids) == len(set(ids))


def test_the_demo_is_five_agents_and_a_first_scan_is_seven():
    demo = json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())
    assert len(demo["unique_agents"]) == 5 and len(demo["registry"]["agents"]) == 11
    support = next(u for u in demo["unique_agents"] if u["linked_by"] == "declared")
    assert [r["kind"] for r in support["records"]] == ["code", "infrastructure", "infrastructure"]
    # No declaration file, so nothing says the two endpoints serve one agent.
    first_run = json.loads((FIXTURES / "first-run.envelope.json").read_text())
    assert len(first_run["unique_agents"]) == 7
    assert json.loads((FIXTURES / "no-agents.envelope.json").read_text())["unique_agents"] == []


def test_same_as_feeds_no_rule_and_no_score():
    """The link is a label for the dashboard. Declaring it must not move a finding or a score."""
    from stoa.config import load_config
    from stoa.report_json import build_document
    from stoa.scanner import ScanOptions, run_scan
    import shutil, tempfile

    def scan(root: Path) -> dict:
        config = load_config(root)
        return build_document(run_scan(ScanOptions(root=root, no_git=True), config), config)

    with tempfile.TemporaryDirectory() as tmp:
        linked = Path(tmp) / "linked"
        shutil.copytree(REPO_ROOT / "examples" / "meridian-pay", linked)
        unlinked = Path(tmp) / "unlinked"
        shutil.copytree(linked, unlinked)
        declared = unlinked / "stoa-declared.toml"
        text = declared.read_text()
        assert "same_as" in text
        declared.write_text("\n".join(line for line in text.splitlines() if not line.startswith("same_as")))
        a, b = scan(linked), scan(unlinked)
    assert a["summary"] == b["summary"] and a["dimension_summary"] == b["dimension_summary"]
    strip = lambda doc: [{k: v for k, v in agent.items() if k != "declared"} for agent in doc["agents"]]
    assert strip(a) == strip(b)


def test_same_as_must_be_a_list_of_ids(tmp_path):
    from stoa.declarations import Declarations

    path = tmp_path / "stoa-declared.toml"
    path.write_text('[agents."abc"]\nname = "x"\nsame_as = "def"\n')
    declarations, warnings = Declarations.load(path)
    assert any("same_as" in w for w in warnings)
    assert declarations.agents["abc"].same_as == []
