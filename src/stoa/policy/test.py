"""``stoa policy test``: replay scenarios through the policies (``policy-test/0.1``).

A scenario file is JSONL, one call per line::

    {"agent": "meridian-support", "tool": "issue_refund", "args": {"amount": 500, "order_id": "o-1"},
     "side_effect": "payment", "approval": false, "ts": "2026-09-18T15:00:00.000Z", "expect": "block",
     "note": "the fourth refund of the day"}

Two outcomes per call: ``actual`` is what the SDK does under the file's
own enforcement settings (``allow``, ``block``, ``escalate`` or ``mask``;
a policy in observe mode never blocks), and ``would`` is what the same
policies would do if every one of them were enforced. ``expect`` is matched
against ``actual``; ``expect_would`` against ``would``; omit either to
record only. The replay uses a fresh window store and the registry's
declared tools and limits. Per policy: how often it fired, how often it
decided the call, matches, and false positives (a block or escalate where
the author expected allow). Results carry ``evidence_level: tested`` and
attach to the passport.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..runtime.policy import decide, load_policy
from ..runtime.registry import load_registry_facts
from .conditions import WindowStore

TEST_SCHEMA = "policy-test/0.1"
_ACTION_FOR = {"deny": "block", "require_approval": "escalate", "mask": "mask", "observe": "log", "allow": "allow"}


def _parse(ts: str | None) -> datetime:
    if ts:
        for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_scenarios(path: str | Path) -> tuple[list[dict], list[str]]:
    scenarios, problems = [], []
    for line_no, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if not isinstance(item, dict) or not item.get("tool"):
                raise ValueError("needs a tool")
        except ValueError as exc:
            problems.append(f"line {line_no}: {exc}")
            continue
        item["_line"] = line_no
        scenarios.append(item)
    return scenarios, problems


def run_policy_test(scenarios: list[dict], policy_path: str | Path, *, registry_path: str | Path | None = None, generated_at: str | None = None) -> dict:
    policy = load_policy(policy_path)
    facts = load_registry_facts(registry_path)
    store = WindowStore(None)
    per_policy: dict[str, dict] = {}
    per_agent: dict[str, dict] = {}
    results = []
    scenarios = sorted(scenarios, key=lambda s: (_parse(s.get("ts")), s.get("_line", 0)))
    for item in scenarios:
        agent_key = str(item.get("agent") or "?")
        agent_facts = facts.for_agent(agent_key)
        agent_id = agent_facts.agent_id if agent_facts else agent_key
        args = dict(item.get("args") or {})
        amount = args.get("amount") if isinstance(args.get("amount"), (int, float)) and not isinstance(args.get("amount"), bool) else None
        approval_id = "scenario-approval" if item.get("approval") else None
        ns = {
            "tool": item["tool"], "args": args, "side_effect": item.get("side_effect", "write"), "amount": amount,
            "approval": {"granted": approval_id is not None, "span_id": approval_id},
            "agent": {"id": agent_id, "name": agent_facts.name if agent_facts else agent_key, "declared_tools": sorted(agent_facts.tools) if agent_facts else [], "max_per_action": agent_facts.max_per_action if agent_facts else None},
            "session": {"id": None}, "text": item.get("text"),
        }
        now = _parse(item.get("ts"))
        decisions = decide(policy, ns, fail_open=True, trigger=item.get("trigger", "tool_call"), store=store, now=now)
        rank = {"deny": 3, "require_approval": 2, "mask": 1, "observe": 0, "allow": 0}
        # what the SDK does: only enforced denies and escalations change the call
        actual, deciding = "allow", None
        for d in decisions:
            if d.decision in ("deny", "require_approval") and d.enforced and rank[d.decision] > rank.get({"block": "deny", "escalate": "require_approval"}.get(actual, "allow"), 0):
                actual, deciding = _ACTION_FOR[d.decision], d.rule_id
        if actual == "allow" and any(d.decision == "mask" for d in decisions):
            actual = "mask"
        # what the same policies would do if every one were enforced
        would, would_by = "allow", None
        for d in decisions:
            if rank[d.decision] > rank.get({"block": "deny", "escalate": "require_approval", "mask": "mask"}.get(would, "allow"), 0):
                would, would_by = _ACTION_FOR[d.decision], d.rule_id
        if actual != "block":
            store.observe(now, agent_id, item["tool"], {"amount": amount} if amount is not None else {})
        expect = item.get("expect")
        expect_would = item.get("expect_would")
        matched = (expect is None or expect == actual) and (expect_would is None or expect_would == would)
        false_positive = (expect == "allow" and actual in ("block", "escalate")) or (expect_would == "allow" and would in ("block", "escalate"))
        for d in decisions:
            bucket = per_policy.setdefault(d.rule_id, {"evaluated": 0, "fired": 0, "decided": 0, "would_decide": 0, "matched": 0, "mismatched": 0, "false_positives": 0, "enforced": False})
            bucket["evaluated"] += 1
            bucket["enforced"] = bucket["enforced"] or d.enforced
            if d.decision not in ("allow", "observe"):
                bucket["fired"] += 1
            if d.rule_id == deciding:
                bucket["decided"] += 1
            if d.rule_id == would_by:
                bucket["would_decide"] += 1
            if d.rule_id in (deciding, would_by) and (expect is not None or expect_would is not None):
                bucket["matched" if matched else "mismatched"] += 1
                if false_positive:
                    bucket["false_positives"] += 1
        a = per_agent.setdefault(ns["agent"]["name"] or agent_id, {"scenarios": 0, "matched": 0, "false_positives": 0, "blocked": 0, "escalated": 0})
        a["scenarios"] += 1
        a["matched"] += int(matched and (expect is not None or expect_would is not None))
        a["false_positives"] += int(false_positive)
        a["blocked"] += int(actual == "block")
        a["escalated"] += int(actual == "escalate")
        results.append({"line": item.get("_line"), "agent": ns["agent"]["name"], "tool": item["tool"], "amount": amount, "expect": expect, "actual": actual, "decided_by": deciding, "expect_would": expect_would, "would": would, "would_by": would_by, "matched": matched, "false_positive": false_positive, "note": item.get("note")})
    return {
        "schema": TEST_SCHEMA,
        "generated_at": generated_at,
        "policy_file": str(policy_path),
        "mode": policy.mode,
        "evidence_level": "tested",
        "scenarios": len(scenarios),
        "matched": sum(1 for r in results if r["matched"] and (r["expect"] is not None or r["expect_would"] is not None)),
        "expected": sum(1 for r in results if r["expect"] is not None or r["expect_would"] is not None),
        "false_positives": sum(1 for r in results if r["false_positive"]),
        "policies": dict(sorted(per_policy.items())),
        "agents": dict(sorted(per_agent.items())),
        "results": results,
    }


def render_policy_test(doc: dict) -> str:
    lines = [f"Policy test: {doc['scenarios']} scenario(s) against {doc['policy_file']} (mode {doc['mode']}); {doc['matched']} of {doc['expected']} expectations matched, {doc['false_positives']} false positive(s)", ""]
    lines.append(f"  {'policy':<24} {'evaluated':>9} {'fired':>6} {'decided':>8} {'would':>6} {'matched':>8} {'false+':>7}  enforced")
    for pid, c in doc["policies"].items():
        lines.append(f"  {pid:<24} {c['evaluated']:>9} {c['fired']:>6} {c['decided']:>8} {c['would_decide']:>6} {c['matched']:>8} {c['false_positives']:>7}  {'yes' if c['enforced'] else 'no'}")
    lines.append("")
    for r in doc["results"]:
        mark = "ok " if r["matched"] else "MISMATCH"
        would = f", would {r['would']} by {r['would_by']}" if r["would"] != r["actual"] and r["would_by"] else ""
        expected = f" (expected {r['expect'] or '-'} / would {r['expect_would'] or '-'})" if not r["matched"] else ""
        lines.append(f"  {mark:<8} {r['agent']} {r['tool']}{(' ' + str(r['amount'])) if r['amount'] is not None else ''}: {r['actual']}{(' by ' + r['decided_by']) if r['decided_by'] else ''}{would}{expected}{(' · ' + r['note']) if r.get('note') else ''}")
    return "\n".join(lines) + "\n"
