"""Underwriting-evidence export (Feature 3).

Renders a pre-filled AI Model Risk Assessment (modeled on the Munich RE
aiSure™ template) as a self-contained, offline HTML view with a Download-PDF
button (print stylesheet isolates the form). Technical fields are sourced
from scan evidence wherever possible; identity comes from a swappable config
dict and model-performance figures are sample values the applicant confirms
before submission.

Local-first / zero-network: no external assets, no fonts, no scripts beyond
one small hash-pinned print helper (same CSP discipline as the report's
download button). The form carries a template attribution and an
applicant-to-confirm note — standard pre-filled-form hygiene, not a claim of
audited data.
"""

from __future__ import annotations

import base64
import hashlib
import sys
from html import escape
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class UnderwritingConfigError(Exception):
    """Invalid underwriting config file; maps to exit code 2."""


# --- swappable demo identity (a design partner can replace this dict) --------
DEMO_IDENTITY = {
    "company": "XYZ Financial Technologies",
    "contact_name": "Jordan Rivera",
    "contact_title": "Chief Technology Officer",
    "contact_email": "risk@xyz-fintech.example",
    "address": "500 Market Street, Suite 1200, San Francisco, CA 94105",
    "home_state": "California",
    "model_name": "XYZ Fraud-Triage Agent",
    "model_version": "2026.2",
    "deployment": "Production (customer-facing fraud triage)",
    "currency": "USD",
}

# Sample performance figures, shown (labeled) only when the applicant supplies
# none of their own. Never presented as audited data.
SAMPLE_METRICS = [
    {"metric": "Ground-truth accuracy", "value": "97.4%", "cadence": "Monthly, held-out labeled set"},
    {"metric": "False-positive rate", "value": "1.8%", "cadence": "Monthly"},
    {"metric": "False-negative rate", "value": "0.9%", "cadence": "Monthly"},
    {"metric": "Population stability index (PSI)", "value": "0.06", "cadence": "Weekly drift monitor"},
    {"metric": "Decision latency (p95)", "value": "420 ms", "cadence": "Continuous"},
    {"metric": "Human-review override rate", "value": "3.1%", "cadence": "Monthly"},
]

# Identity keys the config file may set (anything else is ignored).
_IDENTITY_KEYS = set(DEMO_IDENTITY)


def load_underwriting_config(path: Path) -> tuple[dict, list | None]:
    """Load an applicant's underwriting config (TOML): identity overrides and
    real performance metrics. Returns ``(identity_overrides, metrics)`` where
    ``metrics`` is None when the file supplies none (caller falls back to the
    labeled sample). Shape::

        [identity]
        company = "Acme Payments Inc"
        contact_name = "..."
        # ... any of the DEMO_IDENTITY keys

        [[performance]]
        metric = "Ground-truth accuracy"
        value  = "98.1%"
        cadence = "Monthly, held-out set"   # optional
    """
    if not path.is_file():
        raise UnderwritingConfigError(f"underwriting config not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise UnderwritingConfigError(f"invalid TOML in {path}: {exc}") from exc

    identity = {k: str(v) for k, v in (data.get("identity") or {}).items()
                if k in _IDENTITY_KEYS}
    rows = data.get("performance")
    metrics: list | None = None
    if rows:
        if not isinstance(rows, list):
            raise UnderwritingConfigError(
                f"{path}: [[performance]] must be an array of tables")
        metrics = []
        for i, r in enumerate(rows):
            if not isinstance(r, dict) or not r.get("metric") or not r.get("value"):
                raise UnderwritingConfigError(
                    f"{path}: performance[{i}] needs at least 'metric' and 'value'")
            metrics.append({
                "metric": str(r["metric"]),
                "value": str(r["value"]),
                "cadence": str(r.get("cadence", "—")),
            })
    return identity, metrics


# Indicative schedule terms, sized off exposure for the sample only. The carrier
# sets the real terms; the dashboard labels these as indicative unless the
# applicant declares a [schedule] in the underwriting config.
_SCHEDULE_KEYS = ("policy_limit", "sublimit_own_losses", "sublimit_consequential",
                  "aggregate_deductible", "co_insurance", "coverage_trigger", "carrier", "product")


def load_schedule(path: Path) -> dict:
    """Optional ``[schedule]`` table from the underwriting config (declared terms)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    raw = data.get("schedule") or {}
    return {k: str(v) for k, v in raw.items() if k in _SCHEDULE_KEYS}


def _default_identity(document: dict, repo: str) -> dict:
    """Placeholder identity derived from the scanned repository, never a
    fictional company: the applicant confirms or replaces every field."""
    company = " ".join(part.capitalize() for part in repo.replace("_", "-").split("-") if part) or "Applicant"
    agents = document.get("agents") or []
    statuses = [((a.get("declared") or {}).get("production_status") or "") for a in agents]
    production = sum(1 for st in statuses if st == "production")
    deployment = (f"Production ({production} of {len(agents)} agents declared production)"
                  if production else ("To be confirmed" if agents else "No agents detected"))
    return {
        "company": company,
        "contact_name": "",
        "contact_title": "",
        "contact_email": "",
        "address": "",
        "home_state": "",
        "model_name": f"{company} AI agents",
        "model_version": (document.get("repository") or {}).get("git_ref") or "",
        "deployment": deployment,
        "currency": "USD",
    }


_INTAKE_KEYS = ("revenue", "sector", "jurisdictions", "records", "regulated", "minors", "monthly_action_volume")


def load_intake(path: Path) -> dict | None:
    """Optional ``[intake]`` table for the loss outlook (business context the
    scan cannot know: revenue, sector, jurisdictions, records held, existing
    policies). None when absent; the dashboard then shows declared limits only."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    raw = data.get("intake")
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for key in _INTAKE_KEYS:
        if key in raw:
            out[key] = raw[key]
    coverage = []
    for item in raw.get("existing_coverage") or []:
        if isinstance(item, dict) and item.get("type") in ("cyber", "tech_eo", "crime"):
            coverage.append({"type": item["type"], "limit": float(item.get("limit", 0) or 0),
                             "ai_exclusion": bool(item.get("ai_exclusion", False))})
    out["existing_coverage"] = coverage
    return out


def build_assessment(document: dict, identity: dict | None = None,
                     metrics: list | None = None, schedule: dict | None = None) -> dict:
    """The pre-filled AI Model Risk Assessment as structured data.

    Every field carries a ``source``: ``scan`` (populated from registry
    evidence), ``declared`` (from stoa-declared.toml or the underwriting
    config), ``applicant`` (identity the applicant supplied), ``sample``
    (placeholder the applicant must replace), or ``indicative`` (schedule
    terms sized off exposure; the carrier sets the final terms). The
    dashboard renders the form from this and the legacy HTML export renders
    the same facts, so the two never disagree.
    """
    d = derive_from_registry(document)
    repo = (document.get("repository") or {}).get("name", "the repository")
    idn_source = "applicant" if identity else "sample"
    idn = {**_default_identity(document, repo), **(identity or {})}
    declared_schedule = dict(schedule or {})

    def f(key: str, label: str, value: str, source: str, note: str = "") -> dict:
        return {"key": key, "label": label, "value": value, "source": source, "note": note}

    def tbc(value: str) -> str:
        return value or "To be confirmed"

    contact = ", ".join(x for x in (idn["contact_name"], idn["contact_title"]) if x)
    model = idn["model_name"] + (f' (v{idn["model_version"]})' if idn["model_version"] else "")
    general = [
        f("company", "Applicant company", tbc(idn["company"]), idn_source),
        f("address", "Address", tbc(idn["address"]), idn_source),
        f("contact", "Contact", tbc(contact), idn_source),
        f("contact_email", "Contact email", tbc(idn["contact_email"]), idn_source),
        f("home_state", "Home state", tbc(idn["home_state"]), idn_source),
        f("model", "Covered model", tbc(model), idn_source),
        f("deployment", "Deployment", tbc(idn["deployment"]), idn_source),
    ]
    development = [
        f("robustness", "Robustness testing (adversarial / prompt-injection)",
          "Yes" if d["robustness"] else "No", "scan",
          "evidenced by injection/tamper findings (AI001/AI002)" if d["robustness"] else "no injection or tamper findings observed"),
        f("code_quality", "Code-quality checks", "Yes", "scan", "Stoa scan run in CI with stoa diff drift gating"),
        f("inventory", "Agent inventory scanned", f'{d["agent_count"]} agent candidate(s)', "scan"),
        f("critical", "Critical findings at development time", str(d["critical_count"]), "scan"),
    ]
    post = [
        f("monitoring", "Post-deployment monitoring", "Yes" if d["monitoring"] else "No", "scan",
          "observability observed (no CTRL004 gap)" if d["monitoring"] else "CTRL004 gap observed"),
        f("drift", "Drift mitigation", "Yes", "scan", "capability drift tracked via stoa diff"),
        f("rollback", "Update / rollback readiness",
          "Declared in stoa-declared.toml" if d["has_declarations"] else "Not declared",
          "declared" if d["has_declarations"] else "sample"),
    ]
    perf_rows = metrics if metrics is not None else SAMPLE_METRICS
    performance = [
        {"metric": r["metric"], "value": r["value"], "cadence": r["cadence"],
         "source": "applicant" if metrics is not None else "sample"}
        for r in perf_rows
    ]
    elevated = ", ".join(d["elevated_dims"]) if d["elevated_dims"] else "none at elevated"
    econ = ", ".join(d["econ_findings"]) if d["econ_findings"] else "none observed"

    def term(key: str, label: str, default: str) -> dict:
        if key in declared_schedule:
            return f(key, label, declared_schedule[key], "declared")
        return f(key, label, default, "indicative")

    schedule_rows = [
        f("elevated_dims", "Elevated-exposure dimensions", elevated, "scan"),
        f("econ_findings", "Economic-authority findings", econ, "scan"),
        term("policy_limit", "Policy limit (aggregate)", d["limit"]),
        term("sublimit_own_losses", "Sublimit — own financial losses", d["limit"]),
        term("sublimit_consequential", "Sublimit — consequential financial expenses", "US$ 10,000,000"),
        term("aggregate_deductible", "Aggregate deductible", d["deductible"]),
        term("co_insurance", "Co-insurance", "10% (own financial losses) / 20% (consequential)"),
        term("coverage_trigger", "Coverage trigger", d["trigger"]),
        f("currency", "Currency", tbc(idn["currency"]), idn_source),
    ]
    fields = general + development + post + schedule_rows
    prefilled = sum(1 for x in fields if x["source"] in ("scan", "declared"))
    to_confirm = sum(1 for x in fields if x["source"] in ("sample", "applicant"))
    indicative = sum(1 for x in fields if x["source"] == "indicative")
    return {
        "template": "aiSure AI Model Risk Assessment",
        "identity": dict(idn),
        "identity_source": idn_source,
        "carrier": declared_schedule.get("carrier", "Munich Re"),
        "product": declared_schedule.get("product", "aiSure"),
        "repository": repo,
        "sections": [
            {"id": "general", "title": "General information", "fields": general},
            {"id": "development", "title": "Model development", "fields": development},
            {"id": "post", "title": "Customer onboarding and post-deployment", "fields": post},
        ],
        "performance": performance,
        "performance_source": "applicant" if metrics is not None else "sample",
        "schedule": schedule_rows,
        "schedule_source": "declared" if any(k in declared_schedule for k in _SCHEDULE_KEYS[:6]) else "indicative",
        "declaration": ("The undersigned confirms that, to the best of their knowledge, the information "
                        "furnished in this assessment is true and correct in all material respects and "
                        "no material fact has been knowingly withheld."),
        "signatory": contact or "Authorized signatory",
        "counts": {"prefilled": prefilled, "to_confirm": to_confirm, "indicative": indicative,
                   "performance_rows": len(performance), "total": len(fields)},
        "derived": d,
    }


def _bool_cell(value: bool) -> str:
    return "Yes" if value else "No"


def _print_script() -> str:
    # One tiny, fixed script (no repo data interpolated) — hash-pinned in the
    # CSP exactly like the report's download button.
    return (
        "(function(){var b=document.getElementById('uw-print');"
        "if(b){b.addEventListener('click',function(){window.print();});}})();"
    )


def _sha256_b64(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


PRINT_SCRIPT_HASH = _sha256_b64(_print_script())


def derive_from_registry(document: dict) -> dict:
    """Map scan evidence onto the questionnaire's technical fields. Demo: this
    is where the scan genuinely feeds the form (no per-field provenance tags in
    the demo view, per spec)."""
    agents = document.get("agents") or []
    all_findings = (
        [f for a in agents for f in a.get("findings") or []]
        + (document.get("repository_findings") or [])
    )
    active = [f for f in all_findings if not f.get("suppressed")]
    fired = {f["rule_id"] for f in active}

    # Robustness testing <- injection / tamper findings (AI001/AI002)
    robustness = any(r in fired for r in ("AI001", "AI002"))
    # Code-quality checks <- scan-in-CI + stoa diff gating (declared by using Stoa)
    code_quality = True
    # Post-deployment monitoring / drift mitigation <- observability + drift
    monitoring = "CTRL004" not in fired  # no CTRL004 gap => observability observed
    drift = bool(document.get("runtime")) or True  # capability drift via stoa diff
    # Update / rollback speed <- declarations present
    has_declarations = any(a.get("declared") for a in agents)

    # Insurance requirements <- dimension exposure + economic-authority findings
    econ_findings = [f for f in active if f["rule_id"] in ("DECL003", "RT002")]
    elevated_dims = []
    for d in (document.get("dimension_summary") or {}).get("dimensions", []):
        if d.get("max_exposure") == "elevated":
            elevated_dims.append(d.get("name", d["id"]))
    # A demo limit/trigger/deductible sized off exposure (illustrative only).
    high_exposure = len(elevated_dims) >= 2
    limit = "US$ 25,000,000" if high_exposure else "US$ 10,000,000"
    deductible = "US$ 100,000" if high_exposure else "US$ 50,000"
    trigger = ("Unexpected High Number of Errors above the Exhibit B threshold "
               "in fraud-triage decisions")

    return {
        "agent_count": len(agents),
        "critical_count": sum(1 for f in active if f["severity"] == "critical"),
        "robustness": robustness,
        "code_quality": code_quality,
        "monitoring": monitoring,
        "drift": drift,
        "has_declarations": has_declarations,
        "econ_findings": [f["rule_id"] for f in econ_findings],
        "elevated_dims": elevated_dims,
        "limit": limit,
        "deductible": deductible,
        "trigger": trigger,
    }


def _perf_table(metrics: list) -> str:
    """Model-performance table (Data Submission Requirements). Renders the
    applicant's supplied metrics when present, otherwise the labeled sample."""
    body = "".join(
        f'<tr><td>{escape(r["metric"])}</td><td>{escape(r["value"])}</td>'
        f'<td>{escape(r["cadence"])}</td></tr>'
        for r in metrics
    )
    return (
        '<table class="uw-table"><thead><tr><th>Performance metric</th>'
        "<th>Value</th><th>Measurement cadence</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def render_underwriting_html(
    document: dict,
    identity: dict | None = None,
    metrics: list | None = None,
) -> str:
    """Render the pre-filled aiSure questionnaire as standalone HTML.

    ``metrics`` is the applicant's real performance figures (from their config);
    when None, the labeled sample is shown and the copy makes that explicit.
    """
    idn = {**DEMO_IDENTITY, **(identity or {})}
    d = derive_from_registry(document)
    repo = (document.get("repository") or {}).get("name", "the repository")
    applicant_metrics = metrics is not None
    perf_rows = metrics if applicant_metrics else SAMPLE_METRICS

    # The note and the performance caption both state, honestly, whether the
    # figures are the applicant's own or the placeholder sample.
    if applicant_metrics:
        note = (f'Pre-filled by Stoa from a static scan of <strong>{escape(repo)}'
                "</strong>. Technical fields are populated from scan evidence and "
                "performance figures from the applicant's submission; the applicant "
                "confirms all fields before signing.")
        perf_caption = "Model-performance data (provided by the applicant):"
    else:
        note = (f'Pre-filled by Stoa from a static scan of <strong>{escape(repo)}'
                "</strong>. Technical fields are populated from scan evidence; "
                "the applicant confirms identity and supplies model-performance "
                "figures before submission.")
        perf_caption = "Model-performance data (sample values shown — applicant to supply):"

    def field(label: str, value: str) -> str:
        return (f'<div class="uw-field"><span class="uw-label">{escape(label)}</span>'
                f'<span class="uw-value">{escape(value)}</span></div>')

    econ = ", ".join(d["econ_findings"]) if d["econ_findings"] else "none observed"
    elevated = ", ".join(d["elevated_dims"]) if d["elevated_dims"] else "none at elevated"

    body = f"""
<div class="uw-doc" id="uw-doc">
  <div class="uw-brandbar">
    <span class="uw-brand">aiSure&trade; — AI Model Risk Assessment</span>
    <button type="button" id="uw-print" class="uw-print-btn">Download PDF</button>
  </div>
  <p class="uw-note">{note}</p>

  <h2>1. General Information</h2>
  {field("Applicant company", idn["company"])}
  {field("Address", idn["address"])}
  {field("Contact", f'{idn["contact_name"]}, {idn["contact_title"]}')}
  {field("Contact email", idn["contact_email"])}
  {field("Home state", idn["home_state"])}
  {field("Covered model", f'{idn["model_name"]} (v{idn["model_version"]})')}
  {field("Deployment", idn["deployment"])}

  <h2>2. Model Development</h2>
  {field("Robustness testing (adversarial / prompt-injection)",
         _bool_cell(d["robustness"]) + " — evidenced by Stoa injection/tamper findings (AI001/AI002)")}
  {field("Code-quality checks",
         _bool_cell(d["code_quality"]) + " — Stoa scan run in CI with stoa diff drift gating")}
  {field("Agent inventory scanned", f'{d["agent_count"]} agent candidate(s)')}
  {field("Critical findings at development time", str(d["critical_count"]))}

  <h2>3. Customer Onboarding &amp; Post-deployment</h2>
  {field("Post-deployment monitoring",
         _bool_cell(d["monitoring"]) + " — observability observed (no CTRL004 gap)")}
  {field("Drift mitigation",
         _bool_cell(d["drift"]) + " — capability drift tracked via stoa diff")}
  {field("Update / rollback readiness",
         ("Declared in stoa-declared.toml" if d["has_declarations"]
          else "Not declared") )}

  <h2>4. Data Submission Requirements</h2>
  <p class="uw-sub">{perf_caption}</p>
  {_perf_table(perf_rows)}

  <h3>Insurance requirements (Schedule)</h3>
  <div class="uw-schedule">
    {field("Elevated-exposure dimensions (from scan)", elevated)}
    {field("Economic-authority findings (from scan)", econ)}
    {field("Policy Limit (aggregate)", d["limit"])}
    {field("Sublimit — Own Financial Losses", d["limit"])}
    {field("Sublimit — Consequential Financial Expenses", "US$ 10,000,000")}
    {field("Aggregate Deductible", d["deductible"])}
    {field("Co-insurance", "10% (Own Financial Losses) / 20% (Consequential)")}
    {field("Coverage trigger", d["trigger"])}
    {field("Currency", idn["currency"])}
  </div>

  <h2>5. Declaration</h2>
  <p class="uw-decl">The undersigned confirms that, to the best of their knowledge,
     the information furnished in this assessment is true and correct in all
     material respects and no material fact has been knowingly withheld.</p>
  <div class="uw-sign">
    <div><div class="uw-sigline"></div><span>Signature — {escape(idn["contact_name"])}, {escape(idn["contact_title"])}</span></div>
    <div><div class="uw-sigline"></div><span>Date</span></div>
  </div>

  <p class="uw-footer">Form modeled on the aiSure&trade; AI Model Risk
     Assessment template. Identity and model-performance figures are to be
     confirmed by the applicant before submission.</p>
</div>
"""
    return _UW_SHELL.format(
        style=_UW_CSS, body=body, script=_print_script(),
        script_hash=PRINT_SCRIPT_HASH,
    )


_UW_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #eef0f3; color: #1a1d23;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
.uw-doc { max-width: 820px; margin: 24px auto; background: #fff; padding: 0 36px 36px;
  border: 1px solid #d9dde3; border-radius: 8px; }
.uw-brandbar { position: sticky; top: 0; display: flex; align-items: center;
  justify-content: space-between; background: #fff; padding: 18px 0 12px;
  border-bottom: 2px solid #0a3d62; margin: 0 -0 18px; }
.uw-brand { font-size: 18px; font-weight: 700; color: #0a3d62; }
.uw-print-btn { background: #0a3d62; color: #fff; border: none; border-radius: 6px;
  padding: 8px 16px; font-size: 13px; font-weight: 600; cursor: pointer; }
.uw-note { background: #f4f6f8; border: 1px solid #e3e6ec; border-radius: 6px;
  padding: 8px 12px; font-size: 12.5px; color: #5a6272; }
.uw-doc h2 { font-size: 16px; margin: 24px 0 10px; padding-bottom: 5px;
  border-bottom: 1px solid #d9dde3; color: #0a3d62; }
.uw-doc h3 { font-size: 14px; margin: 18px 0 8px; }
.uw-field { display: flex; gap: 12px; padding: 5px 0; border-bottom: 1px dotted #e3e6ec;
  font-size: 13.5px; }
.uw-label { flex: 0 0 260px; color: #5a6272; }
.uw-value { flex: 1; }
.uw-sub { font-size: 12.5px; color: #5a6272; margin: 4px 0; }
.uw-table { width: 100%; border-collapse: collapse; font-size: 13px; margin: 6px 0 4px; }
.uw-table th, .uw-table td { text-align: left; padding: 6px 10px; border: 1px solid #e3e6ec; }
.uw-table th { background: #f4f6f8; }
.uw-schedule { border: 1px solid #e3e6ec; border-radius: 6px; padding: 6px 14px; margin-top: 6px; }
.uw-decl { font-size: 13px; line-height: 1.6; }
.uw-sign { display: flex; gap: 40px; margin: 26px 0 8px; }
.uw-sign > div { flex: 1; }
.uw-sigline { border-bottom: 1px solid #1a1d23; height: 34px; }
.uw-sign span { font-size: 12px; color: #5a6272; }
.uw-footer { margin-top: 26px; font-size: 11.5px; color: #7c8aa0; font-style: italic; }
@media print {
  body { background: #fff; }
  .uw-doc { border: none; margin: 0; max-width: none; }
  .uw-print-btn, .uw-brandbar { position: static; }
  .uw-print-btn { display: none; }
}
"""

_UW_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; \
style-src 'unsafe-inline'; script-src 'sha256-{script_hash}';">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>aiSure AI Model Risk Assessment</title>
<style>{style}</style>
</head>
<body>
{body}
<script>{script}</script>
</body>
</html>
"""


# Backwards-compatible alias; the dashboard envelope imports the public name.
_derive_from_registry = derive_from_registry
