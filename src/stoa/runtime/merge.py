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

# The two proxy dimensions the runtime tier may upgrade (design §8). Only
# these, only for agents with runtime evidence, only for the analyzed
# window — everything else keeps its scan-time assessment untouched.
_RUNTIME_UPGRADEABLE = ("conduct-variability", "dependency-drift")

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
)


def _runtime_dimension_exposure(
    dim_id: str, summary: dict, declared: dict, config: StoaConfig
) -> tuple[str, dict]:
    """Re-bucket one upgradeable dimension from observed signals.

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
        if entry.get("id") not in _RUNTIME_UPGRADEABLE:
            continue
        if entry.get("assessability") != "proxy":
            continue  # custom taxonomies may tier these differently; respect that
        exposure, basis = _runtime_dimension_exposure(
            entry["id"], summary, declared, config
        )
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


def merge_runtime_into_registry(
    registry: dict, analysis: dict, config: StoaConfig | None = None
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
    rt_findings = detect_runtime_contradictions(registry, analysis, config)

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
