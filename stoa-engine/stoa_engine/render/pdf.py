"""PDF renderer (Jinja2 HTML templates + WeasyPrint).

Original Stoa-branded layout. Page order:
  1. Cover page — company, date, scan hash, evidence-class legend.
  2. Per-agent one-pager — plain-English narrative for an underwriter.
  3. Evidence-backed answers grouped by the adapter's sections.
  4. Review & sign-off page — code-verified vs human-attested split.

When meta.sample_data is true, a fixed watermark is fixed to every page via
CSS. Contradicted answers/attestations raise a red banner.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from .. import adapters

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
WATERMARK = "SAMPLE — FICTIONAL DATA — NOT FOR SUBMISSION"

CONF_BADGE = {
    "confirmed": ("Confirmed", "badge-confirmed"),
    "attested": ("Attested", "badge-attested"),
    "not_confirmed": ("Not confirmed", "badge-notconfirmed"),
    "contradicted": ("Contradicted", "badge-contradicted"),
    "unknown": ("Unknown", "badge-unknown"),
}

SEVERITY_LABEL = {
    "output_error": "Output error",
    "ip_infringement": "IP infringement",
    "data_disclosure": "Data disclosure",
    "bodily_injury": "Bodily injury",
    "property_damage": "Property damage",
    "regulatory": "Regulatory",
    "none": "No adverse severity",
}


def _fmt_currency(v: Any) -> str:
    if isinstance(v, (int, float)):
        return f"${v:,.0f}"
    return "—"


def _agent_narrative(sys: dict[str, Any]) -> dict[str, Any]:
    """Build the plain-English underwriter narrative for one system."""
    posture = sys.get("posture", {})

    def pv(field):
        return (posture.get(field) or {}).get("value")

    perf = sys.get("performance") or {}
    agg = perf.get("aggregates") or {}
    sev = agg.get("severity_counts", {}) or {}
    top_failures = sorted(
        ((SEVERITY_LABEL.get(k, k), n) for k, n in sev.items()),
        key=lambda kv: kv[1],
        reverse=True,
    )

    can_touch = []
    for cat in (pv("sensitive_data") or []):
        can_touch.append(cat)
    for cat in (pv("data_types") or []):
        can_touch.append(cat)

    agentic = pv("agentic_actions")
    hitl = pv("hitl")

    controls_present, controls_absent = [], []
    (controls_present if pv("io_logging") else controls_absent).append(
        "Input/output logging"
    )
    if hitl is True:
        controls_present.append("Human-in-the-loop review")
    elif hitl is False:
        controls_absent.append("Human-in-the-loop review")
    (controls_present if pv("guardrails_intact") else controls_absent).append(
        "Vendor guardrails intact"
    )

    return {
        "agent_id": sys.get("agent_id"),
        "display_name": sys.get("display_name"),
        "description": sys.get("description"),
        "model": pv("model"),
        "activities": pv("business_activities"),
        "audience": pv("audience"),
        "can_touch": can_touch,
        "agentic": agentic,
        "spend_authority": _spend_authority(sys),
        "top_failures": top_failures,
        "controls_present": controls_present,
        "controls_absent": controls_absent,
        "n_runs": agg.get("n_runs"),
        "error_rate": agg.get("error_rate"),
        "total_loss_proxy": _fmt_currency(agg.get("total_loss_proxy_usd")),
        "evidence_class": perf.get("evidence_class", "simulated"),
    }


def _spend_authority(sys: dict[str, Any]) -> str:
    cm = (sys.get("performance") or {}).get("covered_model_draft") or {}
    scope = cm.get("function_scope", "")
    # surface any "$N" mention from the function scope / description as a hint
    desc = sys.get("description", "")
    for text in (desc, scope):
        if "$" in text:
            # crude but deterministic: take the first $-amount substring
            idx = text.index("$")
            tail = text[idx : idx + 8]
            return tail.split()[0].rstrip(".,;")
    return "No monetary authority observed"


def _group_by_system(fields: list[adapters.ResolvedField]):
    """Split resolved fields into (global fields, {system_id: {name, fields}})."""
    global_fields: "OrderedDict[str, list]" = OrderedDict()
    per_system: "OrderedDict[str, dict]" = OrderedDict()

    for rf in fields:
        if rf.system_scoped:
            bucket = per_system.setdefault(
                rf._system_id, {"name": rf._system_name, "sections": OrderedDict()}
            )
            bucket["sections"].setdefault(rf.section, []).append(rf)
        else:
            global_fields.setdefault(rf.section, []).append(rf)
    return global_fields, per_system


def _signoff_split(submission: dict[str, Any]):
    """Count code-verified vs human-attested posture fields across systems."""
    verified, attested = [], []
    for sys in submission.get("systems", []) or []:
        posture = sys.get("posture", {})
        for fname, ev in posture.items():
            conf = (ev or {}).get("confidence")
            label = f"{sys.get('display_name')}: {fname.replace('_', ' ')}"
            if conf in ("confirmed", "not_confirmed", "contradicted"):
                verified.append({"label": label, "confidence": conf})
            elif conf == "attested":
                attested.append({"label": label, "confidence": conf})
            else:  # unknown -> needs human attestation to close
                attested.append({"label": label, "confidence": "unknown"})
    return verified, attested


def render_pdf(
    submission: dict[str, Any],
    template_name: str,
    out_path: Path,
) -> Path:
    tpl = adapters.load_template(template_name)
    fields = adapters.resolve(tpl, submission)
    global_sections, per_system = _group_by_system(fields)
    verified, attested = _signoff_split(submission)

    contradictions = []
    for sys in submission.get("systems", []) or []:
        for att in sys.get("attestations", []) or []:
            if att.get("status") == "contradicted":
                contradictions.append(
                    {"system": sys.get("display_name"), "claim": att.get("claim_text")}
                )

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.filters["currency"] = _fmt_currency
    tmpl = env.get_template("packet.html.j2")

    html = tmpl.render(
        meta=submission.get("meta", {}),
        company=submission.get("business_context", {}).get("company", {}),
        coverage=submission.get("coverage_request", {}) or {},
        template_title=tpl.title,
        template_name=tpl.name,
        sample=submission.get("meta", {}).get("sample_data", False),
        watermark=WATERMARK,
        narratives=[_agent_narrative(s) for s in submission.get("systems", []) or []],
        global_sections=global_sections,
        per_system=per_system,
        verified=verified,
        attested=attested,
        contradictions=contradictions,
        conf_badge=CONF_BADGE,
    )

    out_path = Path(out_path)
    HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf(str(out_path))
    return out_path
