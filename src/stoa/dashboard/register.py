"""Risk-register rows derived from a registry document.

One row per (dimension, agent) whose scored exposure is ``moderate`` or
``elevated``. Every number on a row is copied from the agent's
``dimension_assessment`` entry: inherent is the bucket of
``score_before_controls`` (schema 1.8), residual is the scanner's own
``exposure``. There is no second formula here — the same bucket thresholds
and the same proxy-tier cap ``dimensions.py`` applies are reused verbatim, so
a row can never show a level the scanner would not.

Declared state (`[[risk_register]]` in stoa-declared.toml, echoed by the
scanner as the registry's top-level ``risk_register``) is merged by
``risk_id``. A declared entry that matches no derived row is kept, flagged
``unmatched``, so a stale declaration is visible rather than dropped.
"""

from __future__ import annotations

from ..dimensions import EXPOSURE_ORDER, PROXY_CAP, _bucket

ROW_LEVELS = ("moderate", "elevated")


def _level(score: int, assessability: str) -> str:
    level = _bucket(int(score))
    if assessability == "proxy" and level == "elevated":
        level = PROXY_CAP
    return level


def _dimension_names(registry: dict) -> dict[str, str]:
    summary = registry.get("dimension_summary") or {}
    return {d["id"]: d.get("name", d["id"]) for d in summary.get("dimensions", [])}


def build_register(registry: dict) -> list[dict]:
    """Derive register rows and merge declared treatments. Deterministic."""
    names = _dimension_names(registry)
    declared_by_id = {e["risk_id"]: e for e in registry.get("risk_register") or []}
    rows: list[dict] = []
    matched: set[str] = set()

    for agent in registry.get("agents") or []:
        assessment = agent.get("dimension_assessment") or {}
        for entry in assessment.get("dimensions") or []:
            if entry.get("exposure") not in ROW_LEVELS:
                continue
            dim_id = entry["id"]
            risk_id = f"{dim_id}/{agent['id']}"
            before = entry.get("score_before_controls", entry.get("score", 0))
            declared = declared_by_id.get(risk_id)
            if declared is not None:
                matched.add(risk_id)
            rows.append({
                "risk_id": risk_id,
                "source": "scanned",
                "dimension_id": dim_id,
                "dimension_name": names.get(dim_id, dim_id),
                "group": entry.get("group", ""),
                "assessability": entry.get("assessability", ""),
                "agent_id": agent["id"],
                "agent_name": agent.get("display_name") or agent.get("name"),
                "agent_path": agent.get("path"),
                "inherent": {"score": before, "level": _level(before, entry.get("assessability", ""))},
                "residual": {"score": entry.get("score", 0), "level": entry["exposure"]},
                "controls_observed": list(entry.get("controls_observed") or []),
                "contributing_findings": list(entry.get("contributing_findings") or []),
                "contributing_capabilities": list(entry.get("contributing_capabilities") or []),
                "statement": entry.get("statement", ""),
                "declared": dict(declared) if declared is not None else None,
                "unmatched": False,
            })

    for risk_id, declared in declared_by_id.items():
        if risk_id in matched:
            continue
        dim_id, _, agent_id = risk_id.partition("/")
        rows.append({
            "risk_id": risk_id,
            "source": "declared",
            "dimension_id": dim_id,
            "dimension_name": names.get(dim_id, dim_id),
            "group": "",
            "assessability": "",
            "agent_id": agent_id,
            "agent_name": None,
            "agent_path": None,
            "inherent": None,
            "residual": None,
            "controls_observed": [],
            "contributing_findings": [],
            "contributing_capabilities": [],
            "statement": "Declared, but no scored exposure at moderate or above matches this risk id in the current scan.",
            "declared": dict(declared),
            "unmatched": True,
        })

    def sort_key(row: dict) -> tuple:
        residual = row["residual"]["level"] if row["residual"] else "none-observed"
        return (-EXPOSURE_ORDER.index(residual), row["dimension_id"], row["agent_path"] or "", row["agent_id"])

    rows.sort(key=sort_key)
    return rows
