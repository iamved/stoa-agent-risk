"""IaC collector, resolved Terraform + the Google connector.

Resolution: variable defaults, tfvars, locals, ${} interpolation, ternaries,
count / for_each, toset / tolist / concat, data.aws_iam_policy_document, local
module calls (one agent per call), and `terraform show -json` plan input.
Google: Dialogflow CX agents with webhooks followed to their service account's
IAM roles, security settings and logging as controls, knowledge connectors
and Discovery Engine chat engines as RAG. The Marlowe fixture drives both.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from stoa.config import load_config
from stoa.iac import (
    Cond, Ref, _body, _resolve, detect_iac_agents, detect_iac_module, detect_iac_plan,
    detect_iac_tree, parse_tf,
)
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
MARLOWE = REPO_ROOT / "examples/marlowe"
KESTREL = REPO_ROOT / "examples/kestrel"


def _scan(root: Path, **kw):
    config = load_config(root)
    return run_scan(ScanOptions(root=root, no_git=True, **kw), config), config


def _dim(agent, dim_id):
    return next(d["score"] for d in agent.dimension_assessment["dimensions"] if d["id"] == dim_id)


def _by_symbol(result, symbol):
    return next(a for a in result.agents if a.symbol == symbol)


# --- parsing + resolution primitives --------------------------------------------


def test_parse_tf_captures_every_top_level_kind():
    f = parse_tf('''
variable "x" { default = "a" }
variable "y" { type = string }
locals { name = "${var.x}-svc"  n = 2 }
data "aws_iam_policy_document" "p" { statement { actions = ["s3:GetObject"] resources = ["*"] } }
module "m" { source = "./mod"  name = local.name }
resource "aws_iam_role" "r" { name = local.name }
output "o" { value = aws_iam_role.r.arn }
''', "main.tf")
    assert f.variables == {"x": "a", "y": None}
    assert f.locals["n"] == 2 and "${var.x}" in f.locals["name"]
    assert [b.type for b in f.blocks] == ["data.aws_iam_policy_document", "aws_iam_role"]
    assert f.module_calls[0].name == "m" and f.module_calls[0].attrs["source"] == "./mod"
    assert isinstance(f.outputs["o"], Ref)


def test_resolve_vars_locals_interpolation_ternary_and_functions():
    env = {"var": {"name": "billing", "on": True, "roles": ["a"], "missing": None},
           "local": {"suffix": "svc"}, "each": {"value": "roles/editor"}, "count": {"index": 1}}
    assert _resolve(Ref("var.name"), env) == "billing"
    assert _resolve("${var.name}-${local.suffix}", env) == "billing-svc"
    assert _resolve("${var.name}-${var.unknown}", env) == "${var.name}-${var.unknown}"   # left alone
    assert isinstance(_resolve(Ref("var.missing"), env), Ref)                           # no default: unresolved
    assert _resolve(Cond(Ref("var.on"), "yes", "no"), env) == "yes"
    assert isinstance(_resolve(Cond(Ref("var.nope"), "yes", "no"), env), Cond)          # cond unresolved
    assert _resolve(Ref("null"), env) is None
    assert _resolve("toset(var.roles)", env) == ["a"]
    assert _resolve('concat(var.roles, ["b", each.value])', env) == ["a", "b", "roles/editor"]
    assert _resolve("${count.index}", env) == 1


def test_ternary_and_index_tokens_parse():
    attrs = _body('''
  count = var.redaction ? 1 : 0
  sec   = var.redaction ? google_x.this[0].id : null
  uri   = google_cloudfunctions2_function.f.service_config[0].uri
''')
    assert isinstance(attrs["count"], Cond) and attrs["count"].a == 1 and attrs["count"].b == 0
    assert attrs["sec"].a == "google_x.this[0].id" and attrs["sec"].b == "null"
    assert attrs["uri"] == "google_cloudfunctions2_function.f.service_config[0].uri"


def test_count_and_for_each_expand_with_stable_symbols():
    tf = '''
variable "names" { default = ["a", "b"] }
resource "aws_bedrockagent_agent" "x" {
  for_each   = toset(var.names)
  agent_name = "agent-${each.value}"
  foundation_model = "amazon.nova-pro-v1:0"
}
resource "aws_bedrockagent_agent" "y" {
  count      = 2
  agent_name = "y-${count.index}"
  foundation_model = "amazon.nova-pro-v1:0"
}
'''
    dets = detect_iac_agents(tf, "main.tf")
    assert sorted(d.symbol for d in dets) == [
        'aws_bedrockagent_agent.x["a"]', 'aws_bedrockagent_agent.x["b"]',
        "aws_bedrockagent_agent.y[0]", "aws_bedrockagent_agent.y[1]"]
    assert sorted(d.name for d in dets) == ["agent-a", "agent-b", "y-0", "y-1"]
    assert len({d.id for d in dets}) == 4


def test_data_policy_document_resolves_reach():
    tf = '''
resource "aws_bedrockagent_agent" "x" {
  agent_name = "x"
  agent_resource_role_arn = aws_iam_role.x.arn
  foundation_model = "amazon.nova-pro-v1:0"
}
resource "aws_iam_role" "x" { name = "x" }
data "aws_iam_policy_document" "x" {
  statement {
    effect    = "Allow"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem"]
    resources = ["*"]
  }
  statement {
    effect  = "Deny"
    actions = ["s3:*"]
    resources = ["*"]
  }
}
resource "aws_iam_role_policy" "x" {
  role   = aws_iam_role.x.id
  policy = data.aws_iam_policy_document.x.json
}
'''
    det = detect_iac_agents(tf, "main.tf")[0]
    assert det.capabilities == ["database_read", "database_write"]
    assert not any("not resolvable" in e.description for e in det.evidence)


# --- module instantiation (the Marlowe fixture) --------------------------------------


def test_fixture_yields_one_agent_per_module_call_plus_the_chat_engine():
    result, _ = _scan(MARLOWE)
    assert result.files_scanned == 6                          # 5 .tf + terraform.tfvars
    assert sorted(a.symbol for a in result.agents) == [
        "google_discovery_engine_chat_engine.knowledge_assistant",
        "module.billing_assistant.google_dialogflow_cx_agent.this",
        "module.field_service.google_dialogflow_cx_agent.this",
    ]
    assert len({a.id for a in result.agents}) == 3
    billing = _by_symbol(result, "module.billing_assistant.google_dialogflow_cx_agent.this")
    assert billing.path == "infra/modules/cx-agent/main.tf" and billing.platform == "dialogflow_cx"
    assert billing.name == "marlowe-billing-assistant"        # resolved from the call's input
    call = next(e for e in billing.evidence if e.rule_id == "IAC_MODULE_CALL")
    assert 'module "billing_assistant"' in call.description and "infra/main.tf:" in call.description
    assert all("google" in a.providers and "gcp" in a.integrations for a in result.agents)


def test_tfvars_override_variable_default_in_attribution():
    result, _ = _scan(MARLOWE)
    field = _by_symbol(result, "module.field_service.google_dialogflow_cx_agent.this")
    descs = " | ".join(e.description for e in field.evidence)
    assert "project marlowe-prod" in descs and "marlowe-dev" not in descs


def test_controls_and_reach_differ_per_instance():
    result, _ = _scan(MARLOWE)
    billing = _by_symbol(result, "module.billing_assistant.google_dialogflow_cx_agent.this")
    field = _by_symbol(result, "module.field_service.google_dialogflow_cx_agent.this")
    b_ids, f_ids = [e.rule_id for e in billing.evidence], [e.rule_id for e in field.evidence]
    assert "IAC_CONTROL_GUARDRAIL" in b_ids and "IAC_CONTROL_OBSERVABILITY" in b_ids
    assert "IAC_CONTROL_GUARDRAIL" not in f_ids and "IAC_CONTROL_OBSERVABILITY" not in f_ids
    sec = next(e for e in billing.evidence if e.rule_id == "IAC_CONTROL_GUARDRAIL")
    assert "redaction REDACT_WITH_SERVICE" in sec.description and "retention 30 days" in sec.description
    assert billing.capabilities == ["database_read", "tool_calling", "vector_search"]
    assert {"cloud_resource_access", "database_write", "messaging"} <= set(field.capabilities)
    f_descs = " | ".join(e.description for e in field.evidence)
    assert "roles/editor" in f_descs and "primitive role, broad reach" in f_descs
    assert "bigquery" in field.integrations
    # for_each expanded to one IAM member per role, via concat() on the billing side
    assert sum(1 for e in billing.evidence if e.rule_id == "IAC_IAM_POLICY") == 2
    assert _dim(billing, "mandate-overreach") == 0 < _dim(field, "mandate-overreach")


def test_module_directory_is_not_scanned_as_a_bare_agent():
    result, _ = _scan(MARLOWE)
    assert not any(a.symbol == "google_dialogflow_cx_agent.this" for a in result.agents)


def test_unreferenced_module_directory_is_a_root_module():
    files = {"": [("main.tf", 'resource "aws_bedrockagent_agent" "a" { agent_name = "a" }')],
             "other": [("other/main.tf", 'resource "aws_bedrockagent_agent" "b" { agent_name = var.n }')]}
    dets = detect_iac_tree(files)
    assert sorted(d.symbol for d in dets) == ["aws_bedrockagent_agent.a", "aws_bedrockagent_agent.b"]
    assert next(d for d in dets if d.symbol.endswith(".b")).name == "b"     # var.n unresolved: falls back


# --- Google connector units -----------------------------------------------------------

CX = '''
resource "google_dialogflow_cx_agent" "a" {
  display_name = "A"
  location     = "us-central1"
  security_settings = "projects/p/locations/us-central1/securitySettings/s"
}
'''


def test_external_webhook_and_literal_security_settings():
    tf = CX + '''
resource "google_dialogflow_cx_webhook" "w" {
  parent       = google_dialogflow_cx_agent.a.id
  display_name = "crm"
  generic_web_service { uri = "https://crm.example.com/hooks/dialogflow" }
}
'''
    det = detect_iac_agents(tf, "main.tf")[0]
    assert det.platform == "dialogflow_cx" and det.providers == ["google"]
    assert set(det.capabilities) == {"tool_calling", "external_http"}
    assert "validation" in det.controls
    assert any("crm.example.com" in e.description for e in det.evidence)


def test_chat_engine_linked_to_cx_agent_is_attributed_not_duplicated():
    tf = CX + '''
resource "google_discovery_engine_data_store" "d" { data_store_id = "faq" location = "global" display_name = "FAQ" industry_vertical = "GENERIC" content_config = "NO_CONTENT" }
resource "google_discovery_engine_chat_engine" "c" {
  engine_id      = "c"
  display_name   = "C"
  collection_id  = "default_collection"
  location       = "global"
  industry_vertical = "GENERIC"
  data_store_ids = [google_discovery_engine_data_store.d.data_store_id]
  chat_engine_config { dialogflow_agent_to_link = google_dialogflow_cx_agent.a.id }
}
'''
    dets = detect_iac_agents(tf, "main.tf")
    assert [d.symbol for d in dets] == ["google_dialogflow_cx_agent.a"]
    assert "vector_search" in dets[0].capabilities
    assert any("over faq" in e.description for e in dets[0].evidence)


def test_cx_tool_resource_and_cloud_run_chain():
    tf = CX + '''
resource "google_dialogflow_cx_tool" "t" {
  parent       = google_dialogflow_cx_agent.a.id
  display_name = "orders"
  open_api_spec { text_schema = "openapi: 3.0.0" }
}
resource "google_dialogflow_cx_webhook" "w" {
  parent = google_dialogflow_cx_agent.a.id
  display_name = "svc"
  generic_web_service { uri = "${google_cloud_run_v2_service.s.uri}/hook" }
}
resource "google_service_account" "sa" { account_id = "sa" }
resource "google_cloud_run_v2_service" "s" {
  name = "s"
  location = "us-central1"
  template { service_account = google_service_account.sa.email }
}
resource "google_storage_bucket_iam_member" "b" {
  bucket = "exports"
  role   = "roles/storage.objectAdmin"
  member = google_service_account.sa.member
}
resource "google_project_iam_member" "unknown" {
  project = "p"
  role    = "roles/some.customRole"
  member  = "serviceAccount:${google_service_account.sa.email}"
}
'''
    det = detect_iac_agents(tf, "main.tf")[0]
    assert {"tool_calling", "external_http", "filesystem_read", "filesystem_write"} <= set(det.capabilities)
    descs = " | ".join(e.description for e in det.evidence)
    assert "calls Cloud Run service s (service account sa)" in descs
    assert "roles/storage.objectAdmin on storage bucket exports" in descs
    assert "not in Stoa's dictionary" in descs                # unknown role: reported, not guessed
    assert "OpenAPI service" in descs


# --- terraform show -json input ---------------------------------------------------------


def _plan_doc() -> dict:
    """A hand-written plan: a Bedrock agent whose role ARN is unknown until apply,
    plus a module instance with a Databricks endpoint whose grant principal is unknown."""
    return {
        "format_version": "1.2",
        "planned_values": {"root_module": {
            "resources": [
                {"address": "aws_bedrockagent_agent.a", "mode": "managed", "type": "aws_bedrockagent_agent",
                 "name": "a", "values": {"agent_name": "plan-agent",
                                         "foundation_model": "anthropic.claude-3-haiku-20240307-v1:0"}},
                {"address": "aws_iam_role.r", "mode": "managed", "type": "aws_iam_role", "name": "r",
                 "values": {"name": "r"}},
                {"address": "aws_iam_role_policy.p", "mode": "managed", "type": "aws_iam_role_policy", "name": "p",
                 "values": {"policy": json.dumps({"Statement": [{"Effect": "Allow",
                                                                 "Action": ["ses:SendEmail"], "Resource": "*"}]})}},
            ],
            "child_modules": [{"address": "module.dbx", "resources": [
                {"address": "module.dbx.databricks_model_serving.ep", "mode": "managed",
                 "type": "databricks_model_serving", "name": "ep",
                 "values": {"name": "resolved-endpoint", "config": [{"served_entities": [
                     {"entity_name": "prod.agents.x", "environment_vars": {"OPENAI_API_KEY": "{{secrets/x}}"}}]}]}},
                {"address": "module.dbx.databricks_service_principal.ep_sp", "mode": "managed",
                 "type": "databricks_service_principal", "name": "ep_sp", "values": {"display_name": "ep_sp"}},
                {"address": "module.dbx.databricks_grants.g", "mode": "managed", "type": "databricks_grants",
                 "name": "g", "values": {"catalog": "prod", "grant": [{"privileges": ["ALL_PRIVILEGES"]}]}},
            ]}],
        }},
        "configuration": {"root_module": {
            "resources": [
                {"address": "aws_bedrockagent_agent.a", "mode": "managed", "type": "aws_bedrockagent_agent", "name": "a",
                 "expressions": {"agent_name": {"references": ["var.name"]},
                                 "agent_resource_role_arn": {"references": ["aws_iam_role.r.arn", "aws_iam_role.r"]}}},
                {"address": "aws_iam_role_policy.p", "mode": "managed", "type": "aws_iam_role_policy", "name": "p",
                 "expressions": {"role": {"references": ["aws_iam_role.r.id", "aws_iam_role.r"]}}},
            ],
            "module_calls": {"dbx": {"source": "./modules/dbx", "module": {"resources": [
                {"address": "databricks_grants.g", "mode": "managed", "type": "databricks_grants", "name": "g",
                 "expressions": {"grant": [{"principal": {"references": [
                     "databricks_service_principal.ep_sp.application_id", "databricks_service_principal.ep_sp"]}}]}},
            ]}}},
        }},
    }


def test_plan_input_links_unknown_values_through_references():
    dets = detect_iac_plan(_plan_doc(), "plan.json")
    assert sorted(d.symbol for d in dets) == ["aws_bedrockagent_agent.a", "module.dbx.databricks_model_serving.ep"]
    bed = next(d for d in dets if d.platform == "bedrock")
    assert bed.name == "plan-agent" and bed.path == "plan.json"        # resolved value kept, var ref not used
    assert bed.capabilities == ["email_send"]                           # role linked via references
    dbx = next(d for d in dets if d.platform == "databricks")
    assert dbx.name == "resolved-endpoint" and dbx.providers == ["openai"]
    assert dbx.capabilities == ["database_read", "database_write"]      # grant principal linked via references
    assert all(any(e.rule_id == "IAC_PLAN_SOURCE" for e in d.evidence) for d in dets)


def test_plan_state_form_is_accepted():
    doc = _plan_doc()
    doc["values"] = doc.pop("planned_values")
    assert len(detect_iac_plan(doc, "state.json")) == 2


def test_scan_with_tf_plan_replaces_file_discovery(tmp_path):
    work = tmp_path / "k"; shutil.copytree(KESTREL, work)
    (work / "plan.json").write_text(json.dumps(_plan_doc()))
    result, config = _scan(work, tf_plan=work / "plan.json")
    assert sorted(a.symbol for a in result.agents) == ["aws_bedrockagent_agent.a", "module.dbx.databricks_model_serving.ep"]
    assert all(a.path == "plan.json" and a.language == "terraform" for a in result.agents)
    doc = build_document(result, config)                                # validates: repo-relative path
    assert doc["summary"]["agent_candidates"] == 2
    # a bad plan degrades to a warning, never a crash
    (work / "plan.json").write_text("not json")
    result, _ = _scan(work, tf_plan=work / "plan.json")
    assert result.agents == [] and any("--tf-plan" in w for w in result.warnings)


# --- regression ------------------------------------------------------------------------------


def test_other_examples_unchanged_and_deterministic():
    for ex, count in (("tidewater", 4), ("kestrel", 2), ("meridian-ops", 12), ("sparkwing", 8),
                      ("support-desk", 9), ("threshold-voice", 11)):
        result, _ = _scan(REPO_ROOT / "examples" / ex)
        assert len(result.agents) == count, ex
    a, ca = _scan(MARLOWE); b, cb = _scan(MARLOWE)
    assert json.dumps(build_document(a, ca), sort_keys=True) == json.dumps(build_document(b, cb), sort_keys=True)


def test_registry_and_exports_accept_module_instances():
    from stoa.assurance import build_assurance_packet, render_assurance_markdown
    from stoa.underwriting import render_underwriting_html
    result, config = _scan(MARLOWE)
    doc = build_document(result, config)
    assert {a["platform"] for a in doc["agents"]} == {"dialogflow_cx", "vertex_ai_agent_builder"}
    assert render_assurance_markdown(build_assurance_packet(doc))
    assert "3 agent candidate(s)" in render_underwriting_html(doc)
