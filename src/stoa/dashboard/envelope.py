"""The ``stoa-dashboard/1.0`` envelope the compiled UI reads.

Wraps documents the scanner already produces — the registry, an optional
``stoa-diff/1.0`` document, history summaries — together with the static
lookup tables the UI needs to label them (rule metadata, the crosswalk, the
dimension taxonomy). The UI never re-derives any of it.

Deterministic: the assurance packet's header takes the registry's own
``head_commit`` for its sha and timestamp, so identical inputs give a
byte-identical envelope.
"""

from __future__ import annotations

from pathlib import Path

from .. import __version__
from ..assurance import GROUPS, build_assurance_packet
from ..crosswalk import CrosswalkError, load_crosswalk
from ..dimensions import TaxonomyError, load_taxonomy
from ..graph_model import build_graph, overlay_runtime, to_json_dict
from ..rules import HIGH_IMPACT_CAPABILITIES, RULES, SENSITIVE_INTEGRATIONS
from ..underwriting import derive_from_registry
from .register import build_register

ENVELOPE_SCHEMA = "stoa-dashboard/1.0"

# One report-level NIST AI RMF alignment — never per-rule tags (docs/crosswalk.md).
NIST_AI_RMF = [
    {"function": "MAP",
     "stoa": "The agent inventory and the dimension matrix establish context: "
             "what agents exist and where their exposure sits."},
    {"function": "MEASURE",
     "stoa": "The findings and their file:line evidence, with OWASP and EU AI Act "
             "anchors, quantify and characterize that exposure."},
    {"function": "MANAGE",
     "stoa": "stoa diff gating and the assurance export carry that evidence into "
             "change control and external review."},
    {"function": "GOVERN",
     "stoa": "An organizational function outside a static scan's view; not assessed."},
]


def _rules_table(crosswalk_path: Path | None) -> dict:
    try:
        crosswalk = load_crosswalk(crosswalk_path)
    except CrosswalkError:
        crosswalk = None
    table: dict[str, dict] = {}
    for rule_id in sorted(RULES):
        spec = RULES[rule_id]
        record = {
            "title": spec.title,
            "category": spec.category,
            "default_severity": spec.default_severity,
            "gateable": spec.gateable,
            "remediation": spec.remediation,
            "canonical_name": spec.canonical_name,
        }
        if crosswalk is not None:
            record["crosswalk"] = crosswalk.entry(rule_id).to_dict()
        table[rule_id] = record
    return table


def _taxonomy_block(taxonomy_path: Path | None, registry: dict) -> dict:
    """Dimension names, definitions, and group labels for the UI.

    Falls back to what the registry's own dimension_summary carries when the
    taxonomy file cannot be loaded, so a dashboard is always labelable.
    """
    groups = {letter: label.split(" — ", 1)[-1] for letter, label in GROUPS if letter != "index"}
    try:
        taxonomy = load_taxonomy(taxonomy_path)
    except TaxonomyError:
        summary = registry.get("dimension_summary") or {}
        return {
            "id": (summary.get("taxonomy") or {}).get("id"),
            "version": (summary.get("taxonomy") or {}).get("version"),
            "dimensions": [
                {"id": d["id"], "name": d.get("name", d["id"]), "definition": "",
                 "assessability": d.get("assessability", ""), "group": d.get("group", "")}
                for d in summary.get("dimensions", [])
            ],
            "groups": groups,
        }
    return {
        "id": taxonomy.id,
        "version": taxonomy.version,
        "dimensions": [
            {"id": d.id, "name": d.name, "definition": d.definition,
             "assessability": d.assessability, "group": d.group}
            for d in taxonomy.dimensions
        ],
        "groups": groups,
    }


def build_envelope(
    registry: dict,
    *,
    diff: dict | None = None,
    history: list[dict] | None = None,
    taxonomy_path: Path | None = None,
    crosswalk_path: Path | None = None,
) -> dict:
    """Assemble the envelope. Pure function; no I/O, no wall clock."""
    head = (registry.get("repository") or {}).get("head_commit") or {}
    graph = build_graph(registry)
    if registry.get("runtime"):
        graph = overlay_runtime(graph, registry)
    assurance = build_assurance_packet(
        registry, git_sha=head.get("hash"), scan_timestamp=head.get("date"),
    )
    return {
        "schema": ENVELOPE_SCHEMA,
        "generator": {"name": "stoa", "version": __version__},
        "registry": registry,
        "diff": diff,
        "history": list(history or []),
        "register": build_register(registry),
        # The same architecture graph the legacy report draws (graph_model),
        # so the Inventory graph tab reuses that model rather than rebuilding it.
        "graph": to_json_dict(graph),
        "assurance": assurance,
        "underwriting": derive_from_registry(registry),
        "rules": _rules_table(crosswalk_path),
        "taxonomy": _taxonomy_block(taxonomy_path, registry),
        "frameworks": {"nist_ai_rmf": NIST_AI_RMF},
        # The scanner's own vocabulary, so the UI never hardcodes which
        # capabilities or integrations it treats as high impact.
        "vocabulary": {
            "high_impact_capabilities": sorted(HIGH_IMPACT_CAPABILITIES),
            "sensitive_integrations": sorted(SENSITIVE_INTEGRATIONS),
        },
    }
