"""The contradiction detector (Assurance layer Phase 4, `DECL001`-`DECL007`) —
cross-checks human-declared facts (``stoa-declared.toml``, Phase 1) against
what the scanner actually observed (autonomy inference, findings,
capabilities, permission tags). This is the differentiator: a self-attested
questionnaire can't catch "declared recommend-only, scanner found an
unguarded output-exec path with no approval gate" — Stoa can, because both
sides come from the same run.

Every DECL finding cites **both** sides of the contradiction: the usual
``path``/``line`` (code evidence — the signal that contradicts) *and*
``declared_ref`` (declaration evidence — the exact ``stoa-declared.toml`` key
path), so a reviewer is one click from each in the report.

Runs once per agent, after autonomy inference and declared-metadata
attachment are both finalized (it reads ``agent.autonomy_level``,
``agent.declared``, ``agent.permission_tags``, ``agent.findings`` — nothing
here does its own pattern matching over source). ``detect_stale_declarations``
is the one exception: it has no agent to attach to (the declared id no
longer matches any scanned agent), so it produces a repository-level finding
pointing at the declarations file itself.
"""

from __future__ import annotations

from .ai_rules import _finding
from .config import StoaConfig
from .models import AgentCandidate, Finding

_MONEY_TAGS = {"move_funds", "approve_transactions"}
_MONEY_OR_CONTRACT_TAGS = {"move_funds", "approve_transactions", "sign_contracts"}


def _declared_ref(declarations_path: str, agent_id: str, key: str | None = None) -> dict:
    base = f'agents."{agent_id}"'
    return {"path": declarations_path, "key": f"{base}.{key}" if key else base}


def _code_evidence(agent: AgentCandidate) -> tuple[str, int]:
    """Fallback code location for contradictions with no single triggering
    finding — the agent's own detection anchor, mirroring how CTRL001-004
    anchor to the agent's own evidence line rather than a specific call site."""
    if agent.evidence:
        return agent.path, agent.evidence[0].line
    return agent.path, 1


def detect_agent_contradictions(
    agent: AgentCandidate,
    declarations_path: str,
    declarations_exist: bool,
    config: StoaConfig,
) -> list[Finding]:
    """DECL001-DECL006 for one scanned agent."""
    findings: list[Finding] = []
    declared = agent.declared
    autonomy = agent.autonomy_level or {}
    fallback_path, fallback_line = _code_evidence(agent)

    if declared is not None:
        # DECL001 — declared intent contradicts inferred autonomy.
        intent = declared.get("autonomy_intent")
        level = autonomy.get("level")
        if intent in ("recommend_only", "human_approved") and level in (
            "bounded_autonomous", "unrestricted_autonomous",
        ):
            signals = autonomy.get("signals") or []
            path, line = (signals[0]["path"], signals[0]["line"]) if signals else (fallback_path, fallback_line)
            f = _finding(
                config, "DECL001", path, line,
                f"autonomy_intent={intent!r} vs inferred={level!r}", "high",
                message=(
                    f"Agent `{agent.symbol}` is declared `{intent}`, but the scanner "
                    f"inferred `{level}` from a side-effecting path with no correlated "
                    "approval gate. Either the declaration is stale, or the approval "
                    "control is missing."
                ),
                context_key=f"DECL001:{agent.id}",
            )
            f.declared_ref = _declared_ref(declarations_path, agent.id, "autonomy_intent")
            findings.append(f)

        # DECL002 — economic authority declared, no enforcement observed on a
        # money-moving path.
        economic_authority = declared.get("economic_authority")
        has_money_tag = bool(_MONEY_TAGS & set(agent.permission_tags))
        has_bounding = any(s.get("signal") == "bounding" for s in autonomy.get("signals") or [])
        if economic_authority and has_money_tag and not has_bounding:
            f = _finding(
                config, "DECL002", fallback_path, fallback_line,
                f"economic_authority declared for `{agent.symbol}`, no bounding signal", "high",
                message=(
                    f"Agent `{agent.symbol}` has a declared economic_authority limit, "
                    "but no cap check or rate limiter was observed on its money-moving "
                    "path (move_funds/approve_transactions)."
                ),
                context_key=f"DECL002:{agent.id}",
            )
            f.declared_ref = _declared_ref(declarations_path, agent.id, "economic_authority")
            findings.append(f)

        # DECL004 — scanner has evidence of a data class not in declared
        # data_classes (e.g. undeclared "authentication" alongside a leaked
        # credential finding).
        declared_classes = set(declared.get("data_classes") or [])
        has_secret_finding = any(f.rule_id in ("SEC001", "SEC002") for f in agent.findings)
        if has_secret_finding and "authentication" not in declared_classes:
            secret_finding = next(f for f in agent.findings if f.rule_id in ("SEC001", "SEC002"))
            f = _finding(
                config, "DECL004", secret_finding.path, secret_finding.line,
                f"credential evidence for `{agent.symbol}`, 'authentication' not declared", "high",
                message=(
                    f"Agent `{agent.symbol}` has evidence of authentication-class data "
                    f"({secret_finding.rule_id} at line {secret_finding.line}) that "
                    "isn't in its declared data_classes."
                ),
                context_key=f"DECL004:{agent.id}",
            )
            f.declared_ref = _declared_ref(declarations_path, agent.id, "data_classes")
            findings.append(f)

        # DECL005 — declared production, but no observability observed.
        if declared.get("production_status") == "production":
            ctrl004 = next((f for f in agent.findings if f.rule_id == "CTRL004"), None)
            if ctrl004 is not None:
                f = _finding(
                    config, "DECL005", ctrl004.path, ctrl004.line,
                    f"production_status=production for `{agent.symbol}`, CTRL004 fired", "high",
                    message=(
                        f"Agent `{agent.symbol}` is declared production, but no "
                        "observability construct was observed (CTRL004)."
                    ),
                    context_key=f"DECL005:{agent.id}",
                )
                f.declared_ref = _declared_ref(declarations_path, agent.id, "production_status")
                findings.append(f)
    else:
        # DECL006 — a declarations file exists, but doesn't mention this agent.
        if declarations_exist:
            f = _finding(
                config, "DECL006", fallback_path, fallback_line,
                f"no declaration entry for `{agent.symbol}`", "high",
                message=(
                    f"stoa-declared.toml exists but has no [agents.\"{agent.id}\"] "
                    f"entry for `{agent.symbol}`."
                ),
                context_key=f"DECL006:{agent.id}",
            )
            f.declared_ref = _declared_ref(declarations_path, agent.id)
            findings.append(f)

    # DECL003 — money/contract permission with no declared economic authority.
    # Independent of whether the agent is declared at all: an undeclared
    # money-moving agent is itself the gap DECL003 names.
    has_econ = bool(declared and declared.get("economic_authority"))
    if _MONEY_OR_CONTRACT_TAGS & set(agent.permission_tags) and not has_econ:
        f = _finding(
            config, "DECL003", fallback_path, fallback_line,
            f"money/contract permission for `{agent.symbol}`, no economic_authority declared", "high",
            message=(
                f"Agent `{agent.symbol}` can move funds, approve transactions, or "
                "sign contracts, but has no declared economic_authority."
            ),
            context_key=f"DECL003:{agent.id}",
        )
        f.declared_ref = _declared_ref(declarations_path, agent.id, "economic_authority")
        findings.append(f)

    return findings


def detect_stale_declarations(
    stale_ids: list[str],
    declarations_path: str,
    config: StoaConfig,
) -> list[Finding]:
    """DECL007 — declared agent ids no longer produced by the scanner. No
    agent to attach to; the finding points at the declarations file itself."""
    findings: list[Finding] = []
    for agent_id in stale_ids:
        f = _finding(
            config, "DECL007", declarations_path, 1,
            f'agents."{agent_id}"', "high",
            message=(
                f'stoa-declared.toml declares agent id "{agent_id}", which no '
                "longer matches any scanned agent."
            ),
            context_key=f"DECL007:{agent_id}",
        )
        f.declared_ref = _declared_ref(declarations_path, agent_id)
        findings.append(f)
    return findings
