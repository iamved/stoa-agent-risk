"""Export orchestration: submission JSON in -> packet files out.

Ties together the adapter loader and the three renderers. Collects both the
submission's declared gaps and the adapter completeness gaps.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import adapters
from .models import Gap, Submission
from .render import evidence as evidence_render
from .render import pdf as pdf_render
from .render import xlsx as xlsx_render

TEMPLATES = ("posture", "performance")


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def validate(path: str) -> Submission:
    """Pydantic validation (raises on failure)."""
    return Submission.model_validate(load_json(path))


def collect_gaps(submission: dict[str, Any], template: str) -> list[Gap]:
    """Declared gaps for this template + adapter completeness gaps."""
    declared = [
        Gap.model_validate(g)
        for g in submission.get("gaps", [])
        if g.get("template") == template
    ]
    tpl = adapters.load_template(template)
    computed = adapters.completeness_gaps(tpl, submission)
    # de-dup on (field_id, template)
    seen = {(g.template, g.field_id) for g in declared}
    merged = list(declared)
    for g in computed:
        if (g.template, g.field_id) not in seen:
            merged.append(g)
    return merged


def _templates_for(template: str) -> list[str]:
    return list(TEMPLATES) if template == "all" else [template]


def export(submission_path: str, template: str, out_dir: str) -> dict[str, Any]:
    """Render the packet. Returns a summary dict of written files + gaps."""
    submission = load_json(submission_path)
    validate(submission_path)  # fail fast on invalid input

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    all_gaps: list[Gap] = []

    for tpl in _templates_for(template):
        pdf_path = out / f"packet_{tpl}.pdf"
        pdf_render.render_pdf(submission, tpl, pdf_path)
        written.append(pdf_path)
        all_gaps.extend(collect_gaps(submission, tpl))

    # XLSX is the performance-data workbook; render whenever performance data
    # exists (i.e. for 'performance' or 'all').
    if template in ("performance", "all"):
        xlsx_path = out / "performance_data.xlsx"
        xlsx_render.render_xlsx(submission, xlsx_path)
        written.append(xlsx_path)

    # Evidence copy + manifest last (manifest hashes everything else).
    evidence_render.copy_submission(submission_path, out)
    written.append(out / "submission.json")
    manifest = evidence_render.write_manifest(out, submission)
    written.append(manifest)

    return {
        "out_dir": str(out),
        "files": [str(p) for p in written],
        "gaps": [g.model_dump() for g in all_gaps],
        "sample_data": submission.get("meta", {}).get("sample_data", False),
    }
