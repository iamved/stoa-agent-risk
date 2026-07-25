"""Interactive graph section: CSP hash-pinning, JSON blob safety, offline-ness."""

from __future__ import annotations

import base64
import hashlib
import json
import re

from stoa.config import StoaConfig
from stoa.models import AgentCandidate, Evidence, Finding, RepositoryInfo, ScanResult
from stoa.report_graph import GLUE_SCRIPT_HASH, VENDOR_SCRIPT_HASH, csp_script_src
from stoa.report_html import render_html


def _result():
    finding = Finding(
        fingerprint="f1", rule_id="SEC001", title="x", category="secret",
        severity="critical", confidence="high", path="a.py", line=1, column=1,
        snippet="[REDACTED]", remediation="x",
    )
    agent = AgentCandidate(
        id="agentid1", name="my_agent", symbol="run", path="a.py", language="python",
        confidence="high", detection_score=8,
        evidence=[Evidence(rule_id="AGENT_LANGCHAIN", line=1, description="LangChain agent")],
        providers=["openai"], frameworks=["langchain"], integrations=["stripe"],
        capabilities=["payment_access"], call_sites={"stripe": 2}, findings=[finding],
    )
    return ScanResult(
        repository=RepositoryInfo(name="repo"), files_scanned=1,
        agents=[agent], findings=[finding],
    )


def test_graph_section_present_by_default():
    html = render_html(_result(), StoaConfig())
    assert "Architecture graph" in html
    assert 'id="stoa-graph-data"' in html


def test_no_graph_config_omits_section_and_scripts():
    html = render_html(_result(), StoaConfig(no_graph=True))
    assert "Architecture graph" not in html
    assert "<script" not in html.lower()
    assert "script-src" not in html


def test_json_data_blob_is_parseable_with_expected_counts():
    html = render_html(_result(), StoaConfig())
    m = re.search(
        r'<script type="application/json" id="stoa-graph-data">(.*?)</script>',
        html, re.DOTALL,
    )
    assert m, "graph data script tag not found"
    payload = json.loads(m.group(1))
    # 1 agent + 1 tool(stripe) + 1 tool(openai) + 1 resource(payment_access)
    assert len(payload["nodes"]) == 4
    assert len(payload["edges"]) == 3
    node_types = {n["type"] for n in payload["nodes"]}
    assert node_types == {"agent", "tool", "resource"}


def test_csp_meta_carries_both_script_hashes():
    html = render_html(_result(), StoaConfig())
    assert csp_script_src() in html
    assert f"sha256-{VENDOR_SCRIPT_HASH}" in html
    assert f"sha256-{GLUE_SCRIPT_HASH}" in html
    assert "unsafe-inline" not in html.split("script-src", 1)[1].split(";")[0]


def test_emitted_script_hashes_match_declared_constants():
    """The declared CSP hashes must equal SHA-256 of the *exact* emitted
    <script> content, or the browser would refuse to run the real scripts."""
    html = render_html(_result(), StoaConfig())
    scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert len(scripts) == 2  # vendor, then glue
    hashes = [
        base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode("ascii")
        for s in scripts
    ]
    assert hashes == [VENDOR_SCRIPT_HASH, GLUE_SCRIPT_HASH]


def test_no_external_resources_anywhere():
    """No tag/attribute that would trigger an actual network request. A plain
    <a href> credit link is fine (user-initiated navigation, not a fetch —
    CSP default-src doesn't gate it); so are inert URLs inside the vendored
    library's own license comments, which are never fetched or executed."""
    html = render_html(_result(), StoaConfig())
    assert not re.search(r'<script[^>]+\bsrc\s*=\s*["\']https?://', html)
    assert not re.search(r'<link[^>]+\bhref\s*=\s*["\']https?://', html)
    assert not re.search(r'<img[^>]+\bsrc\s*=\s*["\']https?://', html)
    assert "@import" not in html
    assert "XMLHttpRequest" not in html
    assert "fetch(" not in html


def test_empty_registry_graph_section_shows_friendly_message_not_crash():
    result = ScanResult(repository=RepositoryInfo(name="repo"), files_scanned=1, agents=[], findings=[])
    html = render_html(result, StoaConfig())
    assert "Architecture graph" in html
    assert "No agent candidates detected" in html
