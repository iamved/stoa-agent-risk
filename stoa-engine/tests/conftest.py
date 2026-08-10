import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "examples" / "sample_submission.json"


@pytest.fixture(scope="session")
def sample_path() -> Path:
    return SAMPLE


@pytest.fixture(scope="session")
def sample_dict() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))
