"""Deterministic generator for examples/sample_submission.json.

Fictional company (Meridian Commerce Co.). Run:  python examples/_gen_sample.py
Deterministic: fixed seed, fixed base timestamp — output is byte-stable.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_TS = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
SCAN_HASH = "sha256:9f2c1a7b4e0d3c88a15e6b2f0c4d7e91a3b8c2d5f6079e1a2b3c4d5e6f708192"


def ev(value, evidence, confidence, scan_hash=SCAN_HASH):
    return {"value": value, "evidence": evidence, "confidence": confidence, "scan_hash": scan_hash}


def refund_runs():
    """40 runs, ~5% failure. Severities mostly output_error; one data_disclosure
    at $8,500. Deterministic pattern, no RNG."""
    runs = []
    # Two failures among 40 -> 5%. Pick indices 12 (data_disclosure) and 27 (output_error).
    fail_idx = {12: ("data_disclosure", 8500.0), 27: ("output_error", 320.0)}
    for i in range(40):
        ts = (BASE_TS + timedelta(minutes=7 * i)).isoformat()
        if i in fail_idx:
            sev, loss = fail_idx[i]
            runs.append({
                "ts": ts,
                "scenario_id": f"refund-sc-{i:03d}",
                "scenario_class": "policy_refund_amount",
                "expected": "refund within policy entitlement",
                "actual": (
                    "refund of $180 issued to unrelated account (PII exposed in trace)"
                    if sev == "data_disclosure"
                    else "refund $60 over policy entitlement"
                ),
                "pass": False,
                "severity": sev,
                "loss_proxy_usd": loss,
            })
        else:
            runs.append({
                "ts": ts,
                "scenario_id": f"refund-sc-{i:03d}",
                "scenario_class": "policy_refund_amount",
                "expected": "refund within policy entitlement",
                "actual": "refund matched policy entitlement",
                "pass": True,
                "severity": "none",
                "loss_proxy_usd": 0.0,
            })
    return runs


def support_runs():
    """30 runs, ~3% failure -> 1 failure (output_error, low loss)."""
    runs = []
    fail_idx = {19: ("output_error", 150.0)}
    for i in range(30):
        ts = (BASE_TS + timedelta(minutes=11 * i)).isoformat()
        if i in fail_idx:
            sev, loss = fail_idx[i]
            runs.append({
                "ts": ts,
                "scenario_id": f"support-sc-{i:03d}",
                "scenario_class": "grounded_answer_accuracy",
                "expected": "answer grounded in knowledge base",
                "actual": "answer included an unsupported claim",
                "pass": False,
                "severity": sev,
                "loss_proxy_usd": loss,
            })
        else:
            runs.append({
                "ts": ts,
                "scenario_id": f"support-sc-{i:03d}",
                "scenario_class": "grounded_answer_accuracy",
                "expected": "answer grounded in knowledge base",
                "actual": "answer grounded and correct",
                "pass": True,
                "severity": "none",
                "loss_proxy_usd": 0.0,
            })
    return runs


def aggregates(runs, robustness):
    n = len(runs)
    errs = sum(1 for r in runs if not r["pass"])
    rate = round(errs / n, 4)
    # Wilson-ish interval, kept simple + deterministic for the sample.
    import math
    if n:
        se = math.sqrt(max(rate * (1 - rate), 1e-9) / n)
        lo = round(max(0.0, rate - 1.96 * se), 4)
        hi = round(min(1.0, rate + 1.96 * se), 4)
    else:
        lo = hi = 0.0
    sev_counts = {}
    for r in runs:
        if not r["pass"]:
            sev_counts[r["severity"]] = sev_counts.get(r["severity"], 0) + 1
    total_loss = round(sum(r["loss_proxy_usd"] for r in runs), 2)
    return {
        "n_runs": n,
        "error_rate": rate,
        "ci_95": [lo, hi],
        "severity_counts": sev_counts,
        "total_loss_proxy_usd": total_loss,
        "robustness": robustness,
    }


def build():
    r_runs = refund_runs()
    s_runs = support_runs()

    submission = {
        "meta": {
            "schema_version": "1.0",
            "generated_at": BASE_TS.isoformat(),
            "extractor_version": "stoa-engine/0.1.0",
            "registry_scan_hash": SCAN_HASH,
            "sample_data": True,
        },
        "business_context": {
            "company": {
                "name": "Meridian Commerce Co.",
                "website": "https://meridian-commerce.example",
                "employees": 140,
                "industry": "E-commerce retail",
                "naics": "454110",
                "annual_revenue_usd": 38000000,
                "gross_profit_usd": 14200000,
                "description": (
                    "Direct-to-consumer e-commerce platform selling home and lifestyle "
                    "goods, with AI systems supporting customer service and refunds."
                ),
            },
            "loss_history": [
                {
                    "date": "2024-11-02",
                    "description": "Chargeback dispute wave after a promo-code misconfiguration; no AI involvement.",
                    "status": "closed",
                }
            ],
            "contracts": {
                "avg_value_usd": 42000,
                "largest_value_usd": 610000,
                "pct_standard_terms": 0.82,
                "liability_cap": {"type": "fee_pct", "value": 1.0},
                "provisions": [
                    "limitation_of_liability",
                    "indemnity",
                    "warranty_disclaimer",
                    "ai_output_disclaimer",
                ],
                "legal_counsel_reviews": True,
            },
            "other_policies": [
                "Commercial General Liability",
                "Cyber Liability",
                "Technology E&O",
            ],
            "projections": {
                "next_2y": {"users": 2100000, "outputs": 9500000, "revenue_usd": 52000000}
            },
            "governance_owners": [
                {"name": "Dana Whitfield", "title": "VP Engineering"},
                {"name": "Priya Raman", "title": "Head of Risk & Compliance"},
            ],
        },
        "systems": [
            {
                "agent_id": "refund-agent",
                "display_name": "Refund Agent",
                "description": (
                    "Agentic assistant that evaluates refund requests and initiates "
                    "payment refunds up to $500 without a human approval step."
                ),
                "posture": {
                    "model": ev("GPT-4o (hosted)", ["src/agents/refund.py:L12"], "confirmed"),
                    "business_activities": ev(
                        "Evaluates refund eligibility and initiates payment refunds",
                        ["src/agents/refund.py:L20-L58"], "confirmed"),
                    "fine_tuned": ev(False, ["src/agents/refund.py:L12"], "confirmed"),
                    "data_types": ev(
                        ["company_proprietary", "licensed_third_party"],
                        ["src/agents/refund.py:L31"], "confirmed"),
                    "sensitive_data": ev(
                        ["pii", "payment"],
                        ["src/agents/refund.py:L34", "src/db/customers.py:L88"], "confirmed"),
                    "output_types": ev(["text"], ["src/agents/refund.py:L60"], "confirmed"),
                    "audience": ev("third_party", ["src/agents/refund.py:L60"], "confirmed"),
                    "io_logging": ev(True, ["src/agents/refund.py:L71", "config/logging.yaml:L4"], "confirmed"),
                    # NO hitl, confirmed by scan (approval construct absent).
                    "hitl": ev(False, ["src/agents/refund.py:L41", "scan:AI003-approval-absence"], "confirmed"),
                    "agentic_actions": ev(True, ["src/agents/refund.py:L41-L52"], "confirmed"),
                    "frameworks": ev([], [], "unknown"),
                    "guardrails_intact": ev(True, ["src/agents/refund.py:L18"], "confirmed"),
                },
                "attestations": [
                    {
                        "claim_id": "refund-hitl-review",
                        "claim_text": "A human reviews every refund before it is issued.",
                        "declared": True,
                        "observed": False,
                        "status": "contradicted",
                    },
                    {
                        "claim_id": "refund-logging",
                        "claim_text": "All refund inputs and outputs are logged and retained.",
                        "declared": True,
                        "observed": True,
                        "status": "verified",
                    },
                ],
                "performance": {
                    "runs": r_runs,
                    "aggregates": aggregates(r_runs, {"n_tests": 25, "passed": 22, "pass_rate": 0.88}),
                    "covered_model_draft": {
                        "covered_model": "Refund Agent (GPT-4o, refund-eligibility function)",
                        "function_scope": "Determines refund entitlement and issues refunds up to $500",
                        "error_definition": "Refund issued that deviates from policy-entitled amount by more than $25",
                        "ground_truth_source": "Refund policy engine reconciliation (nightly batch)",
                        "unexpected_error_threshold": "error_rate > 0.11 over any rolling 500 outputs",
                        "proposed_error_limit_usd": 250000,
                    },
                    "evidence_class": "simulated",
                },
            },
            {
                "agent_id": "support-copilot",
                "display_name": "Support Copilot",
                "description": (
                    "Non-agentic chat assistant that answers customer questions grounded "
                    "in the knowledge base. It cannot take actions on accounts."
                ),
                "posture": {
                    "model": ev("Claude 3.5 Sonnet (hosted)", ["src/agents/support.py:L9"], "confirmed"),
                    "business_activities": ev(
                        "Answers customer support questions from a grounded knowledge base",
                        ["src/agents/support.py:L14-L40"], "confirmed"),
                    "fine_tuned": ev(False, ["src/agents/support.py:L9"], "confirmed"),
                    "data_types": ev(["company_proprietary"], ["src/agents/support.py:L22"], "confirmed"),
                    "sensitive_data": ev(["pii"], ["src/agents/support.py:L25"], "confirmed"),
                    "output_types": ev(["text"], ["src/agents/support.py:L40"], "confirmed"),
                    "audience": ev("third_party", ["src/agents/support.py:L40"], "confirmed"),
                    "io_logging": ev(True, ["src/agents/support.py:L47"], "confirmed"),
                    # Non-agentic assistant: HITL not applicable. Declared as such,
                    # no code verification -> attested (not a "no").
                    "hitl": ev("not_applicable", ["onboarding:q22"], "attested"),
                    "agentic_actions": ev(False, ["src/agents/support.py:L14-L40"], "confirmed"),
                    "frameworks": ev(["nist_ai_rmf"], ["onboarding:q31"], "attested"),
                    "guardrails_intact": ev(True, ["src/agents/support.py:L11"], "confirmed"),
                },
                "attestations": [
                    {
                        "claim_id": "support-no-actions",
                        "claim_text": "The assistant cannot take actions on customer accounts.",
                        "declared": True,
                        "observed": True,
                        "status": "verified",
                    },
                    {
                        "claim_id": "support-grounding",
                        "claim_text": "Answers are grounded in the approved knowledge base.",
                        "declared": True,
                        "observed": True,
                        "status": "verified",
                    },
                ],
                "performance": {
                    "runs": s_runs,
                    "aggregates": aggregates(s_runs, {"n_tests": 18, "passed": 18, "pass_rate": 1.0}),
                    "covered_model_draft": {
                        "covered_model": "Support Copilot (Claude 3.5 Sonnet, grounded QA function)",
                        "function_scope": "Answers customer questions grounded in the knowledge base",
                        "error_definition": "Answer contains an unsupported factual claim not present in the knowledge base",
                        "ground_truth_source": "Human-labeled QA review sample",
                        "unexpected_error_threshold": "error_rate > 0.06 over any rolling 500 outputs",
                        "proposed_error_limit_usd": 100000,
                    },
                    "evidence_class": "simulated",
                },
            },
        ],
        "coverage_request": {
            "heads": ["output_error", "data_disclosure", "regulatory"],
            "limit_usd": 5000000,
            "rationale": (
                "Agentic refund initiation and PII/payment access concentrate financial "
                "and disclosure exposure; limit sized to largest-contract and refund-authority exposure."
            ),
        },
        "gaps": [
            {
                "template": "posture",
                "field_id": "checklist.other_policies",
                "description": "Confirm full schedule and limits of other policies in force (detail beyond names).",
                "owner": "human",
            },
            {
                "template": "performance",
                "field_id": "general.projections",
                "description": "Two-year projection figures require officer sign-off before submission.",
                "owner": "human",
            },
            {
                "template": "posture",
                "field_id": "contracts.largest_value",
                "description": "Largest contract value to be confirmed against signed master agreements.",
                "owner": "human",
            },
        ],
    }
    return submission


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "sample_submission.json"
    out.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
