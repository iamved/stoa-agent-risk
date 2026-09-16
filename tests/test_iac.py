"""IaC collector (Step 2): agents configured in Terraform, not written in code.

The Tidewater fixture is the target: two Databricks Model Serving endpoints
in infra/main.tf — one well-controlled (ai_gateway + a narrow SELECT grant),
one not (no gateway, catalog-wide ALL_PRIVILEGES + MODIFY). The scanner must
find both, credit the stated controls, read reach from grants, and leave every
existing example byte-for-byte unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import fake_openai_key
from stoa.config import load_config
from stoa.iac import detect_iac_agents, extract_tf_blocks
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
TIDEWATER = REPO_ROOT / "examples/tidewater"


def _scan(root: Path):
    config = load_config(root)
    return run_scan(ScanOptions(root=root, no_git=True), config), config


# --- the zero-dependency HCL extractor ----------------------------------------


def test_extractor_handles_nested_repeated_blocks_lists_refs_and_templates():
    hcl = '''
resource "databricks_model_serving" "x" {
  name = "ep"                      # comment
  config {
    served_entities {
      entity_name    = "prod.agents.x"
      entity_version = "3"
      environment_vars = { OPENAI_API_KEY = "{{secrets/agents/key}}" }
    }
  }
  ai_gateway {
    rate_limits { calls = 100  renewal_period = "minute" }
    inference_table_config { enabled = true }
  }
}

resource "databricks_grants" "g" {
  table = "prod.t"
  grant { principal = databricks_service_principal.x_sp.application_id  privileges = ["SELECT", "MODIFY"] }
  grant { principal = "someone@example.com"  privileges = ["SELECT"] }
  policy = jsonencode({ a = 1 })
}
'''
    blocks = {(b.type, b.name): b for b in extract_tf_blocks(hcl)}
    ep = blocks[("databricks_model_serving", "x")]
    assert ep.line == 2 and ep.attrs["name"] == "ep"
    se = ep.attrs["config"]["served_entities"]
    assert se["entity_name"] == "prod.agents.x" and se["entity_version"] == "3"
    assert se["environment_vars"]["OPENAI_API_KEY"] == "{{secrets/agents/key}}"   # braces inside strings survive
    gw = ep.attrs["ai_gateway"]
    assert gw["rate_limits"]["calls"] == 100 and gw["inference_table_config"]["enabled"] is True
    g = blocks[("databricks_grants", "g")]
    assert isinstance(g.attrs["grant"], list) and len(g.attrs["grant"]) == 2      # repeated blocks -> list
    assert g.attrs["grant"][0]["privileges"] == ["SELECT", "MODIFY"]
    assert g.attrs["grant"][0]["principal"] == "databricks_service_principal.x_sp.application_id"  # ref kept raw
    assert g.attrs["policy"].startswith("jsonencode(")                            # function call kept raw


def test_unresolved_values_are_not_guessed():
    hcl = '''
resource "databricks_model_serving" "y" {
  name = var.endpoint_name
  config { served_entities { entity_name = var.model } }
}
resource "databricks_grants" "g" {
  table = var.table
  grant { principal = var.principal  privileges = ["SELECT"] }
}
'''
    (det,) = detect_iac_agents(hcl, "infra/main.tf")
    assert det.symbol == "databricks_model_serving.y" and det.name == "y"   # var.* name -> resource name
    assert det.capabilities == []                          # a var.* principal is never attributed
    assert det.controls == set()


# --- the Tidewater fixture: the collector's acceptance criteria ------------------


def test_fixture_finds_both_iac_agents_alongside_the_code_agents():
    result, _ = _scan(TIDEWATER)
    iac = [a for a in result.agents if a.source == "iac"]
    code = [a for a in result.agents if a.source == "code"]
    assert len(code) == 2 and len(iac) == 2
    assert {a.path for a in iac} == {"infra/main.tf"}
    assert {a.symbol for a in iac} == {
        "databricks_model_serving.support_agent", "databricks_model_serving.refund_agent"}
    assert all(a.frameworks == [] and "databricks" in a.integrations for a in iac)
    for a in iac:
        assert a.language == "terraform" and a.confidence == "high"
        assert a.platform == "databricks" and a.discovery_tier == "recognized"
        assert any(e.rule_id == "AGENT_IAC_SERVING_ENDPOINT" for e in a.evidence)
        assert a.evidence[0].line > 0                      # evidence at the resource block's line
    assert result.files_scanned == 3                       # 2 .py + main.tf (databricks.yml is a follow-up)


def _iac_agent(result, name):
    return next(a for a in result.agents if a.source == "iac" and a.symbol.endswith("." + name))


def test_support_endpoint_gets_its_stated_controls_credited():
    result, _ = _scan(TIDEWATER)
    a = _iac_agent(result, "support_agent")
    assert a.capabilities == ["database_read"]             # one narrow SELECT grant
    assert a.providers == []                                # no third-party model egress configured
    gap = next(d for d in a.dimension_assessment["dimensions"] if d["id"] == "control-coverage-gap")
    assert {"validation", "rate_limit", "observability"} <= set(gap["controls_observed"])
    kinds = {e.rule_id for e in a.evidence}
    assert {"IAC_CONTROL_GUARDRAIL", "IAC_CONTROL_RATE_LIMIT", "IAC_CONTROL_OBSERVABILITY", "IAC_GRANT"} <= kinds


def test_refund_endpoint_shows_broad_reach_egress_and_no_controls():
    result, _ = _scan(TIDEWATER)
    a = _iac_agent(result, "refund_agent")
    assert {"database_read", "database_write"} <= set(a.capabilities)
    assert a.providers == ["openai"]                        # OPENAI_API_KEY in environment_vars
    assert not any(e.rule_id.startswith("IAC_CONTROL_") for e in a.evidence)
    grants = [e.description for e in a.evidence if e.rule_id == "IAC_GRANT"]
    assert any("catalog-wide" in d for d in grants)        # ALL_PRIVILEGES on the prod catalog
    assert any("MODIFY" in d and "prod.payments.refunds" in d for d in grants)
    gap = next(d for d in a.dimension_assessment["dimensions"] if d["id"] == "control-coverage-gap")
    assert not ({"validation", "rate_limit", "observability"} & set(gap["controls_observed"]))


def test_contrast_shows_in_dimension_exposure():
    """The whole point of two agents: the IaC layer alone separates them."""
    result, _ = _scan(TIDEWATER)
    def exposure(symbol, dim):
        a = _iac_agent(result, symbol)
        return next(d for d in a.dimension_assessment["dimensions"] if d["id"] == dim)["exposure"]
    order = {"none-observed": 0, "low": 1, "moderate": 2, "elevated": 3}
    assert order[exposure("refund_agent", "control-coverage-gap")] >= order[exposure("support_agent", "control-coverage-gap")]
    assert order[exposure("refund_agent", "mandate-overreach")] >= order[exposure("support_agent", "mandate-overreach")]


# --- registry: additive, dormant for code-only scans ------------------------------


def test_registry_emits_provenance_only_for_iac_agents():
    result, config = _scan(TIDEWATER)
    doc = build_document(result, config)
    assert doc["schema_version"] == "1.7"
    by_source = {}
    for a in doc["agents"]:
        by_source.setdefault(a.get("source", "code"), []).append(a)
    assert len(by_source["iac"]) == 2 and len(by_source["code"]) == 2
    for a in by_source["iac"]:
        assert a["source"] == "iac" and a["discovery_tier"] == "recognized" and a["platform"] == "databricks"
    for a in by_source["code"]:
        assert "source" not in a and "discovery_tier" not in a and "platform" not in a


def test_existing_examples_are_unchanged():
    expected = {"meridian-ops": 12, "sparkwing": 8, "support-desk": 9, "threshold-voice": 11}
    for ex, n in expected.items():
        result, config = _scan(REPO_ROOT / "examples" / ex)
        assert len(result.agents) == n, ex
        doc = build_document(result, config)
        assert all("source" not in a for a in doc["agents"]), ex     # dormant: no IaC there


def test_deterministic():
    r1, c1 = _scan(TIDEWATER)
    r2, c2 = _scan(TIDEWATER)
    assert json.dumps(build_document(r1, c1), sort_keys=True) == json.dumps(build_document(r2, c2), sort_keys=True)



# --- secrets in IaC are scanned and redacted like code ------------------------------


def test_literal_secret_in_terraform_is_found_and_redacted(tmp_path):
    key = fake_openai_key()
    hcl = (
        'resource "databricks_model_serving" "ep" {\n'
        '  name = "ep"\n'
        '  config {\n'
        '    served_entities {\n'
        '      entity_name = "prod.agents.ep"\n'
        '      environment_vars = { OPENAI_API_KEY = "' + key + '" }\n'
        '    }\n'
        '  }\n'
        '}\n'
    )
    (tmp_path / "main.tf").write_text(hcl, encoding="utf-8")
    result, config = _scan(tmp_path)
    sec = [f for f in result.findings if f.rule_id == "SEC001"]
    assert sec, "a literal API key in HCL must be caught"
    assert key not in json.dumps(build_document(result, config))          # redacted before serialization
    (agent,) = [a for a in result.agents if a.source == "iac"]
    assert any(f.rule_id == "SEC001" for f in agent.findings)            # attached to the endpoint it belongs to


def test_architecture_graph_accepts_iac_agents():
    from stoa.graph_model import build_graph
    result, config = _scan(TIDEWATER)
    graph = build_graph(build_document(result, config))
    agent_nodes = {n.id for n in graph.nodes if n.type == "agent"}
    assert {a.id for a in result.agents} <= agent_nodes                  # all four agents, IaC included


# --- hygiene: vocabulary, opt-out, drift, exports ----------------------------------


def test_databricks_integration_shared_by_code_and_iac_agents():
    result, _ = _scan(TIDEWATER)
    code_support = next(a for a in result.agents if a.path == "agents/support_agent.py")
    assert "databricks" in code_support.integrations          # imports databricks.vector_search
    assert all("databricks" in a.integrations for a in result.agents if a.source == "iac")


def test_iac_opt_out_keeps_secret_scanning(tmp_path):
    key = fake_openai_key()
    (tmp_path / "main.tf").write_text(
        'resource "databricks_model_serving" "ep" {\n  name = "ep"\n'
        '  config { served_entities { entity_name = "prod.agents.ep"\n'
        '    environment_vars = { OPENAI_API_KEY = "' + key + '" } } }\n}\n', encoding="utf-8")
    (tmp_path / "stoa.toml").write_text("[iac]\nenabled = false\n", encoding="utf-8")
    result, config = _scan(tmp_path)
    assert config.iac_enabled is False
    assert not [a for a in result.agents if a.source == "iac"]           # no IaC agents
    assert any(f.rule_id == "SEC001" for f in result.findings)          # but the leak is still caught
    assert key not in json.dumps(build_document(result, config))


def test_widening_a_grant_is_high_drift(tmp_path):
    """SELECT -> ALL_PRIVILEGES on the support endpoint is 'existing agent gains a
    high-impact capability' — exactly the drift event stoa diff exists to catch."""
    import shutil
    from stoa.registry_diff import diff_registries
    work = tmp_path / "tw"; shutil.copytree(TIDEWATER, work)
    base_r, base_c = _scan(work); base = build_document(base_r, base_c)
    tf = work / "infra" / "main.tf"
    txt = tf.read_text()
    old = 'privileges = ["SELECT"]\n  }\n}\n\n# RAG source'
    assert old in txt
    tf.write_text(txt.replace(old, 'privileges = ["ALL_PRIVILEGES"]\n  }\n}\n\n# RAG source'))
    head_r, head_c = _scan(work); head = build_document(head_r, head_c)
    support_id = _iac_agent(head_r, "support_agent").id
    assert "database_write" in _iac_agent(head_r, "support_agent").capabilities
    diff = diff_registries(base, head)
    # per-agent change entries are keyed by agent_id; capability entries by id
    entry = next(e for e in diff["agents"]["changed"] if e["agent_id"] == support_id)
    added = next(c for c in entry["capabilities"]["added"] if c["id"] == "database_write")
    assert added["high_impact"] is True and added["drift_severity"] == "high"
    assert diff["summary"]["max_drift_severity"] == "high"       # the summary escalates too


def test_assurance_and_underwriting_exports_accept_iac_agents():
    from stoa.assurance import build_assurance_packet, render_assurance_markdown
    from stoa.underwriting import render_underwriting_html
    result, config = _scan(TIDEWATER)
    doc = build_document(result, config)
    packet = build_assurance_packet(doc)
    assert render_assurance_markdown(packet)                 # renders, no crash
    html = render_underwriting_html(doc)
    assert "4 agent candidate(s)" in html                     # IaC agents counted in the inventory
