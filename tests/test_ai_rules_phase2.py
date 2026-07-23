"""Phase 2 AI rules: AI005 (supply chain), AI003/AI007/CTRL004 (correlation)."""

from __future__ import annotations

from stoa.ai_rules import detect_ai005, detect_ai_correlations
from stoa.config import StoaConfig


def ai005(content, path="src/m.py", testlike=False, config=None):
    return detect_ai005(content, path, testlike, config or StoaConfig())


def corr(content, caps, symbol="agent", path="src/a.py", config=None):
    return detect_ai_correlations(content, path, symbol, caps, 1, config or StoaConfig())


def by(findings, variant=None, rule=None):
    out = findings
    if variant:
        out = [f for f in out if f.variant == variant]
    if rule:
        out = [f for f in out if f.rule_id == rule]
    return out


# --- AI005 -----------------------------------------------------------------

def test_ai005_trust_remote_code_high():
    fs = by(ai005('m = AutoModel.from_pretrained("org/x", trust_remote_code=True)'),
            variant="trust-remote-code")
    assert len(fs) == 1
    assert fs[0].severity == "high" and fs[0].confidence == "high"
    assert fs[0].canonical_name == "STOA-LLM05-UNPINNED-MODEL"
    assert fs[0].owasp == {"llm_top10_v1_1": "LLM05", "llm_top10_2025": "LLM03"}


def test_ai005_unpinned_artifact_without_revision():
    fs = by(ai005('m = AutoModel.from_pretrained("someorg/reranker")'), variant="unpinned-artifact")
    assert len(fs) == 1 and fs[0].severity == "medium"


def test_ai005_pinned_revision_not_flagged():
    assert ai005('m = AutoModel.from_pretrained("someorg/reranker", revision="a1b2c3d")') == []


def test_ai005_floating_alias_low():
    fs = by(ai005('llm = ChatOpenAI(model="gpt-4o")'), variant="floating-alias")
    assert len(fs) == 1 and fs[0].severity == "low"


def test_ai005_dated_snapshot_not_flagged():
    assert by(ai005('llm = ChatOpenAI(model="gpt-4o-2024-08-06")'), variant="floating-alias") == []


def test_ai005_latest_alias_flagged():
    assert by(ai005('model = "claude-3-5-sonnet-latest"'), variant="floating-alias")


def test_ai005_floating_alias_skipped_in_tests():
    assert by(ai005('model = "gpt-4o"', testlike=True), variant="floating-alias") == []


def test_ai005_insecure_endpoint_supersedes_net001():
    fs = by(ai005('llm = ChatOpenAI(base_url="http://gpu-gw.mlplatform.io/v1")'),
            variant="insecure-endpoint")
    assert len(fs) == 1
    assert fs[0].supersedes == ["NET001"]
    assert "insecure_endpoint" in fs[0].evidence_tags


def test_ai005_localhost_endpoint_not_flagged():
    assert by(ai005('llm = ChatOpenAI(base_url="http://localhost:11434/v1")'),
              variant="insecure-endpoint") == []


def test_ai005_disabled_by_config():
    cfg = StoaConfig()
    cfg.enabled_rules["AI005"] = False
    assert ai005('m = AutoModel.from_pretrained("x", trust_remote_code=True)', config=cfg) == []


# --- AI003 -----------------------------------------------------------------

AGENT_TOOL_PAYMENT = """
from langchain.agents import create_react_agent
@tool
def issue_refund(order_id: str, amount: float) -> str:
    stripe.Refund.create(payment_intent=order_id, amount=int(amount * 100))
    return "refunded"
agent = create_react_agent(model, tools=[issue_refund])
"""


def test_ai003_fires_without_approval():
    fs = by(corr(AGENT_TOOL_PAYMENT, ["payment_access"]), rule="AI003")
    assert len(fs) == 1
    assert fs[0].severity == "info"
    assert "One review prompt per candidate" in fs[0].message


def test_ai003_suppressed_by_interrupt():
    content = AGENT_TOOL_PAYMENT.replace(
        'stripe.Refund.create', 'decision = interrupt({})\n    stripe.Refund.create'
    )
    assert by(corr(content, ["payment_access"]), rule="AI003") == []


def test_ai003_not_fired_without_high_impact_capability():
    assert by(corr(AGENT_TOOL_PAYMENT, ["web_search"]), rule="AI003") == []


def test_ai003_one_per_candidate():
    # Two high-impact caps -> still exactly one AI003 finding, listing both.
    fs = by(corr(AGENT_TOOL_PAYMENT, ["payment_access", "database_write"]), rule="AI003")
    assert len(fs) == 1
    assert "payment-access" in fs[0].message and "database-write" in fs[0].message


# --- AI007 -----------------------------------------------------------------

def test_ai007_fires_on_default_sampling():
    content = 'agent = create_react_agent(m, tools=[t])\nr = client.messages.create(messages=msgs, max_tokens=200)\n'
    fs = by(corr(content, ["payment_access"]), rule="AI007")
    assert len(fs) == 1 and fs[0].severity == "info"
    assert "proxy signal only" in fs[0].message


def test_ai007_not_fired_with_temperature_zero():
    content = 'r = client.messages.create(messages=msgs, temperature=0)\n'
    assert by(corr(content, ["payment_access"]), rule="AI007") == []


def test_ai007_not_fired_without_high_impact():
    content = 'r = client.messages.create(messages=msgs)\n'
    assert by(corr(content, ["web_search"]), rule="AI007") == []


# --- CTRL004 ---------------------------------------------------------------

def test_ctrl004_fires_without_observability():
    content = '@tool\ndef apply(order_id):\n    db.orders.update(order_id)\n    return "ok"\n'
    fs = by(corr(content, ["database_write"]), rule="CTRL004")
    assert len(fs) == 1 and fs[0].severity == "info"


def test_ctrl004_suppressed_by_logger():
    content = 'logger = structlog.get_logger()\n@tool\ndef apply(o):\n    logger.info("x")\n    db.orders.update(o)\n'
    assert by(corr(content, ["database_write"]), rule="CTRL004") == []


def test_ctrl004_print_is_adhoc_not_observability():
    content = '@tool\ndef apply(o):\n    print("applying")\n    db.orders.update(o)\n'
    fs = by(corr(content, ["database_write"]), rule="CTRL004")
    assert len(fs) == 1
    assert "ad_hoc_output_observed" in fs[0].evidence_tags


def test_correlation_rules_need_tool_binding():
    # No tool binding -> no AI003 / CTRL004 (AI007 keyed on model call instead).
    content = 'db.orders.update(o)\nclient.messages.create(messages=m)\n'
    fs = corr(content, ["database_write"])
    assert by(fs, rule="AI003") == []
    assert by(fs, rule="CTRL004") == []


# --- end-to-end through the scanner + serializer ---------------------------

def test_phase2_rules_flow_through_scanner(tmp_path):
    from pathlib import Path
    from stoa.report_json import build_document
    from stoa.scanner import ScanOptions, gate_findings, run_scan

    (tmp_path / "agent.py").write_text(
        "from langchain.agents import create_react_agent\n"
        "from langchain_openai import ChatOpenAI\n"
        "llm = ChatOpenAI(model='gpt-4o')\n"
        "@tool\n"
        "def issue_refund(order_id):\n"
        "    stripe.Refund.create(payment_intent=order_id, amount=100)\n"
        "    return 'ok'\n"
        "agent = create_react_agent(llm, tools=[issue_refund])\n"
        "r = agent.invoke({'input': 'x'})\n",
        encoding="utf-8",
    )
    result = run_scan(ScanOptions(root=Path(tmp_path), no_git=True))
    rule_ids = {f.rule_id for f in result.findings}
    assert {"AI005", "AI003", "CTRL004"}.issubset(rule_ids)

    # Phase 2 rules are report-only: none may gate, even at high confidence.
    assert gate_findings(result, __import__("stoa.config", fromlist=["StoaConfig"]).StoaConfig()) == []

    doc = build_document(result, StoaConfig())
    ai = [f for a in doc["agents"] for f in a["findings"] if f["rule_id"].startswith("AI")]
    assert ai
    sample = next(f for f in ai if f["rule_id"] == "AI005")
    assert sample["canonical_name"] == "STOA-LLM05-UNPINNED-MODEL"
    assert "owasp" in sample and "message" in sample and "id" in sample


def test_ai005_endpoint_snippet_is_redacted(tmp_path):
    # A token accidentally embedded in a base_url must still be redacted.
    from pathlib import Path
    from stoa.scanner import ScanOptions, run_scan
    from conftest import fake_openai_key

    key = fake_openai_key()
    (tmp_path / "c.py").write_text(
        f'client = OpenAI(base_url="http://gw.mlplatform.io/{key}/v1")\n', encoding="utf-8"
    )
    result = run_scan(ScanOptions(root=Path(tmp_path), no_git=True))
    for f in result.findings:
        assert key not in f.snippet
        assert key not in (f.message or "")
