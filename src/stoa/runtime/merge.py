"""Registry enrichment from runtime analysis (`stoa runtime merge`).

Purely additive over an existing ``stoa-registry.json`` document:

- per-agent ``runtime_evidence`` — the observed-behavior summary for agents
  with spans in the analyzed window;
- per-agent ``liveness_state`` — fills the field SCHEMA.md has reserved
  since 1.0 ("Runtime-derived Active / Idle / Deprecated status"):
  ``"active"`` (spans observed) or ``"idle"`` (registry agent, zero spans).
  ``"deprecated"`` stays reserved — inferring it needs more than one window;
- a top-level ``runtime`` block (window, coverage counts) so consumers and
  the assurance packet can state the evidence window without re-reading
  traces.

A registry that never passes through merge carries none of these fields and
serializes exactly as today — absence of the block *is* the compatibility
contract. Merge never mutates its input; it returns a deep copy.
"""

from __future__ import annotations

import copy

from .. import SCHEMA_VERSION
from ..config import StoaConfig
from ..rules import DATED_MODEL_SNAPSHOT
from .rt_rules import detect_runtime_contradictions

# Dimensions the runtime tier may re-bucket, and the span evidence each one
# needs before it is allowed to (1.1). A dimension whose evidence is absent
# in the window keeps its scan-time assessment untouched; a dimension with
# no honest runtime signal (injection-tamper-surface: redacted traces cannot
# show what reached the prompt) is never upgraded.
_RUNTIME_UPGRADEABLE = (
    "conduct-variability",
    "dependency-drift",
    "mandate-overreach",
    "unreviewed-high-impact-action",
    "control-coverage-gap",
    "boundary-leakage",
    "output-fidelity",
)
_NEVER_RUNTIME = ("injection-tamper-surface",)

_EVIDENCE_FIELDS = (
    "span_count",
    "spans_by_kind",
    "error_rate",
    "observed_capabilities",
    "observed_integrations",
    "observed_providers",
    "observed_models",
    "high_impact_actions",
    "high_impact_approved",
    "approval_rate_high_impact",
    "max_observed_amount",
    "window_total_amounts",
    "evidence_quality",
    "delegations_to",
    "trace_files",
    "observed_tools",
    "tool_counts",
    "money_actions",
    "money_actions_approved",
    "approval_rate_money",
    "flag_counts",
    "side_effect_counts",
)


def _runtime_dimension_exposure(
    dim_id: str, summary: dict, declared: dict, config: StoaConfig,
    agent_integrations: list | None = None,
) -> tuple[str | None, dict]:
    """Re-bucket one upgradeable dimension from observed signals. Returns
    ``(None, basis)`` when the window holds no evidence for that dimension,
    in which case the scan-time assessment stands.

    Deliberately a small, hand-recomputable table (thresholds in
    ``[runtime.dimensions]``), never a statistic a reviewer can't verify:

    - **dependency-drift** — elevated when more than one distinct model id
      was observed for the agent in-window (its model dependency actually
      changed under it); low when every observed id carries a dated
      snapshot/revision pin; moderate otherwise (stable but floating).
    - **conduct-variability** — elevated when the error rate meets
      ``error_rate_elevated`` or the observed approval rate contradicts a
      declared human gate; moderate at ``error_rate_moderate``; else low.

    Returns ``(exposure, basis)`` — the basis dict is serialized so the
    bucket is auditable from the registry alone.
    """
    actions = (summary.get("spans_by_kind") or {}).get("action", 0) + (summary.get("spans_by_kind") or {}).get("tool_call", 0)
    flags = summary.get("flag_counts") or {}

    if dim_id == "mandate-overreach":
        # Observed reach against the declaration: undeclared tools and amounts over the declared limit.
        basis = {"actions": actions, "undeclared_tool": flags.get("undeclared_tool", 0), "over_declared_limit": flags.get("over_declared_limit", 0), "observed_tools": summary.get("observed_tools") or []}
        if not actions:
            return None, basis
        if flags.get("over_declared_limit") or flags.get("undeclared_tool"):
            return "elevated", basis
        return "low", basis

    if dim_id == "unreviewed-high-impact-action":
        unapproved = summary.get("high_impact_actions", 0) - summary.get("high_impact_approved", 0)
        unapproved_money = summary.get("money_actions", 0) - summary.get("money_actions_approved", 0)
        basis = {"high_impact_actions": summary.get("high_impact_actions", 0), "unapproved_high_impact": unapproved, "money_actions": summary.get("money_actions", 0), "unapproved_money": unapproved_money}
        if not (summary.get("high_impact_actions") or summary.get("money_actions")):
            return None, basis
        return ("elevated" if unapproved or unapproved_money else "low"), basis

    if dim_id == "control-coverage-gap":
        rate_hi = summary.get("approval_rate_high_impact")
        rate_money = summary.get("approval_rate_money")
        basis = {"approval_rate_high_impact": rate_hi, "approval_rate_money": rate_money, "approval_spans": summary.get("approval_spans", 0)}
        rates = [r for r in (rate_hi, rate_money) if r is not None]
        if not rates:
            return None, basis
        worst = min(rates)
        gate = declared.get("autonomy_intent") in ("recommend_only", "human_approved")
        if worst < 1.0 and gate:
            return "elevated", basis
        if worst < 1.0:
            return "moderate", basis
        return "low", basis

    if dim_id == "boundary-leakage":
        sends = (summary.get("side_effect_counts") or {}).get("external_send", 0)
        static = set(agent_integrations or [])
        outside = sorted(i for i in (summary.get("observed_integrations") or []) if i not in static)
        basis = {"external_send": sends, "integrations_outside_scan": outside, "retrievals": (summary.get("spans_by_kind") or {}).get("retrieval", 0)}
        if not actions and not basis["retrievals"]:
            return None, basis
        if sends and outside:
            return "elevated", basis
        if sends or outside:
            return "moderate", basis
        return "low", basis

    if dim_id == "output-fidelity":
        llm_calls = summary.get("llm_calls", 0)
        llm_error_rate = summary.get("llm_error_rate") or 0.0
        basis = {"llm_calls": llm_calls, "llm_error_rate": llm_error_rate}
        if not llm_calls:
            return None, basis
        if llm_error_rate >= config.runtime_error_rate_elevated:
            return "elevated", basis
        if llm_error_rate >= config.runtime_error_rate_moderate:
            return "moderate", basis
        return "low", basis

    if dim_id == "dependency-drift":
        models = summary.get("observed_models") or []
        basis = {"distinct_models_observed": len(models), "models": models}
        if len(models) > 1:
            return "elevated", basis
        if models and all(DATED_MODEL_SNAPSHOT.search(m) for m in models):
            return "low", basis
        return ("moderate", basis) if models else ("low", basis)

    error_rate = summary.get("error_rate") or 0.0
    approval_rate = summary.get("approval_rate_high_impact")
    declared_gate = declared.get("autonomy_intent") in ("recommend_only", "human_approved")
    gate_contradicted = bool(
        declared_gate and approval_rate is not None and approval_rate < 1.0
    )
    basis = {
        "error_rate": error_rate,
        "approval_rate_high_impact": approval_rate,
        "declared_gate_contradicted": gate_contradicted,
    }
    if error_rate >= config.runtime_error_rate_elevated or gate_contradicted:
        return "elevated", basis
    if error_rate >= config.runtime_error_rate_moderate:
        return "moderate", basis
    return "low", basis


def _overlay_dimensions(agent: dict, summary: dict, config: StoaConfig) -> None:
    """Upgrade the agent's proxy dimensions to the ``runtime`` tier in place
    (``agent`` is already merge's deep copy). Entries keep their scan-time
    ``score`` (still labeled by ``contributing_*`` as static input); the
    authoritative runtime fields are ``exposure`` + ``runtime_basis`` +
    ``evidence_window``."""
    assessment = agent.get("dimension_assessment")
    if not assessment:
        return
    evidence_window = {
        "start": summary.get("first_ts"),
        "end": summary.get("last_ts"),
        "span_count": summary.get("span_count"),
    }
    if not (evidence_window["start"] and evidence_window["end"]
            and evidence_window["span_count"]):
        return  # never claim runtime assessability without a real window
    declared = agent.get("declared") or {}
    for entry in assessment.get("dimensions") or []:
        if entry.get("id") not in _RUNTIME_UPGRADEABLE or entry.get("id") in _NEVER_RUNTIME:
            continue
        # The two proxy dimensions keep the 1.4 contract: upgraded from proxy
        # only, so a custom taxonomy that tiers them otherwise is respected.
        # The dimensions added in 1.1 upgrade from their scan-time tier.
        allowed = ("proxy",) if entry["id"] in ("conduct-variability", "dependency-drift") else ("strong", "partial", "proxy")
        if entry.get("assessability") not in allowed:
            continue
        exposure, basis = _runtime_dimension_exposure(
            entry["id"], summary, declared, config, agent.get("integrations") or []
        )
        if exposure is None:
            continue  # no evidence for this dimension in the window: scan-time stands
        entry["static_exposure"] = entry.get("exposure")
        entry["assessability"] = "runtime"
        entry["exposure"] = exposure
        entry["evidence_window"] = evidence_window
        entry["runtime_basis"] = basis
        entry["statement"] = (
            f"Assessed from traces: {evidence_window['start']} → "
            f"{evidence_window['end']}, {evidence_window['span_count']} span(s). "
            "Observed in this window — not a claim about future behavior."
        )


def _recompute_dimension_summary(enriched: dict) -> None:
    """Refresh the top-level rollup after per-agent runtime upgrades so it
    never contradicts the entries beneath it. A summary row becomes
    ``runtime``-tier when at least one contributing agent entry did — a row
    still labeled ``proxy`` therefore can never show ``elevated``, keeping
    the cap invariant at both levels."""
    summary = enriched.get("dimension_summary")
    if not summary:
        return
    exposure_order = ["none-observed", "low", "moderate", "elevated", "not-assessable"]
    for row in summary.get("dimensions") or []:
        levels: list[str] = []
        any_runtime = False
        for agent in enriched.get("agents") or []:
            for entry in (agent.get("dimension_assessment") or {}).get("dimensions") or []:
                if entry["id"] == row["id"]:
                    levels.append(entry["exposure"])
                    if entry.get("assessability") == "runtime":
                        any_runtime = True
        if not levels:
            continue
        row["max_exposure"] = max(levels, key=exposure_order.index)
        row["agents_elevated"] = levels.count("elevated")
        row["agents_moderate"] = levels.count("moderate")
        if any_runtime:
            row["assessability"] = "runtime"


def _annotate(rt_findings: dict[str, list[dict]], config: StoaConfig) -> None:
    """Stamp the crosswalk entry on RT findings, as report_json does for the
    scan's own findings. Skipped silently when the crosswalk cannot load."""
    from ..crosswalk import CrosswalkError, load_crosswalk

    try:
        crosswalk = load_crosswalk(config.crosswalk_path)
    except CrosswalkError:
        return
    for findings in rt_findings.values():
        for finding in findings:
            finding["crosswalk"] = crosswalk.entry(finding["rule_id"]).to_dict()


def merge_runtime_into_registry(
    registry: dict, analysis: dict, config: StoaConfig | None = None,
    baseline: dict | None = None,
) -> dict:
    """Return a deep-copied registry enriched with runtime evidence.

    Also runs the RT contradiction detector (rt_rules.py) and appends its
    findings to each agent's ``findings`` list — sorted by the same
    ``(line, rule_id, fingerprint)`` key the scanner uses. The scan-time
    ``summary.findings`` counts are deliberately NOT updated: they describe
    the static scan; RT findings are counted in the top-level ``runtime``
    block instead, so the merge stays strictly additive.
    """
    config = config or StoaConfig()
    enriched = copy.deepcopy(registry)
    enriched["schema_version"] = SCHEMA_VERSION
    per_agent = analysis.get("agents") or {}
    window = (analysis.get("window") or {})
    rt_findings = detect_runtime_contradictions(registry, analysis, config, baseline)
    _annotate(rt_findings, config)

    covered = 0
    rt_count = 0
    for agent in enriched.get("agents") or []:
        summary = per_agent.get(agent["id"])
        if summary:
            covered += 1
            agent["runtime_evidence"] = {
                "window": {
                    "start": summary.get("first_ts") or window.get("start"),
                    "end": summary.get("last_ts") or window.get("end"),
                },
                **{f: summary.get(f) for f in _EVIDENCE_FIELDS},
            }
            agent["liveness_state"] = "active"
            _overlay_dimensions(agent, summary, config)
        else:
            agent["liveness_state"] = "idle"
        new_findings = rt_findings.get(agent["id"]) or []
        if new_findings:
            rt_count += len(new_findings)
            agent["findings"] = sorted(
                list(agent.get("findings") or []) + new_findings,
                key=lambda f: (f.get("line", 0), f.get("rule_id", ""),
                               f.get("fingerprint", "")),
            )

    _recompute_dimension_summary(enriched)

    enriched["runtime"] = {
        "analysis_schema": analysis.get("schema"),
        "window": {"start": window.get("start"), "end": window.get("end")},
        "span_count": window.get("span_count", 0),
        "agents_covered": covered,
        "agents_total": len(enriched.get("agents") or []),
        "unmatched_agents": len(analysis.get("unmatched_agents") or []),
        "rt_findings": rt_count,
        "evidence_quality": sorted(
            {
                (per_agent.get(a["id"]) or {}).get("evidence_quality")
                for a in enriched.get("agents") or []
                if per_agent.get(a["id"])
            }
        ),
    }
    return enriched
