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
    for name in ("meridian-pay.envelope.json", "meridian-pay.baseline.json", "hostile.envelope.json",
                 "first-run.envelope.json", "no-agents.envelope.json"):
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


def test_first_run_fixture_has_nothing_a_customer_did_not_supply():
    """The fixture stands for a first `stoa scan`: if it ever gains declared
    or applicant data, the UI's empty states stop being tested."""
    env = json.loads((FIXTURES / "first-run.envelope.json").read_text())
    assert env["registry"]["agents"], "first-run must still find agents"
    assert not any(a.get("declared") for a in env["registry"]["agents"])
    assert env["diff"] is None and env["baseline"] is None and env["history"] == []
    assert env["intake"] is None
    assert env["assessment"]["identity_source"] == "sample"
    assert env["assessment"]["performance_source"] == "sample"
    assert "meridian" not in json.dumps(env["assessment"]["identity"]).lower()


def test_no_agents_fixture_is_empty():
    env = json.loads((FIXTURES / "no-agents.envelope.json").read_text())
    assert env["registry"]["agents"] == []
    assert env["register"] == [] and env["graph"]["nodes"] == []


def test_hosted_demo_carries_the_current_fixture():
    """site/dashboard/index.html is the Meridian Pay fixture run through
    `stoa dashboard`. Compared on the embedded data, not the whole file, so
    the check needs no Node build: run scripts/build_site_dashboard.sh."""
    import re

    from stoa.dashboard.inject import escape_json_for_script, redact_document

    page = (REPO_ROOT / "site" / "dashboard" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<script id="stoa-data" type="application/json">(.*?)</script>', page, re.DOTALL)
    assert match, "hosted demo has no embedded data"
    envelope = {**json.loads((FIXTURES / "meridian-pay.envelope.json").read_text()), "demo": True}
    assert match.group(1) == escape_json_for_script(redact_document(envelope)), (
        "site/dashboard/index.html is stale: run scripts/build_site_dashboard.sh"
    )
