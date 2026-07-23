"""Phase 5: registry diff, drift severity, rename, approvals, dimension delta."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stoa.approvals import Approval, Approvals
from stoa.registry_diff import (
    TaxonomyMismatch,
    agent_evidence_fingerprint,
    diff_registries,
    dimension_increase_exceeds,
    render_changelog,
)


def agent(id="a1", name="agt", path="a.py", confidence="high", caps=None, integs=None,
          providers=None, evidence=None, findings=None, dims=None):
    a = {
        "id": id, "name": name, "path": path, "confidence": confidence,
        "capabilities": caps or [], "integrations": integs or [],
        "providers": providers or [], "findings": findings or [],
        "evidence": evidence or [{"rule_id": "AGENT_LANGCHAIN", "line": 1, "description": "LangChain agent construct"}],
    }
    if dims is not None:
        a["dimension_assessment"] = {"taxonomy": {"id": "stoa-default-8", "version": "1.0"},
                                     "dimensions": dims}
    return a


def registry(agents, schema="1.1", tax=("stoa-default-8", "1.0")):
    doc = {"schema_version": schema, "tool": {"name": "stoa", "version": "0.2.0"},
           "repository": {"git_ref": "abc"}, "agents": agents, "repository_findings": []}
    if tax:
        doc["dimension_summary"] = {"taxonomy": {"id": tax[0], "version": tax[1]}, "dimensions": []}
    return doc


def test_no_change_is_empty_diff():
    a = agent(caps=["database_read"])
    d = diff_registries(registry([a]), registry([a]))
    assert d["summary"]["agents_changed"] == 0
    assert d["summary"]["max_drift_severity"] == "info"


def test_high_impact_capability_gain_is_high_drift():
    base = registry([agent(caps=["database_read"])])
    head = registry([agent(caps=["database_read", "shell_execution"])])
    d = diff_registries(base, head)
    assert d["summary"]["agents_changed"] == 1
    assert d["summary"]["max_drift_severity"] == "high"
    added = d["agents"]["changed"][0]["capabilities"]["added"]
    assert added[0]["id"] == "shell_execution" and added[0]["high_impact"]


def test_non_high_impact_capability_gain_is_medium():
    base = registry([agent(caps=[])])
    head = registry([agent(caps=["web_search"])])
    d = diff_registries(base, head)
    assert d["summary"]["max_drift_severity"] == "medium"


def test_sensitive_integration_gain_is_high():
    base = registry([agent(integs=[])])
    head = registry([agent(integs=["stripe"])])
    d = diff_registries(base, head)
    assert d["summary"]["max_drift_severity"] == "high"


def test_new_agent_with_high_impact_is_high():
    d = diff_registries(registry([]), registry([agent(caps=["payment_access"])]))
    assert d["summary"]["agents_added"] == 1
    assert d["agents"]["added"][0]["drift_severity"] == "high"


def test_removed_agent_is_info():
    d = diff_registries(registry([agent()]), registry([]))
    assert d["summary"]["agents_removed"] == 1
    assert d["agents"]["removed"][0]["drift_severity"] == "info"


def test_rename_detection_by_evidence_overlap():
    ev = [{"rule_id": "AGENT_LANGCHAIN", "line": 5, "description": "LangChain agent construct"},
          {"rule_id": "AGENT_PROVIDER_CALL", "line": 8, "description": "LLM provider invocation"}]
    base = registry([agent(id="old", name="oldname", path="old.py", evidence=ev, caps=["database_read"])])
    head = registry([agent(id="new", name="newname", path="new.py", evidence=ev, caps=["database_read"])])
    d = diff_registries(base, head)
    assert d["summary"]["agents_added"] == 0 and d["summary"]["agents_removed"] == 0
    assert d["agents"]["changed"][0]["renamed_from"] == "oldname"


def test_approval_suppresses_drift():
    head_agent = agent(caps=["shell_execution"])
    fp = agent_evidence_fingerprint(head_agent)
    approvals = Approvals([Approval("a1", "agt", "capability", "shell_execution",
                                    "reviewed", "@me", evidence_fingerprint=fp)], Path("x"))
    d = diff_registries(registry([agent(caps=[])]), registry([head_agent]), approvals)
    assert d["summary"]["unapproved_max_drift_severity"] == "info"
    assert d["agents"]["changed"][0]["capabilities"]["added"][0]["approved"] is True


def test_stale_approval_does_not_satisfy_gate():
    approvals = Approvals([Approval("a1", "agt", "capability", "shell_execution",
                                    "reviewed", "@me", evidence_fingerprint="STALE")], Path("x"))
    d = diff_registries(registry([agent(caps=[])]), registry([agent(caps=["shell_execution"])]), approvals)
    assert d["summary"]["unapproved_max_drift_severity"] == "high"
    assert any(s["value"] == "shell_execution" for s in d["approvals"]["stale"])


def test_expired_approval_is_stale():
    approvals = Approvals([Approval("a1", "agt", "capability", "shell_execution",
                                    "reviewed", "@me", expires="2000-01-01")], Path("x"))
    assert approvals.is_approved("a1", "capability", "shell_execution", "any") is False


def test_taxonomy_mismatch_raises():
    base = registry([agent()], tax=("custom", "2.0"))
    head = registry([agent()], tax=("stoa-default-8", "1.0"))
    with pytest.raises(TaxonomyMismatch):
        diff_registries(base, head)


def test_schema_1_0_base_against_1_1_head():
    base = registry([agent(caps=["database_read"])], schema="1.0", tax=None)
    head = registry([agent(caps=["database_read", "email_send"])], schema="1.1")
    d = diff_registries(base, head)
    assert d["base"]["registry_schema"] == "1.0"
    assert d["summary"]["max_drift_severity"] == "high"


def test_dimension_delta_and_gate():
    base_dims = [{"id": "data-exfiltration", "exposure": "low"}]
    head_dims = [{"id": "data-exfiltration", "exposure": "elevated"}]
    base = registry([agent(caps=["database_read"], dims=base_dims)])
    head = registry([agent(caps=["database_read"], dims=head_dims)])
    d = diff_registries(base, head)
    delta = d["agents"]["changed"][0]["dimension_delta"]
    assert delta and delta[0]["direction"] == "increased"
    assert dimension_increase_exceeds(d, "data-exfiltration", "elevated") is True
    assert dimension_increase_exceeds(d, "data-exfiltration", "moderate") is True


def test_diff_is_deterministic():
    base = registry([agent(caps=["database_read"])])
    head = registry([agent(caps=["database_read", "shell_execution"]), agent(id="b", name="b2", caps=["email_send"])])
    a = json.dumps(diff_registries(base, head))
    b = json.dumps(diff_registries(base, head))
    assert a == b


def test_changelog_renders_escalation_and_marker():
    base = registry([agent(caps=[])])
    head = registry([agent(caps=["shell_execution"])])
    md = render_changelog(diff_registries(base, head), fail_on_drift="high")
    assert "Capability escalations" in md
    assert "shell_execution" in md
    assert "<!-- stoa-diff-comment:v1 -->" in md
    assert "would fail" in md
