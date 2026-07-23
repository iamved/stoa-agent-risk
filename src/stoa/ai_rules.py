"""AI-specific rules (Part II / Part IV §B).

Phase 2 rules are pattern/correlation only (no taint): AI005 supply-chain,
AI003 unobserved-approval, AI007 sampling-config, CTRL004 observability. All
are report-only. AI003/AI007/CTRL004 fire at most once per agent candidate
(the CTRL001–003 cadence); AI005 fires per call site.

Every finding carries the schema-1.1 fields (canonical name, OWASP mapping,
variant, evidence tags, templated message) and a redacted snippet.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from importlib import resources

from .config import StoaConfig
from .models import Finding, finding_fingerprint
from .redaction import redact_line
from .rules import (
    ADHOC_OUTPUT,
    APPROVAL_CONSTRUCT,
    BASE_URL_ASSIGN,
    BASE_URL_DYNAMIC,
    BASE_URL_HTTP,
    DATED_MODEL_SNAPSHOT,
    EMBEDDING_OR_MODERATION,
    FROM_PRETRAINED,
    HIGH_IMPACT_CAPABILITIES,
    LOCAL_HTTP_HOST,
    MODEL_ASSIGN,
    MODEL_CALL_SITE,
    OBSERVABILITY_CONSTRUCT,
    REVISION_KW,
    RULES,
    TEMPERATURE_DETERMINISTIC,
    TOOL_BINDING,
    TORCH_PICKLE_LOAD,
    TRUST_REMOTE_CODE,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

SNIPPET_MAX = 200
_DOWNLOAD_HINT = ("hf_hub_download", "snapshot_download", "urlretrieve",
                  "requests.get", "wget", "urlopen")


@lru_cache(maxsize=1)
def model_aliases() -> frozenset[str]:
    data = tomllib.loads(
        (resources.files("stoa") / "data" / "model_aliases.toml").read_text(encoding="utf-8")
    )
    return frozenset(data.get("aliases", []))


def _display_cap(cap: str) -> str:
    return cap.replace("_", "-")


def _line_of(content: str, index: int) -> int:
    return content.count("\n", 0, index) + 1


def _finding(
    config: StoaConfig,
    rule_id: str,
    path: str,
    line: int,
    snippet: str,
    confidence: str,
    message: str,
    *,
    severity: str | None = None,
    variant: str | None = None,
    tags: list[str] | None = None,
    supersedes: list[str] | None = None,
    context_key: str,
    title: str | None = None,
) -> Finding:
    spec = RULES[rule_id]
    sev = config.severity_overrides.get(rule_id, severity or spec.default_severity)
    return Finding(
        fingerprint=finding_fingerprint(rule_id, path, context_key),
        rule_id=rule_id,
        title=title or spec.title,
        category=spec.category,
        severity=sev,
        confidence=confidence,
        path=path,
        line=line,
        column=1,
        snippet=redact_line(snippet.strip())[:SNIPPET_MAX],
        remediation=spec.remediation,
        canonical_name=spec.canonical_name,
        owasp=spec.owasp,
        variant=variant,
        evidence_tags=sorted(tags) if tags else [],
        supersedes=sorted(supersedes) if supersedes else [],
        message=message,
    )


# ---------------------------------------------------------------------------
# AI005 — unpinned model / supply chain (per call site)
# ---------------------------------------------------------------------------

def detect_ai005(content: str, path: str, is_testlike: bool, config: StoaConfig) -> list[Finding]:
    if not config.rule_enabled("AI005"):
        return []
    findings: list[Finding] = []

    for match in TRUST_REMOTE_CODE.finditer(content):
        line = _line_of(content, match.start())
        snippet = content.splitlines()[line - 1] if line <= len(content.splitlines()) else match.group(0)
        findings.append(_finding(
            config, "AI005", path, line, snippet, "high",
            message=(
                f"`{snippet.strip()[:80]}` (line {line}) permits execution of "
                "repository-supplied code at load time, and no `revision` pin was "
                "observed (OWASP LLM05). Consider pinning a reviewed revision and "
                "removing `trust_remote_code`, or vendoring the modeling code."
            ),
            severity="high", variant="trust-remote-code",
            title="`trust_remote_code=True` observed on a model artifact load",
            context_key=f"trust-remote-code:{line}",
        ))

    for match in FROM_PRETRAINED.finditer(content):
        model_id, trailing = match.group(2), match.group(3)
        if REVISION_KW.search(trailing) or "trust_remote_code" in trailing:
            continue  # pinned, or already covered by trust-remote-code
        if model_id.startswith((".", "/")) or model_id.endswith((".bin", ".pt", ".safetensors")):
            continue  # local artifact path
        line = _line_of(content, match.start())
        findings.append(_finding(
            config, "AI005", path, line, match.group(0), "medium",
            message=(
                f"`from_pretrained(\"{model_id}\")` (line {line}) loads a model "
                "artifact with no `revision` pin observed (OWASP LLM05). Consider "
                "pinning a reviewed revision so the artifact cannot change under you."
            ),
            severity="medium", variant="unpinned-artifact",
            context_key=f"unpinned-artifact:{model_id}",
        ))

    if any(hint in content for hint in _DOWNLOAD_HINT):
        for match in TORCH_PICKLE_LOAD.finditer(content):
            line = _line_of(content, match.start())
            findings.append(_finding(
                config, "AI005", path, line, content.splitlines()[line - 1], "medium",
                message=(
                    f"A deserialization load (line {line}) reads an artifact obtained "
                    "from a download call in this file, with no integrity control "
                    "observed (OWASP LLM05). Consider verifying a checksum or pinning "
                    "the artifact."
                ),
                severity="medium", variant="unpinned-artifact",
                context_key=f"unpinned-load:{line}",
            ))

    if not is_testlike:
        seen_aliases: set[str] = set()
        for match in MODEL_ASSIGN.finditer(content):
            model_id = match.group(2) or match.group(4) or match.group(6)
            if not model_id or model_id in seen_aliases:
                continue
            floating = model_id.endswith("-latest") or model_id in model_aliases()
            if not floating or DATED_MODEL_SNAPSHOT.search(match.group(0)):
                continue
            seen_aliases.add(model_id)
            line = _line_of(content, match.start())
            findings.append(_finding(
                config, "AI005", path, line, match.group(0), "low",
                message=(
                    f"Model string `{model_id}` (line {line}) is a floating alias "
                    "that can resolve to different model versions over time (OWASP "
                    "LLM05). Consider pinning a dated snapshot for reproducibility."
                ),
                severity="low", variant="floating-alias",
                context_key=f"floating-alias:{model_id}",
            ))

    for match in BASE_URL_ASSIGN.finditer(content):
        value = match.group(1).strip()
        line = _line_of(content, match.start())
        http = BASE_URL_HTTP.match(value)
        if http and not LOCAL_HTTP_HOST.match(http.group(1)):
            findings.append(_finding(
                config, "AI005", path, line, match.group(0), "high",
                message=(
                    f"A model endpoint is configured over plaintext HTTP to "
                    f"`{http.group(1)}` (line {line}), which is neither local nor "
                    "TLS-protected (OWASP LLM05). Use an HTTPS endpoint."
                ),
                severity="medium", variant="insecure-endpoint",
                tags=["insecure_endpoint"], supersedes=["NET001"],
                context_key=f"insecure-endpoint:{line}",
            ))
        elif BASE_URL_DYNAMIC.search(value) and "in " not in content.lower():
            findings.append(_finding(
                config, "AI005", path, line, match.group(0), "low",
                message=(
                    f"A model endpoint (line {line}) is read from configuration with "
                    "no allowlist comparison observed in this file (OWASP LLM05). "
                    "Consider validating the endpoint against an allowlist."
                ),
                severity="info", variant="insecure-endpoint",
                tags=["dynamic_endpoint"],
                context_key=f"dynamic-endpoint:{line}",
            ))

    return findings


# ---------------------------------------------------------------------------
# Correlation rules (one per agent candidate): AI003, AI007, CTRL004
# ---------------------------------------------------------------------------

def detect_ai_correlations(
    content: str,
    path: str,
    symbol: str,
    capabilities: list[str],
    anchor_line: int,
    config: StoaConfig,
) -> list[Finding]:
    """AI003, AI007, CTRL004 for one agent candidate (≥ medium confidence)."""
    findings: list[Finding] = []
    high_impact = sorted(HIGH_IMPACT_CAPABILITIES.intersection(capabilities))
    has_tool = bool(TOOL_BINDING.search(content))

    # AI003 — high-impact tool capability with no approval construct observed.
    if config.rule_enabled("AI003") and has_tool and high_impact:
        if not APPROVAL_CONSTRUCT.search(content):
            caps = ", ".join(_display_cap(c) for c in high_impact)
            findings.append(_finding(
                config, "AI003", path, anchor_line,
                f"high-impact capability for candidate {symbol}", "low",
                message=(
                    f"Agent candidate `{symbol}` binds a tool whose body contains "
                    f"high-impact capability call sites ({caps}). No approval "
                    "construct (interrupt, confirmation guard, `requires_approval`) "
                    "was observed in this file. Approval logic may exist elsewhere "
                    "and would not be visible to this scan. One review prompt per "
                    "candidate — this notice will not repeat."
                ),
                context_key=f"AI003:{symbol}",
            ))

    # AI007 — high-impact-adjacent model calls without deterministic sampling.
    if config.rule_enabled("AI007") and high_impact:
        call_lines = [
            _line_of(content, m.start())
            for m in MODEL_CALL_SITE.finditer(content)
            if not EMBEDDING_OR_MODERATION.search(
                content[max(0, m.start() - 40): m.start() + 40]
            )
        ]
        if call_lines and not TEMPERATURE_DETERMINISTIC.search(content):
            lines_txt = ", ".join(str(n) for n in sorted(set(call_lines)))
            findings.append(_finding(
                config, "AI007", path, anchor_line,
                f"sampling config for candidate {symbol}", "low",
                message=(
                    f"Agent candidate `{symbol}` binds {_display_cap(high_impact[0])}, "
                    f"and model call sites in this file do not set a sampling bound "
                    f"(lines {lines_txt}). This is a proxy signal only: sampling "
                    "configuration influences, but does not determine, behavioral "
                    "consistency, and runtime evaluation is required for direct "
                    "assessment. One review prompt per candidate — this notice will "
                    "not repeat."
                ),
                context_key=f"AI007:{symbol}",
            ))

    # CTRL004 — tool-binding candidate with no observability construct at all.
    if config.rule_enabled("CTRL004") and has_tool:
        if not OBSERVABILITY_CONSTRUCT.search(content):
            tags = ["ad_hoc_output_observed"] if ADHOC_OUTPUT.search(content) else None
            findings.append(_finding(
                config, "CTRL004", path, anchor_line,
                f"observability for candidate {symbol}", "low",
                message=(
                    f"Agent candidate `{symbol}` binds tools executing capability "
                    "call sites; no logging or tracing construct was observed in "
                    "this file. Observability may exist at middleware or platform "
                    "level and would not be visible to this scan. One review prompt "
                    "per candidate."
                ),
                tags=tags,
                context_key=f"CTRL004:{symbol}",
            ))

    return findings
