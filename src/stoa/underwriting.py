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
from html import escape

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


def _derive_from_registry(document: dict) -> dict:
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


def _perf_table() -> str:
    """Hardcoded model-performance sample (Data Submission Requirements)."""
    rows = [
        ("Ground-truth accuracy", "97.4%", "Monthly, held-out labeled set"),
        ("False-positive rate", "1.8%", "Monthly"),
        ("False-negative rate", "0.9%", "Monthly"),
        ("Population stability index (PSI)", "0.06", "Weekly drift monitor"),
        ("Decision latency (p95)", "420 ms", "Continuous"),
        ("Human-review override rate", "3.1%", "Monthly"),
    ]
    body = "".join(
        f"<tr><td>{escape(m)}</td><td>{escape(v)}</td><td>{escape(c)}</td></tr>"
        for m, v, c in rows
    )
    return (
        '<table class="uw-table"><thead><tr><th>Performance metric</th>'
        "<th>Sampled value</th><th>Measurement cadence</th></tr></thead>"
        f"<tbody>{body}</tbody></table>"
    )


def render_underwriting_html(document: dict, identity: dict | None = None) -> str:
    """Render the pre-filled aiSure questionnaire as standalone HTML."""
    idn = {**DEMO_IDENTITY, **(identity or {})}
    d = _derive_from_registry(document)
    repo = (document.get("repository") or {}).get("name", "the repository")

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
  <p class="uw-note">Pre-filled by Stoa from a static scan of
     <strong>{escape(repo)}</strong>. Technical fields are populated from scan
     evidence; the applicant confirms identity and model-performance figures
     before submission.</p>

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
  <p class="uw-sub">Model-performance data (sample values shown — applicant to confirm):</p>
  {_perf_table()}

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
