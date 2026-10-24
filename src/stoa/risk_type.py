"""One customer-facing risk type per agent, and a plain-English explanation.

The eight dimensions map to the risk types used on stoa.insure:

| Dimension | Risk type |
|---|---|
| boundary-leakage | Data Leakage |
| mandate-overreach | Erroneous Transactions |
| unreviewed-high-impact-action | Erroneous Transactions (money) or Data Loss & Corruption (writes) |
| output-fidelity | AI Hallucinations |
| injection-tamper-surface | Prompt Injections |
| conduct-variability | Performance Failure, or Algorithmic Bias when the agent decides about people |
| dependency-drift | Performance Failure |
| control-coverage-gap | cross-cutting: lowers the confidence in whatever the primary is |

The primary type is the one driven by the agent's highest dimension
(exposure bucket first, score second, taxonomy order as the tie-break).
The explanation is five short lines built from templates over the
registry's own facts; identical inputs give identical text. No model
is called.
"""

from __future__ import annotations

from .evidence import evidence_mix

# The dashboard's display names for the eight dimensions; ids stay the taxonomy's.
DIMENSION_LABEL = {
    "boundary-leakage": "Data leaks", "mandate-overreach": "Excess access", "injection-tamper-surface": "Injection risk",
    "control-coverage-gap": "Missing safeguards", "unreviewed-high-impact-action": "Unchecked actions", "output-fidelity": "Unreliable output",
    "conduct-variability": "Inconsistent behavior", "dependency-drift": "Dependency drift",
}


def dimension_label(dim_id: str) -> str:
    return DIMENSION_LABEL.get(dim_id, dim_id.replace("-", " "))


RISK_TYPES = (
    "Data Leakage", "Erroneous Transactions", "Data Loss & Corruption", "AI Hallucinations",
    "Prompt Injections", "Performance Failure", "Algorithmic Bias",
)
_EXPOSURE_RANK = {"none-observed": 0, "not-assessable": 0, "low": 1, "moderate": 2, "elevated": 3}
_ORDER = ["boundary-leakage", "mandate-overreach", "unreviewed-high-impact-action", "output-fidelity", "injection-tamper-surface", "conduct-variability", "dependency-drift", "control-coverage-gap"]
_MONEY_CAPS = {"payment_access"}
_WRITE_CAPS = {"database_write", "filesystem_write", "shell_execution", "code_execution", "cloud_resource_access", "source_control"}
_DECIDES_ABOUT_PEOPLE = {"personal", "health", "financial"}

CAP_PHRASE = {
    "payment_access": "move money", "database_write": "change records", "database_read": "read records", "filesystem_write": "write files",
    "shell_execution": "run shell commands", "code_execution": "run code", "email_send": "send email", "messaging": "send messages",
    "external_http": "call outside services", "cloud_resource_access": "change cloud resources", "source_control": "change source code",
    "vector_search": "search documents", "tool_calling": None, "function_calling": None, "reads": None, "search": None,
    "queue_access": "write to queues", "browser_automation": "drive a browser",
}
CONTROL_PHRASE = {
    "approval": "a person approves before it acts", "kill_switch": "a kill switch", "authentication": "callers are signed in",
    "validation": "inputs are checked", "rate_limit": "a rate limit", "observability": "logging", "deterministic_sampling": "fixed model settings", "sandbox": "an isolated environment",
}


def _type_for(dim_id: str, agent: dict) -> str:
    caps = set(agent.get("capabilities") or [])
    money = bool(caps & _MONEY_CAPS) or any(t.get("money_action") for t in agent.get("tools") or [] if isinstance(t, dict))
    declared_classes = set((agent.get("declared") or {}).get("data_classes") or [])
    if dim_id == "boundary-leakage":
        return "Data Leakage"
    if dim_id == "mandate-overreach":
        return "Erroneous Transactions" if money or not (caps & _WRITE_CAPS) else "Data Loss & Corruption"
    if dim_id == "unreviewed-high-impact-action":
        return "Erroneous Transactions" if money else "Data Loss & Corruption"
    if dim_id == "output-fidelity":
        return "AI Hallucinations"
    if dim_id == "injection-tamper-surface":
        return "Prompt Injections"
    if dim_id == "conduct-variability":
        return "Algorithmic Bias" if declared_classes & _DECIDES_ABOUT_PEOPLE and (agent.get("declared") or {}).get("users") in ("customers", "public") else "Performance Failure"
    if dim_id == "dependency-drift":
        return "Performance Failure"
    return "Performance Failure"


def classify(agent: dict) -> dict | None:
    """``{primary, driver, driver_exposure, driver_score, confidence}`` or None without an assessment."""
    entries = [e for e in (agent.get("dimension_assessment") or {}).get("dimensions") or [] if e.get("id") in _ORDER]
    if not entries:
        return None
    scored = [e for e in entries if e["id"] != "control-coverage-gap"]
    scored.sort(key=lambda e: (-_EXPOSURE_RANK.get(e.get("exposure"), 0), -float(e.get("score") or 0), _ORDER.index(e["id"])))
    driver = scored[0]
    gap = next((e for e in entries if e["id"] == "control-coverage-gap"), None)
    gap_rank = _EXPOSURE_RANK.get((gap or {}).get("exposure"), 0)
    confidence = "low" if gap_rank >= 3 else "medium" if gap_rank == 2 else "high"
    if driver.get("exposure") in ("none-observed", "not-assessable", None) and not float(driver.get("score") or 0):
        return {"primary": "Performance Failure", "driver": None, "driver_exposure": None, "driver_score": 0, "confidence": confidence, "note": "no dimension shows exposure"}
    return {"primary": _type_for(driver["id"], agent), "driver": driver["id"], "driver_exposure": driver.get("exposure"), "driver_score": driver.get("score"), "confidence": confidence}


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def explain(agent: dict, *, policies: list[dict] | None = None) -> dict:
    """Five lines: what it can do, what could go wrong, what protects it, what is missing, how good the evidence is."""
    caps = agent.get("capabilities") or []
    tools = [t for t in agent.get("tools") or [] if isinstance(t, dict)]
    money_tools = [t["name"] for t in tools if t.get("money_action")]
    name = (agent.get("declared") or {}).get("name") or agent.get("display_name") or agent.get("name") or agent.get("id")
    verbs = [CAP_PHRASE.get(c, c.replace("_", " ")) for c in caps if CAP_PHRASE.get(c, c) is not None]
    can_do = f"{name} can {_join(sorted(set(verbs)))}" if verbs else f"{name} recommends and answers; the scan found no tool that changes anything"
    if money_tools:
        can_do += f", through {len(money_tools)} money-moving tool{'s' if len(money_tools) != 1 else ''} ({', '.join(money_tools[:3])}{', ...' if len(money_tools) > 3 else ''})"
    can_do += "."

    classification = classify(agent) or {}
    primary = classification.get("primary")
    driver = classification.get("driver")
    controls = sorted({c for d in (agent.get("dimension_assessment") or {}).get("dimensions") or [] for c in d.get("controls_observed") or []})
    # The scan's own findings; runtime (RT) findings are counted on the Runtime tab, not here.
    high_findings = [f for f in agent.get("findings") or [] if f.get("severity") in ("critical", "high") and not f.get("suppressed") and not str(f.get("rule_id", "")).startswith("RT")]
    wrong = {
        "Erroneous Transactions": "money or account changes go out wrong, twice, or without anyone deciding",
        "Data Leakage": "data the agent can read ends up where it should not",
        "Data Loss & Corruption": "records or systems are changed or lost without a check",
        "AI Hallucinations": "the agent states something untrue and acts on it",
        "Prompt Injections": "text from a user or a document steers what the agent does",
        "Performance Failure": "the agent stops working or behaves differently after a change nobody made on purpose",
        "Algorithmic Bias": "people get different outcomes for reasons nobody chose",
    }.get(primary or "", "")
    go_wrong = f"Most likely failure: {wrong}." if wrong else "No dimension shows exposure in this scan."
    if driver:
        go_wrong += f" Driven by {dimension_label(driver).lower()} ({classification.get('driver_exposure')})."
    if high_findings:
        go_wrong += f" {len(high_findings)} high-severity finding{'s' if len(high_findings) != 1 else ''} point{'s' if len(high_findings) == 1 else ''} there."

    protects_parts = [CONTROL_PHRASE.get(c, c.replace("_", " ")) for c in controls]
    guarded = [t["name"] for t in tools if t.get("guards")]
    if guarded:
        protects_parts.append(f"guardrails on {len(guarded)} tool{'s' if len(guarded) != 1 else ''}")
    scoped = [p for p in (policies or []) if p.get("action") in ("block", "escalate")]
    if scoped:
        enforced = [p for p in scoped if p.get("enforced")]
        protects_parts.append(f"{len(scoped)} block-or-escalate polic{'ies' if len(scoped) != 1 else 'y'}, {len(enforced)} enforced")
    protects = f"Detected: {_join(protects_parts)}." if protects_parts else "No safeguard was detected on this agent."

    missing_parts = []
    expected = ["approval", "kill_switch", "observability", "rate_limit"] if (money_tools or "payment_access" in caps) else ["kill_switch", "observability"]
    for c in expected:
        if c not in controls and not (c == "approval" and any(p.get("action") == "escalate" for p in scoped)):
            missing_parts.append(CONTROL_PHRASE.get(c, c))
    declared = agent.get("declared") or {}
    if (money_tools or "payment_access" in caps) and not (declared.get("economic_authority") or {}).get("max_per_action"):
        missing_parts.append("a declared spending limit")
    if not declared:
        missing_parts.append("a declaration (owner, purpose, intended autonomy)")
    missing = f"Missing: {_join(missing_parts)}." if missing_parts else "Nothing the scan expected is missing."

    mix = evidence_mix(agent)
    runtime = agent.get("runtime_evidence")
    parts = [f"{n} {level}" for level, n in mix.items() if n]
    evidence = f"Evidence: {', '.join(parts)}." if parts else "Evidence: none beyond detection."
    if runtime:
        evidence += f" Observed over {runtime.get('span_count')} spans."
    else:
        evidence += " Nothing observed at runtime yet."
    return {"can_do": can_do, "could_go_wrong": go_wrong, "protects": protects, "missing": missing, "evidence": evidence}


def annotate_risk_types(document: dict, *, policies: list[dict] | None = None) -> None:
    """Stamp ``risk_type`` and ``explanation`` on every agent, in place."""
    for agent in document.get("agents") or []:
        name = (agent.get("declared") or {}).get("name") or agent.get("display_name") or agent.get("name")
        scoped = [p for p in (policies or []) if p.get("scope", {}).get("agent") in ("*", name, agent.get("id")) and p.get("trigger") in ("tool_call", "any")]
        classification = classify(agent)
        if classification is not None:
            agent["risk_type"] = classification
        agent["explanation"] = explain(agent, policies=scoped)
