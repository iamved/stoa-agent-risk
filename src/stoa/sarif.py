"""SARIF 2.1.0 output (Part IV §C.4).

Emits findings as a SARIF log so GitHub Code Scanning can ingest them, with a
`stoa-dim:<dimension>` tag and a `properties.dimensions` array on each result
so results can be filtered by risk dimension. Deterministic; no timestamps.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import __version__
from .models import ScanResult
from .report_json import _atomic_write
from .rules import RULES

_LEVEL = {"critical": "error", "high": "error", "medium": "warning",
          "low": "note", "info": "note"}


def build_sarif(result: ScanResult) -> dict:
    findings = result.findings
    used_rules = sorted({f.rule_id for f in findings})
    rules = []
    for rule_id in used_rules:
        spec = RULES.get(rule_id)
        if spec is None:
            continue
        rules.append({
            "id": spec.canonical_name or rule_id,
            "name": rule_id,
            "shortDescription": {"text": spec.title},
            "helpUri": f"https://stoa-agent-risk.dev/docs/rules/{rule_id}",
            "properties": {"tags": _rule_tags(spec)},
        })

    results = []
    for f in sorted(findings, key=lambda x: (x.path, x.line, x.rule_id)):
        if f.suppressed:
            continue
        spec = RULES.get(f.rule_id)
        results.append({
            "ruleId": (spec.canonical_name if spec and spec.canonical_name else f.rule_id),
            "level": "error" if f.gate_eligible else _LEVEL.get(f.severity, "note"),
            "message": {"text": f.message or f.title},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f.path},
                    "region": {"startLine": max(1, f.line), "startColumn": max(1, f.column)},
                },
            }],
            "partialFingerprints": {"stoaFingerprint": f.fingerprint},
            "properties": {
                "dimensions": sorted(f.dimensions),
                "tags": [f"stoa-dim:{d}" for d in sorted(f.dimensions)],
                "confidence": f.confidence,
            },
        })

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "Stoa",
                "version": __version__,
                "informationUri": "https://stoa-agent-risk.dev",
                "rules": rules,
            }},
            "results": results,
        }],
    }


def _rule_tags(spec) -> list[str]:
    tags = ["security", spec.category]
    if spec.owasp:
        tags.append(f"owasp-{spec.owasp.get('llm_top10_v1_1', '').lower()}")
    return tags


def write_sarif(result: ScanResult, output_path: Path) -> None:
    _atomic_write(output_path, json.dumps(build_sarif(result), indent=2, ensure_ascii=False) + "\n")
