"""XSS safety: repository-derived values never reach the report unescaped."""

from __future__ import annotations

from pathlib import Path

from stoa.config import StoaConfig
from stoa.models import (
    AgentCandidate,
    CommitInfo,
    Evidence,
    Finding,
    RepositoryInfo,
    ScanResult,
)
from stoa.report_html import html_text, render_html
from stoa.scanner import ScanOptions, run_scan

PAYLOAD = "</td><script>alert('xss')</script>"


def _malicious_result() -> ScanResult:
    finding = Finding(
        fingerprint="deadbeef",
        rule_id="SEC003",
        title="Interpolated SQL statement",
        category="injection",
        severity="high",
        confidence="medium",
        path=f"src/{PAYLOAD}.py",
        line=3,
        column=1,
        snippet=f'q = f"SELECT {PAYLOAD}"',
        remediation="Use parameterized queries instead of string interpolation.",
    )
    agent = AgentCandidate(
        id="abc123",
        name=PAYLOAD,
        symbol=PAYLOAD,
        path=f"src/{PAYLOAD}.py",
        language="python",
        confidence="high",
        detection_score=9,
        evidence=[Evidence(rule_id="AGENT_LANGCHAIN", line=1, description=PAYLOAD)],
        providers=[PAYLOAD],
        frameworks=["langchain"],
        integrations=[PAYLOAD],
        capabilities=["payment_access"],
        call_sites={PAYLOAD: 2},
        last_touched_by=f"Alice {PAYLOAD}",
        last_commit=CommitInfo(hash=PAYLOAD, date="2026-01-01T00:00:00+00:00"),
        codeowners=[f"@{PAYLOAD}"],
        findings=[finding],
    )
    return ScanResult(
        repository=RepositoryInfo(name=f"repo-{PAYLOAD}"),
        files_scanned=1,
        agents=[agent],
        findings=[finding],
    )


def test_html_text_escapes_quotes_and_tags():
    assert html_text('<a href="x">') == "&lt;a href=&quot;x&quot;&gt;"


def test_malicious_values_escaped_everywhere():
    html = render_html(_malicious_result(), StoaConfig())
    assert "<script>" not in html
    assert "alert('xss')" not in html
    assert "&lt;script&gt;" in html


def test_report_has_csp_and_no_javascript():
    html = render_html(_malicious_result(), StoaConfig())
    assert "Content-Security-Policy" in html
    assert "default-src 'none'" in html
    assert "<script" not in html.lower()


def test_scan_of_malicious_source_produces_escaped_report(tmp_path: Path):
    source = (
        "from langchain.agents import AgentExecutor\n"
        "from openai import OpenAI\n"
        "tools = [x]\n"
        f'name = "{PAYLOAD}"\n'
        "executor = AgentExecutor(agent=a, tools=tools)\n"
        "executor.invoke({})\n"
        f'q = f"SELECT x FROM t WHERE n = {{n}}"  # {PAYLOAD}\n'
    )
    (tmp_path / "evil_agent.py").write_text(source, encoding="utf-8")
    result = run_scan(ScanOptions(root=tmp_path, no_git=True))
    html = render_html(result, StoaConfig())
    assert "<script>" not in html


def test_details_used_for_evidence():
    html = render_html(_malicious_result(), StoaConfig())
    assert "<details>" in html
    assert "<summary>" in html
