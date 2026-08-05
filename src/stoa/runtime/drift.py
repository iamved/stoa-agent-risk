"""Behavioral baseline + drift (`stoa runtime baseline` / `stoa runtime drift`).

Mirrors `stoa diff`'s philosophy for *code* drift, applied to *behavior*:
the baseline is a committed, code-reviewed artifact
(``.stoa/baseline.json``, like ``.stoa/approvals.toml``), and drift is
report-only unless the user explicitly opts into gating with
``--fail-on-drift``.

The distribution-shift statistic is deliberately simple and explainable —
two numbers a reviewer can recompute by hand, never anything opaque: a
category's observed frequency (count / total spans) is compared to its
baseline frequency, and flagged when the ratio exceeds
``ratio_threshold`` in either direction AND the current count is at least
``min_count`` (small samples never alarm). Thresholds live in
``stoa.toml [runtime.drift]``.

Drift classes (documented in docs/runtime.md):

- **high** — a high-impact capability observed that is absent from both the
  baseline and the static registry; an approval-rate drop ≥ ``approval_drop``
  on a high-impact path; an observed amount exceeding declared
  ``economic_authority`` limits.
- **medium** — a new non-high-impact capability/integration; a frequency-
  ratio shift as defined above.
- **info** — a baseline capability no longer observed.

Deterministic body given identical inputs; wall-clock in headers only.
"""

from __future__ import annotations

from ..rules import HIGH_IMPACT_CAPABILITIES

BASELINE_SCHEMA = "runtime-baseline/1.0"
DRIFT_SCHEMA = "runtime-drift/1.0"
DRIFT_ORDER = ["info", "medium", "high"]

_BASELINE_FIELDS = (
    "span_count",
    "spans_by_kind",
    "capability_counts",
    "integration_counts",
    "observed_capabilities",
    "observed_integrations",
    "approval_rate_high_impact",
)


class BaselineVersionMismatch(Exception):
    """Unsupported baseline schema; maps to exit code 2."""


def build_baseline(analysis: dict, *, generated_at: str | None = None) -> dict:
    """Distill an analysis document into a committed behavioral baseline."""
    agents = {
        agent_id: {f: summary.get(f) for f in _BASELINE_FIELDS}
        for agent_id, summary in (analysis.get("agents") or {}).items()
    }
    return {
        "schema": BASELINE_SCHEMA,
        "header": {
            "generated_at": generated_at,
            "stoa_version": (analysis.get("header") or {}).get("stoa_version"),
        },
        "window": analysis.get("window"),
        "agents": agents,
    }


def check_baseline_version(baseline: dict) -> None:
    schema = str(baseline.get("schema", ""))
    major = schema.rsplit("/", 1)[-1].split(".")[0] if "/" in schema else ""
    if major != BASELINE_SCHEMA.rsplit("/", 1)[-1].split(".")[0]:
        raise BaselineVersionMismatch(
            f"unsupported baseline schema {schema!r} (this stoa reads {BASELINE_SCHEMA})"
        )


def _event(cls: str, kind: str, agent_id: str, **detail) -> dict:
    return {"class": cls, "kind": kind, "agent_id": agent_id, **detail}


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _frequency_shifts(
    now: dict, base: dict, agent_id: str, *,
    ratio_threshold: float, min_count: int,
) -> list[dict]:
    events = []
    for field in ("spans_by_kind", "capability_counts", "integration_counts"):
        now_counts: dict = now.get(field) or {}
        base_counts: dict = base.get(field) or {}
        now_total = now.get("span_count") or 0
        base_total = base.get("span_count") or 0
        for category in sorted(set(now_counts) | set(base_counts)):
            count_now = now_counts.get(category, 0)
            if count_now < min_count:
                continue
            rate_now = _rate(count_now, now_total)
            rate_base = _rate(base_counts.get(category, 0), base_total)
            if rate_base == 0.0:
                continue  # brand-new categories are handled as new-capability events
            ratio = rate_now / rate_base
            if ratio >= ratio_threshold or ratio <= 1.0 / ratio_threshold:
                events.append(_event(
                    "medium", "frequency_shift", agent_id,
                    field=field, category=category,
                    rate_now=round(rate_now, 4), rate_baseline=round(rate_base, 4),
                    ratio=round(ratio, 2), count_now=count_now,
                ))
    return events


def _declared_limits(registry: dict | None, agent_id: str) -> dict:
    if not registry:
        return {}
    for agent in registry.get("agents") or []:
        if agent["id"] == agent_id:
            return ((agent.get("declared") or {}).get("economic_authority")) or {}
    return {}


def _static_capabilities(registry: dict | None, agent_id: str) -> set[str]:
    if not registry:
        return set()
    for agent in registry.get("agents") or []:
        if agent["id"] == agent_id:
            return set(agent.get("capabilities") or [])
    return set()


def compute_drift(
    analysis: dict,
    baseline: dict,
    registry: dict | None = None,
    *,
    ratio_threshold: float = 3.0,
    min_count: int = 20,
    approval_drop: float = 0.10,
    generated_at: str | None = None,
) -> dict:
    """Compare current observed behavior to the committed baseline."""
    check_baseline_version(baseline)
    events: list[dict] = []
    now_agents: dict = analysis.get("agents") or {}
    base_agents: dict = baseline.get("agents") or {}

    for agent_id in sorted(set(now_agents) | set(base_agents)):
        now = now_agents.get(agent_id) or {}
        base = base_agents.get(agent_id) or {}
        caps_now = set(now.get("observed_capabilities") or [])
        caps_base = set(base.get("observed_capabilities") or [])
        integ_now = set(now.get("observed_integrations") or [])
        integ_base = set(base.get("observed_integrations") or [])
        static_caps = _static_capabilities(registry, agent_id)

        # new capabilities ---------------------------------------------------
        for cap in sorted(caps_now - caps_base):
            if cap in HIGH_IMPACT_CAPABILITIES and cap not in static_caps:
                events.append(_event(
                    "high", "new_high_impact_capability", agent_id,
                    capability=cap,
                    absent_from=("baseline" if registry is None
                                 else "baseline and static registry"),
                ))
            else:
                events.append(_event(
                    "medium", "new_capability", agent_id, capability=cap,
                    high_impact=cap in HIGH_IMPACT_CAPABILITIES,
                ))
        for integ in sorted(integ_now - integ_base):
            events.append(_event(
                "medium", "new_integration", agent_id, integration=integ,
            ))

        # approval-rate drop on high-impact paths -----------------------------
        rate_base = base.get("approval_rate_high_impact")
        rate_now = now.get("approval_rate_high_impact")
        if rate_base is not None and rate_now is not None:
            if rate_base - rate_now >= approval_drop:
                events.append(_event(
                    "high", "approval_rate_drop", agent_id,
                    rate_baseline=rate_base, rate_now=rate_now,
                ))

        # observed amounts vs declared economic authority -----------------------
        limits = _declared_limits(registry, agent_id)
        max_amount = now.get("max_observed_amount")
        per_action = limits.get("max_per_action")
        if max_amount and per_action and max_amount["amount"] > per_action.get("amount", float("inf")):
            events.append(_event(
                "high", "amount_exceeds_declared_max_per_action", agent_id,
                observed=max_amount, declared=per_action,
            ))
        daily = limits.get("daily_aggregate")
        totals = now.get("window_total_amounts") or {}
        if daily and totals.get(daily.get("currency", "USD"), 0) > daily.get("amount", float("inf")):
            events.append(_event(
                "high", "window_total_exceeds_declared_daily_aggregate", agent_id,
                observed={"amount": totals.get(daily.get("currency", "USD")),
                          "currency": daily.get("currency", "USD")},
                declared=daily,
                note="window total compared against the declared daily limit; "
                     "an analysis window longer than a day overstates this",
            ))

        # frequency shifts -------------------------------------------------------
        if base:
            events += _frequency_shifts(
                now, base, agent_id,
                ratio_threshold=ratio_threshold, min_count=min_count,
            )

        # capabilities no longer observed -------------------------------------------
        for cap in sorted(caps_base - caps_now):
            events.append(_event(
                "info", "capability_no_longer_observed", agent_id, capability=cap,
            ))

    max_class = "info"
    for event in events:
        if DRIFT_ORDER.index(event["class"]) > DRIFT_ORDER.index(max_class):
            max_class = event["class"]

    return {
        "schema": DRIFT_SCHEMA,
        "header": {
            "generated_at": generated_at,
            "baseline_window": baseline.get("window"),
            "analysis_window": analysis.get("window"),
        },
        "summary": {
            "events": len(events),
            "by_class": {
                cls: sum(1 for e in events if e["class"] == cls)
                for cls in reversed(DRIFT_ORDER)
            },
            "max_drift_class": max_class if events else "none",
        },
        "events": events,
        "thresholds": {
            "ratio_threshold": ratio_threshold,
            "min_count": min_count,
            "approval_drop": approval_drop,
        },
    }
