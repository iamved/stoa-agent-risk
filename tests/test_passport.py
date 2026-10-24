"""Evidence levels, risk types and explanations, the passport, and stoa policy test."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from stoa.cli import main
from stoa.evidence import LEVELS, annotate_evidence_levels, evidence_mix
from stoa.passport import PASSPORT_SCHEMA, build_passport, build_passports, registry_hash, render_passport_html
from stoa.policy.test import load_scenarios, run_policy_test
from stoa.risk_type import RISK_TYPES, annotate_risk_types, classify, explain

FIXTURES = Path(__file__).resolve().parents[1] / "ui" / "fixtures"
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "meridian-pay"


def _envelope():
    return json.loads((FIXTURES / "meridian-pay.envelope.json").read_text())


def test_evidence_levels_follow_the_source_of_the_fact():
    registry = _envelope()["registry"]
    annotate_evidence_levels(registry)
    by_name = {((a.get("declared") or {}).get("name") or a["name"]): a for a in registry["agents"]}
    support = by_name["meridian-support"]
    levels = {f["rule_id"][:2 if f["rule_id"].startswith("RT") else 4]: f["evidence_level"] for f in support["findings"]}
    assert levels["DECL"] == "declared" and levels["RT"] == "observed" and levels["AI00"] == "static"
    assert support["capability_evidence"]["payment_access"] == "observed"
    knowledge = by_name["meridian-knowledge"]
    assert knowledge["capability_evidence"] == {"vector_search": "reachable"}
    assert set(evidence_mix(support)) == set(LEVELS) and evidence_mix(support)["observed"] >= 1
    assert all(f["evidence_level"] in LEVELS for a in registry["agents"] for f in a["findings"])


def test_risk_type_and_explanation_are_deterministic_and_plain():
    registry = _envelope()["registry"]
    annotate_risk_types(registry)
    by_name = {((a.get("declared") or {}).get("name") or a["name"]): a for a in registry["agents"]}
    support = by_name["meridian-support"]
    assert support["risk_type"]["primary"] == "Erroneous Transactions" and support["risk_type"]["driver"] == "mandate-overreach"
    assert support["risk_type"]["confidence"] == "low"  # control coverage gap is elevated
    assert by_name["meridian-knowledge"]["risk_type"]["primary"] == "Prompt Injections"
    assert by_name["meridian-escalation"]["risk_type"]["primary"] == "Data Loss & Corruption"
    assert all(a["risk_type"]["primary"] in RISK_TYPES for a in registry["agents"] if a.get("risk_type"))
    text = support["explanation"]
    assert text["can_do"].startswith("meridian-support can move money")
    assert "Erroneous" not in text["could_go_wrong"] and "money or account changes" in text["could_go_wrong"] and "excess access (elevated)" in text["could_go_wrong"]
    assert "a person approves before it acts" in text["missing"] and "a declared spending limit" in text["missing"]
    assert "Observed over" in text["evidence"]
    for line in text.values():
        assert "—" not in line and len(line) < 320
    # the scan's own high findings are counted, never the runtime ones
    assert "2 high-severity findings" in text["could_go_wrong"]
    again = copy.deepcopy(_envelope()["registry"])
    annotate_risk_types(again)
    assert again["agents"] == registry["agents"]
    # no assessment: no classification, still an explanation
    bare = {"id": "x", "name": "x", "capabilities": [], "tools": [], "findings": []}
    assert classify(bare) is None and explain(bare)["can_do"].startswith("x recommends and answers")


def test_passport_is_deterministic_hashes_the_registry_and_lapses_on_drift():
    envelope = _envelope()
    registry = envelope["registry"]
    policies = envelope["runtime"]["policies"]
    support = build_passport(registry, "bc3db1f17013", diff=envelope["diff"], policies=policies)
    assert support["schema"] == PASSPORT_SCHEMA and support["agent"]["name"] == "meridian-support"
    assert support["validity"]["status"] == "lapsed" and "drift high" in support["validity"]["reason"]
    assert support["validity"]["expires"] == "2026-12-14" and support["scan_date"] == "2026-09-15"
    assert support["killswitch_drill"]["seconds_to_stop"] == 1.8
    assert support["policy_test"]["scenarios"] == 5 and support["policy_test"]["false_positives"] == 0
    assert any(p["id"] == "POL-FIN-002-BC3DB1" and p["enforced"] and p["counts"]["blocked"] == 1 for p in support["policies"]["attached"])
    assert support["reach"]["observed"] and support["evidence_mix"]["tested"] == 5
    account = build_passport(registry, "b8f0111742fc", diff=envelope["diff"], policies=policies)
    assert account["validity"]["status"] == "valid" and account["drift"]["status"] == "unchanged"
    # deterministic, and the hash moves with the registry
    assert build_passport(registry, "bc3db1f17013", diff=envelope["diff"], policies=policies)["verify_hash"] == support["verify_hash"]
    changed = copy.deepcopy(registry)
    changed["agents"][0]["capabilities"].append("shell_execution")
    assert registry_hash(changed) != registry_hash(registry)
    assert build_passport(changed, "bc3db1f17013", diff=envelope["diff"], policies=policies)["registry_hash"] != support["registry_hash"]
    assert len(build_passports(registry)) == len(registry["agents"])
    html = render_passport_html(support, company="Meridian Pay")
    assert "Agent passport: meridian-support" in html and "lapsed" in html and support["verify_hash"] in html and "—" not in html


def test_envelope_carries_a_passport_per_agent():
    envelope = _envelope()
    names = sorted(p["agent"]["name"] for p in envelope["passports"])
    assert names == ["account-actions", "meridian-escalation", "meridian-front", "meridian-knowledge", "meridian-support"]
    assert all(p["verify_hash"] for p in envelope["passports"])


def test_policy_test_replays_the_demo_scenarios(tmp_path):
    registry = _envelope()["registry"]
    (tmp_path / "stoa-registry.json").write_text(json.dumps(registry))
    scenarios, problems = load_scenarios(EXAMPLE / "scenarios.jsonl")
    assert not problems and len(scenarios) == 7
    doc = run_policy_test(scenarios, EXAMPLE / "stoa.policy.toml", registry_path=tmp_path / "stoa-registry.json")
    assert doc["schema"] == "policy-test/0.1" and doc["evidence_level"] == "tested"
    assert doc["matched"] == doc["expected"] == 7 and doc["false_positives"] == 0
    blocked = [r for r in doc["results"] if r["actual"] == "block"]
    assert len(blocked) == 1 and blocked[0]["decided_by"] == "POL-FIN-002-BC3DB1" and blocked[0]["amount"] == 500
    assert doc["policies"]["POL-FIN-002-BC3DB1"]["enforced"] and doc["policies"]["POL-FIN-001-BC3DB1"]["would_decide"] == 4
    assert doc["agents"]["meridian-support"]["blocked"] == 1
    # a broken line is reported, not fatal
    bad = tmp_path / "s.jsonl"
    bad.write_text('not json\n{"tool": "x", "agent": "nobody"}\n')
    scenarios, problems = load_scenarios(bad)
    assert len(scenarios) == 1 and problems and "line 1" in problems[0]


def test_cli_policy_test_and_passport(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    envelope = _envelope()
    (tmp_path / "stoa-registry.json").write_text(json.dumps(envelope["registry"]))
    assert main(["policy", "test", str(EXAMPLE / "scenarios.jsonl"), "--policies", str(EXAMPLE / "stoa.policy.toml"), "--out", "pt.json", "--fail-on-mismatch"]) == 0
    assert "7 of 7 expectations matched" in capsys.readouterr().out
    assert json.loads((tmp_path / "pt.json").read_text())["scenarios"] == 7
    assert main(["policy", "test", str(EXAMPLE / "scenarios.jsonl"), "--policies", str(EXAMPLE / "stoa.policy.toml"), "--registry", "missing.json"]) == 2
    assert main(["passport", "--agent-id", "meridian-support", "--out", "p.html"]) == 0
    out = capsys.readouterr().out
    assert "wrote p.html" in out
    assert "Agent passport: meridian-support" in (tmp_path / "p.html").read_text()
    assert main(["passport", "--agent-id", "account-actions", "--json", "--out", "p.json"]) == 0
    assert json.loads((tmp_path / "p.json").read_text())["schema"] == PASSPORT_SCHEMA
    assert main(["passport", "--agent-id", "nobody"]) == 2
