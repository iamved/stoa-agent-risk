"""The runtime contradiction detector (RT001–RT005) — declared/scanned vs
**observed**.

Extends the DECL-family philosophy one layer out: DECL rules cross-check
declared facts against what the *scan* observed; RT rules cross-check
declared facts and scanned reach against what *traces* observed. Every
finding carries evidence from both sides, mirroring how DECL findings carry
``path``/``line`` + ``declared_ref``:

- ``path``/``line`` — the agent's code anchor (its detection evidence line);
- ``trace_ref`` — ``{file, line, span_id}``, the trace-side evidence;
- ``declared_ref`` — the exact ``stoa-declared.toml`` key contradicted,
  where a declaration is involved.

Emitted only by ``stoa runtime merge`` — never by ``stoa scan``. All five
rules are ``gateable=False``: v1 is shadow mode, and the only runtime gate
is the opt-in ``stoa runtime drift --fail-on-drift``.

Suppression: trace-anchored findings can't carry an inline
``# stoa: ignore[...]`` comment (there is no code line to annotate), so they
suppress via ``[runtime] suppress = ["RT002:<agent_id>"]`` in ``stoa.toml``
(``"*"`` for any agent). Suppressed findings stay counted and listed —
never dropped — matching the inline-suppression contract.

RT003 scope note: only capabilities in the scanner's own vocabulary are
compared against static reach — a custom capability id recorded by the SDK
cannot be meaningfully compared to what the scanner could have found, so it
is reported in the analysis document but never fires RT003. Data-class
signals are not detectable under redact-by-default tracing and are
documented as out of scope for v1.
"""

from __future__ import annotations

from ..config import StoaConfig
from ..models import finding_fingerprint
from ..rules import HIGH_IMPACT_CAPABILITIES, RULES
from .spans import scanner_vocabulary

_OVERSIGHT_INTENTS = ("recommend_only", "human_approved")


def _agent_anchor(agent: dict) -> tuple[str, int]:
    evidence = agent.get("evidence") or []
    if evidence:
        return agent["path"], evidence[0]["line"]
    return agent["path"], 1


def _declared_ref(agent_id: str, key: str | None = None) -> dict:
    base = f'agents."{agent_id}"'
    return {"path": "stoa-declared.toml", "key": f"{base}.{key}" if key else base}


def _suppression(config: StoaConfig, rule_id: str, agent_id: str) -> str | None:
    for entry in config.runtime_suppress:
        rule, _, target = entry.partition(":")
        if rule == rule_id and target in ("*", agent_id):
            return f"suppressed via [runtime].suppress ({entry!r}) in stoa.toml"
    return None


def _finding(
    config: StoaConfig,
    rule_id: str,
    agent: dict,
    context_key: str,
    message: str,
    *,
    confidence: str,
    trace_ref: dict | None = None,
    declared_ref: dict | None = None,
) -> dict:
    spec = RULES[rule_id]
    path, line = _agent_anchor(agent)
    reason = _suppression(config, rule_id, agent["id"])
    finding = {
        "fingerprint": finding_fingerprint(rule_id, path, context_key),
        "rule_id": rule_id,
        "title": spec.title,
        "category": spec.category,
        "severity": config.severity_overrides.get(rule_id, spec.default_severity),
        "confidence": confidence,
        "path": path,
        "line": line,
        "column": 1,
        "snippet": context_key,
        "remediation": spec.remediation,
        "suppressed": reason is not None,
        "suppression_reason": reason,
        "is_new": False,
        "message": message,
    }
    if trace_ref:
        finding["trace_ref"] = trace_ref
    if declared_ref:
        finding["declared_ref"] = declared_ref
    return finding


def detect_runtime_contradictions(
    registry: dict, analysis: dict, config: StoaConfig | None = None
) -> dict[str, list[dict]]:
    """RT001–RT005 for every registry agent, keyed by agent id.

    Pure function over the two documents; deterministic given identical
    inputs. Agents with no runtime evidence produce only RT004 (whose whole
    point is that absence).
    """
    config = config or StoaConfig()
    per_agent: dict = analysis.get("agents") or {}
    no_evidence = set(analysis.get("no_runtime_evidence") or [])
    window = analysis.get("window") or {}
    monitoring_declared = bool((registry.get("evidence") or {}).get("monitoring"))
    capability_vocab = scanner_vocabulary()["capability"]

    findings: dict[str, list[dict]] = {}
    for agent in registry.get("agents") or []:
        agent_id = agent["id"]
        declared = agent.get("declared") or {}
        summary = per_agent.get(agent_id)
        out: list[dict] = []

        if summary:
            refs = summary.get("trace_refs") or {}

            # RT001 — declared oversight, unapproved high-impact actions observed.
            intent = declared.get("autonomy_intent")
            unapproved_ref = refs.get("first_unapproved_high_impact")
            unapproved = summary["high_impact_actions"] - summary["high_impact_approved"]
            if (
                config.rule_enabled("RT001")
                and intent in _OVERSIGHT_INTENTS
                and unapproved > 0
            ):
                out.append(_finding(
                    config, "RT001", agent,
                    f"autonomy_intent={intent!r} vs {unapproved} unapproved high-impact action(s)",
                    message=(
                        f"Agent `{agent['symbol']}` is declared `{intent}`, but "
                        f"{unapproved} of {summary['high_impact_actions']} observed "
                        "high-impact action(s) in the analyzed window carried no "
                        "approval span. The declared oversight is not observed on "
                        "the live path."
                    ),
                    confidence="high",
                    trace_ref=unapproved_ref,
                    declared_ref=_declared_ref(agent_id, "autonomy_intent"),
                ))

            # RT002 — observed money movement vs declared economic authority.
            econ = declared.get("economic_authority") or {}
            max_amount = summary.get("max_observed_amount")
            per_action = econ.get("max_per_action")
            if (
                config.rule_enabled("RT002")
                and max_amount and per_action
                and max_amount.get("currency") == per_action.get("currency")
                and max_amount["amount"] > per_action.get("amount", float("inf"))
            ):
                out.append(_finding(
                    config, "RT002", agent,
                    f"observed {max_amount['amount']} {max_amount['currency']} > "
                    f"declared max_per_action {per_action['amount']}",
                    message=(
                        f"Agent `{agent['symbol']}` was observed moving "
                        f"{max_amount['amount']} {max_amount['currency']} in a single "
                        f"action; its declared economic authority caps a single action "
                        f"at {per_action['amount']} {per_action.get('currency')}."
                    ),
                    confidence="high",
                    trace_ref=refs.get("max_amount_span"),
                    declared_ref=_declared_ref(agent_id, "economic_authority.max_per_action"),
                ))
            daily = econ.get("daily_aggregate")
            totals = summary.get("window_total_amounts") or {}
            if (
                config.rule_enabled("RT002")
                and daily
                and totals.get(daily.get("currency", "USD"), 0) > daily.get("amount", float("inf"))
            ):
                observed_total = totals[daily.get("currency", "USD")]
                out.append(_finding(
                    config, "RT002", agent,
                    f"window total {observed_total} {daily.get('currency')} > "
                    f"declared daily_aggregate {daily['amount']}",
                    message=(
                        f"Agent `{agent['symbol']}`'s observed window total of "
                        f"{observed_total} {daily.get('currency')} exceeds its declared "
                        f"daily aggregate of {daily['amount']} {daily.get('currency')}. "
                        "The window total is compared against the declared daily limit; "
                        "an analysis window longer than a day overstates this."
                    ),
                    confidence="high",
                    trace_ref=refs.get("max_amount_span"),
                    declared_ref=_declared_ref(agent_id, "economic_authority.daily_aggregate"),
                ))

            # RT003 — observed reach beyond everything on paper.
            if config.rule_enabled("RT003"):
                static_caps = set(agent.get("capabilities") or [])
                for capability in summary.get("observed_capabilities") or []:
                    if capability not in capability_vocab:
                        continue  # custom id: not comparable to static reach
                    if capability in static_caps:
                        continue
                    out.append(_finding(
                        config, "RT003", agent,
                        f"observed capability {capability!r} absent from static registry",
                        message=(
                            f"Traces show agent `{agent['symbol']}` exercising "
                            f"`{capability}`, which the static scan never found for "
                            "this agent and no declaration covers — its observed "
                            "reach exceeds everything on paper. The code path may "
                            "live in an unscanned dependency or a separate service."
                        ),
                        confidence="medium",
                        trace_ref=(refs.get("first_capability_span") or {}).get(capability),
                    ))

            # RT005 — good news: declared-style oversight confirmed live.
            inferred = (agent.get("autonomy_level") or {}).get("level")
            if (
                config.rule_enabled("RT005")
                and inferred == "human_approved"
                and summary["high_impact_actions"] > 0
                and summary.get("approval_rate_high_impact") == 1.0
            ):
                high_impact_ref = next(
                    (ref for cap, ref in sorted(
                        (refs.get("first_capability_span") or {}).items())
                     if cap in HIGH_IMPACT_CAPABILITIES),
                    None,
                )
                out.append(_finding(
                    config, "RT005", agent,
                    f"approval observed on {summary['high_impact_actions']}/"
                    f"{summary['high_impact_actions']} high-impact action(s)",
                    message=(
                        f"Static inference classifies `{agent['symbol']}` as "
                        "`human_approved`, and traces confirm an approval span on "
                        f"100% of its {summary['high_impact_actions']} high-impact "
                        f"action(s) in the window {window.get('start')} → "
                        f"{window.get('end')}. Reported as observed — not as proof "
                        "of future behavior."
                    ),
                    confidence="high",
                    trace_ref=high_impact_ref,
                ))

        elif agent_id in no_evidence:
            # RT004 — observability claimed, not evidenced.
            if (
                config.rule_enabled("RT004")
                and declared.get("production_status") == "production"
                and monitoring_declared
            ):
                out.append(_finding(
                    config, "RT004", agent,
                    "production + monitoring declared, zero spans observed",
                    message=(
                        f"Agent `{agent['symbol']}` is declared production and "
                        "stoa-declared.toml points at monitoring evidence, but the "
                        f"analyzed trace window ({window.get('start')} → "
                        f"{window.get('end')}, {window.get('span_count')} span(s) "
                        "total) contains no spans for it. Observability is claimed "
                        "but not evidenced for this agent."
                    ),
                    confidence="medium",
                    declared_ref=_declared_ref(agent_id, "production_status"),
                ))

        if out:
            findings[agent_id] = out
    return findings
