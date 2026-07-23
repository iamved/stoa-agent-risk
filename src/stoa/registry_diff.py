"""Registry-to-registry capability drift (`stoa diff`, Part III).

Compares two deterministic registries and reports capability/population/finding
drift plus dimension deltas. A diff describes *call sites added or removed in
code*, never runtime behavior. Output (`stoa-diff/1.0`) has no timestamps —
provenance is the registries' embedded commit SHAs and scanner versions — so
identical inputs give byte-identical output.

This is a separate module from ``diff.py`` (git line-diff gating); that machine
is untouched.
"""

from __future__ import annotations

from hashlib import sha256

from .models import SEVERITY_ORDER
from .rules import HIGH_IMPACT_CAPABILITIES, SENSITIVE_INTEGRATIONS

DIFF_SCHEMA = "stoa-diff/1.0"
DRIFT_ORDER = ["info", "low", "medium", "high"]
_EXPOSURE_ORDER = ["none-observed", "low", "moderate", "elevated", "not-assessable"]


def _evidence_fps(agent: dict) -> set[str]:
    return {
        sha256(f"{e.get('rule_id')}:{e.get('description')}".encode()).hexdigest()[:12]
        for e in agent.get("evidence", [])
    }


def agent_evidence_fingerprint(agent: dict) -> str:
    """Stable fingerprint of an agent's evidence set (line-independent)."""
    return sha256("|".join(sorted(_evidence_fps(agent))).encode()).hexdigest()[:12]


def _max_drift(levels: list[str]) -> str:
    return max(levels, key=DRIFT_ORDER.index) if levels else "info"


def _cap_drift(added: list[str]) -> str:
    return "high" if HIGH_IMPACT_CAPABILITIES.intersection(added) else "medium"


def _integ_drift(added: list[str]) -> str:
    return "high" if SENSITIVE_INTEGRATIONS.intersection(added) else "medium"


def _match_agents(base: dict, head: dict) -> tuple[dict, dict, list[tuple[str, str]]]:
    """Return (base_by_id, head_by_id, renames[(base_id, head_id)])."""
    base_by_id = {a["id"]: a for a in base.get("agents", [])}
    head_by_id = {a["id"]: a for a in head.get("agents", [])}
    base_only = set(base_by_id) - set(head_by_id)
    head_only = set(head_by_id) - set(base_by_id)
    renames: list[tuple[str, str]] = []
    for bid in sorted(base_only):
        bfps = _evidence_fps(base_by_id[bid])
        if not bfps:
            continue
        best, best_score = None, 0.0
        for hid in sorted(head_only):
            hfps = _evidence_fps(head_by_id[hid])
            if not hfps:
                continue
            jac = len(bfps & hfps) / len(bfps | hfps)
            if jac > best_score:
                best, best_score = hid, jac
        if best is not None and best_score >= 0.70:
            renames.append((bid, best))
            head_only.discard(best)
    return base_by_id, head_by_id, renames


def _finding_ids(agent: dict) -> dict[str, dict]:
    return {f.get("fingerprint"): f for f in agent.get("findings", [])}


def _dimension_delta(base_agent: dict, head_agent: dict) -> list[dict]:
    base_dims = {d["id"]: d["exposure"]
                 for d in (base_agent.get("dimension_assessment") or {}).get("dimensions", [])}
    head_dims = {d["id"]: d["exposure"]
                 for d in (head_agent.get("dimension_assessment") or {}).get("dimensions", [])}
    out = []
    for dim in sorted(set(base_dims) | set(head_dims)):
        b = base_dims.get(dim, "none-observed")
        h = head_dims.get(dim, "none-observed")
        if b != h:
            direction = ("increased" if _EXPOSURE_ORDER.index(h) > _EXPOSURE_ORDER.index(b)
                         else "decreased")
            out.append({"id": dim, "from": b, "to": h, "direction": direction})
    return out


def _changed_agent(base_agent: dict, head_agent: dict, approvals, renamed_from: str | None) -> dict | None:
    def delta(key):
        b, h = set(base_agent.get(key, [])), set(head_agent.get(key, []))
        return sorted(h - b), sorted(b - h)

    cap_add, cap_rem = delta("capabilities")
    int_add, int_rem = delta("integrations")
    prov_add, prov_rem = delta("providers")

    base_f, head_f = _finding_ids(base_agent), _finding_ids(head_agent)
    new_findings = [head_f[k] for k in head_f if k not in base_f]
    resolved = [base_f[k] for k in base_f if k not in head_f]
    dim_delta = _dimension_delta(base_agent, head_agent)
    conf_changed = base_agent.get("confidence") != head_agent.get("confidence")

    if not any([cap_add, cap_rem, int_add, int_rem, prov_add, prov_rem,
                new_findings, resolved, dim_delta, conf_changed, renamed_from]):
        return None

    drifts = []
    caps_added = []
    for cap in cap_add:
        sev = "high" if cap in HIGH_IMPACT_CAPABILITIES else "medium"
        drifts.append(sev)
        caps_added.append({
            "id": cap, "high_impact": cap in HIGH_IMPACT_CAPABILITIES,
            "drift_severity": sev, "approved": _is_approved(approvals, head_agent, "capability", cap),
        })
    integs_added = []
    for integ in int_add:
        sev = "high" if integ in SENSITIVE_INTEGRATIONS else "medium"
        drifts.append(sev)
        integs_added.append({
            "id": integ, "sensitive": integ in SENSITIVE_INTEGRATIONS,
            "drift_severity": sev, "approved": _is_approved(approvals, head_agent, "integration", integ),
        })
    if prov_add:
        drifts.append("medium")
    if conf_changed and _conf_rank(head_agent) > _conf_rank(base_agent):
        drifts.append("medium")
    if cap_rem or int_rem or prov_rem or resolved:
        drifts.append("info")

    return {
        "agent_id": head_agent["id"],
        "name": head_agent["name"],
        "path": head_agent["path"],
        **({"renamed_from": renamed_from} if renamed_from else {}),
        "confidence": {"base": base_agent.get("confidence"), "head": head_agent.get("confidence")},
        "capabilities": {"added": caps_added,
                         "removed": [{"id": c, "high_impact": c in HIGH_IMPACT_CAPABILITIES,
                                      "drift_severity": "info"} for c in cap_rem]},
        "integrations": {"added": integs_added,
                         "removed": [{"id": i, "sensitive": i in SENSITIVE_INTEGRATIONS,
                                      "drift_severity": "info"} for i in int_rem]},
        "providers": {"added": prov_add, "removed": prov_rem},
        "findings_delta": {
            "new": [{"fingerprint": f["fingerprint"], "rule_id": f["rule_id"],
                     "severity": f["severity"], "line": f["line"]} for f in new_findings],
            "resolved": [{"fingerprint": f["fingerprint"], "rule_id": f["rule_id"]} for f in resolved],
        },
        "dimension_delta": dim_delta,
        "drift_severity": _max_drift(drifts),
    }


def _conf_rank(agent: dict) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(agent.get("confidence", "low"), 0)


def _is_approved(approvals, head_agent: dict, kind: str, value: str) -> bool:
    if approvals is None:
        return False
    return approvals.is_approved(head_agent["id"], kind, value,
                                 agent_evidence_fingerprint(head_agent))


def _added_agent(agent: dict, approvals) -> dict:
    caps = agent.get("capabilities", [])
    hi = HIGH_IMPACT_CAPABILITIES.intersection(caps)
    reasons = []
    if hi:
        drift = "high"
        reasons.append(f"new agent binds high-impact capability {sorted(hi)[0]}")
    elif SENSITIVE_INTEGRATIONS.intersection(agent.get("integrations", [])):
        drift = "high"
        reasons.append("new agent binds a sensitive integration")
    else:
        drift = "medium"
        reasons.append("new agent")
    return {
        "agent_id": agent["id"], "name": agent["name"], "path": agent["path"],
        "confidence": agent.get("confidence"),
        "capabilities": caps, "integrations": agent.get("integrations", []),
        "providers": agent.get("providers", []),
        "drift_severity": drift, "drift_reasons": reasons,
        "approved": _is_approved(approvals, agent, "new-agent", agent["name"]),
    }


def diff_registries(base: dict, head: dict, approvals=None) -> dict:
    """Compute the stoa-diff/1.0 document (deterministic)."""
    _check_taxonomy_match(base, head)
    base_by_id, head_by_id, renames = _match_agents(base, head)
    rename_head = {h: b for b, h in renames}
    rename_base = {b for b, _ in renames}

    added, removed, changed = [], [], []
    for hid in sorted(head_by_id):
        if hid in base_by_id:
            entry = _changed_agent(base_by_id[hid], head_by_id[hid], approvals, None)
            if entry:
                changed.append(entry)
        elif hid in rename_head:
            bid = rename_head[hid]
            entry = _changed_agent(base_by_id[bid], head_by_id[hid], approvals,
                                   base_by_id[bid].get("name"))
            changed.append(entry or _min_changed(base_by_id[bid], head_by_id[hid]))
        else:
            added.append(_added_agent(head_by_id[hid], approvals))
    for bid in sorted(base_by_id):
        if bid not in head_by_id and bid not in rename_base:
            a = base_by_id[bid]
            removed.append({"agent_id": bid, "name": a["name"], "path": a["path"],
                            "drift_severity": "info"})

    escalations = {"high": 0, "medium": 0, "low": 0}
    all_drifts, unapproved_drifts = [], []
    for entry in changed:
        for coll in ("capabilities", "integrations"):
            for item in entry[coll]["added"]:
                sev = item["drift_severity"]
                if sev in escalations:
                    escalations[sev] += 1
                all_drifts.append(sev)
                if not item.get("approved"):
                    unapproved_drifts.append(sev)
    for entry in added:
        all_drifts.append(entry["drift_severity"])
        if not entry.get("approved"):
            unapproved_drifts.append(entry["drift_severity"])

    new_crit = sum(1 for e in changed for f in e["findings_delta"]["new"] if f["severity"] == "critical")
    new_high = sum(1 for e in changed for f in e["findings_delta"]["new"] if f["severity"] == "high")
    resolved = sum(len(e["findings_delta"]["resolved"]) for e in changed)

    return {
        "schema": DIFF_SCHEMA,
        "scanner_version": head.get("tool", {}).get("version", "unknown"),
        "base": {"registry_schema": base.get("schema_version", "1.0"),
                 "commit": base.get("repository", {}).get("git_ref"),
                 "ref": base.get("repository", {}).get("base_ref")},
        "head": {"registry_schema": head.get("schema_version", "1.1"),
                 "commit": head.get("repository", {}).get("git_ref"), "ref": "HEAD"},
        "summary": {
            "agents_added": len(added), "agents_removed": len(removed),
            "agents_changed": len(changed), "escalations": escalations,
            "reductions": sum(1 for e in changed
                              if e["capabilities"]["removed"] or e["integrations"]["removed"]),
            "findings_delta": {"new_critical": new_crit, "new_high": new_high, "resolved": resolved},
            "max_drift_severity": _max_drift(all_drifts),
            "unapproved_max_drift_severity": _max_drift(unapproved_drifts) if unapproved_drifts else "info",
            "approvals_applied": len(all_drifts) - len(unapproved_drifts),
        },
        "agents": {"added": added, "removed": removed, "changed": changed},
        "approvals": {"applied": [], "stale": approvals.stale_records() if approvals else [],
                      "file": approvals.path_str() if approvals else None},
    }


def _min_changed(base_agent, head_agent) -> dict:
    return {"agent_id": head_agent["id"], "name": head_agent["name"], "path": head_agent["path"],
            "renamed_from": base_agent.get("name"),
            "confidence": {"base": base_agent.get("confidence"), "head": head_agent.get("confidence")},
            "capabilities": {"added": [], "removed": []},
            "integrations": {"added": [], "removed": []},
            "providers": {"added": [], "removed": []},
            "findings_delta": {"new": [], "resolved": []}, "dimension_delta": [],
            "drift_severity": "info"}


class TaxonomyMismatch(Exception):
    """Diffing registries built with different taxonomies; maps to exit 2."""


def _check_taxonomy_match(base: dict, head: dict) -> None:
    def tax(reg):
        s = reg.get("dimension_summary")
        return (s or {}).get("taxonomy")
    bt, ht = tax(base), tax(head)
    if bt and ht and bt != ht:
        raise TaxonomyMismatch(
            f"base taxonomy {bt} != head taxonomy {ht}; cannot compare dimensions"
        )


_DRIFT_GLYPH = {"high": "🔴 high", "medium": "🟡 medium", "low": "⚪ low", "info": "◽ info"}


def render_changelog(diff: dict, fail_on_drift: str | None = None) -> str:
    """GitHub-flavored Markdown agent changelog, generated from the diff only."""
    s = diff["summary"]
    unapproved = s["unapproved_max_drift_severity"]
    changed, added, removed = diff["agents"]["changed"], diff["agents"]["added"], diff["agents"]["removed"]
    n_unappr_high = sum(
        1 for e in changed for coll in ("capabilities", "integrations")
        for item in e[coll]["added"]
        if item["drift_severity"] == "high" and not item.get("approved")
    )
    header = (f"⚠️ {n_unappr_high} unapproved high-severity drift"
              if n_unappr_high else "no unapproved high-severity drift")
    lines = [f"## Stoa · Agent Changelog — {header}", ""]
    base_ref = diff["base"].get("ref") or diff["base"].get("commit") or "base"
    gate = ""
    if fail_on_drift and fail_on_drift != "none":
        would = DRIFT_ORDER.index(unapproved) >= DRIFT_ORDER.index(fail_on_drift)
        gate = f" · gate: **{'would fail' if would else 'passes'}** (`--fail-on-drift {fail_on_drift}`)"
    lines.append(f"`{base_ref}` → `HEAD` · {s['agents_changed']} changed, "
                 f"{s['agents_added']} added, {s['agents_removed']} removed{gate}")

    escal_rows = []
    for e in changed:
        for coll, label in (("capabilities", ""), ("integrations", " integration")):
            for item in e[coll]["added"]:
                impact = " (high-impact)" if item.get("high_impact") else ""
                dims = ""
                approved = "✅" if item.get("approved") else "❌"
                escal_rows.append(
                    f"| `{e['name']}` | + `{item['id']}`{impact}{label} | "
                    f"`{e['path']}` | {_DRIFT_GLYPH[item['drift_severity']]} | {approved} |")
    if escal_rows:
        lines += ["", "### ⬆️ Capability escalations", "",
                  "| Agent | Change | Location | Drift | Approved |",
                  "|---|---|---|---|---|", *escal_rows]

    if added:
        lines += ["", "### 🆕 New agents", "",
                  "| Agent | Confidence | Capabilities | Integrations | Drift |",
                  "|---|---|---|---|---|"]
        for a in added:
            caps = ", ".join(a["capabilities"]) or "—"
            integs = ", ".join(a["integrations"]) or "—"
            lines.append(f"| `{a['name']}` | {a['confidence']} | {caps} | {integs} | "
                         f"{_DRIFT_GLYPH[a['drift_severity']]} |")

    reductions = [(e["name"], item["id"], coll)
                  for e in changed for coll in ("capabilities", "integrations")
                  for item in e[coll]["removed"]]
    if reductions or removed:
        lines += ["", "### 🧹 Reductions & removals"]
        for name, val, coll in reductions:
            lines.append(f"- `{name}` − `{val}` (call site removed)")
        for a in removed:
            lines.append(f"- `{a['name']}` agent no longer detected")

    new_findings = [(e, f) for e in changed for f in e["findings_delta"]["new"]]
    if new_findings:
        lines += ["", "### 🩺 Finding delta on changed agents"]
        for e, f in new_findings:
            gate_note = " (gate-eligible)" if f.get("severity") == "critical" else ""
            lines.append(f"- **New {f['severity']}** — {f['rule_id']} at "
                         f"`{e['path']}:{f['line']}`{gate_note}")

    lines += ["", "<details><summary>How to approve intentional changes</summary>", "",
              "```", "stoa approve --agent <name> --capability <value> \\",
              '  --reason "reviewed in TICKET-123" --by @security-oncall', "```", "",
              "Approvals live in `.stoa/approvals.toml` (CODEOWNERS-protected).",
              "</details>", "",
              "*Static analysis of call sites — not runtime behavior. Capability "
              "changes describe what the code can reach; removals may reflect refactors.*",
              "<!-- stoa-diff-comment:v1 -->"]
    return "\n".join(lines) + "\n"


def dimension_increase_exceeds(diff: dict, dim_id: str, level: str) -> bool:
    """True if any changed agent's dimension increased to >= level."""
    target = _EXPOSURE_ORDER.index(level)
    for entry in diff["agents"]["changed"]:
        for d in entry.get("dimension_delta", []):
            if d["id"] == dim_id and d["direction"] == "increased" \
                    and _EXPOSURE_ORDER.index(d["to"]) >= target:
                return True
    return False
