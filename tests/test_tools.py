"""Tool inventory (0.8.0): tools as first-class objects, attributed across files.

The Meridian Pay fixture is the target: one account-actions agent per stack
binding the same seven tools, with issue_refund retried and un-keyed. The
inventory must name the tools, carry their reach onto the agent, flip
autonomy, fire the declaration contradiction in all three stacks, and raise
AI008 on the retried money tool — while agents without tools are untouched.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from stoa.config import load_config
from stoa.imports import build_import_graph
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan
from stoa.tools import bind_agent_tools, collect_tools

REPO_ROOT = Path(__file__).resolve().parents[1]
MERIDIAN = REPO_ROOT / "examples/meridian-pay"
# The AWS twin of account-actions the fixtures use: the same agent, defined a second time as a Bedrock agent.
TWIN = REPO_ROOT / "ui/fixtures/twins/account_actions.tf"


def _two_stacks(tmp_path: Path) -> Path:
    work = tmp_path / "two-stacks"
    shutil.copytree(MERIDIAN, work)
    shutil.copy(TWIN, work / "aws" / "account_actions.tf")
    return work


def _scan(root: Path):
    config = load_config(root)
    return run_scan(ScanOptions(root=root, no_git=True), config), config


def _agent(result, path_suffix: str):
    return next(a for a in result.agents if a.path.endswith(path_suffix))


def _rules(agent) -> set[str]:
    return {f.rule_id for f in agent.findings}


# --- definition pass ---------------------------------------------------------------


def test_python_tool_idioms_are_collected():
    files = {"t.py": '''
from langchain_core.tools import tool, StructuredTool
from tenacity import retry, stop_after_attempt
import requests

@retry(stop=stop_after_attempt(3))
def _post(path, body):
    return requests.post("https://api.example.com" + path, json=body, timeout=5).json()

@tool
def issue_refund(account_id: str, amount: float = 0.0) -> str:
    """Refund."""
    if amount > 500:
        raise ValueError("cap")
    return _post("/refunds", {"a": account_id, "amount": amount, "idempotency_key": account_id})["status"]

@mcp.tool()
async def lookup(order_id: str) -> dict:
    return db.query("select * from orders where id = %s", (order_id,))

def plain(x): return x
def wrapped(q: str) -> str:
    return q
search = StructuredTool.from_function(func=wrapped, name="search")

TOOLS = [{"type": "function", "function": {"name": "render", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}}}}]
def dispatch(name, args):
    if name == "render":
        subprocess.run(args["cmd"], shell=True)
'''}
    tools = {t.name: t for t in collect_tools(files)["t.py"]}
    assert set(tools) == {"issue_refund", "lookup", "wrapped", "render"}
    r = tools["issue_refund"]
    assert [p["name"] for p in r.params] == ["account_id", "amount"] and r.params[1]["type"] == "float"
    assert r.money_action and "payment_access" in r.capabilities
    assert r.guards == ["amount > 500"]
    assert r.retry and "via _post" in r.retry                 # retry found one hop into the helper
    assert r.idempotency_key is True
    assert tools["lookup"].kind == "mcp_tool" and "database_read" in tools["lookup"].capabilities
    assert tools["wrapped"].kind == "langchain_tool"
    assert tools["render"].kind == "json_schema" and [p["name"] for p in tools["render"].params] == ["prompt"]
    assert "shell_execution" in tools["render"].capabilities   # implementation found through the dispatcher


def test_ts_and_uc_tool_idioms_are_collected():
    files = {
        "a.ts": '''
import { tool } from "ai";
export const sendEmail = tool({ description: "send", parameters: z.object({ to: z.string(), body: z.string() }),
  execute: async ({ to, body }) => { await sgMail.send({ to, text: body }); } });
server.tool("refund_order", { orderId: z.string() }, async ({ orderId }) => { await fetch(url, { method: "POST" }); });
''',
        "b.py": 'tools = UCFunctionToolkit(function_names=["prod.tools.issue_refund", "prod.tools.lookup_order"]).tools\n',
    }
    idx = collect_tools(files)
    ts = {t.name: t for t in idx["a.ts"]}
    assert [p["name"] for p in ts["sendEmail"].params] == ["to", "body"]
    assert ts["refund_order"].kind == "mcp_tool" and ts["refund_order"].money_action
    uc = {t.name: t for t in idx["b.py"]}
    assert uc["issue_refund"].kind == "uc_function" and uc["issue_refund"].resolved is False
    assert "payment_access" in uc["issue_refund"].capabilities and uc["lookup_order"].capabilities == []


# --- binding pass -----------------------------------------------------------------------


def test_binding_resolves_names_through_the_import_graph():
    files = {
        "tools/money.py": '@tool\ndef issue_refund(a: str, amount: float) -> str:\n    return requests.post("https://x/refund", json={}).text\n',
        "tools/misc.py": '@tool\ndef weather(city: str) -> str:\n    return "sunny"\n',
        "agents/a.py": 'from tools.money import issue_refund\nfrom tools.misc import weather\nTOOLS = [issue_refund, weather]\nmodel = ChatOpenAI().bind_tools(TOOLS)\n',
        "agents/b.py": 'from tools.misc import weather\nagent = create_react_agent(llm, [weather])\n',
    }
    idx = collect_tools(files); g = build_import_graph(files)
    a = [t.name for t in bind_agent_tools(files["agents/a.py"], "agents/a.py", idx, g)]
    b = [t.name for t in bind_agent_tools(files["agents/b.py"], "agents/b.py", idx, g)]
    assert set(a) == {"issue_refund", "weather"} and b == ["weather"]   # list variable expanded; per-agent, not per-repo


# --- the fixture, three stacks -----------------------------------------------------------------


def test_account_actions_agent_names_its_tools_in_both_stacks_and_the_chatbot_binds_them_too(tmp_path):
    result, _ = _scan(_two_stacks(tmp_path))
    code = _agent(result, "code/agents/account_actions_agent.py")
    aws = next(a for a in result.agents if a.symbol == "aws_bedrockagent_agent.account_actions")
    chatbot = _agent(result, "code/agents/support_agent.py")
    expected = {"issue_refund", "waive_fee", "update_contact_info", "reissue_card", "place_travel_notice", "change_payout_account"}
    for agent in (code, aws, chatbot):
        assert {t["name"] for t in agent.tools} == expected, agent.path
    assert {t["kind"] for t in code.tools} == {"langchain_tool"}
    assert {t["kind"] for t in aws.tools} == {"bedrock_action_group"}
    assert {t["kind"] for t in chatbot.tools} == {"langchain_tool"}
    # reach travels from the tool to the agent
    assert "payment_access" in code.capabilities and "payment_access" in chatbot.capabilities
    assert "database_write" in aws.capabilities                       # from the action group Lambda's role
    assert all("database_write" in t["capabilities"] for t in aws.tools)


def test_declaration_contradiction_fires_in_both_stacks_and_on_the_chatbot(tmp_path):
    result, _ = _scan(MERIDIAN)
    for suffix in ("code/agents/account_actions_agent.py", "code/agents/support_agent.py"):
        agent = _agent(result, suffix)
        assert agent.autonomy_level["level"] == "unrestricted_autonomous", suffix
        assert "DECL001" in _rules(agent), suffix
    front = _agent(result, "code/agents/front_agent.py")
    assert front.autonomy_level["level"] == "recommend_only"          # verify_identity is not a side effect
    # The AWS twin, declared with the same human_approved intent, contradicts it the same way.
    work = _two_stacks(tmp_path)
    with open(work / "stoa-declared.toml", "a") as handle:
        handle.write('\n[agents."ddb08fa73da1"]\nname = "meridian-account-actions"\nsame_as = ["b8f0111742fc"]\nowner = "x@meridian.example"\npurpose = "twin"\nproduction_status = "production"\nautonomy_intent = "human_approved"\n')
    result, _ = _scan(work)
    aws = next(a for a in result.agents if a.symbol == "aws_bedrockagent_agent.account_actions")
    assert aws.autonomy_level["level"] == "unrestricted_autonomous" and "DECL001" in _rules(aws)


def test_ai008_fires_on_the_retried_unkeyed_refund_only():
    result, _ = _scan(MERIDIAN)
    code = _agent(result, "code/agents/account_actions_agent.py")
    ai8 = [f for f in code.findings if f.rule_id == "AI008"]
    assert len(ai8) == 1 and ai8[0].path == "code/tools/account_tools.py" and ai8[0].severity == "high"
    assert "issue_refund" in ai8[0].message and "via _post_refund" in ai8[0].message
    assert ai8[0].dimensions and set(ai8[0].dimensions) >= {"unreviewed-high-impact-action", "control-coverage-gap"}


def test_ai008_is_silent_with_an_idempotency_key_or_without_retry(tmp_path):
    work = tmp_path / "m"; shutil.copytree(MERIDIAN, work)
    p = work / "code/tools/account_tools.py"
    s = p.read_text().replace('"dispute_id": dispute_id})', '"dispute_id": dispute_id}, headers={"Idempotency-Key": dispute_id})')
    p.write_text(s)
    result, _ = _scan(work)
    assert "AI008" not in _rules(_agent(result, "code/agents/account_actions_agent.py"))
    p.write_text(MERIDIAN.joinpath("code/tools/account_tools.py").read_text().replace("@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=8))\n", ""))
    result, _ = _scan(work)
    assert "AI008" not in _rules(_agent(result, "code/agents/account_actions_agent.py"))


# --- registry, regression -------------------------------------------------------------------------


def test_registry_emits_tools_only_when_present():
    result, config = _scan(MERIDIAN)
    doc = build_document(result, config)
    assert doc["schema_version"] == "1.8"
    with_tools = [a for a in doc["agents"] if "tools" in a]
    without = [a for a in doc["agents"] if "tools" not in a]
    assert with_tools and without                                     # knowledge/escalation agents bind none
    t = next(t for a in with_tools for t in a["tools"] if t["name"] == "issue_refund" and t["kind"] == "langchain_tool")
    assert set(t) >= {"name", "path", "line", "kind", "params", "capabilities", "high_impact", "money_action",
                      "guards", "retry", "idempotency_key", "resolved"}
    json.dumps(doc)


def test_other_examples_agent_counts_unchanged():
    for ex, count in (("tidewater", 4), ("kestrel", 2), ("marlowe", 3), ("meridian-ops", 12), ("sparkwing", 8),
                      ("support-desk", 9), ("threshold-voice", 11)):
        result, _ = _scan(REPO_ROOT / "examples" / ex)
        assert len(result.agents) == count, ex


def test_a_tool_finding_shared_by_two_agents_is_one_finding():
    """Two code agents bind issue_refund; AI008 on it is one finding, on both agents, counted once."""
    result, config = _scan(MERIDIAN)
    ai8 = [f for f in result.findings if f.rule_id == "AI008"]
    assert len(ai8) == 1
    doc = build_document(result, config)
    carriers = [a["path"] for a in doc["agents"] if any(f["fingerprint"] == ai8[0].fingerprint for f in a["findings"])]
    assert sorted(carriers) == ["code/agents/account_actions_agent.py", "code/agents/support_agent.py"]
    assert sum(1 for f in doc["repository_findings"] if f["rule_id"] == "AI008") == 1
    counted = sum(doc["summary"]["findings"].values())
    distinct = len({f["fingerprint"] for a in doc["agents"] for f in a["findings"]} | {f["fingerprint"] for f in doc["repository_findings"]})
    assert counted == distinct
