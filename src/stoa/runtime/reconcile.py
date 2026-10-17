"""The three-way tool table (`stoa runtime reconcile`) — `runtime-reconcile/1.0`.

For every registry agent: the tools the scan listed (schema 1.7 ``tools``),
the tools traces show it calling, and the overlap. Three columns a reviewer
asks for in that order:

- **declared and used**   listed by the scan, observed in the window;
- **used but undeclared** observed, not in the scanned inventory (RT006);
- **declared but dormant** listed, not observed for ``dormant_days``
  (measured back from the window end, the data's clock, not the wall's).

Built from the analysis document, so it never re-reads traces.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

RECONCILE_SCHEMA = "runtime-reconcile/1.0"


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def reconcile(registry: dict, analysis: dict, *, dormant_days: int = 30, generated_at: str | None = None) -> dict:
    per_agent = analysis.get("agents") or {}
    window_end = _parse((analysis.get("window") or {}).get("end"))
    cutoff = window_end - timedelta(days=dormant_days) if window_end else None
    agents = []
    totals = {"declared_and_used": 0, "used_but_undeclared": 0, "declared_but_dormant": 0}
    for agent in registry.get("agents") or []:
        listed = sorted({t["name"] for t in agent.get("tools") or [] if isinstance(t, dict) and t.get("name")})
        summary = per_agent.get(agent["id"]) or {}
        counts = summary.get("tool_counts") or {}
        last_ts = summary.get("tool_last_ts") or {}
        used = sorted(counts)
        both = [t for t in listed if t in counts]
        undeclared = [t for t in used if t not in listed]
        dormant = []
        for tool in listed:
            seen = _parse(last_ts.get(tool))
            if seen is None or (cutoff is not None and seen < cutoff):
                dormant.append(tool)
        row = {
            "agent_id": agent["id"],
            "name": (agent.get("declared") or {}).get("name") or agent.get("display_name") or agent.get("name"),
            "has_runtime_evidence": bool(summary),
            "declared_and_used": [{"tool": t, "calls": counts[t], "last_seen": last_ts.get(t)} for t in both],
            "used_but_undeclared": [{"tool": t, "calls": counts[t], "last_seen": last_ts.get(t)} for t in undeclared],
            "declared_but_dormant": [{"tool": t, "last_seen": last_ts.get(t)} for t in dormant],
        }
        for key in totals:
            totals[key] += len(row[key])
        agents.append(row)
    return {
        "schema": RECONCILE_SCHEMA,
        "generated_at": generated_at,
        "window": analysis.get("window"),
        "dormant_days": dormant_days,
        "totals": totals,
        "agents": agents,
    }


def render_reconcile(doc: dict) -> str:
    lines = [f"Tools reconciled over {doc['window'].get('start')} to {doc['window'].get('end')} (dormant after {doc['dormant_days']} days)", ""]
    t = doc["totals"]
    lines.append(f"  declared and used {t['declared_and_used']}   used but undeclared {t['used_but_undeclared']}   declared but dormant {t['declared_but_dormant']}")
    for row in doc["agents"]:
        lines += ["", f"{row['name']}  ({row['agent_id']})" + ("" if row["has_runtime_evidence"] else "   no runtime evidence")]
        for label, key in (("declared and used", "declared_and_used"), ("used but undeclared", "used_but_undeclared"), ("declared but dormant", "declared_but_dormant")):
            items = row[key]
            if not items:
                continue
            names = ", ".join(f"{i['tool']}" + (f" x{i['calls']}" if "calls" in i else "") for i in items)
            lines.append(f"  {label:<22}{names}")
    return "\n".join(lines) + "\n"
