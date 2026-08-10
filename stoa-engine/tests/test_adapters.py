"""Adapter completeness: for every template, each required field either
resolves or appears as a gap. Never silently missing."""

import pytest

from stoa_engine import adapters


@pytest.mark.parametrize("template", ["posture", "performance"])
def test_required_fields_resolve_or_gap(sample_dict, template):
    tpl = adapters.load_template(template)
    resolved = adapters.resolve(tpl, sample_dict)
    gaps = adapters.completeness_gaps(tpl, sample_dict)
    gap_ids = {g.field_id for g in gaps}

    for rf in resolved:
        if rf.required and not rf.resolved:
            fid = rf.field_id
            if rf.system_scoped:
                fid = f"{rf.field_id}[{rf._system_id}]"
            assert fid in gap_ids, f"required field {fid} neither resolved nor gapped"


def test_tristate_contradicted_warns():
    tpl = adapters.load_template("posture")
    submission = {
        "meta": {}, "systems": [{
            "agent_id": "x", "display_name": "X",
            "posture": {"hitl": {"value": True, "evidence": ["a:1"],
                                 "confidence": "contradicted", "scan_hash": None}},
        }],
    }
    fields = adapters.resolve(tpl, submission)
    hitl = [f for f in fields if f.field_id == "system.hitl"][0]
    assert hitl.display == "Not confirmed"
    assert hitl.warning is True


def test_unknown_is_not_a_no():
    tpl = adapters.load_template("posture")
    submission = {
        "meta": {}, "systems": [{
            "agent_id": "x", "display_name": "X",
            "posture": {"frameworks": {"value": [], "evidence": [],
                                       "confidence": "unknown", "scan_hash": None}},
        }],
    }
    fields = adapters.resolve(tpl, submission)
    fw = [f for f in fields if f.field_id == "system.frameworks"][0]
    assert fw.display == "Unknown"
    assert fw.resolved is False  # unknown required field becomes a gap


def test_templates_registered():
    assert set(adapters.available_templates()) == {"posture", "performance"}
