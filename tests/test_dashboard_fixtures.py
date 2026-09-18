"""The committed UI fixtures must be exactly what the current scanner
produces. A detector or schema change without `python ui/fixtures/build.py`
fails here, so the UI is never developed against stale data."""

from __future__ import annotations

import json
import runpy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "ui" / "fixtures"


def test_committed_fixtures_are_current(tmp_path):
    module = runpy.run_path(str(FIXTURES / "build.py"))
    module["build"](tmp_path)
    for name in ("meridian-pay.envelope.json", "meridian-pay.baseline.json", "hostile.envelope.json"):
        fresh = (tmp_path / name).read_bytes()
        committed = (FIXTURES / name).read_bytes()
        assert fresh == committed, f"{name} is stale: run `python ui/fixtures/build.py`"


def test_fixture_builder_is_deterministic(tmp_path):
    module = runpy.run_path(str(FIXTURES / "build.py"))
    module["build"](tmp_path / "a")
    module["build"](tmp_path / "b")
    for name in ("meridian-pay.envelope.json", "large.envelope.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


def test_hostile_fixture_plants_every_payload_class():
    env = json.loads((FIXTURES / "hostile.envelope.json").read_text())
    text = json.dumps(env, ensure_ascii=False)
    assert "</script><script>alert(1)</script>" in text
    assert "<!-- comment -->" in text
    assert " " in text and " " in text
    assert "${{7*7}}" in text
