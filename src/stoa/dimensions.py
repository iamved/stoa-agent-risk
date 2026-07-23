"""Dimension exposure mapping (Part IV §A).

Turns findings, capabilities, and observed controls into a per-agent,
per-dimension exposure assessment using a data-driven taxonomy
(`data/dimensions.toml`, replaceable via `stoa.toml [dimensions] taxonomy`).

Scoring is deterministic (Part IV §A.5):

    score = min(100, Σ finding_weight(sev,conf) + Σ capability_weight − Σ control_credit)   (floor 0)

buckets: 0 → none-observed · 1–24 → low · 25–54 → moderate · ≥55 → elevated,
then a proxy-tier cap forces proxy dimensions to at most `moderate` — Stoa must
never imply it measured behavior it only saw a config signal for. Weights are
data, not code; changing them bumps the taxonomy version.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .models import AgentCandidate, Finding
from .rules import (
    APPROVAL_CONSTRUCT,
    CONTROL_PATTERNS,
    DATED_MODEL_SNAPSHOT,
    OBSERVABILITY_CONSTRUCT,
    TEMPERATURE_DETERMINISTIC,
)

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

EXPOSURE_ORDER = ["none-observed", "low", "moderate", "elevated", "not-assessable"]
PROXY_CAP = "moderate"
UNCLASSIFIED = "unclassified"


class TaxonomyError(Exception):
    """Invalid taxonomy; maps to exit code 2."""


@dataclass(frozen=True)
class Dimension:
    id: str
    name: str
    definition: str
    assessability: str


@dataclass
class Taxonomy:
    id: str
    version: str
    dimensions: list[Dimension]
    finding_weights: dict[str, int]
    confidence_multipliers: dict[str, float]
    capability_weight: float
    provider_weight: float
    control_credit: float
    rule_dimensions: dict[str, list[str]]
    capability_dimensions: dict[str, list[str]]
    control_dimensions: dict[str, list[str]]

    @property
    def dimension_ids(self) -> list[str]:
        return [d.id for d in self.dimensions]

    def assessability(self, dim_id: str) -> str:
        for d in self.dimensions:
            if d.id == dim_id:
                return d.assessability
        return "partial"


def _parse_taxonomy(data: dict, source: str) -> Taxonomy:
    tax = data.get("taxonomy", {})
    dims_raw = data.get("dimensions", [])
    if not tax.get("id") or not tax.get("version") or not dims_raw:
        raise TaxonomyError(f"{source}: taxonomy needs [taxonomy] id/version and [[dimensions]]")
    dimensions = [
        Dimension(d["id"], d.get("name", d["id"]), d.get("definition", ""),
                  d.get("assessability", "partial"))
        for d in dims_raw
    ]
    scoring = data.get("scoring", {})
    return Taxonomy(
        id=tax["id"],
        version=str(tax["version"]),
        dimensions=dimensions,
        finding_weights=data.get("finding_weights", {}),
        confidence_multipliers=data.get("confidence_multipliers", {}),
        capability_weight=float(scoring.get("capability_weight", 18)),
        provider_weight=float(scoring.get("provider_weight", 8)),
        control_credit=float(scoring.get("control_credit", 20)),
        rule_dimensions=data.get("rule_dimensions", {}),
        capability_dimensions=data.get("capability_dimensions", {}),
        control_dimensions=data.get("control_dimensions", {}),
    )


@lru_cache(maxsize=1)
def default_taxonomy() -> Taxonomy:
    text = (resources.files("stoa") / "data" / "dimensions.toml").read_text(encoding="utf-8")
    return _parse_taxonomy(tomllib.loads(text), "default taxonomy")


def load_taxonomy(path: Path | None) -> Taxonomy:
    if path is None:
        return default_taxonomy()
    if not path.is_file():
        raise TaxonomyError(f"taxonomy file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise TaxonomyError(f"invalid taxonomy TOML in {path}: {exc}") from exc
    return _parse_taxonomy(data, str(path))


def _rule_dims(finding: Finding, taxonomy: Taxonomy) -> list[str]:
    """Dimensions a finding contributes to (AI005 is variant-aware)."""
    if finding.rule_id == "AI005":
        v = finding.variant
        if v == "floating-alias":
            return ["behavioral-instability", "model-drift"]
        if v in ("trust-remote-code", "unpinned-artifact"):
            return ["adversarial-manipulation"]
        if v == "insecure-endpoint":
            return ["model-drift"]
    return taxonomy.rule_dimensions.get(finding.rule_id, [])


def observed_controls(content: str) -> set[str]:
    """Positive control evidence — the one place Stoa reports good news."""
    controls: set[str] = set()
    if APPROVAL_CONSTRUCT.search(content):
        controls.add("approval")
    if CONTROL_PATTERNS["CTRL001"].search(content):
        controls.add("authentication")
    if CONTROL_PATTERNS["CTRL002"].search(content):
        controls.add("validation")
    if CONTROL_PATTERNS["CTRL003"].search(content):
        controls.add("rate_limit")
    if OBSERVABILITY_CONSTRUCT.search(content):
        controls.add("observability")
    if TEMPERATURE_DETERMINISTIC.search(content):
        controls.add("deterministic_sampling")
    if DATED_MODEL_SNAPSHOT.search(content):
        controls.add("pinned_model")
    return controls


def _bucket(score: int) -> str:
    if score <= 0:
        return "none-observed"
    if score < 25:
        return "low"
    if score < 55:
        return "moderate"
    return "elevated"


def _statement(assessability, exposure, n_find, n_cap, controls) -> str:
    if assessability == "proxy":
        base = "Proxy signals only"
        if exposure == "none-observed":
            return base + ": no adverse config signal observed. Runtime evaluation required for direct assessment."
        return (f"{base}: {n_find} finding(s) and {n_cap} capability signal(s) contribute. "
                "Runtime evaluation required for direct assessment.")
    if exposure == "none-observed":
        if controls:
            return f"No exposure observed; controls observed: {', '.join(sorted(controls))}."
        return "No exposure observed in scanned files."
    control_phrase = (f" {len(controls)} mitigating control(s) observed"
                      if controls else " no mitigating control observed in scanned files")
    return f"{n_find} finding(s) and {n_cap} capability signal(s) contribute exposure;{control_phrase}."


def assess_agent(agent: AgentCandidate, content: str, providers: list[str],
                 taxonomy: Taxonomy) -> dict:
    """Build the per-agent `dimension_assessment` block (deterministic)."""
    controls = observed_controls(content)
    active_findings = [f for f in agent.findings if not f.suppressed]
    entries = []
    unclassified_findings: list[str] = []

    for dim in taxonomy.dimensions:
        score = 0.0
        contrib_find: list[str] = []
        contrib_cap: list[str] = []
        controls_here: list[str] = []

        for f in active_findings:
            if dim.id in _rule_dims(f, taxonomy):
                w = taxonomy.finding_weights.get(f.severity, 0) * \
                    taxonomy.confidence_multipliers.get(f.confidence, 1.0)
                score += w
                contrib_find.append(f.stable_id if f.canonical_name else f.fingerprint)

        for cap in agent.capabilities:
            if dim.id in taxonomy.capability_dimensions.get(cap, []):
                score += taxonomy.capability_weight
                contrib_cap.append(cap)

        if dim.id == "model-drift" and providers:
            score += taxonomy.provider_weight
            contrib_cap.append(f"provider:{sorted(providers)[0]}")

        for control in controls:
            if dim.id in taxonomy.control_dimensions.get(control, []):
                score -= taxonomy.control_credit
                controls_here.append(control)

        final = max(0, min(100, round(score)))
        exposure = _bucket(final)
        if dim.assessability == "proxy" and exposure == "elevated":
            exposure = PROXY_CAP
        if dim.assessability == "runtime-required":
            exposure = "not-assessable"

        entries.append({
            "id": dim.id,
            "assessability": dim.assessability,
            "exposure": exposure,
            "score": final,
            "contributing_findings": sorted(set(contrib_find)),
            "contributing_capabilities": sorted(set(contrib_cap)),
            "controls_observed": sorted(set(controls_here)),
            "statement": _statement(dim.assessability, exposure,
                                    len(contrib_find), len(contrib_cap), controls_here),
        })

    # Unclassified safety net: findings whose rule maps to no dimension.
    for f in active_findings:
        if not _rule_dims(f, taxonomy):
            unclassified_findings.append(f.stable_id if f.canonical_name else f.fingerprint)
    if unclassified_findings:
        entries.append({
            "id": UNCLASSIFIED,
            "assessability": "partial",
            "exposure": "low",
            "score": 0,
            "contributing_findings": sorted(set(unclassified_findings)),
            "contributing_capabilities": [],
            "controls_observed": [],
            "statement": "Findings not mapped to any taxonomy dimension; shown so nothing is dropped.",
        })

    return {"taxonomy": {"id": taxonomy.id, "version": taxonomy.version}, "dimensions": entries}


def dimension_summary(agents: list[AgentCandidate], taxonomy: Taxonomy) -> dict:
    """Org-level rollup: per-dimension max exposure and agent counts."""
    dims = []
    for dim in taxonomy.dimensions:
        levels = []
        for agent in agents:
            if agent.dimension_assessment is None:
                continue
            for entry in agent.dimension_assessment["dimensions"]:
                if entry["id"] == dim.id:
                    levels.append(entry["exposure"])
        max_exp = max(levels, key=lambda e: EXPOSURE_ORDER.index(e)) if levels else "none-observed"
        dims.append({
            "id": dim.id,
            "name": dim.name,
            "assessability": dim.assessability,
            "max_exposure": max_exp,
            "agents_elevated": levels.count("elevated"),
            "agents_moderate": levels.count("moderate"),
        })
    return {"taxonomy": {"id": taxonomy.id, "version": taxonomy.version}, "dimensions": dims}


def set_finding_dimensions(findings: list[Finding], taxonomy: Taxonomy) -> None:
    """Populate each finding's `dimensions` field from the taxonomy map."""
    for f in findings:
        dims = _rule_dims(f, taxonomy)
        if dims:
            f.dimensions = sorted(dims)
