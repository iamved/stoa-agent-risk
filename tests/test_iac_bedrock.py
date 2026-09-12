"""IaC collector, Amazon Bedrock: agents configured across several Terraform files.

The Kestrel fixture is the target: two ``aws_bedrockagent_agent`` resources
whose tools, guardrail, logging, and IAM live in *other* files of the same
module. The scanner must follow agent -> action group -> Lambda -> role ->
policy, credit stated controls, parse all three IAM policy forms, report
anything unresolved as unresolved, and leave every other example unchanged.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from stoa.config import load_config
from stoa.iac import _caps_for_action, detect_iac_agents, detect_iac_module
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
KESTREL = REPO_ROOT / "examples/kestrel"
TIDEWATER = REPO_ROOT / "examples/tidewater"


def _scan(root: Path):
    config = load_config(root)
    return run_scan(ScanOptions(root=root, no_git=True), config), config


def _agent(result, name: str):
    return next(a for a in result.agents if a.symbol == f"aws_bedrockagent_agent.{name}")


def _rule_ids(agent) -> list[str]:
    return [e.rule_id for e in agent.evidence]


def _dim(agent, dim_id: str) -> int:
    return next(d["score"] for d in agent.dimension_assessment["dimensions"] if d["id"] == dim_id)


# --- the fixture ---------------------------------------------------------------


def test_fixture_finds_both_bedrock_agents_and_no_code_agents():
    result, _ = _scan(KESTREL)
    assert result.files_scanned == 7                                # 5 .tf + 2 .py
    assert len(result.agents) == 2
    assert {a.symbol for a in result.agents} == {
        "aws_bedrockagent_agent.claims_assistant", "aws_bedrockagent_agent.dispatch_agent",
    }
    for a in result.agents:
        assert a.source == "iac" and a.platform == "bedrock" and a.path == "infra/agents.tf"
        assert a.language == "terraform" and a.confidence == "high" and a.frameworks == []
        assert "bedrock" in a.providers and "anthropic" in a.providers   # hosted vendor model
        assert "aws" in a.integrations


def test_claims_assistant_is_read_only_with_guardrail_and_logging_credited():
    result, _ = _scan(KESTREL)
    claims = _agent(result, "claims_assistant")
    assert claims.capabilities == ["database_read", "tool_calling", "vector_search"]
    ids = _rule_ids(claims)
    assert "IAC_CONTROL_GUARDRAIL" in ids and "IAC_CONTROL_OBSERVABILITY" in ids
    assert "IAC_KNOWLEDGE_BASE" in ids and "IAC_TOOL_BINDING" in ids
    guardrail = next(e for e in claims.evidence if e.rule_id == "IAC_CONTROL_GUARDRAIL")
    assert "customer_facing" in guardrail.description and "in infra/guardrails.tf" in guardrail.description
    # the narrow Lambda policy is what reach came through
    policy = next(e for e in claims.evidence if "dynamodb:GetItem" in e.description)
    assert "Lambda claims_lookup's role" in policy.description and "in infra/iam.tf" in policy.description
    assert _dim(claims, "mandate-overreach") == 0


def test_dispatch_agent_reach_follows_the_lambda_role_chain():
    result, _ = _scan(KESTREL)
    dispatch = _agent(result, "dispatch_agent")
    caps = set(dispatch.capabilities)
    assert {"database_write", "email_send", "messaging", "filesystem_write", "code_execution",
            "tool_calling"} <= caps
    ids = _rule_ids(dispatch)
    assert "IAC_CONTROL_GUARDRAIL" not in ids            # planted: no guardrail
    assert "IAC_CONTROL_OBSERVABILITY" in ids            # account-wide logging still covers it
    assert "ses" in dispatch.integrations
    descs = " | ".join(e.description for e in dispatch.evidence)
    assert "dynamodb:* on all resources" in descs and "wildcard actions, broad reach" in descs
    assert "AmazonS3FullAccess" in descs and "full-access policy" in descs
    assert "code interpreter enabled" in descs
    assert "reroute_shipment, notify_customer, notify_driver" in descs
    claims = _agent(result, "claims_assistant")
    assert _dim(dispatch, "mandate-overreach") > _dim(claims, "mandate-overreach")
    assert _dim(dispatch, "unreviewed-high-impact-action") > 0


def test_lambda_handlers_are_not_mistaken_for_agents():
    result, _ = _scan(KESTREL)
    assert not any(a.path.startswith("functions/") for a in result.agents)


# --- module scope: cross-file resolution ------------------------------------------

AGENT_TF = '''
resource "aws_bedrockagent_agent" "x" {
  agent_name              = "x"
  agent_resource_role_arn = aws_iam_role.x.arn
  foundation_model        = "anthropic.claude-3-haiku-20240307-v1:0"
}
'''
IAM_TF = '''
resource "aws_iam_role" "x" {
  name = "x"
}
resource "aws_iam_role_policy" "x" {
  role = aws_iam_role.x.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = ["dynamodb:PutItem"], Resource = "*" }]
  })
}
'''


def test_module_scope_links_an_agent_to_iam_in_another_file():
    dets = detect_iac_module([("infra/agent.tf", AGENT_TF), ("infra/iam.tf", IAM_TF)])
    assert len(dets) == 1
    det = dets[0]
    assert det.path == "infra/agent.tf" and det.symbol == "aws_bedrockagent_agent.x"
    assert det.capabilities == ["database_read", "database_write"]
    assert any("(in infra/iam.tf)" in e.description for e in det.evidence)
    # the same agent alone: reach honestly unresolved, never guessed
    alone = detect_iac_agents(AGENT_TF, "infra/agent.tf")[0]
    assert alone.capabilities == []
    assert any("reach unresolved" in e.description for e in alone.evidence)
    assert alone.id == det.id                          # identity does not depend on module contents


def test_databricks_grants_in_a_separate_file_are_now_attributed():
    """Module scope helps the Databricks path too: grants split out of main.tf."""
    main = (TIDEWATER / "infra/main.tf").read_text()
    cut = main.index('resource "databricks_grants"')
    dets = detect_iac_module([("infra/main.tf", main[:cut]), ("infra/grants.tf", main[cut:])])
    # the split leaves support_agent in main.tf and its SELECT grant in grants.tf
    support = next(d for d in dets if d.symbol == "databricks_model_serving.support_agent")
    assert support.path == "infra/main.tf" and support.capabilities == ["database_read"]
    assert any("(in infra/grants.tf)" in e.description for e in support.evidence)


# --- IAM policy forms and action mapping ----------------------------------------


def test_all_three_policy_forms_parse_and_a_data_source_is_unresolved():
    tf = AGENT_TF + '''
resource "aws_iam_role" "x" { name = "x" }
resource "aws_iam_role_policy" "heredoc" {
  role   = aws_iam_role.x.name
  policy = <<EOF
{ "Version": "2012-10-17",
  "Statement": [ { "Effect": "Allow", "Action": ["ses:SendEmail"], "Resource": "*" } ] }
EOF
}
resource "aws_iam_role_policy_attachment" "managed" {
  role       = aws_iam_role.x.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess"
}
resource "aws_iam_role_policy_attachment" "custom" {
  role       = aws_iam_role.x.name
  policy_arn = aws_iam_policy.custom.arn
}
resource "aws_iam_policy" "custom" {
  policy = jsonencode({ Statement = [{ Effect = "Allow", Action = "sns:Publish", Resource = "*" }] })
}
resource "aws_iam_role_policy" "opaque" {
  role   = aws_iam_role.x.name
  policy = data.aws_iam_policy_document.opaque.json
}
'''
    det = detect_iac_agents(tf, "main.tf")[0]
    assert set(det.capabilities) == {"email_send", "database_read", "messaging"}
    assert "ses" in det.integrations
    descs = [e.description for e in det.evidence if e.rule_id == "IAC_IAM_POLICY"]
    assert any("not resolvable in this module" in d for d in descs)   # the data-source policy
    assert any("AmazonDynamoDBReadOnlyAccess" in d for d in descs)


def test_deny_statements_do_not_grant_reach():
    tf = AGENT_TF + '''
resource "aws_iam_role" "x" { name = "x" }
resource "aws_iam_role_policy" "x" {
  role = aws_iam_role.x.id
  policy = jsonencode({ Statement = [{ Effect = "Deny", Action = ["s3:*"], Resource = "*" }] })
}
'''
    det = detect_iac_agents(tf, "main.tf")[0]
    assert det.capabilities == []


def test_iam_action_mapping_is_conservative():
    assert _caps_for_action("dynamodb:Query") == {"database_read"}
    assert _caps_for_action("dynamodb:UpdateItem") == {"database_read", "database_write"}
    assert _caps_for_action("rds-data:ExecuteStatement") == {"database_read", "database_write"}
    assert _caps_for_action("s3:GetObject") == {"filesystem_read"}
    assert _caps_for_action("s3:*") == {"filesystem_read", "filesystem_write"}
    assert _caps_for_action("ses:SendEmail") == {"email_send"}
    assert _caps_for_action("sns:Publish") == {"messaging"}
    assert _caps_for_action("sqs:SendMessage") == {"queue_access"}
    assert _caps_for_action("ssm:SendCommand") == {"shell_execution"}
    assert _caps_for_action("*") == {"cloud_resource_access"}
    assert _caps_for_action("iam:CreateRole") == {"cloud_resource_access"}
    # plumbing and read-only management calls grant nothing
    assert _caps_for_action("iam:PassRole") == set()
    assert _caps_for_action("ec2:DescribeInstances") == set()
    assert _caps_for_action("bedrock:InvokeModel") == set()
    assert _caps_for_action("logs:PutLogEvents") == set()
    assert _caps_for_action("secretsmanager:GetSecretValue") == set()


def test_unresolved_role_and_model_are_not_guessed():
    tf = '''
resource "aws_bedrockagent_agent" "y" {
  agent_name              = var.name
  agent_resource_role_arn = var.role_arn
  foundation_model        = var.model
}
'''
    det = detect_iac_agents(tf, "main.tf")[0]
    assert det.name == "y" and det.symbol == "aws_bedrockagent_agent.y"
    assert det.providers == ["bedrock"]                  # no vendor guessed from var.model
    assert det.capabilities == []
    assert any("agent role is not defined in this module" in e.description for e in det.evidence)


def test_return_control_and_user_input_action_groups():
    tf = AGENT_TF + '''
resource "aws_bedrockagent_agent_action_group" "rc" {
  action_group_name = "in-app"
  agent_id          = aws_bedrockagent_agent.x.agent_id
  action_group_executor { custom_control = "RETURN_CONTROL" }
}
resource "aws_bedrockagent_agent_action_group" "ask" {
  action_group_name             = "ask"
  agent_id                      = aws_bedrockagent_agent.x.agent_id
  parent_action_group_signature = "AMAZON.UserInput"
}
'''
    det = detect_iac_agents(tf, "main.tf")[0]
    assert "tool_calling" in det.capabilities and "code_execution" not in det.capabilities
    descs = " | ".join(e.description for e in det.evidence)
    assert "returns control to the caller" in descs and "ask the user" in descs


# --- pipeline integration -----------------------------------------------------------


def test_registry_emits_bedrock_provenance_and_validates():
    result, config = _scan(KESTREL)
    doc = build_document(result, config)
    for a in doc["agents"]:
        assert a["source"] == "iac" and a["platform"] == "bedrock" and a["discovery_tier"] == "recognized"
    assert doc["summary"]["agent_candidates"] == 2
    json.dumps(doc)                                       # serializable, no set() leaked


def test_deterministic():
    a, ca = _scan(KESTREL)
    b, cb = _scan(KESTREL)
    assert json.dumps(build_document(a, ca), sort_keys=True) == json.dumps(build_document(b, cb), sort_keys=True)


def test_other_examples_are_unchanged():
    for ex, count in (("tidewater", 4), ("meridian-ops", 12), ("sparkwing", 8), ("support-desk", 9),
                      ("threshold-voice", 11)):
        result, _ = _scan(REPO_ROOT / "examples" / ex)
        assert len(result.agents) == count, ex
        assert not any(a.platform == "bedrock" for a in result.agents), ex


def test_widening_a_lambda_policy_is_high_drift(tmp_path):
    from stoa.registry_diff import diff_registries
    work = tmp_path / "k"; shutil.copytree(KESTREL, work)
    base_r, base_c = _scan(work); base = build_document(base_r, base_c)
    iam = work / "infra" / "iam.tf"
    txt = iam.read_text()
    old = 'Action   = ["dynamodb:GetItem", "dynamodb:Query"]'
    assert old in txt
    iam.write_text(txt.replace(old, 'Action   = ["dynamodb:*"]'))
    head_r, head_c = _scan(work); head = build_document(head_r, head_c)
    claims = _agent(head_r, "claims_assistant")
    assert "database_write" in claims.capabilities
    diff = diff_registries(base, head)
    entry = next(e for e in diff["agents"]["changed"] if e["agent_id"] == claims.id)
    added = next(c for c in entry["capabilities"]["added"] if c["id"] == "database_write")
    assert added["high_impact"] is True and added["drift_severity"] == "high"
    assert diff["summary"]["max_drift_severity"] == "high"


def test_exports_accept_bedrock_agents():
    from stoa.assurance import build_assurance_packet, render_assurance_markdown
    from stoa.underwriting import render_underwriting_html
    result, config = _scan(KESTREL)
    doc = build_document(result, config)
    assert render_assurance_markdown(build_assurance_packet(doc))
    assert "2 agent candidate(s)" in render_underwriting_html(doc)
