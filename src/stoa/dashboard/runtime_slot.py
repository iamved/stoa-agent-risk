"""The envelope's ``runtime`` slot (stoa-dashboard/1.1).

One call runs the whole trace pipeline over a directory and returns the
registry enriched by ``stoa runtime merge`` together with the documents the
Runtime screen reads: ``runtime-analysis/1.1``, ``runtime-reconcile/1.0``,
``runtime-chain/1.0`` and, when a committed baseline is given,
``runtime-drift/1.0``. Everything in it is derived from the traces and the
registry; nothing is scored again.
"""

from __future__ import annotations

from pathlib import Path

from ..config import StoaConfig
from ..runtime.analysis import analyze_traces
from ..runtime.chain import verify_dir
from ..runtime.drift import compute_drift
from ..runtime.merge import merge_runtime_into_registry
from ..runtime.reconcile import reconcile

RUNTIME_SLOT_SCHEMA = "dashboard-runtime/1.0"


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
) -> tuple[dict, dict]:
    """Returns ``(enriched_registry, slot)``."""
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
        "analysis": analysis,
        "reconcile": reconcile(registry, analysis, dormant_days=dormant_days, generated_at=generated_at),
        "chain": verify_dir(traces_dir, key).to_dict(),
        "drift": drift,
        "baseline_present": baseline is not None,
    }
    return enriched, slot
