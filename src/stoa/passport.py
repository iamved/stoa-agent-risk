"""The agent passport (``stoa-passport/0.1``): one page per agent that says
what it is, what it can do, how risky it reads, what protects it, what the
traces showed, and how far to trust the page.

Built from the registry (enriched by the runtime merge when traces were
given), the diff, and the policy block of the dashboard's runtime slot.
Pure and deterministic: the only clock is the scan's own ``head_commit``
date, so the same inputs give the same passport and the same verify hash.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from html import escape

from . import __version__
from .evidence import evidence_mix
from .risk_type import classify, dimension_label, explain

PASSPORT_SCHEMA = "stoa-passport/0.1"
VALIDITY_DAYS = 90
VALIDITY_RULE = f"lapses on drift above medium, or {VALIDITY_DAYS} days after the scan"
_DRIFT_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3}


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def registry_hash(registry: dict) -> str:
    body = {k: v for k, v in registry.items() if k not in ("passports",)}
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:16]


def _agent_name(agent: dict) -> str:
    return (agent.get("declared") or {}).get("name") or agent.get("display_name") or agent.get("name") or agent["id"]


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts.replace("Z", "+0000") if fmt.endswith("%z") else ts, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _drift_for(diff: dict | None, agent_id: str) -> dict:
    if not diff:
        return {"status": "untracked", "severity": None, "detail": "no baseline"}
    agents = diff.get("agents") or {}
    for entry in agents.get("changed") or []:
        if entry.get("agent_id") == agent_id:
            sev = entry.get("drift_severity") or "info"
            unapproved = [c for coll in ("capabilities", "integrations") for c in (entry.get(coll) or {}).get("added") or [] if not c.get("approved")]
            return {"status": "changed", "severity": sev, "detail": f"{len(unapproved)} unapproved addition(s)" if unapproved else "changes approved or informational"}
    for entry in agents.get("added") or []:
        if entry.get("agent_id") == agent_id:
            return {"status": "added", "severity": entry.get("drift_severity") or "medium", "detail": "; ".join(entry.get("drift_reasons") or [])}
    return {"status": "unchanged", "severity": None, "detail": f"vs {(diff.get('base') or {}).get('commit') or 'baseline'}"}


def build_passport(registry: dict, agent_id: str, *, diff: dict | None = None, policies: dict | None = None, runtime_slot: dict | None = None) -> dict:
    agents = {a["id"]: a for a in registry.get("agents") or []}
    agent = agents[agent_id]
    declared = agent.get("declared") or {}
    name = _agent_name(agent)
    scan_date = _parse(((registry.get("repository") or {}).get("head_commit") or {}).get("date"))
    tools = [t for t in agent.get("tools") or [] if isinstance(t, dict)]
    cap_evidence = agent.get("capability_evidence") or {c: "static" for c in agent.get("capabilities") or []}
    runtime = agent.get("runtime_evidence") or {}
    dims = [{"id": d["id"], "exposure": d.get("exposure"), "score": d.get("score"), "assessability": d.get("assessability"), "static_exposure": d.get("static_exposure")} for d in (agent.get("dimension_assessment") or {}).get("dimensions") or []]
    doc_policies = ((policies or {}).get("document") or {}).get("policies") or []
    summary = (policies or {}).get("summary") or {}
    scoped = [p for p in doc_policies if p.get("scope", {}).get("agent") in ("*", name, agent_id) and p.get("trigger") in ("tool_call", "any")]
    policy_rows = [{"id": p["id"], "title": p.get("title", ""), "action": p.get("action"), "enforced": bool(p.get("enforced")), "condition": p.get("condition_text", ""), "counts": {k: v for k, v in (summary.get(p["id"]) or {}).items() if k != "last_decision"}} for p in scoped]
    drills = [d for d in (policies or {}).get("killswitch_drills") or [] if d.get("agent_id") in (None, agent_id, name)]
    test = ((policies or {}).get("test") or {}).get("agents", {}).get(name) or ((policies or {}).get("test") or {}).get("agents", {}).get(agent_id)
    drift = _drift_for(diff, agent_id)
    lapsed_by_drift = _DRIFT_RANK.get(drift.get("severity") or "info", 0) > _DRIFT_RANK["medium"]
    expires = (scan_date + timedelta(days=VALIDITY_DAYS)).strftime("%Y-%m-%d") if scan_date else None
    classification = agent.get("risk_type") or classify(agent) or {}
    body = {
        "schema": PASSPORT_SCHEMA,
        "agent": {
            "id": agent_id, "name": name, "owner": declared.get("owner") or None, "purpose": declared.get("purpose") or None,
            "production_status": declared.get("production_status"), "users": declared.get("users"),
            "declared_autonomy": declared.get("autonomy_intent"), "inferred_autonomy": (agent.get("autonomy_level") or {}).get("level"),
            "defined_in": agent.get("path"), "source": agent.get("source") or "code", "platform": agent.get("platform"),
        },
        "capabilities": [{"id": c, "evidence_level": lvl} for c, lvl in sorted(cap_evidence.items())],
        "tools": [{"name": t.get("name"), "money_action": bool(t.get("money_action")), "high_impact": bool(t.get("high_impact")), "guardrails": list(t.get("guards") or [])} for t in tools],
        "reach": {
            "reachable": sorted(c for c, lvl in cap_evidence.items() if lvl == "reachable"),
            "static": sorted(c for c, lvl in cap_evidence.items() if lvl == "static"),
            "observed": sorted(runtime.get("observed_capabilities") or []),
        },
        "dimensions": dims,
        "risk_type": classification,
        "explanation": agent.get("explanation") or explain(agent, policies=scoped),
        "controls_observed": sorted({c for d in (agent.get("dimension_assessment") or {}).get("dimensions") or [] for c in d.get("controls_observed") or []}),
        "policies": {"mode": ((policies or {}).get("document") or {}).get("mode"), "attached": policy_rows},
        "drift": drift,
        "evidence_mix": {**evidence_mix(agent), "tested": int((test or {}).get("scenarios") or 0)},
        "runtime": {"window": runtime.get("window"), "span_count": runtime.get("span_count"), "money_actions": runtime.get("money_actions"), "approval_rate_money": runtime.get("approval_rate_money"), "flag_counts": runtime.get("flag_counts")} if runtime else None,
        "killswitch_drill": drills[-1] if drills else None,
        "policy_test": test,
        "registry_hash": registry_hash(registry),
        "scanner_version": __version__,
        "scan_date": scan_date.strftime("%Y-%m-%d") if scan_date else None,
        "validity": {"rule": VALIDITY_RULE, "expires": expires, "status": "lapsed" if lapsed_by_drift else "valid", "reason": f"drift {drift.get('severity')} since the baseline" if lapsed_by_drift else None},
    }
    body["verify_hash"] = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()[:16]
    return body


def build_passports(registry: dict, *, diff: dict | None = None, policies: dict | None = None, runtime_slot: dict | None = None) -> list[dict]:
    return [build_passport(registry, a["id"], diff=diff, policies=policies, runtime_slot=runtime_slot) for a in sorted(registry.get("agents") or [], key=lambda a: _agent_name(a))]


# --- HTML --------------------------------------------------------------------------------------

_CSS = """
body{font:13.5px/1.5 "Public Sans",system-ui,sans-serif;color:#182a3e;background:#faf9f5;margin:0;padding:28px}
main{max-width:860px;margin:0 auto}h1{font-size:20px;margin:0 0 2px}h2{font-size:13px;margin:22px 0 6px;letter-spacing:.06em;text-transform:uppercase;color:#57697c}
.band{background:#0e1c36;color:#fff;border-radius:8px;padding:14px 18px;margin:14px 0}.band b{color:#e3c88a}
table{border-collapse:collapse;width:100%;background:#fff;border:1px solid #e3e0d6;border-radius:8px}td,th{padding:7px 10px;border-bottom:1px solid #e3e0d6;text-align:left;vertical-align:top;font-size:12.5px}th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#57697c}
.kv td:first-child{color:#57697c;width:28%}.chip{display:inline-block;border:1px solid #e3e0d6;border-radius:4px;padding:0 6px;font-size:11.5px;margin-right:4px}.hi{color:#b54708;font-weight:600}.ok{color:#2f6f4f}
.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}.muted{color:#57697c}p{margin:4px 0}@media print{body{padding:0;background:#fff}}
"""


def render_passport_html(passport: dict, *, company: str | None = None) -> str:
    a = passport["agent"]
    e = escape
    rt = passport.get("risk_type") or {}
    ex = passport.get("explanation") or {}
    rows = lambda pairs: "".join(f"<tr><td>{e(str(k))}</td><td>{v}</td></tr>" for k, v in pairs)
    caps = " ".join(f'<span class="chip">{e(c["id"])} <span class="muted">{e(c["evidence_level"])}</span></span>' for c in passport["capabilities"]) or '<span class="muted">none detected</span>'
    tools = "".join(f"<tr><td class=mono>{e(t['name'])}</td><td>{'money' if t['money_action'] else 'high impact' if t['high_impact'] else ''}</td><td>{', '.join(map(e, t['guardrails'])) or '<span class=muted>none</span>'}</td></tr>" for t in passport["tools"]) or "<tr><td colspan=3 class=muted>no tool definitions detected</td></tr>"
    dims = "".join(f"<tr><td>{e(dimension_label(d['id']))}</td><td class={'hi' if d['exposure']=='elevated' else ''}>{e(str(d['exposure']))}</td><td>{e(str(d['score']))}</td><td>{e('traces' if d['assessability'] == 'runtime' else str(d['assessability']))}</td></tr>" for d in passport["dimensions"])
    pol = passport["policies"]["attached"]
    pols = "".join(f"<tr><td class=mono>{e(p['id'])}</td><td>{e(p['title'])}</td><td>{e(p['action'])}{' <b>enforced</b>' if p['enforced'] else ''}</td><td class=mono>{e(p['condition'])}</td><td>{', '.join(f'{k} {v}' for k, v in p['counts'].items() if v)}</td></tr>" for p in pol) or "<tr><td colspan=5 class=muted>no policy scoped to this agent</td></tr>"
    runtime = passport.get("runtime")
    drill = passport.get("killswitch_drill")
    test = passport.get("policy_test")
    val = passport["validity"]
    mix = ", ".join(f"{n} {lvl}" for lvl, n in passport["evidence_mix"].items() if n) or "none"
    return f"""<!doctype html><html lang=en><head><meta charset="utf-8"><title>Agent passport: {e(a['name'])}</title><style>{_CSS}</style></head><body><main>
<h1>Agent passport: {e(a['name'])}</h1><div class=muted>{e(company or '')}{' · ' if company else ''}scanned {e(passport.get('scan_date') or '')} · registry {passport['registry_hash']} · stoa {e(passport['scanner_version'])}</div>
<div class=band><b>{e(rt.get('primary') or 'No exposure')}</b>{(' driven by ' + e(dimension_label(rt['driver']).lower()) + ' (' + e(str(rt.get('driver_exposure'))) + ')') if rt.get('driver') else ''} · confidence {e(rt.get('confidence') or '')} · passport <b>{e(val['status'])}</b>{(' (' + e(val['reason']) + ')') if val.get('reason') else ''}, {e(val['rule'])}{(', expires ' + e(val['expires'])) if val.get('expires') else ''}</div>
<h2>Identity</h2><table class=kv>{rows([("Owner", e(a['owner'] or 'not declared')), ("Purpose", e(a['purpose'] or 'not declared')), ("Status", e(a['production_status'] or 'not declared')), ("Users", e(a['users'] or 'not declared')), ("Declared autonomy", e(a['declared_autonomy'] or 'not declared')), ("Inferred autonomy", e(a['inferred_autonomy'] or 'indeterminate')), ("Defined in", f"<span class=mono>{e(a['defined_in'] or '')}</span> ({e(a['source'])}{(', ' + e(a['platform'])) if a.get('platform') else ''})")])}</table>
<h2>In plain words</h2><p>{e(ex.get('can_do',''))}</p><p>{e(ex.get('could_go_wrong',''))}</p><p>{e(ex.get('protects',''))}</p><p>{e(ex.get('missing',''))}</p><p class=muted>{e(ex.get('evidence',''))}</p>
<h2>Capabilities and reach</h2><p>{caps}</p><p class=muted>reachable from infrastructure: {', '.join(map(e, passport['reach']['reachable'])) or 'none'} · observed at runtime: {', '.join(map(e, passport['reach']['observed'])) or 'none'}</p>
<h2>Tools</h2><table><tr><th>Tool</th><th>Kind</th><th>Guardrails detected</th></tr>{tools}</table>
<h2>Exposure by category</h2><table><tr><th>Category</th><th>Exposure</th><th>Score</th><th>Assessed</th></tr>{dims}</table>
<h2>Safeguards detected</h2><p>{', '.join(map(e, passport['controls_observed'])) or '<span class=muted>none</span>'}</p>
<h2>Policies{(' (mode ' + e(passport['policies']['mode']) + ')') if passport['policies'].get('mode') else ''}</h2><table><tr><th>Policy</th><th>Title</th><th>Action</th><th>Condition</th><th>In the window</th></tr>{pols}</table>
<h2>Runtime</h2><p>{(f"{runtime['span_count']} spans, {runtime.get('money_actions') or 0} money actions, approval rate {runtime['approval_rate_money'] if runtime.get('approval_rate_money') is not None else 'n/a'}; window {e(str((runtime.get('window') or {}).get('start')))} to {e(str((runtime.get('window') or {}).get('end')))}") if runtime else '<span class=muted>nothing observed at runtime yet</span>'}</p>
<p>Kill switch drill: {(f"stopped in {drill['seconds_to_stop']}s" + (f" ({e(str(drill.get('by')))})" if drill.get('by') else '')) if drill and drill.get('seconds_to_stop') is not None else '<span class=muted>none recorded</span>'}</p>
<p>Policy test: {(f"{test['scenarios']} scenarios, {test['matched']} matched expectations, {test['false_positives']} false positives") if test else '<span class=muted>none run</span>'}</p>
<h2>Drift</h2><p>{e(passport['drift']['status'])}{(' · ' + e(passport['drift']['severity'])) if passport['drift'].get('severity') else ''} · {e(passport['drift']['detail'])}</p>
<h2>Evidence</h2><p>{e(mix)}</p>
<p class=muted>Verify hash {passport['verify_hash']}. Generated by stoa {e(passport['scanner_version'])} from registry {passport['registry_hash']}; the hash changes when the registry changes.</p>
</main></body></html>
"""
