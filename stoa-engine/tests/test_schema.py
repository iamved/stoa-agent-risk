"""Schema round-trip: the sample validates against both JSON Schema and the
Pydantic models, and survives a model -> dict -> model round-trip."""

import json
from pathlib import Path

import jsonschema

from stoa_engine.models import Submission

ROOT = Path(__file__).resolve().parent.parent


def test_json_schema_valid(sample_dict):
    schema = json.loads((ROOT / "schema" / "submission.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(sample_dict)


def test_pydantic_roundtrip(sample_dict):
    sub = Submission.model_validate(sample_dict)
    again = Submission.model_validate(sub.model_dump(by_alias=True, mode="json"))
    assert [s.agent_id for s in again.systems] == ["refund-agent", "support-copilot"]
    assert [len(s.performance.runs) for s in again.systems] == [40, 30]


def test_evidence_quadruple_preserved(sample_dict):
    sub = Submission.model_validate(sample_dict)
    hitl = sub.systems[0].posture.hitl
    # absence-of-evidence rule and quadruple integrity
    assert hitl.confidence.value == "confirmed"
    assert hitl.evidence  # non-empty evidence list
    frameworks = sub.systems[0].posture.frameworks
    assert frameworks.confidence.value == "unknown"  # never silently a "no"


def test_contradiction_present(sample_dict):
    sub = Submission.model_validate(sample_dict)
    statuses = [a.status.value for a in sub.systems[0].attestations]
    assert "contradicted" in statuses
