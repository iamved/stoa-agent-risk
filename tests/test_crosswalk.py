"""Feature 1: the regulatory crosswalk (annotation layer, never scoring).

Guards the hard constraints: dimension scores unchanged (golden snapshot),
every rule mapped or explicitly blank, versioned + deterministic, SARIF
framework tags emitted, override path honored, and the says/never-says
vocabulary lint over every generated string.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stoa import SCHEMA_VERSION
from stoa.config import StoaConfig, load_config
from stoa.crosswalk import (
    OWASP_LLM_2025,
    Crosswalk,
    CrosswalkError,
    default_crosswalk,
    load_crosswalk,
)
from stoa.report_json import build_document
from stoa.rules import RULES
from stoa.sarif import build_sarif
from stoa.scanner import ScanOptions, run_scan

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "tests" / "fixtures" / "dimension_scores_golden.json"

# The says/never-says banned words (docs/dimensions.md). Whole-word match so
# "uncovered" / "discovery" don't false-positive.
BANNED = ("compliant", "protected", "covered", "mitigated", "safe", "secure")


def _scan(example: str):
    root = REPO_ROOT / example
    config = load_config(root)
    return run_scan(ScanOptions(root=root, no_git=True), config), config


# --- hard constraint 1: scores unchanged -------------------------------------


def test_dimension_scores_byte_identical_to_pre_change_golden():
    golden = json.loads(GOLDEN.read_text())
    current = {}
    for example in ("examples/support-desk", "examples/sparkwing"):
        result, _ = _scan(example)
        for agent in result.agents:
            key = f"{example}::{agent.path}::{agent.symbol}"
            current[key] = {
                d["id"]: {"score": d["score"], "exposure": d["exposure"]}
                for d in agent.dimension_assessment["dimensions"]
            }
    assert current == golden, "crosswalk must not change any dimension score/exposure"


# --- completeness: every rule mapped or honestly blank -----------------------


def test_every_rule_is_mapped_or_explicitly_blank():
    cw = default_crosswalk()
    for rule_id in RULES:
        entry = cw.entry(rule_id)
        assert entry.relation != "unmapped", f"{rule_id} missing from crosswalk.toml"
        # blank owasp is allowed (honest), but eu_ai_act must always be present
        assert entry.eu_ai_act, f"{rule_id} has no EU AI Act anchor"
        assert entry.so_what, f"{rule_id} has no plain-English gloss"


def test_owasp_values_are_valid_2025_classes_or_blank():
    valid = {code for code, _ in OWASP_LLM_2025}
    cw = default_crosswalk()
    for rule_id in RULES:
        owasp = cw.entry(rule_id).owasp_llm_2025
        assert owasp == "" or owasp in valid, f"{rule_id}: bad OWASP {owasp!r}"


def test_rt005_is_the_only_control_observed_relation():
    cw = default_crosswalk()
    control_observed = [
        rid for rid in RULES if cw.entry(rid).relation == "control-observed"
    ]
    assert control_observed == ["RT005"]


# --- registry wiring ----------------------------------------------------------


def test_findings_carry_crosswalk_tags_in_registry():
    result, config = _scan("examples/support-desk")
    doc = build_document(result, config)
    assert doc["schema_version"] == SCHEMA_VERSION == "1.8"
    assert doc["crosswalk"]["id"] == "stoa-crosswalk-1"
    assert doc["crosswalk"]["owasp_llm_version"] == "2025"

    all_findings = (
        [f for a in doc["agents"] for f in a["findings"]] + doc["repository_findings"]
    )
    assert all_findings
    for f in all_findings:
        assert "crosswalk" in f
        cw = f["crosswalk"]
        assert set(cw) == {"owasp_llm_2025", "eu_ai_act", "relation", "so_what"}

    ai001 = next((f for f in all_findings if f["rule_id"] == "AI001"), None)
    if ai001:
        assert ai001["crosswalk"]["owasp_llm_2025"] == "LLM01"
        assert ai001["crosswalk"]["eu_ai_act"] == "Art. 15"


def test_dimension_summary_gains_framework_rollup():
    result, config = _scan("examples/support-desk")
    doc = build_document(result, config)
    for dim in doc["dimension_summary"]["dimensions"]:
        assert "crosswalk" in dim
        assert set(dim["crosswalk"]) == {"owasp_llm_2025", "eu_ai_act"}
        # roll-up owasp codes are sorted LLM01..LLM10
        codes = dim["crosswalk"]["owasp_llm_2025"]
        assert codes == sorted(codes, key=lambda c: (0, int(c[3:])) if c.startswith("LLM") else (1, c))


def test_legacy_owasp_field_untouched_by_crosswalk():
    """The pre-existing AI-finding owasp dict is frozen for back-compat; the
    crosswalk is a separate object and must not overwrite it."""
    result, config = _scan("examples/support-desk")
    doc = build_document(result, config)
    ai = [f for a in doc["agents"] for f in a["findings"] if f["rule_id"].startswith("AI")]
    for f in ai:
        if "owasp" in f:  # legacy dict shape preserved
            assert set(f["owasp"]) == {"llm_top10_v1_1", "llm_top10_2025"}
            assert "owasp_llm_2025" not in f  # crosswalk lives under f["crosswalk"]


# --- SARIF wiring -------------------------------------------------------------


def test_sarif_carries_framework_tags():
    result, _ = _scan("examples/sparkwing")
    sarif = build_sarif(result)
    all_tags = [
        t for r in sarif["runs"][0]["results"] for t in r["properties"]["tags"]
    ]
    assert any(t.startswith("stoa-dim:") for t in all_tags)  # existing, still present
    assert any(t.startswith("owasp:LLM") for t in all_tags)
    assert any(t.startswith("euaiact:Art") for t in all_tags)


# --- override + unmapped ------------------------------------------------------


def test_override_path_and_unmapped_state(tmp_path):
    override = tmp_path / "crosswalk.toml"
    override.write_text(
        '[crosswalk]\nid = "custom"\nversion = "9.9"\n'
        '[rules.AI001]\nowasp_llm_2025 = "LLM01"\neu_ai_act = "Art. 99"\n'
        'relation = "exposure"\nso_what = "custom gloss"\n'
    )
    cw = load_crosswalk(override)
    assert cw.version == "9.9"
    assert cw.entry("AI001").eu_ai_act == "Art. 99"
    # a rule absent from the override renders as explicit unmapped, not dropped
    assert cw.entry("SEC001").relation == "unmapped"
    assert cw.entry("SEC001").so_what  # still has a rendering string


def test_config_crosswalk_path_is_loaded(tmp_path):
    (tmp_path / "cw.toml").write_text(
        '[crosswalk]\nid = "c"\nversion = "1.0"\n'
    )
    (tmp_path / "stoa.toml").write_text('[crosswalk]\npath = "cw.toml"\n')
    config = load_config(tmp_path)
    assert config.crosswalk_path == (tmp_path / "cw.toml").resolve()


def test_invalid_crosswalk_relation_rejected(tmp_path):
    bad = tmp_path / "bad.toml"
    bad.write_text(
        '[crosswalk]\nid = "x"\nversion = "1"\n'
        '[rules.AI001]\nrelation = "bogus"\n'
    )
    with pytest.raises(CrosswalkError, match="relation"):
        load_crosswalk(bad)


# --- versioned + deterministic ------------------------------------------------


def test_crosswalk_is_versioned():
    cw = default_crosswalk()
    assert cw.version_block()["version"] == cw.version
    assert cw.version_block()["owasp_llm_version"] == "2025"


def test_registry_deterministic_with_crosswalk():
    result, config = _scan("examples/sparkwing")
    a = json.dumps(build_document(result, config), sort_keys=True)
    result2, config2 = _scan("examples/sparkwing")
    b = json.dumps(build_document(result2, config2), sort_keys=True)
    assert a == b


# --- vocabulary lint (says / never-says) -------------------------------------


def test_crosswalk_glosses_pass_banned_words_lint():
    cw = default_crosswalk()
    for rule_id in RULES:
        gloss = cw.entry(rule_id).so_what.lower()
        words = set(gloss.replace(",", " ").replace(".", " ").replace("-", " ").split())
        for banned in BANNED:
            assert banned not in words, f"{rule_id} gloss uses banned word {banned!r}: {gloss!r}"
