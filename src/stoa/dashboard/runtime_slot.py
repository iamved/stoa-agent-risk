"""The envelope's ``runtime`` slot (stoa-dashboard/1.1).

One call runs the whole trace pipeline over a directory and returns the
registry enriched by ``stoa runtime merge`` together with the documents the
Runtime screen reads: ``runtime-analysis/1.1``, ``runtime-reconcile/1.0``,
``runtime-chain/1.0`` and, when a committed baseline is given,
``runtime-drift/1.0``. Everything in it is derived from the traces and the
registry; nothing is scored again.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import StoaConfig
from ..runtime.analysis import analyze_traces
from ..runtime.chain import verify_dir
from ..runtime.drift import compute_drift
from ..runtime.merge import merge_runtime_into_registry
from ..runtime.reconcile import reconcile

RUNTIME_SLOT_SCHEMA = "dashboard-runtime/1.0"


def _policy_block(policy_path: str | Path | None, analysis: dict, test_path: str | Path | None = None) -> dict | None:
    from ..policy.conditions import condition_text
    from ..policy.killswitch import find_state
    from ..policy.schema import find_policy_file, load_policy_document

    path = Path(policy_path) if policy_path else find_policy_file()
    summary = analysis.get("policy_summary") or {}
    document = None
    if path is not None and path.is_file():
        doc = load_policy_document(path)
        document = {
            "path": path.name,
            "mode": doc.mode,
            "problems": doc.problems,
            "policies": [{**p.to_dict(), "condition_text": condition_text(p.condition), "enforced": p.enforced(doc.mode)} for p in doc.policies],
        }
    drills = list(summary.get("killswitch_drills") or [])
    try:
        from ..policy.killswitch import drills as recorded_drills

        drills += [{**d, "source": "state"} for d in recorded_drills(find_state()) if d not in drills]
    except Exception:  # noqa: BLE001
        pass
    test = None
    for candidate in ([Path(test_path)] if test_path else []) + ([path.parent / ".stoa" / "policy-test.json"] if path else []):
        if candidate.is_file():
            try:
                test = json.loads(candidate.read_text(encoding="utf-8"))
                test = {k: v for k, v in test.items() if k != "results"} | {"results": test.get("results", [])[:50]}
                break
            except (OSError, ValueError):
                test = None
    if document is None and not summary.get("policies"):
        return None
    return {"document": document, "summary": summary.get("policies") or {}, "killswitch_drills": drills, "test": test}


DETECTR_SCHEMA = "dashboard-detectr/0.1"


def _detectr_block(traces_dir: str | Path, registry: dict, analysis: dict, generated_at: str | None) -> dict | None:
    """Hallucination DetectR over the sessions that carry captured content.
    Layer 0 only here (no external checker); every number is derived from
    the reports. ``None`` when no trace has content."""
    from ..detectr.ledger import chain, ledgers_from_trace_dir
    from ..detectr.metrics import compute_metrics
    from ..detectr.pipeline import check_ledger

    try:
        ledgers = ledgers_from_trace_dir(traces_dir)
    except Exception:  # noqa: BLE001 - never fatal for the page
        return None
    store = {l.trajectory_id: l for l in ledgers}
    # Approvals are span fields the SDK always records; a session counts as
    # captured only when it holds text or payloads the customer opted to keep.
    with_content = [l for l in ledgers if any(e.content_captured and e.kind != "approval" for e in l.entries)]
    if not with_content:
        return None
    agents = {a.get("id"): a for a in registry.get("agents") or []}
    reports = []
    for ledger in with_content:
        report = check_ledger(ledger, entries=chain(ledger, store), registry=registry, agent=agents.get(ledger.agent_id), deferred=False)
        reports.append(report.to_dict())
    detected_at = generated_at or (analysis.get("window") or {}).get("end")
    metrics = compute_metrics(reports, detected_at=detected_at)
    findings = [f for r in reports for f in r["findings"]]
    by_agent: dict = {}
    for r in reports:
        row = by_agent.setdefault(r["agent_id"], {"trajectories": 0, "claims": 0, "labels": {"grounded": 0, "unsupported": 0, "contradicted": 0, "unverifiable": 0}, "findings": 0})
        row["trajectories"] += 1
        for label, n in r["counts"].items():
            row["labels"][label] += n
            row["claims"] += n
        row["findings"] += len(r["findings"])
    for agent_id, row in by_agent.items():
        cell = (metrics["agents"].get(agent_id) or {}).get("all") or {}
        row["hallucination_rate"] = cell.get("hallucination_rate")
    return {
        "schema": DETECTR_SCHEMA,
        "trajectories": len(ledgers),
        "with_content": len(with_content),
        "counts": metrics["total"]["labels"],
        "hallucination_rate": metrics["total"]["hallucination_rate"],
        "by_agent": by_agent,
        "findings": findings,
        "metrics": metrics,
    }


def build_runtime_slot(
    traces_dir: str | Path,
    registry: dict,
    config: StoaConfig | None = None,
    *,
    baseline: dict | None = None,
    registry_path: str | None = None,
    generated_at: str | None = None,
    dormant_days: int = 30,
    key: str | None = None,
    policy_path: str | Path | None = None,
    test_path: str | Path | None = None,
) -> tuple[dict, dict]:
    """Returns ``(enriched_registry, slot)``. ``policy_path`` (or a
    ``stoa.policy.toml`` found by searching upward) puts the policy document
    beside the outcomes so the dashboard can show both."""
    config = config or StoaConfig()
    analysis = analyze_traces(traces_dir, registry, generated_at=generated_at, registry_path=registry_path)
    enriched = merge_runtime_into_registry(registry, analysis, config, baseline)
    drift = None
    if baseline is not None:
        try:
            drift = compute_drift(
                analysis, baseline, registry,
                ratio_threshold=config.runtime_drift_ratio_threshold,
                min_count=config.runtime_drift_min_count,
                approval_drop=config.runtime_drift_approval_drop,
                generated_at=generated_at,
            )
        except Exception:  # noqa: BLE001 - an unreadable baseline is reported, never fatal
            drift = None
    slot = {
        "schema": RUNTIME_SLOT_SCHEMA,
        "traces_dir": str(traces_dir),
        "policies": _policy_block(policy_path, analysis, test_path),
        "analysis": analysis,
        "reconcile": reconcile(registry, analysis, dormant_days=dormant_days, generated_at=generated_at),
        "chain": verify_dir(traces_dir, key).to_dict(),
        "drift": drift,
        "baseline_present": baseline is not None,
        "detectr": _detectr_block(traces_dir, registry, analysis, generated_at),
    }
    return enriched, slot
