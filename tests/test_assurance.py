"""Assurance layer Phase 5: the assurance packet (stoa export --assurance)."""

from __future__ import annotations

from stoa.assurance import AREAS, build_assurance_packet, render_assurance_markdown


def finding(rule_id, severity="high", path="a.py", line=1, declared_ref=None, suppressed=False,
            title="x", message=None):
    return {
        "rule_id": rule_id, "severity": severity, "path": path, "line": line,
        "declared_ref": declared_ref, "suppressed": suppressed, "title": title, "message": message,
    }


def agent(id="a1", name="agt", path="a.py", providers=None, integrations=None,
          capabilities=None, permission_tags=None, findings=None, declared=None,
          autonomy_level=None, evidence=None):
    return {
        "id": id, "name": name, "path": path, "symbol": name,
        "providers": providers or [], "integrations": integrations or [],
        "capabilities": capabilities or [], "permission_tags": permission_tags or [],
        "findings": findings or [], "declared": declared, "autonomy_level": autonomy_level,
        "evidence": evidence or [{"rule_id": "AGENT_LANGCHAIN", "line": 1, "description": "x"}],
    }


def registry(agents=None, business=None, governance=None, evidence=None,
             repository_findings=None, schema_version="1.2"):
    return {
        "schema_version": schema_version,
        "tool": {"name": "stoa", "version": "0.3.0"},
        "repository": {"name": "repo", "git_ref": "abc123"},
        "summary": {"findings": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}},
        "agents": agents or [],
        "repository_findings": repository_findings or [],
        **({"business": business} if business else {}),
        **({"governance": governance} if governance else {}),
        **({"evidence": evidence} if evidence else {}),
    }


# --- structural completeness: every area present, gaps explicit ------------


def test_all_18_areas_present_even_for_empty_registry():
    packet = build_assurance_packet(registry())
    assert len(packet["areas"]) == 18
    assert {key for _, _, key, _, _ in AREAS} == set(packet["areas"].keys())


def test_empty_registry_has_zero_contradictions_and_valid_header():
    packet = build_assurance_packet(registry())
    assert packet["contradictions"] == []
    assert packet["header"]["agent_count"] == 0
    assert packet["header"]["contradiction_count"] == 0
    assert packet["schema"] == "assurance-packet/1.2"


def test_business_exposure_rows_are_all_not_provided_when_undeclared():
    packet = build_assurance_packet(registry())
    rows = packet["areas"]["business_exposure"]["rows"]
    assert len(rows) == 6  # every row from area 1 present
    assert all(r["status"] == "not_provided" for r in rows)


def test_business_exposure_declared_fields_get_declared_status():
    packet = build_assurance_packet(registry(business={"industries": ["fintech"]}))
    rows = {r["field"]: r for r in packet["areas"]["business_exposure"]["rows"]}
    assert rows["industries"]["status"] == "declared"
    assert rows["industries"]["evidence"]["key"] == "business.industries"
    assert rows["revenue"]["status"] == "not_provided"  # not captured, still listed


def test_claims_evidence_area_documents_reserved_observed_provenance():
    packet = build_assurance_packet(registry())
    row = packet["areas"]["claims_evidence"]["rows"][0]
    assert row["status"] == "not_provided"
    assert "observed" in row["evidence"]["note"]


# --- per-agent areas ----------------------------------------------------------


def test_ai_inventory_reflects_declared_and_scanned_fields():
    a = agent(id="a1", declared={"owner": "jane@x.com", "purpose": "billing"})
    packet = build_assurance_packet(registry([a]))
    entry = packet["areas"]["ai_inventory"]["agents"][0]
    assert entry["fields"]["owner"]["status"] == "declared"
    assert entry["fields"]["owner"]["evidence"]["key"] == 'agents."a1".owner'
    assert entry["fields"]["purpose"]["status"] == "declared"
    assert entry["fields"]["geography"]["status"] == "not_provided"
    assert entry["fields"]["agent"]["status"] == "scanned"


def test_autonomy_area_reflects_inferred_level_and_declared_intent():
    a = agent(
        id="a1",
        autonomy_level={"level": "unrestricted_autonomous", "signals": [], "reason": None},
        declared={"autonomy_intent": "recommend_only"},
    )
    packet = build_assurance_packet(registry([a]))
    entry = packet["areas"]["autonomy"]["agents"][0]
    assert entry["fields"]["inferred_level"]["status"] == "scanned"
    assert entry["fields"]["inferred_level"]["evidence"]["value"] == "unrestricted_autonomous"
    assert entry["fields"]["declared_intent"]["status"] == "declared"


def test_permissions_area_merges_tags_and_capabilities():
    a = agent(id="a1", permission_tags=["move_funds"], capabilities=["payment_access"])
    packet = build_assurance_packet(registry([a]))
    entry = packet["areas"]["permissions"]["agents"][0]
    assert entry["fields"]["permissions"]["status"] == "scanned"
    assert "move_funds" in entry["fields"]["permissions"]["evidence"]["value"]
    assert "payment_access" in entry["fields"]["permissions"]["evidence"]["value"]


def test_economic_authority_area_only_applies_to_money_moving_agents():
    money_agent = agent(id="a1", permission_tags=["move_funds"])
    other_agent = agent(id="a2", permission_tags=[])
    packet = build_assurance_packet(registry([money_agent, other_agent]))
    entries = packet["areas"]["economic_authority"]["agents"]
    assert len(entries) == 1  # only the money-moving agent applies
    assert entries[0]["agent_id"] == "a1"
    assert entries[0]["fields"]["economic_authority"]["status"] == "not_provided"


def test_technical_controls_area_flags_gap_findings():
    a = agent(id="a1", findings=[finding("CTRL004", severity="info", path="a.py", line=3)])
    packet = build_assurance_packet(registry([a]))
    entry = packet["areas"]["technical_controls"]["agents"][0]
    assert entry["fields"]["observability"]["status"] == "not_provided"
    assert entry["fields"]["observability"]["evidence"]["gap_rule_id"] == "CTRL004"
    assert entry["fields"]["authentication"]["status"] == "scanned"  # no CTRL001 finding


# --- contradictions section --------------------------------------------------


def test_contradictions_collected_from_agents_and_repository_findings():
    a = agent(id="a1", findings=[finding("DECL001", severity="critical",
                                          declared_ref={"path": "stoa-declared.toml", "key": "x"})])
    repo_finding = finding("DECL007", severity="low", path="stoa-declared.toml",
                            declared_ref={"path": "stoa-declared.toml", "key": "y"})
    packet = build_assurance_packet(registry([a], repository_findings=[repo_finding]))
    rule_ids = {c["rule_id"] for c in packet["contradictions"]}
    assert rule_ids == {"DECL001", "DECL007"}
    assert packet["header"]["contradiction_count"] == 2


def test_suppressed_contradictions_excluded():
    a = agent(id="a1", findings=[finding("DECL001", suppressed=True)])
    packet = build_assurance_packet(registry([a]))
    assert packet["contradictions"] == []


def test_non_decl_findings_never_appear_as_contradictions():
    a = agent(id="a1", findings=[finding("SEC001", severity="critical")])
    packet = build_assurance_packet(registry([a]))
    assert packet["contradictions"] == []


# --- determinism ---------------------------------------------------------------


def test_packet_body_deterministic_across_calls():
    a = agent(id="a1", declared={"owner": "x"}, permission_tags=["move_funds"])
    reg = registry([a])
    p1 = build_assurance_packet(reg, git_sha="abc", scan_timestamp="t1")
    p2 = build_assurance_packet(reg, git_sha="abc", scan_timestamp="t1")
    assert p1 == p2


def test_header_is_the_only_place_caller_supplied_values_appear():
    reg = registry()
    p1 = build_assurance_packet(reg, git_sha="sha1", scan_timestamp="t1")
    p2 = build_assurance_packet(reg, git_sha="sha2", scan_timestamp="t2")
    assert p1["areas"] == p2["areas"]
    assert p1["contradictions"] == p2["contradictions"]
    assert p1["header"] != p2["header"]


# --- markdown rendering -------------------------------------------------------


def test_markdown_renders_all_areas_and_contradictions():
    a = agent(id="a1", findings=[finding("DECL001", severity="critical", path="a.py", line=5,
                                          declared_ref={"path": "stoa-declared.toml", "key": "x.y"})])
    packet = build_assurance_packet(registry([a]), git_sha="abc", scan_timestamp="t")
    md = render_assurance_markdown(packet)
    assert "## Stoa · Assurance Packet" in md
    assert "DECL001" in md
    assert "a.py:5" in md
    assert "x.y" in md
    for _, _, _, name, _ in AREAS:
        assert f"— {name} (" in md or name in md


def test_markdown_no_contradictions_says_none_found():
    packet = build_assurance_packet(registry())
    md = render_assurance_markdown(packet)
    assert "None found." in md
