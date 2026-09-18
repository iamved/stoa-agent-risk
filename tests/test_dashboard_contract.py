"""M1 data contract: schema 1.8 additive fields, the risk register block,
the dashboard envelope, and history entries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import init_git_repo, run_git
from stoa.config import ConfigError, load_config
from stoa.dashboard import (
    ENVELOPE_SCHEMA,
    HISTORY_SCHEMA,
    build_envelope,
    build_register,
    entry_from_registry,
    load_history,
    record_history,
)
from stoa.declarations import Declarations
from stoa.report_json import build_document
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
MERIDIAN_PAY = REPO_ROOT / "examples" / "meridian-pay"


@pytest.fixture(scope="module")
def meridian_registry() -> dict:
    config = load_config(MERIDIAN_PAY)
    result = run_scan(ScanOptions(root=MERIDIAN_PAY, no_git=True), config)
    return build_document(result, config)


# --- schema 1.8 additive fields ----------------------------------------------


def test_score_before_controls_present_and_never_below_score(meridian_registry):
    seen = 0
    for agent in meridian_registry["agents"]:
        for entry in agent["dimension_assessment"]["dimensions"]:
            assert "score_before_controls" in entry
            assert entry["score_before_controls"] >= entry["score"]
            if not entry["controls_observed"]:
                assert entry["score_before_controls"] == entry["score"]
            seen += 1
    assert seen > 0


def test_head_commit_absent_without_git(meridian_registry):
    assert "head_commit" not in meridian_registry["repository"]


def test_head_commit_is_the_commit_date_not_wall_clock(tmp_path):
    repo = tmp_path / "repo"
    init_git_repo(repo)
    (repo / "agent.py").write_text("from openai import OpenAI\nclient = OpenAI()\n")
    run_git(repo, "add", ".")
    run_git(repo, "-c", "user.name=T", "-c", "user.email=t@example.invalid",
            "commit", "-q", "-m", "init", "--date", "2026-01-02T03:04:05+00:00")
    config = load_config(repo)
    doc1 = build_document(run_scan(ScanOptions(root=repo), config), config)
    doc2 = build_document(run_scan(ScanOptions(root=repo), config), config)
    head = doc1["repository"]["head_commit"]
    assert head["hash"] == doc1["repository"]["git_ref"]
    assert head["date"] and "T" in head["date"]
    assert doc1 == doc2, "same commit must produce a byte-identical registry"


# --- [[risk_register]] in stoa-declared.toml ---------------------------------


def _declared(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "stoa-declared.toml"
    path.write_text("version = 1\n" + body)
    return path


def test_register_entries_parse(tmp_path):
    path = _declared(tmp_path, '''
[[risk_register]]
risk_id = "unreviewed-high-impact-action/abcdef123456"
owner = "jane.doe@example.com"
treatment = "mitigate"
rationale = "Dual approval being added in Q4"
review_by = 2026-12-01
status = "in_progress"
''')
    decl, warnings = Declarations.load(path)
    assert warnings == []
    assert len(decl.risk_register) == 1
    entry = decl.risk_register[0]
    assert entry.treatment == "mitigate"
    assert entry.review_by == "2026-12-01"
    assert entry.status == "in_progress"


def test_register_invalid_values_warn_and_degrade(tmp_path):
    path = _declared(tmp_path, '''
[[risk_register]]
risk_id = "no-slash-here"

[[risk_register]]
risk_id = "boundary-leakage/abc"
treatment = "ignore"
review_by = "soon"
bogus = 1

[[risk_register]]
risk_id = "boundary-leakage/abc"
treatment = "accept"
''')
    decl, warnings = Declarations.load(path)
    assert len(decl.risk_register) == 1
    entry = decl.risk_register[0]
    assert entry.treatment is None and entry.review_by is None
    joined = "\n".join(warnings)
    assert "needs risk_id" in joined
    assert "treatment='ignore'" in joined
    assert "not an ISO date" in joined
    assert "unknown key risk_register[1].bogus" in joined
    assert "duplicate risk_register risk_id" in joined


def test_register_must_be_array_of_tables(tmp_path):
    path = _declared(tmp_path, "[risk_register]\nrisk_id = 'x/y'\n")
    with pytest.raises(ConfigError):
        Declarations.load(path)


def test_register_reaches_registry_and_unknown_agent_warns(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "agent.py").write_text("from openai import OpenAI\nclient = OpenAI()\n")
    (root / "stoa-declared.toml").write_text('''version = 1
[[risk_register]]
risk_id = "mandate-overreach/000000000000"
owner = "a@b.c"
treatment = "transfer"
''')
    config = load_config(root)
    result = run_scan(ScanOptions(root=root, no_git=True), config)
    doc = build_document(result, config)
    assert doc["risk_register"][0]["treatment"] == "transfer"
    assert any("names an agent id not found" in w for w in result.declaration_warnings)


# --- envelope ----------------------------------------------------------------


def test_envelope_shape_and_determinism(meridian_registry):
    env1 = build_envelope(meridian_registry)
    env2 = build_envelope(meridian_registry)
    assert env1["schema"] == ENVELOPE_SCHEMA
    assert json.dumps(env1, sort_keys=True) == json.dumps(env2, sort_keys=True)
    assert env1["registry"] is meridian_registry
    assert env1["diff"] is None and env1["history"] == []
    assert env1["assurance"]["schema"].startswith("assurance-packet/")
    assert env1["assurance"]["header"]["scan_timestamp"] is None  # no wall clock
    assert "AI002" in env1["rules"] and env1["rules"]["AI002"]["crosswalk"]["so_what"]
    dims = {d["id"] for d in env1["taxonomy"]["dimensions"]}
    assert "mandate-overreach" in dims and env1["taxonomy"]["groups"]["B"] == "Security"
    assert [f["function"] for f in env1["frameworks"]["nist_ai_rmf"]] == ["MAP", "MEASURE", "MANAGE", "GOVERN"]


def test_envelope_never_alters_scores(meridian_registry):
    before = json.dumps(meridian_registry, sort_keys=True)
    build_envelope(meridian_registry)
    assert json.dumps(meridian_registry, sort_keys=True) == before


# --- register rows -----------------------------------------------------------


def test_register_rows_copy_scanner_levels(meridian_registry):
    rows = build_register(meridian_registry)
    assert rows, "meridian-pay has elevated exposures"
    by_agent = {a["id"]: a for a in meridian_registry["agents"]}
    for row in rows:
        assert row["source"] == "scanned" and row["unmatched"] is False
        entry = next(d for d in by_agent[row["agent_id"]]["dimension_assessment"]["dimensions"]
                     if d["id"] == row["dimension_id"])
        assert row["residual"]["level"] == entry["exposure"]
        assert row["residual"]["score"] == entry["score"]
        assert row["inherent"]["score"] == entry["score_before_controls"]
        assert row["residual"]["level"] in ("moderate", "elevated")
    levels = [r["residual"]["level"] for r in rows]
    assert levels == sorted(levels, key=lambda l: ("elevated", "moderate").index(l))


def test_register_merges_declared_and_keeps_unmatched(meridian_registry):
    doc = json.loads(json.dumps(meridian_registry))
    first = build_register(doc)[0]
    doc["risk_register"] = [
        {"risk_id": first["risk_id"], "owner": "o@x.y", "treatment": "mitigate", "rationale": "r"},
        {"risk_id": "boundary-leakage/ffffffffffff", "owner": "", "treatment": "accept", "rationale": ""},
    ]
    rows = build_register(doc)
    merged = next(r for r in rows if r["risk_id"] == first["risk_id"])
    assert merged["declared"]["treatment"] == "mitigate" and merged["unmatched"] is False
    stale = next(r for r in rows if r["risk_id"] == "boundary-leakage/ffffffffffff")
    assert stale["source"] == "declared" and stale["unmatched"] is True and stale["residual"] is None


# --- history -----------------------------------------------------------------


def _fake_registry(hash_: str, date: str, elevated: int = 0) -> dict:
    return {
        "schema_version": "1.8", "tool": {"name": "stoa", "version": "0"},
        "repository": {"name": "r", "git_ref": hash_, "head_commit": {"hash": hash_, "date": date}},
        "summary": {"agent_candidates": 3, "findings": {"critical": 1}},
        "dimension_summary": {"dimensions": [
            {"id": "mandate-overreach", "max_exposure": "elevated", "agents_elevated": elevated, "agents_moderate": 0},
        ]},
    }


def test_history_entry_is_a_summary_not_a_registry():
    entry = entry_from_registry(_fake_registry("abc1234", "2026-01-01T00:00:00+00:00"))
    assert entry["schema"] == HISTORY_SCHEMA
    assert entry["head_commit"]["hash"] == "abc1234"
    assert entry["dimensions"][0]["max_exposure"] == "elevated"
    assert "agents" not in entry
    assert entry_from_registry({"repository": {}}) is None


def test_history_records_prunes_and_overwrites_same_commit(tmp_path):
    for i in range(4):
        record_history(tmp_path, _fake_registry(f"c{i}", f"2026-01-0{i + 1}T00:00:00+00:00", elevated=i), keep=3)
    entries = load_history(tmp_path)
    assert [e["head_commit"]["hash"] for e in entries] == ["c1", "c2", "c3"]
    record_history(tmp_path, _fake_registry("c3", "2026-01-04T00:00:00+00:00", elevated=9), keep=3)
    entries = load_history(tmp_path)
    assert len(entries) == 3 and entries[-1]["dimensions"][0]["agents_elevated"] == 9
    assert record_history(tmp_path, {"repository": {}}, keep=3) is None
    assert record_history(tmp_path, _fake_registry("c9", "2026-02-01T00:00:00+00:00"), keep=0) is None


def test_dashboard_config_section(tmp_path):
    (tmp_path / "stoa.toml").write_text("[dashboard]\nenabled = false\nhistory_keep = 4\n")
    config = load_config(tmp_path)
    assert config.dashboard_enabled is False and config.dashboard_history_keep == 4
    (tmp_path / "stoa.toml").write_text("[dashboard]\nhistory_keep = -1\n")
    with pytest.raises(ConfigError):
        load_config(tmp_path)
